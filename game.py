"""Motorul jocului: decide ce răspunde jocul, fără niciun model generativ.

Jucătorul descrie cuvântul în conversație, fără să-l spună. La fiecare mesaj, Jev (server.py)
dă o distribuție de probabilitate peste cuvintele din data/cuvinte.txt, plus „niciunul".
Aici decidem doar ce face jocul cu distribuția: ghicește, cere mai multe indicii sau renunță.
Replicile jocului sunt șabloane fixe, nu text generat.
"""

from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
NONE = "niciunul"  # eticheta pentru „niciun cuvânt din listă nu se potrivește"

GUESS_THRESHOLD = 0.7  # ghicim când cel mai probabil cuvânt trece de pragul ăsta
MAX_MESSAGES = 8  # după atâtea mesaje ale jucătorului ghicim oricum
MAX_GUESSES = 5  # după atâtea ghiciri greșite ne dăm bătuți
MAX_WORDS = 254  # Jev acceptă cel mult 255 de variante într-un Choice (una e „niciunul")

# Replici când jocul nu are încă o idee bună. Alegem una după numărul de mesaje, ca să varieze.
NO_IDEA = [
    "Încă nu îmi dau seama. Spune-mi mai mult.",
    "Hmm, nu am nicio idee încă. Cum arată? Unde îl găsești?",
    "Mai dă-mi un indiciu.",
    "Tot nu știu. La ce folosește sau ce face?",
]
SOME_IDEA = [
    "Hmm, mă duce cu gândul la ceva… dar nu sunt sigur. Mai spune-mi.",
    "Cred că mă apropii. Mai dă-mi un indiciu.",
    "Am o bănuială, dar mai am nevoie de un detaliu.",
    "Aproape! Mai spune-mi ceva.",
]
AFTER_WRONG_GUESS = "Nu? Bine, atunci mai spune-mi ceva despre el."
GIVE_UP = "M-ai învins! Nu îmi dau seama la ce cuvânt te-ai gândit."
UNKNOWN_WORD = "M-ai învins! Cred că nu cunosc cuvântul ăsta."


def load_words():
    lines = (DATA / "cuvinte.txt").read_text(encoding="utf-8").splitlines()
    words = list(dict.fromkeys(line.strip() for line in lines if line.strip() and not line.startswith("#")))
    if len(words) > MAX_WORDS:
        raise ValueError(f"Prea multe cuvinte: {len(words)} (maxim {MAX_WORDS}).")
    return words


def next_turn(word_probs, rejected, player_messages, after_wrong_guess=False):
    """Decide replica jocului.

    word_probs: {cuvânt: probabilitate} de la Jev, cu cheia NONE pentru „niciunul".
    rejected: cuvintele ghicite greșit până acum (nu le mai propunem).
    player_messages: câte mesaje a scris jucătorul până acum.
    """
    if len(rejected) >= MAX_GUESSES:
        return {"kind": "giveup", "message": GIVE_UP}

    rejected = set(rejected)
    probs = {w: p for w, p in word_probs.items() if w not in rejected}
    total = sum(probs.values())
    probs = {w: p / total for w, p in probs.items()} if total > 0 else {NONE: 1.0}
    ranked = sorted(probs.items(), key=lambda item: item[1], reverse=True)
    words_only = [(w, p) for w, p in ranked if w != NONE]
    info = {"candidates": [w for w, _ in words_only[:3]], "none": round(probs.get(NONE, 0.0), 3)}

    if not words_only:
        return {"kind": "giveup", "message": GIVE_UP, "confidence": 0.0, **info}
    top_word, top_p = words_only[0]
    info["confidence"] = round(top_p, 3)

    if top_p >= GUESS_THRESHOLD:
        return {"kind": "guess", "guess": top_word, "message": f"Te gândești la „{top_word}”?", **info}
    if player_messages >= MAX_MESSAGES:
        if ranked[0][0] == NONE:
            return {"kind": "giveup", "message": UNKNOWN_WORD, **info}
        return {"kind": "guess", "guess": top_word, "message": f"Nu sunt sigur… „{top_word}”?", **info}

    if after_wrong_guess:
        message = AFTER_WRONG_GUESS
    else:
        lines = SOME_IDEA if top_p >= 0.3 else NO_IDEA
        message = lines[player_messages % len(lines)]
    return {"kind": "hint", "message": message, **info}
