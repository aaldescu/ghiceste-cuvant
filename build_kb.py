"""Construiește baza de cunoștințe a jocului cu Jev (TypeSafe AI).

Pentru fiecare cuvânt din data/cuvinte.txt, Jev răspunde într-un singur pas (one-shot)
la toate întrebările da/nu din data/intrebari.json. Rezultatul e o probabilitate
P(da | cuvânt, întrebare) salvată în data/kb.json.

Rulează din nou după ce adaugi cuvinte sau întrebări: se calculează doar perechile lipsă.
    python3 build_kb.py            # completează ce lipsește
    python3 build_kb.py --rebuild  # recalculează tot
"""

import argparse
import asyncio
import json
import sys

from typesafe_sdk import AsyncTypeSafeClient, Noul, TypeSafeError

from game import KB_PATH, load_questions, load_words

CHUNK_SIZE = 20  # câte întrebări trimitem într-o cerere
CONCURRENCY = 8  # câte cereri rulează în paralel


def load_existing_kb(rebuild):
    if rebuild or not KB_PATH.exists():
        return {}
    return json.loads(KB_PATH.read_text(encoding="utf-8")).get("words", {})


async def classify_word(client, semaphore, word, questions):
    """Întreabă Jev toate întrebările pentru un cuvânt; întoarce {id_întrebare: P(da)}."""
    answers, model = {}, None
    for start in range(0, len(questions), CHUNK_SIZE):
        chunk = questions[start : start + CHUNK_SIZE]
        async with semaphore:
            result = await client.system_one(
                state={
                    "context": "Joc de ghicit cuvinte. Răspunde la întrebare despre sensul obișnuit al cuvântului.",
                    "cuvant": word,
                },
                questions={q["id"]: Noul(instructions=q["text"]) for q in chunk},
            )
        answers.update({name: answer.noul for name, answer in result.nouls.items()})
        model = result.model
    return word, answers, model


async def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rebuild", action="store_true", help="recalculează toată baza de cunoștințe")
    args = parser.parse_args()

    words = load_words()
    questions = load_questions()
    kb = load_existing_kb(args.rebuild)

    todo = []
    for word in words:
        known = kb.get(word, {})
        missing = [q for q in questions if q["id"] not in known]
        if missing:
            todo.append((word, missing))

    if not todo:
        print(f"Baza de cunoștințe e completă: {len(words)} cuvinte × {len(questions)} întrebări.")
        return

    print(f"Întreb Jev despre {len(todo)} cuvinte…")
    semaphore = asyncio.Semaphore(CONCURRENCY)
    model = None
    try:
        async with AsyncTypeSafeClient() as client:
            tasks = [classify_word(client, semaphore, w, missing) for w, missing in todo]
            for done, task in enumerate(asyncio.as_completed(tasks), start=1):
                word, answers, model = await task
                kb.setdefault(word, {}).update(answers)
                print(f"  [{done}/{len(todo)}] {word}")
    except TypeSafeError as error:
        print(f"Eroare TypeSafe: {error}", file=sys.stderr)
        sys.exit(1)
    finally:
        # Salvăm și progresul parțial, ca o rulare întreruptă să poată continua.
        words_set = set(words)
        data = {"model": model, "words": {w: a for w, a in kb.items() if w in words_set}}
        KB_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Salvat în {KB_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
