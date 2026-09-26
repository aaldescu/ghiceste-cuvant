"""Ghicește cuvântul: jucătorul descrie un cuvânt în conversație, fără să-l spună, iar jocul îl ghicește.

Fără model generativ. La fiecare mesaj, Jev (TypeSafe AI, clasificator one-shot) citește toată
conversația și dă, într-o singură cerere:
  - o distribuție de probabilitate peste cuvintele din data/cuvinte.txt (plus „niciunul");
  - dacă jocul tocmai a ghicit, ce a vrut să spună jucătorul: da sau nu.
Replica jocului e aleasă din șabloane fixe în game.py.

Cuvântul NU există nicăieri în sistem: nici în server, nici în browser.
Serverul e fără stare: browserul trimite la fiecare pas toată conversația.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from typesafe_sdk import (
    Choice,
    TypeSafeAPIConnectionError,
    TypeSafeAPIError,
    TypeSafeAPITimeoutError,
    TypeSafeAuthenticationError,
    TypeSafeClient,
    TypeSafeError,
    TypeSafeRateLimitError,
)

import game

HERE = Path(__file__).resolve().parent
PORT = int(os.environ.get("PORT", "8000"))
MAX_BODY = 50_000
MAX_CONVERSATION = 40  # mesaje în total (jucător + joc)
MAX_TEXT = 300
JEV_TIMEOUT = 15  # secunde; o cerere normală durează sub o secundă

WORDS = game.load_words()
WORD_SET = set(WORDS)

CONTEXT = (
    "Joc de ghicit cuvinte. Jucătorul se gândește la un cuvânt și îl descrie în conversație, "
    "fără să-l spună. Jocul încearcă să ghicească. Mesajele sunt în ordine; "
    "`cuvinte_respinse` sunt cuvinte pe care jucătorul a spus deja că nu sunt cuvântul lui."
)
GUESS_ANSWER = Choice(
    instructions="Ultimul mesaj al jocului a fost o încercare de a ghici cuvântul. "
    "Ce a răspuns jucătorul în ultimul lui mesaj?",
    criteria={
        "da": "Jucătorul confirmă: jocul a ghicit cuvântul.",
        "nu": "Jucătorul spune că nu e cuvântul, sau continuă să descrie fără să confirme.",
    },
)


def word_question(excluded):
    return Choice(
        instructions="La care dintre aceste cuvinte se gândește jucătorul, după tot ce a spus în conversație? "
        f"Alege `{game.NONE}` dacă niciun cuvânt nu se potrivește.",
        criteria={
            **{w: None for w in WORDS if w not in excluded},
            game.NONE: "Niciun cuvânt din listă nu se potrivește cu descrierea.",
        },
    )


class BadRequest(Exception):
    pass


def parse_turn(payload):
    conversation = payload.get("conversation")
    rejected = payload.get("rejected", [])
    guess = payload.get("guess")
    guess_answer = payload.get("guess_answer")
    if not isinstance(conversation, list) or not 0 < len(conversation) <= MAX_CONVERSATION:
        raise BadRequest("Conversație invalidă.")
    for m in conversation:
        if not isinstance(m, dict) or m.get("from") not in ("player", "game"):
            raise BadRequest("Mesaj invalid.")
        if not isinstance(m.get("text"), str) or not 0 < len(m["text"].strip()) <= MAX_TEXT:
            raise BadRequest(f"Un mesaj trebuie să aibă între 1 și {MAX_TEXT} de caractere.")
    if conversation[-1]["from"] != "player":
        raise BadRequest("Ultimul mesaj trebuie să fie al jucătorului.")
    if not isinstance(rejected, list) or not all(w in WORD_SET for w in rejected):
        raise BadRequest("Listă de cuvinte respinse invalidă.")
    if guess is not None and guess not in WORD_SET:
        raise BadRequest("Ghicire invalidă.")
    if guess_answer is not None and not isinstance(guess_answer, bool):
        raise BadRequest("Răspuns invalid.")
    return conversation, rejected, guess, guess_answer


def play_turn(conversation, rejected, guess, guess_answer):
    """Un pas de joc: o singură cerere la Jev, apoi game.next_turn decide replica."""
    # Dacă jocul a ghicit, întrebăm speculativ fără cuvântul ghicit: îl folosim doar dacă răspunsul e „nu".
    excluded = set(rejected) | ({guess} if guess else set())
    questions = {"cuvant": word_question(excluded)}
    if guess and guess_answer is None:
        questions["raspuns_ghicire"] = GUESS_ANSWER
    result = jev.system_one(
        state={
            "context": CONTEXT,
            "conversatie": [
                {"cine": "jucător" if m["from"] == "player" else "joc", "text": m["text"].strip()}
                for m in conversation
            ],
            "cuvinte_respinse": sorted(excluded),
        },
        questions=questions,
    )

    if guess:
        if guess_answer is None:
            guess_answer = result.choices["raspuns_ghicire"].probabilities.get("da", 0.0) >= 0.5
        if guess_answer:
            return {"kind": "done", "message": f"Am ghicit: „{guess}”! Mai jucăm?", "rejected": rejected}
        rejected = rejected + [guess]

    player_messages = sum(m["from"] == "player" for m in conversation)
    probs = result.choices["cuvant"].probabilities
    turn = game.next_turn(probs, rejected, player_messages, after_wrong_guess=bool(guess))
    return {**turn, "rejected": rejected}


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
        if self.path != "/api/turn":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise BadRequest("Cerere prea mare.")
            payload = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(payload, dict):
                raise BadRequest("Cerere invalidă.")
            self.send_json(200, play_turn(*parse_turn(payload)))
        except (BadRequest, ValueError) as e:
            self.send_json(400, {"error": str(e) if isinstance(e, BadRequest) else "Cerere invalidă."})
        except TypeSafeAuthenticationError:
            self.send_json(500, {"error": "Lipsește sau e greșită cheia TYPESAFE_API_KEY."})
        except TypeSafeRateLimitError:
            self.send_json(429, {"error": "Prea multe cereri. Așteaptă puțin."})
        except TypeSafeAPITimeoutError:
            self.send_json(504, {"error": "Jev răspunde prea greu."})
        except TypeSafeAPIConnectionError:
            self.send_json(502, {"error": "Nu mă pot conecta la Jev."})
        except TypeSafeAPIError as e:
            print(f"Jev: {e}")
            self.send_json(502, {"error": "Eroare la Jev."})
        except TypeSafeError as e:
            print(f"TypeSafe: {e}")
            self.send_json(500, {"error": "Eroare la Jev."})


if __name__ == "__main__":
    try:
        jev = TypeSafeClient(timeout=JEV_TIMEOUT)
    except TypeSafeError:
        sys.exit("Lipsește TYPESAFE_API_KEY. Jocul are nevoie de Jev ca să înțeleagă conversația.")
    print(f"Ghicește cuvântul: {len(WORDS)} cuvinte")
    print(f"Rulează pe http://localhost:{PORT}")
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()
