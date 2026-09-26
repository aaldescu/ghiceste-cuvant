"""Motorul jocului: decide ce răspunde jocul, fără niciun model generativ.

Jucătorul descrie cuvântul în conversație, fără să-l spună. Vocabularul (data/cuvinte.txt) e prea mare
pentru o singură întrebare la Jev (cel mult 255 de variante), așa că e așezat într-un graf:
subcategorii (data/categorii.json) → cuvinte (data/graf.json, făcut de build_graph.py).
La fiecare mesaj, server.py întreabă Jev întâi care subcategorii se potrivesc, apoi care cuvânt,
doar dintre cuvintele subcategoriilor alese (select_words). Aici decidem ce face jocul cu
distribuția finală: ghicește, cere mai multe indicii sau renunță.
Replicile jocului sunt șabloane fixe, nu text generat.
"""

import json
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
GRAPH_PATH = DATA / "graf.json"
NONE = "niciunul"  # eticheta pentru „niciun cuvânt din listă nu se potrivește"

SURE = 0.7  # peste pragul ăsta jocul întreabă sigur pe el
UNSURE = 0.3  # sub pragul ăsta jocul doar încearcă o variantă
NEXT_GUESS_MIN = 0.15  # la o ghicire, ținem minte al doilea cuvânt dacă are cel puțin atât (vezi next_turn)
MAX_GUESSES = 20  # după atâtea ghiciri greșite ne dăm bătuți
MAX_OPTIONS = 255  # Jev acceptă cel mult 255 de variante într-un Choice
MAX_WORDS = MAX_OPTIONS - 1  # cuvinte într-o întrebare; o variantă e „niciunul"
CATEGORY_MASS = 0.95  # luăm subcategorii până acoperă atâta din probabilitate (sau până la MAX_WORDS)

# Verificarea indiciilor, la final, după ce jucătorul își dezvăluie cuvântul (vezi judge_clue).
CLUE_MIN = 0.3  # sub pragul ăsta mesajul nu e indiciu („hmm”, „nu”), deci nu se judecă
LIE_MAX = 0.2  # sub pragul ăsta indiciul e fals: jucătorul e descalificat
TRUE_MIN = 0.5  # între LIE_MAX și TRUE_MIN indiciul e îndoielnic: nu primește punct, dar nu descalifică
USEFUL_MIN = 0.25  # sub pragul ăsta indiciul e vag („e un lucru”): nu primește punct
SAID_WORD_MIN = 0.5  # peste pragul ăsta indiciul conține cuvântul sau o formă a lui: descalificare
ESCAPE_BONUS = 5  # puncte în plus dacă pisica renunță

VERDICTS = {
    "valid": "adevărat și util",
    "vag": "prea general",
    "indoielnic": "poate fi fals",
    "minciuna": "fals",
    "spune_cuvantul": "conține cuvântul",
    "nu_e_indiciu": "nu e indiciu",
}

GIVE_UP = "M-ai învins! Nu îmi dau seama la ce cuvânt te-ai gândit."
UNKNOWN_WORD = "M-ai învins! Cred că nu cunosc cuvântul ăsta."


def guess_message(word, confidence, after_wrong_guess):
    if after_wrong_guess:
        return f"Atunci te gândești la „{word}”?" if confidence >= SURE else f"Atunci „{word}”?"
    if confidence >= SURE:
        return f"Te gândești la „{word}”?"
    if confidence >= UNSURE:
        return f"E cumva „{word}”?"
    return f"Poate „{word}”?"


def load_words():
    lines = (DATA / "cuvinte.txt").read_text(encoding="utf-8").splitlines()
    return list(dict.fromkeys(line.strip() for line in lines if line.strip() and not line.startswith("#")))


def load_categories():
    """{id_subcategorie: {"grup": ..., "descriere": ...}} din data/categorii.json."""
    groups = json.loads((DATA / "categorii.json").read_text(encoding="utf-8"))
    categories = {cid: {"grup": group, "descriere": text} for group, subs in groups.items() for cid, text in subs.items()}
    if len(categories) > MAX_OPTIONS:
        raise ValueError(f"Prea multe subcategorii: {len(categories)} (maxim {MAX_OPTIONS}).")
    return categories


