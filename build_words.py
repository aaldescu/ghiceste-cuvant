"""Construiește vocabularul jocului: cele mai frecvente substantive comune din română.

Surse (descărcate în data/.cache/ la prima rulare):
  - frecvența: subtitrări OpenSubtitles (hermitdave/FrequencyWords, CC BY-SA 4.0);
  - forma de dicționar și partea de vorbire: Lista Oficială de Cuvinte (LOC 6.0) de la dexonline (GNU FDL).
Un cuvânt din lista de frecvență e candidat doar dacă apare în LOC ca substantiv (M, F sau N), exact în
forma asta. Așa scăpăm de formele articulate sau la plural („casa", „câinii").

Unele cuvinte sunt substantive doar într-un sens rar („mai" = ciocan, „eu" = eul). Jev (TypeSafe AI)
alege one-shot partea de vorbire obișnuită a cuvântului și decide dacă e românesc și potrivit pentru joc.
Păstrăm primele N substantive, în ordinea frecvenței, plus cuvintele din data/cuvinte_extra.txt,
fără cele din data/cuvinte_excluse.txt.

Răspunsurile lui Jev se salvează în data/.cache/, ca o rulare întreruptă să continue de unde a rămas.
    python3 build_words.py             # 5000 de substantive
    python3 build_words.py --count 3000
"""

import argparse
import asyncio
import io
import json
import sys
import urllib.request
import zipfile

from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, TypeSafeError

from game import DATA

FREQUENCY_URL = "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/ro/ro_full.txt"
LOC_URL = "https://dexonline.ro/static/download/scrabble/loc-baza-6.0.zip"
CACHE = DATA / ".cache"
FREQUENCY_PATH = CACHE / "ro_full.txt"
LOC_PATH = CACHE / "loc-baza-6.0.txt"
VERDICTS_PATH = CACHE / "substantive-v3.json"
WORDS_PATH = DATA / "cuvinte.txt"
EXTRA_PATH = DATA / "cuvinte_extra.txt"
EXCLUDED_PATH = DATA / "cuvinte_excluse.txt"

NOUN_TYPES = {"M", "F", "N"}  # masculin, feminin, neutru în LOC
CONCURRENCY = 16
BATCH = 500  # câte cuvinte verificăm înainte să vedem dacă avem destule
NOUN_ACCEPT = 0.7  # P(substantiv) minimă în alegerea părții de vorbire
FIT_ACCEPT = 0.5  # P(cuvânt românesc) și P(potrivit pentru joc) minime

CONTEXT = "Construim vocabularul unui joc de ghicit cuvinte în limba română."
QUESTIONS = {
    "parte_de_vorbire": Choice(
        instructions="Ce parte de vorbire este `cuvant`, în sensul în care îl folosesc de obicei vorbitorii de română?",
        criteria={
            "substantiv": "Substantiv: denumește un lucru, o ființă, un loc, o acțiune sau o idee "
            "(casă, câine, timp, dragoste, mare).",
            "verb": "Verb sau formă de verb, inclusiv participiu (a merge, pot, spus, venit, ucis).",
            "adjectiv": "Adjectiv (bun, frumos, mare ca mărime).",
            "adverb": "Adverb (bine, aproape, repede, acum).",
            "pronume": "Pronume sau adjectiv pronominal (eu, noi, tău, mei, cineva, nimic).",
            "numeral": "Numeral (doi, trei, cinci).",
            "legatura": "Prepoziție sau conjuncție (dar, dacă, în, peste).",
            "interjectie": "Interjecție sau formulă de salut (hei, hai, salut, alo).",
        },
    ),
    "romanesc": Noul(
        instructions="Este `cuvant` un cuvânt românesc, așa cum apare într-un dicționar al limbii române?",
        criteria={
            "true": "Cuvânt românesc, inclusiv împrumuturi intrate în uz (taxi, weekend, sandviș, meci).",
            "false": "Cuvânt englezesc sau din altă limbă folosit ca atare (team, king, boy, song), "
            "nume de persoană sau de loc (dan, ana, york), abreviere.",
        },
    ),
    "potrivit": Noul(
        instructions="Este `cuvant` potrivit pentru un joc de familie, în care un jucător descrie cuvântul "
        "și altul îl ghicește?",
        criteria={
            "true": "Un cuvânt pe care majoritatea oamenilor îl cunosc, concret sau abstract.",
            "false": "Cuvânt vulgar sau jignitor, nume de marcă, cuvânt foarte rar, arhaic sau de jargon.",
        },
    ),
}


