"""Ghicește cuvântul: jocul ghicește cuvântul la care te gândești doar din răspunsurile tale.

Fără model generativ: întrebările vin din data/intrebari.json, iar motorul din game.py
alege întrebarea următoare. Jev (TypeSafe AI, clasificator one-shot) e folosit:
  - offline, în build_kb.py, ca să știm cum răspunde fiecare cuvânt la fiecare întrebare;
  - live, doar când jucătorul răspunde liber, cu text, ca să aflăm dacă a vrut să spună da sau nu.

Cuvântul NU există nicăieri în sistem: nici în server, nici în browser.
Serverul e fără stare: browserul trimite la fiecare pas răspunsurile de până acum.
"""

import json
import math
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from typesafe_sdk import (
    Choice,
    TypeSafeAPIConnectionError,
    TypeSafeAPIError,
    TypeSafeAuthenticationError,
    TypeSafeClient,
    TypeSafeError,
    TypeSafeRateLimitError,
)

from game import Game

HERE = Path(__file__).resolve().parent
PORT = int(os.environ.get("PORT", "8000"))
MAX_BODY = 50_000
MAX_ANSWERS = 60

game = Game.load()
try:
    jev = TypeSafeClient()
except TypeSafeError:
    jev = None  # fără cheie, jocul merge doar cu butoane

# Ce poate însemna un răspuns liber, și cât de „da" e fiecare variantă.
ANSWER_LABELS = {
    "da": (1.0, "Răspunsul înseamnă da / adevărat."),
    "probabil": (0.75, "Răspunsul înseamnă probabil da, de obicei, uneori, parțial da."),
    "nu_stiu": (0.5, "Jucătorul nu știe, depinde, sau răspunsul nu are legătură cu întrebarea."),
    "probabil_nu": (0.25, "Răspunsul înseamnă probabil nu, rar, nu prea."),
    "nu": (0.0, "Răspunsul înseamnă nu / fals."),
}
ANSWER_QUESTION = Choice(
    instructions="Într-un joc de ghicit cuvinte, jucătorul a răspuns liber la întrebare. Ce a vrut să spună?",
    criteria={label: description for label, (_, description) in ANSWER_LABELS.items()},
)


class BadRequest(Exception):
    pass


def classify_free_answer(question, text):
    """Transformă un răspuns liber într-un y între 0 (nu) și 1 (da), cu Jev."""
    if jev is None:
        raise BadRequest("Răspunsurile libere au nevoie de TYPESAFE_API_KEY. Folosește butoanele.")
    result = jev.system_one(
        state={"intrebare": question, "raspuns": text},
        questions={"sens": ANSWER_QUESTION},
    )
    answer = result.choices["sens"]
    y = sum(prob * ANSWER_LABELS[label][0] for label, prob in answer.probabilities.items() if label in ANSWER_LABELS)
    return {"y": round(y, 3), "label": answer.choice, "confidence": answer.confidence}


def parse_turn(payload):
    answers = payload.get("answers", [])
    rejected = payload.get("rejected", [])
    if not isinstance(answers, list) or len(answers) > MAX_ANSWERS:
        raise BadRequest("Listă de răspunsuri invalidă.")
    if not isinstance(rejected, list) or not all(w in game.p_yes for w in rejected):
        raise BadRequest("Listă de cuvinte respinse invalidă.")
    parsed = []
    for a in answers:
        q, y = (a.get("q"), a.get("y")) if isinstance(a, dict) else (None, None)
        if q not in game.questions or not isinstance(y, (int, float)) or not math.isfinite(y) or not 0 <= y <= 1:
            raise BadRequest("Răspuns invalid.")
        parsed.append((q, float(y)))
    return parsed, rejected


def parse_classify(payload):
    text = payload.get("text")
    if not isinstance(text, str) or not 0 < len(text.strip()) <= 300:
        raise BadRequest("Răspunsul trebuie să aibă între 1 și 300 de caractere.")
    if payload.get("guess") in game.p_yes:
        question = f"Te gândești la cuvântul „{payload['guess']}”?"
    elif payload.get("q") in game.questions:
        question = game.questions[payload["q"]]
    else:
        raise BadRequest("Întrebare necunoscută.")
    return question, text.strip()


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path not in ("/", "/index.html"):
            self.send_error(404)
            return
        body = (HERE / "public" / "index.html").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        routes = {"/api/turn": self.turn, "/api/classify": self.classify}
        if self.path not in routes:
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise BadRequest("Cerere prea mare.")
            payload = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(payload, dict):
                raise BadRequest("Cerere invalidă.")
            self.send_json(200, routes[self.path](payload))
        except (BadRequest, ValueError) as e:
            self.send_json(400, {"error": str(e) if isinstance(e, BadRequest) else "Cerere invalidă."})
        except TypeSafeAuthenticationError:
            self.send_json(500, {"error": "Lipsește sau e greșită cheia TYPESAFE_API_KEY."})
        except TypeSafeRateLimitError:
            self.send_json(429, {"error": "Prea multe cereri. Așteaptă puțin."})
        except TypeSafeAPIConnectionError:
            self.send_json(502, {"error": "Nu mă pot conecta la Jev. Folosește butoanele."})
        except TypeSafeAPIError as e:
            print(f"Jev: {e}")
            self.send_json(502, {"error": "Eroare la Jev. Folosește butoanele."})
        except TypeSafeError as e:
            print(f"TypeSafe: {e}")
            self.send_json(500, {"error": "Eroare la Jev."})

    def turn(self, payload):
        answers, rejected = parse_turn(payload)
        return game.next_turn(answers, rejected)

    def classify(self, payload):
        return classify_free_answer(*parse_classify(payload))


if __name__ == "__main__":
    print(f"Ghicește cuvântul: {len(game.words)} cuvinte, {len(game.questions)} întrebări")
    if jev is None:
        print("Atenție: TYPESAFE_API_KEY nu e setat, răspunsurile libere nu vor funcționa.")
    print(f"Rulează pe http://localhost:{PORT}")
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()
