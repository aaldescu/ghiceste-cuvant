"""Motorul jocului: alege întrebarea următoare și ghicește, fără niciun model generativ.

Baza de cunoștințe (data/kb.json, făcută de Jev cu build_kb.py) dă pentru fiecare cuvânt
P(da | cuvânt, întrebare). Cu fiecare răspuns actualizăm probabilitatea fiecărui cuvânt
(regula lui Bayes) și alegem întrebarea care, în medie, reduce cel mai mult incertitudinea.

Un răspuns e un număr y între 0 și 1: cât de „da" e răspunsul
(Da = 1, Probabil = 0.75, Nu știu = 0.5, Probabil nu = 0.25, Nu = 0).
"""

import json
import math
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
KB_PATH = DATA / "kb.json"

GUESS_THRESHOLD = 0.6  # ghicim când cel mai probabil cuvânt trece de pragul ăsta
MAX_QUESTIONS = 25  # după atâtea întrebări ghicim oricum
MIN_GAIN = 0.02  # sub câștigul ăsta (în biți) o întrebare nu mai merită pusă
MAX_GUESSES = 5  # după atâtea ghiciri greșite ne dăm bătuți
NOISE = 0.07  # jucătorii (și Jev) mai greșesc: nicio probabilitate nu e 0 sau 1


def load_words():
    lines = (DATA / "cuvinte.txt").read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def load_questions():
    return json.loads((DATA / "intrebari.json").read_text(encoding="utf-8"))


def entropy(probs):
    return -sum(p * math.log2(p) for p in probs if p > 0)


class Game:
    def __init__(self, kb_words, questions):
        self.questions = {q["id"]: q["text"] for q in questions if all(q["id"] in a for a in kb_words.values())}
        self.words = sorted(kb_words)
        # P(da) curățat de extreme, ca un singur răspuns greșit să nu elimine definitiv cuvântul corect.
        self.p_yes = {
            w: {q: NOISE + (1 - 2 * NOISE) * kb_words[w][q] for q in self.questions} for w in self.words
        }

    @classmethod
    def load(cls):
        if not KB_PATH.exists():
            raise FileNotFoundError(f"Lipsește {KB_PATH.name}. Rulează întâi: python3 build_kb.py")
        kb = json.loads(KB_PATH.read_text(encoding="utf-8"))["words"]
        return cls(kb, load_questions())

    def posterior(self, answers, rejected=()):
        """answers: [(id_întrebare, y)]. Întoarce {cuvânt: probabilitate}, fără cuvintele respinse."""
        rejected = set(rejected)
        log_p = {w: 0.0 for w in self.words if w not in rejected}
        for q, y in answers:
            for w in log_p:
                p = self.p_yes[w][q]
                log_p[w] += math.log(y * p + (1 - y) * (1 - p))
        if not log_p:
            return {}
        top = max(log_p.values())
        weights = {w: math.exp(v - top) for w, v in log_p.items()}
        total = sum(weights.values())
        return {w: v / total for w, v in weights.items()}

    def best_question(self, post, asked):
        """Întrebarea cu cel mai mare câștig de informație așteptat, și câștigul ei."""
        current = entropy(post.values())
        best, best_gain = None, 0.0
        for q in self.questions:
            if q in asked:
                continue
            yes = {w: pw * self.p_yes[w][q] for w, pw in post.items()}
            no = {w: pw - yes[w] for w, pw in post.items()}
            p_yes, p_no = sum(yes.values()), sum(no.values())
            expected = sum(
                mass * entropy(v / mass for v in branch.values())
                for mass, branch in ((p_yes, yes), (p_no, no))
                if mass > 0
            )
            gain = current - expected
            if gain > best_gain:
                best, best_gain = q, gain
        return best, best_gain

    def next_turn(self, answers, rejected=()):
        post = self.posterior(answers, rejected)
        if not post or len(rejected) >= MAX_GUESSES:
            return {"kind": "giveup", "message": "M-ai învins! Nu mai am nicio idee la ce cuvânt te-ai gândit."}

        ranked = sorted(post.items(), key=lambda item: item[1], reverse=True)
        top_word, top_p = ranked[0]
        info = {
            "confidence": round(top_p, 3),
            "candidates": [w for w, _ in ranked[:3]],
            "asked": len(answers),
        }

        asked = {q for q, _ in answers}
        question, gain = self.best_question(post, asked)
        if top_p >= GUESS_THRESHOLD or len(answers) >= MAX_QUESTIONS or question is None or gain < MIN_GAIN:
            return {"kind": "guess", "guess": top_word, "message": f"Te gândești la „{top_word}”?", **info}
        return {"kind": "question", "question_id": question, "message": self.questions[question], **info}
