"""Construiește graful jocului: fiecare cuvânt din data/cuvinte.txt legat de categoriile lui.

Categoriile sunt în data/categorii.json (grupuri → subcategorii, cel mult 254 de subcategorii).
Pentru fiecare cuvânt, Jev (TypeSafe AI) alege one-shot subcategoria dintre toate. Un cuvânt intră
în fiecare subcategorie cu probabilitate de cel puțin MIN_LINK (cel mult MAX_LINKS), deci poate
avea mai mulți părinți: „roșie" e și la fructe și legume, și la culori.

Rezultatul se salvează în data/graf.json. Rulează din nou după ce schimbi cuvintele sau categoriile:
se calculează doar cuvintele noi.
    python3 build_graph.py            # completează ce lipsește
    python3 build_graph.py --rebuild  # recalculează tot (de exemplu după ce schimbi categoriile)
"""

import argparse
import asyncio
import json
import sys

from typesafe_sdk import AsyncTypeSafeClient, Choice, TypeSafeError

from game import GRAPH_PATH, load_categories, load_words

CONCURRENCY = 16
MIN_LINK = 0.2  # probabilitatea minimă ca un cuvânt să fie legat de o subcategorie
MAX_LINKS = 3

CONTEXT = "Joc de ghicit cuvinte. Așezăm fiecare cuvânt în categoria potrivită, după sensul lui obișnuit."


def category_question(categories):
    return Choice(
        instructions="În care categorie intră `cuvant`, după sensul lui cel mai obișnuit?",
        criteria={cid: c["descriere"] for cid, c in categories.items()},
    )


def links(probabilities):
    """Subcategoriile unui cuvânt: cea mai probabilă, plus celelalte peste MIN_LINK."""
    ranked = sorted(probabilities.items(), key=lambda item: item[1], reverse=True)
    kept = [(cid, p) for i, (cid, p) in enumerate(ranked[:MAX_LINKS]) if i == 0 or p >= MIN_LINK]
    return {cid: round(p, 3) for cid, p in kept}


async def classify(client, semaphore, question, word):
    async with semaphore:
        result = await client.system_one(state={"context": CONTEXT, "cuvant": word}, questions={"categorie": question})
    return word, links(result.choices["categorie"].probabilities), result.model


async def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rebuild", action="store_true", help="recalculează tot graful")
    args = parser.parse_args()

    words = load_words()
    categories = load_categories()
    graph = {}
    if GRAPH_PATH.exists() and not args.rebuild:
        graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8")).get("cuvinte", {})
    # Legăturile spre categorii care nu mai există nu mai contează: cuvintele alea se recalculează.
    todo = [w for w in words if w not in graph or not set(graph[w]) <= set(categories)]
    if not todo:
        print(f"Graful e complet: {len(words)} cuvinte, {len(categories)} categorii.")
        return

    print(f"Așez {len(todo)} cuvinte în {len(categories)} categorii…")
    question = category_question(categories)
    semaphore = asyncio.Semaphore(CONCURRENCY)
    model = None
    try:
        async with AsyncTypeSafeClient() as client:
            tasks = [classify(client, semaphore, question, w) for w in todo]
            for done, task in enumerate(asyncio.as_completed(tasks), start=1):
                word, word_links, model = await task
                graph[word] = word_links
                if done % 250 == 0 or done == len(todo):
                    print(f"  [{done}/{len(todo)}]")
    except TypeSafeError as error:
        print(f"Eroare TypeSafe: {error}", file=sys.stderr)
        sys.exit(1)
    finally:
        # Salvăm și progresul parțial, ca o rulare întreruptă să poată continua.
        words_set = set(words)
        data = {"model": model, "cuvinte": {w: c for w, c in graph.items() if w in words_set}}
        GRAPH_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
        print(f"Salvat în {GRAPH_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
