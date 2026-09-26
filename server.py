"""Pisica și șoarecele: jucătorul (șoarecele) ascunde un cuvânt și dă indicii, jocul (pisica) îl vânează.

Fără model generativ. Jev (TypeSafe AI, clasificator one-shot) e folosit în două locuri:
  - /api/turn, la fiecare mesaj: citește toată conversația, în două cereri:
      1. care subcategorii din graf se potrivesc (data/categorii.json) și, după o încercare,
         dacă jucătorul a confirmat-o („da, m-ai prins”) sau a dat alt indiciu;
      2. care cuvânt, doar dintre cuvintele subcategoriilor alese (cel mult 254, plus „niciunul").
    Cuvântul NU e scris nicăieri în timpul rundei: e doar în capul jucătorului.
  - /api/judge, la final: dacă pisica l-a prins, cuvântul e încercarea confirmată; altfel jucătorul e
    obligat să-l spună. Jev verifică fiecare indiciu (e adevărat? e util? conține cuvântul?), iar codul
    verifică dacă jucătorul a spus „nu” la o încercare care era chiar cuvântul lui.
Replicile jocului sunt șabloane fixe în game.py.

Serverul e fără stare: browserul trimite la fiecare pas toată conversația.
"""

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from typesafe_sdk import (
    Choice,
    Noul,
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
MAX_CONVERSATION = 60  # mesaje în total (jucător + joc)
MAX_TEXT = 300
JEV_TIMEOUT = 15  # secunde; o cerere normală durează sub o secundă
JUDGE_WORKERS = 8  # câte indicii verificăm în paralel la final

GRAPH = game.Graph.load()
WORD_SET = set(GRAPH.words)
WORDS_BY_LOWER = {w.lower(): w for w in GRAPH.words}

CONTEXT = (
    "Joc de ghicit cuvinte. Jucătorul se gândește la un cuvânt și îl descrie în conversație, "
    "fără să-l spună. Jocul încearcă un cuvânt după fiecare indiciu; dacă jucătorul scrie alt indiciu, "
    "încercarea a fost greșită. `cuvinte_respinse` sunt cuvintele încercate greșit. O încercare greșită "
    "respinge doar acel cuvânt exact: un sinonim sau un cuvânt apropiat poate fi în continuare cuvântul jucătorului."
)
GUESS_ANSWER = Choice(
    instructions="Ultimul mesaj al jocului a fost o încercare de a ghici cuvântul. "
    "Ce a răspuns jucătorul în ultimul lui mesaj?",
    criteria={
        "da": "Jucătorul confirmă: jocul a ghicit cuvântul.",
        "nu": "Jucătorul spune că nu e cuvântul, sau scrie un indiciu nou fără să confirme.",
    },
)
CATEGORY_QUESTION = Choice(
    instructions="În care categorie intră cuvântul la care se gândește jucătorul, după tot ce a spus în conversație?",
    criteria={cid: c["descriere"] for cid, c in GRAPH.categories.items()},
)

JUDGE_CONTEXT = (
    "Joc de ghicit cuvinte. Jucătorul a descris cuvântul lui fără să-l spună, iar acum l-a dezvăluit. "
    "Verificăm fiecare indiciu, în contextul conversației de până la el."
)
JUDGE_QUESTIONS = {
    "e_indiciu": Noul(
        instructions="Spune `indiciu` ceva despre cuvântul jucătorului (o informație, adevărată sau nu)?",
        criteria={
            "true": "Mesajul descrie cuvântul: ce e, cum arată, la ce folosește, cu ce seamănă, "
            "cu ce diferă de o încercare a jocului.",
            "false": "Mesajul e doar o reacție sau o vorbă fără informație (hmm, ok, haha, nu, aproape, mai încearcă).",
        },
    ),
    "adevarat": Noul(
        instructions="Este adevărat `indiciu` despre `cuvant`, în contextul conversației?",
        criteria={
            "true": "Indiciul e adevărat pentru sensul obișnuit al cuvântului (sau pentru un sens cunoscut al lui).",
            "false": "Indiciul e fals pentru cuvânt: spune ceva ce nu se potrivește.",
        },
    ),
    "util": Noul(
        instructions="Ajută `indiciu` cu adevărat la ghicirea lui `cuvant`?",
        criteria={
            "true": "Indiciul restrânge mult posibilitățile spre cuvânt (de exemplu: „gătești în ea” pentru tigaie).",
            "false": "Indiciul e atât de general încât se potrivește la aproape orice (de exemplu: „e un lucru”, "
            "„există”), sau nu spune nimic despre cuvânt.",
        },
    ),
    "spune_cuvantul": Noul(
        instructions="Conține `indiciu` chiar cuvântul `cuvant` sau o formă a lui (plural, articulat, diminutiv)?"
    ),
}


def word_question(words):
    return Choice(
        instructions="La care dintre aceste cuvinte se gândește jucătorul, după tot ce a spus în conversație? "
        f"Alege `{game.NONE}` dacă niciun cuvânt nu se potrivește.",
        criteria={
            **{w: None for w in words},
            game.NONE: "Niciun cuvânt din listă nu se potrivește cu descrierea.",
        },
    )


class BadRequest(Exception):
    pass


def parse_conversation(payload):
    conversation = payload.get("conversation")
    if not isinstance(conversation, list) or not 0 < len(conversation) <= MAX_CONVERSATION:
        raise BadRequest("Conversație invalidă.")
    for m in conversation:
        if not isinstance(m, dict) or m.get("from") not in ("player", "game"):
            raise BadRequest("Mesaj invalid.")
        if not isinstance(m.get("text"), str) or not 0 < len(m["text"].strip()) <= MAX_TEXT:
            raise BadRequest(f"Un mesaj trebuie să aibă între 1 și {MAX_TEXT} de caractere.")
    return conversation


def parse_turn(payload):
    conversation = parse_conversation(payload)
    rejected = payload.get("rejected", [])
    guess = payload.get("guess")
    next_guess = payload.get("next_guess")
    if conversation[-1]["from"] != "player":
        raise BadRequest("Ultimul mesaj trebuie să fie al jucătorului.")
    if not isinstance(rejected, list) or not all(w in WORD_SET for w in rejected):
        raise BadRequest("Listă de cuvinte respinse invalidă.")
    if guess is not None and guess not in WORD_SET:
        raise BadRequest("Încercare invalidă.")
    if next_guess is not None and next_guess not in WORD_SET:
        raise BadRequest("Ghicire de rezervă invalidă.")
    return conversation, rejected, guess, next_guess


def parse_judge(payload):
    conversation = parse_conversation(payload)
    word = payload.get("word")
    rejected = payload.get("rejected", [])
    if not isinstance(word, str) or not 0 < len(word.strip()) <= 60:
        raise BadRequest("Spune cuvântul tău.")
    if not isinstance(rejected, list) or not all(isinstance(w, str) for w in rejected):
        raise BadRequest("Listă de încercări invalidă.")
    return word.strip(), conversation, rejected, bool(payload.get("escaped"))


def as_state_messages(conversation):
    return [{"cine": "jucător" if m["from"] == "player" else "joc", "text": m["text"].strip()} for m in conversation]


def mentioned_words(conversation):
    """Cuvintele din vocabular scrise de jucător. Regula e că nu spune cuvântul, deci nu pot fi răspunsul."""
    text = " ".join(m["text"].lower() for m in conversation if m["from"] == "player")
    tokens = set(re.findall(r"[a-zăâîșțşţ-]+", text.replace("ş", "ș").replace("ţ", "ț")))
    return {w for w in WORD_SET if (w.lower() in text if " " in w else w.lower() in tokens)}


def play_turn(conversation, rejected, guess, next_guess):
    """Un pas al pisicii: două cereri la Jev (subcategorie, apoi cuvânt), apoi game.next_turn alege încercarea.

    guess: încercarea la care răspunde jucătorul acum. Căutăm speculativ fără ea; dacă Jev vede că
    jucătorul a confirmat-o, runda se termină („caught”) și rezultatul căutării nu mai contează.
    """
    rejected = rejected + [guess] if guess and guess not in rejected else list(rejected)
    state = {"context": CONTEXT, "conversatie": as_state_messages(conversation), "cuvinte_respinse": sorted(rejected)}
    questions = {"categorie": CATEGORY_QUESTION}
    if guess:
        questions["raspuns_incercare"] = GUESS_ANSWER
    first = jev.system_one(state=state, questions=questions)
    if guess and first.choices["raspuns_incercare"].probabilities.get("da", 0.0) >= 0.5:
        return {"kind": "caught", "word": guess, "message": f"Te-am prins! 🐱 Era „{guess}”."}

    excluded = set(rejected) | mentioned_words(conversation)
    if next_guess in excluded:
        next_guess = None
    words, coverage = GRAPH.select_words(first.choices["categorie"].probabilities, excluded)
    second = jev.system_one(state=state, questions={"cuvant": word_question(words)})
    # Probabilitatea finală a unui cuvânt: cât acoperă subcategoriile alese × alegerea lui Jev între cuvinte.
    probs = {w: coverage * p for w, p in second.choices["cuvant"].probabilities.items() if w != game.NONE}
    probs[game.NONE] = max(0.0, 1.0 - sum(probs.values()))
    turn = game.next_turn(probs, rejected, after_wrong_guess=bool(rejected), next_guess=next_guess)
    return {**turn, "rejected": rejected}


def judge_round(word, conversation, rejected, escaped):
    """Verifică fiecare mesaj al jucătorului față de cuvântul dezvăluit și calculează scorul."""
    known = WORDS_BY_LOWER.get(word.lower())
    word = known or word
    lied_on = next((w for w in rejected if w.lower() == word.lower()), None)
    messages = as_state_messages(conversation)
    clue_positions = [i for i, m in enumerate(conversation) if m["from"] == "player"]

    def judge(i):
        state = {"context": JUDGE_CONTEXT, "cuvant": word, "conversatie_anterioara": messages[:i], "indiciu": messages[i]["text"]}
        result = jev.system_one(state=state, questions=JUDGE_QUESTIONS)
        judgment = {name: round(answer.noul, 3) for name, answer in result.nouls.items()}
        verdict = game.judge_clue(judgment)
        return {"text": messages[i]["text"], "verdict": verdict, "label": game.VERDICTS[verdict], **judgment}

    with ThreadPoolExecutor(JUDGE_WORKERS) as pool:
        clues = list(pool.map(judge, clue_positions))
    verdicts = [c["verdict"] for c in clues]
    return {"word": word, "clues": clues, **game.score_round(verdicts, escaped, lied_on, known_word=bool(known))}


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/words":
            # Browserul verifică local că cuvântul ales e în dicționar, fără să-l trimită.
            self.send_json(200, {"words": GRAPH.words, "max_guesses": game.MAX_GUESSES})
            return
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
        routes = {
            "/api/turn": lambda p: play_turn(*parse_turn(p)),
            "/api/judge": lambda p: judge_round(*parse_judge(p)),
        }
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
    print(f"Pisica și șoarecele: {len(GRAPH.words)} cuvinte în {len(GRAPH.categories)} categorii")
    print(f"Rulează pe http://localhost:{PORT}")
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()
