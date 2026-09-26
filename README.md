# Ghicește cuvântul

Te gândești la un cuvânt și îl descrii în conversație, **fără să-l spui**. Jocul încearcă să-l ghicească
din ce povestești. **Cuvântul nu e scris nicăieri**: nici în cod, nici pe server, nici în browser.

Nu folosește niciun LLM care generează text. În locul lui e **Jev** de la [TypeSafe AI](https://typesafe.ai),
un clasificator one-shot care întoarce probabilități, nu proză.

## Cum funcționează

1. **Tu descrii.** Scrii liber, în câte mesaje vrei: „e un animal”, „stă pe lângă casă”, „latră”.
2. **Jev citește toată conversația.** La fiecare mesaj, într-o singură cerere (~0,3 s), Jev dă o
   probabilitate pentru fiecare cuvânt din `data/cuvinte.txt`, plus „niciunul” (niciun cuvânt nu se potrivește).
3. **Jocul decide (fără model, în Python).** `game.py` ghicește când un cuvânt trece de 70%. Altfel
   îți cere mai multe indicii, cu replici fixe. După 8 mesaje ghicește oricum.
4. **Răspunzi la ghicire.** Cu butoanele Da / Nu sau liber („exact!”, „nu, e mai mic”). Dacă răspunsul
   e nu, cuvântul e eliminat, iar ce ai scris contează ca indiciu nou. După 5 ghiciri greșite, jocul renunță.

Fișiere:
- `server.py`: server HTTP mic, fără stare (browserul trimite toată conversația la fiecare pas).
- `game.py`: decide ce răspunde jocul din probabilitățile lui Jev.
- `data/cuvinte.txt`: cuvintele pe care jocul le poate ghici (maxim 254).
- `public/index.html`: interfața de chat, JavaScript simplu.
- `test_game.py`: teste pentru motor, fără Jev.

## Pornire

Ai nevoie de Python 3.10+ și de o cheie API TypeSafe (fără ea, serverul nu pornește).

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export TYPESAFE_API_KEY=...   # sau pune-o în .env și: set -a; source .env; set +a
.venv/bin/python server.py
# deschide http://localhost:8000
```

Variabile opționale: `PORT` (implicit 8000), `TYPESAFE_DEFAULT_MODEL` (implicit `jev-latest`).

## Cum îl faci mai bun

- **Mai multe cuvinte:** adaugă-le în `data/cuvinte.txt`. Nu trebuie să construiești nimic,
  merge imediat după ce repornești serverul. Limita e 254 de cuvinte (Jev acceptă 255 de variante într-o alegere).
- Pragurile (când ghicește, după câte mesaje ghicește oricum) și replicile jocului sunt la începutul lui `game.py`.

## Teste

```bash
python3 -m unittest test_game -v
```
