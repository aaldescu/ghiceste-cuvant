import http from "node:http";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import Anthropic from "@anthropic-ai/sdk";

const here = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT) || 3000;
const MODEL = process.env.CLAUDE_MODEL || "claude-opus-5";
const MAX_TURNS = 40;

const client = new Anthropic();

// Cuvântul NU există nicăieri în sistem: nici în prompt, nici în server,
// nici în browser. Jucătorul doar răspunde la întrebări, iar modelul
// restrânge spațiul de cuvinte posibile din conversație.
const SYSTEM_PROMPT = `Ești „Ghicitorul", un joc de tip 20 de întrebări în limba română.
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
- "candidates": până la 3 cuvinte pe care le iei în calcul acum (poate fi listă goală la început).`;

const TURN_SCHEMA = {
  type: "object",
  properties: {
    kind: { type: "string", enum: ["question", "guess", "done"] },
    message: { type: "string" },
    guess: { type: "string" },
    confidence: { type: "number" },
    candidates: { type: "array", items: { type: "string" } },
  },
  required: ["kind", "message", "guess", "confidence", "candidates"],
  additionalProperties: false,
};

const START_MESSAGE =
  "M-am gândit la un cuvânt. Începe să pui întrebări ca să-l ghicești.";

// history: [{ role: "user" | "assistant", content: string }], fără primul mesaj
// (îl adăugăm aici). Serverul e fără stare: istoria vine de la browser.
async function nextTurn(history) {
  const messages = [{ role: "user", content: START_MESSAGE }, ...history];

  const response = await client.beta.messages.create({
    model: MODEL,
    max_tokens: 16000,
    system: SYSTEM_PROMPT,
    messages,
    thinking: { type: "adaptive" },
    output_config: {
      effort: "medium",
      format: { type: "json_schema", schema: TURN_SCHEMA },
    },
    betas: ["server-side-fallback-2026-07-01"],
    fallbacks: "default",
  });

  if (response.stop_reason === "refusal") {
    throw new GameError("Modelul a refuzat cererea. Încearcă un joc nou.");
  }
  if (response.stop_reason === "max_tokens") {
    throw new GameError("Răspunsul a fost trunchiat. Mai încearcă o dată.");
  }

  const text = response.content
    .filter((block) => block.type === "text")
    .map((block) => block.text)
    .join("");
  return JSON.parse(text);
}

class GameError extends Error {}

function validateHistory(history) {
  if (!Array.isArray(history) || history.length > MAX_TURNS * 2) return false;
  return history.every(
    (m, i) =>
      m &&
      typeof m.content === "string" &&
      m.content.length > 0 &&
      m.content.length < 4000 &&
      m.role === (i % 2 === 0 ? "assistant" : "user"),
  );
}

async function readJson(req) {
  let body = "";
  for await (const chunk of req) {
    body += chunk;
    if (body.length > 200_000) throw new GameError("Cerere prea mare.");
  }
  return JSON.parse(body || "{}");
}

function send(res, status, data) {
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(data));
}

const server = http.createServer(async (req, res) => {
  if (req.method === "POST" && req.url === "/api/turn") {
    try {
      const { history = [] } = await readJson(req);
      if (!validateHistory(history)) {
        return send(res, 400, { error: "Istoric de conversație invalid." });
      }
      return send(res, 200, await nextTurn(history));
    } catch (err) {
      if (err instanceof GameError) return send(res, 422, { error: err.message });
      if (err instanceof Anthropic.RateLimitError) {
        return send(res, 429, { error: "Prea multe cereri. Așteaptă puțin." });
      }
      if (err instanceof Anthropic.AuthenticationError) {
        return send(res, 500, { error: "Lipsește sau e greșită cheia ANTHROPIC_API_KEY." });
      }
      if (err instanceof Anthropic.APIError) {
        console.error("Claude API:", err.status, err.message);
        return send(res, 502, { error: "Eroare la Claude API. Mai încearcă." });
      }
      console.error(err);
      return send(res, 500, { error: "Eroare internă." });
    }
  }

  if (req.method === "GET" && (req.url === "/" || req.url === "/index.html")) {
    const html = await fs.readFile(path.join(here, "public", "index.html"));
    res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    return res.end(html);
  }

  res.writeHead(404);
  res.end("Not found");
});

server.listen(PORT, () => {
  console.log(`Ghicește cuvântul rulează pe http://localhost:${PORT} (model: ${MODEL})`);
});