def download(url, path):
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        print(f"Descarc {url}")
        data = urllib.request.urlopen(url).read()
        if url.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                data = archive.read(path.name)
        path.write_bytes(data)
    return path.read_text(encoding="utf-8")


def normalize(word):
    return word.lower().replace("ş", "ș").replace("ţ", "ț")


def load_loc_nouns():
    """Substantivele din LOC, în forma de dicționar (fără apostroful care marchează accentul)."""
    nouns = set()
    for line in download(LOC_URL, LOC_PATH).splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] in NOUN_TYPES:
            nouns.add(normalize(parts[0].replace("'", "")))
    return nouns


def load_candidates():
    """Substantivele din LOC care apar în lista de frecvență, de la cel mai frecvent la cel mai rar."""
    nouns = load_loc_nouns()
    counts = {}
    for line in download(FREQUENCY_URL, FREQUENCY_PATH).splitlines():
        word, _, count = line.rpartition(" ")
        word = normalize(word)
        if word in nouns:
            counts[word] = counts.get(word, 0) + int(count)
    return sorted(counts, key=counts.get, reverse=True)


def load_list(path):
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


async def judge(client, semaphore, word):
    async with semaphore:
        result = await client.system_one(state={"context": CONTEXT, "cuvant": word}, questions=QUESTIONS)
    part_of_speech = result.choices["parte_de_vorbire"].probabilities
    verdict = {name: round(answer.noul, 3) for name, answer in result.nouls.items()}
    return word, {"substantiv": round(part_of_speech.get("substantiv", 0.0), 3), **verdict}


def accepted(verdicts, word):
    v = verdicts.get(word)
    return v is not None and v["substantiv"] >= NOUN_ACCEPT and v["romanesc"] >= FIT_ACCEPT and v["potrivit"] >= FIT_ACCEPT


async def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=5000, help="câte substantive din lista de frecvență")
    args = parser.parse_args()

    excluded = set(load_list(EXCLUDED_PATH))
    candidates = [w for w in load_candidates() if w not in excluded]
    print(f"{len(candidates)} substantive din LOC apar în lista de frecvență")
    verdicts = json.loads(VERDICTS_PATH.read_text(encoding="utf-8")) if VERDICTS_PATH.exists() else {}
    semaphore = asyncio.Semaphore(CONCURRENCY)
    position = 0
    try:
        async with AsyncTypeSafeClient() as client:
            while position < len(candidates) and sum(accepted(verdicts, w) for w in candidates[:position]) < args.count:
                batch = [w for w in candidates[position : position + BATCH] if w not in verdicts]
                position += BATCH
                for word, verdict in await asyncio.gather(*(judge(client, semaphore, w) for w in batch)):
                    verdicts[word] = verdict
                found = sum(accepted(verdicts, w) for w in candidates[:position])
                print(f"  {min(position, len(candidates))} verificate, {found} păstrate")
    except TypeSafeError as error:
        print(f"Eroare TypeSafe: {error}", file=sys.stderr)
        sys.exit(1)
    finally:
        CACHE.mkdir(parents=True, exist_ok=True)
        VERDICTS_PATH.write_text(json.dumps(verdicts, ensure_ascii=False), encoding="utf-8")

    nouns = [w for w in candidates if accepted(verdicts, w)][: args.count]
    words = list(dict.fromkeys(nouns + load_list(EXTRA_PATH)))
    header = (
        "# Vocabularul jocului: un cuvânt pe linie, generat de build_words.py. Nu edita de mână:\n"
        "# adaugă cuvinte în cuvinte_extra.txt și rulează din nou build_words.py și build_graph.py.\n"
        "# Surse: frecvența din OpenSubtitles (hermitdave/FrequencyWords, CC BY-SA 4.0),\n"
        "# formele din Lista Oficială de Cuvinte de la dexonline (LOC 6.0, GNU FDL), filtrate cu Jev.\n"
    )
    WORDS_PATH.write_text(header + "\n".join(words) + "\n", encoding="utf-8")
    print(f"Salvat {len(words)} cuvinte în {WORDS_PATH.name} ({len(nouns)} din frecvență)")


if __name__ == "__main__":
    asyncio.run(main())