class Graph:
    """Cuvintele fiecărei subcategorii. Un cuvânt poate fi în mai multe subcategorii."""

    def __init__(self, word_links, categories):
        self.categories = categories
        self.words = sorted(word_links)
        self.members = {cid: [] for cid in categories}
        for word, links in word_links.items():
            for cid in links:
                if cid in self.members:
                    self.members[cid].append(word)

    @classmethod
    def load(cls):
        if not GRAPH_PATH.exists():
            raise FileNotFoundError(f"Lipsește {GRAPH_PATH.name}. Rulează întâi: python3 build_graph.py")
        word_links = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))["cuvinte"]
        words = set(load_words())
        return cls({w: links for w, links in word_links.items() if w in words}, load_categories())

    def select_words(self, category_probs, excluded=()):
        """Cuvintele de pus în a doua întrebare și cât din probabilitate acoperă subcategoriile lor.

        Luăm subcategoriile de la cea mai probabilă, până acoperă CATEGORY_MASS sau până nu mai
        încap cuvintele lor în MAX_WORDS. Din prima subcategorie luăm oricum cuvintele (cel mult MAX_WORDS).
        """
        excluded = set(excluded)
        chosen, coverage = [], 0.0
        for cid, p in sorted(category_probs.items(), key=lambda item: item[1], reverse=True):
            new = [w for w in self.members.get(cid, []) if w not in excluded and w not in chosen]
            if chosen and len(chosen) + len(new) > MAX_WORDS:
                continue
            chosen.extend(new[: MAX_WORDS - len(chosen)])
            coverage += p
            if coverage >= CATEGORY_MASS or len(chosen) >= MAX_WORDS:
                break
        return chosen, min(coverage, 1.0)


def next_turn(word_probs, rejected, after_wrong_guess=False, next_guess=None):
    """Decide replica jocului: la fiecare mesaj încearcă un cuvânt, până ghicește sau renunță.

    word_probs: {cuvânt: probabilitate} de la Jev, cu cheia NONE pentru „niciunul".
    rejected: cuvintele ghicite greșit până acum (nu le mai propunem).
    next_guess: al doilea candidat de la ghicirea respinsă chiar acum. După un „nu”, Jev tinde să scadă
    și sinonimele cuvântului respins (reparare → reparație), așa că îl propunem pe el,
    dacă mesajul nou nu arată clar spre alt cuvânt și dacă a rămas cel puțin pe jumătate cât primul.
    """
    rejected = set(rejected)
    probs = {w: p for w, p in word_probs.items() if w not in rejected}
    total = sum(probs.values())
    probs = {w: p / total for w, p in probs.items()} if total > 0 else {NONE: 1.0}
    words_only = sorted(((w, p) for w, p in probs.items() if w != NONE), key=lambda item: item[1], reverse=True)
    none_p = probs.get(NONE, 0.0)
    info = {"candidates": [w for w, _ in words_only[:3]], "none": round(none_p, 3)}

    if not words_only or len(rejected) >= MAX_GUESSES:
        return {"kind": "giveup", "message": UNKNOWN_WORD if none_p >= 0.5 else GIVE_UP, **info}

    top_word, top_p = words_only[0]
    # Al doilea candidat câștigă doar dacă a rămas aproape de primul; altfel indiciul nou a schimbat direcția.
    next_p = probs.get(next_guess, 0.0)
    if after_wrong_guess and next_guess and next_guess not in rejected and top_p < SURE and next_p >= top_p / 2:
        top_word, top_p = next_guess, next_p
    info["confidence"] = round(top_p, 3)
    others = [(w, p) for w, p in words_only if w != top_word]
    if others and others[0][1] >= NEXT_GUESS_MIN:
        info["next_guess"] = others[0][0]
    message = guess_message(top_word, top_p, after_wrong_guess)
    return {"kind": "guess", "guess": top_word, "message": message, **info}


def judge_clue(judgment):
    """Verdictul pentru un mesaj al jucătorului, din judecățile lui Jev față de cuvântul dezvăluit.

    judgment: {"e_indiciu", "adevarat", "util", "spune_cuvantul"}, fiecare o probabilitate.
    """
    if judgment["spune_cuvantul"] >= SAID_WORD_MIN:
        return "spune_cuvantul"
    if judgment["e_indiciu"] < CLUE_MIN:
        return "nu_e_indiciu"
    if judgment["adevarat"] < LIE_MAX:
        return "minciuna"
    if judgment["adevarat"] < TRUE_MIN:
        return "indoielnic"
    if judgment["util"] < USEFUL_MIN:
        return "vag"
    return "valid"


def score_round(verdicts, escaped, lied_on_guess=None, known_word=True):
    """Scorul rundei: un punct pentru fiecare indiciu valid, plus bonus dacă pisica a renunțat.

    Descalificare (scor 0): un indiciu fals, un indiciu care conține cuvântul, sau un „nu” la o încercare
    care era chiar cuvântul (lied_on_guess). Un cuvânt care nu e în dicționarul pisicii nu primește puncte:
    pisica n-avea cum să-l prindă.
    """
    if lied_on_guess:
        return {"score": 0, "disqualified": True, "reason": "a_mintit_la_incercare", "lied_on": lied_on_guess}
    for verdict in ("minciuna", "spune_cuvantul"):
        if verdict in verdicts:
            return {"score": 0, "disqualified": True, "reason": verdict}
    if not known_word:
        return {"score": 0, "disqualified": False, "reason": "cuvant_necunoscut"}
    valid = sum(v == "valid" for v in verdicts)
    return {"score": valid + (ESCAPE_BONUS if escaped else 0), "disqualified": False, "reason": None}
