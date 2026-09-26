"""Ghicește cuvântul: Claude ghicește cuvântul la care te gândești doar din conversație.

Server mic, fără stare, scris doar cu biblioteca standard + SDK-ul `anthropic`.
Cuvântul NU există nicăieri în sistem: nici în prompt, nici în server, nici în browser.
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import anthropic

HERE = Path(__file__).resolve().parent
PORT = int(os.environ.get("PORT", "8000"))
MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5")
MAX_TURNS = 40
MAX_BODY = 200_000

client = anthropic.Anthropic()

SYSTEM_PROMPT = """Ești „Ghicitorul", un joc de tip 20 de întrebări în limba română.
Jucătorul s-a gândit la un cuvânt (substantiv comun, obiect, animal, loc, persoană celebră, concept etc.) și NU ți l-a spus. Nu e scris nicăieri. Tu trebuie să-l ghicești doar din conversație.

Reguli:
- Pune câte O singură întrebare pe rând, la care se poate răspunde cu Da / Nu / Nu știu / Probabil / Probabil nu. Jucătorul poate răspunde și liber, cu text.
- Alege întrebări care împart spațiul de posibilități cât mai egal (ca o căutare binară): la început categorii mari (e viu? e obiect? se poate ține în mână?), apoi tot mai specifice.
- Ține cont de TOATE răspunsurile anterioare și nu repeta întrebări. Răspunsurile „Nu știu"/„Probabil" sunt informație slabă, nu le trata ca sigure.
- Când ești destul de sigur (sau după ~15-20 de întrebări), fă o ghicire: un singur cuvânt concret.
- Dacă ghicirea e greșită, continuă cu întrebări noi care exclud ce ai ghicit și nu mai ghici același cuvânt.
- Dacă jucătorul confirmă că ai ghicit, felicită-l scurt și încheie jocul.
- Scrie natural, prietenos, concis, cu diacritice.

Răspunde mereu în formatul JSON cerut:
- "kind": "question" pentru o întrebare, "guess" pentru o ghicire, "done" după ce jucătorul a confirmat că ai ghicit.
- "message": textul afișat jucătorului (întrebarea, ghicirea formulată ca întrebare, sau mesajul final).
- "guess": cuvântul ghicit când kind = "guess", altfel șir gol.
- "confidence": cât de sigur ești acum pe cel mai probabil cuvânt, între 0 și 1.
- "candidates": până la 3 cuvinte pe care le iei în calcul acum (poate fi listă goală la început)."""

TURN_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["question", "guess", "done"]},
        "message": {"type": "string"},
        "guess": {"type": "string"},
        "confidence": {"type": "number"},
        "candidates": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["kind", "message", "guess", "confidence", "candidates"],
    "additionalProperties": False,
}

START_MESSAGE = "M-am gândit la un cuvânt. Începe să pui întrebări ca să-l ghicești."


class GameError(Exception):
    """Eroare care poate fi arătată direct jucătorului."""


def next_turn(history):
    """history: [{"role": "assistant"|"user", "content": str}], fără primul mesaj."""
    messages = [{"role": "user", "content": START_MESSAGE}, *history]

    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=messages,
        thinking={"type": "adaptive"},
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": TURN_SCHEMA},
        },
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )

    if response.stop_reason == "refusal":
        raise GameError("Modelul a refuzat cererea. Încearcă un joc nou.")
    if response.stop_reason == "max_tokens":
        raise GameError("Răspunsul a fost trunchiat. Mai încearcă o dată.")

    text = "".join(block.text for block in response.content if block.type == "text")
    return json.loads(text)


def valid_history(history):
    if not isinstance(history, list) or len(history) > MAX_TURNS * 2:
        return False
    for i, m in enumerate(history):
        expected_role = "assistant" if i % 2 == 0 else "user"
        if (
            not isinstance(m, dict)
            or m.get("role") != expected_role
            or not isinstance(m.get("content"), str)
            or not 0 < len(m["content"]) < 4000
        ):
            return False
    return True


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
                raise GameError("Cerere prea mare.")
            payload = json.loads(self.rfile.read(length) or b"{}")
            history = payload.get("history", [])
            if not valid_history(history):
                self.send_json(400, {"error": "Istoric de conversație invalid."})
                return
            self.send_json(200, next_turn(history))
        except GameError as e:
            self.send_json(422, {"error": str(e)})
        except anthropic.AuthenticationError:
            self.send_json(500, {"error": "Lipsește sau e greșită cheia ANTHROPIC_API_KEY."})
        except anthropic.RateLimitError:
            self.send_json(429, {"error": "Prea multe cereri. Așteaptă puțin."})
        except anthropic.APIStatusError as e:
            print(f"Claude API: {e.status_code} {e.message}")
            self.send_json(502, {"error": "Eroare la Claude API. Mai încearcă."})
        except anthropic.APIConnectionError:
            self.send_json(502, {"error": "Nu mă pot conecta la Claude API."})
        except (ValueError, json.JSONDecodeError):
            self.send_json(400, {"error": "Cerere invalidă."})


if __name__ == "__main__":
    print(f"Ghicește cuvântul rulează pe http://localhost:{PORT} (model: {MODEL})")
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()
