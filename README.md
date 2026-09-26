# Ghicește cuvântul

Un joc de tip „20 de întrebări”: te gândești la un cuvânt, iar jocul încearcă să-l ghicească
doar din răspunsurile tale. **Cuvântul nu e scris nicăieri**: nici în cod, nici pe server, nici în browser.
Răspunzi cu butoane (Da / Nu / Nu știu / Probabil / Probabil nu) sau liber, cu text.

Nu folosește niciun LLM care generează text. În locul lui e **Jev** de la [TypeSafe AI](https://typesafe.ai),
un clasificator one-shot care întoarce probabilități, nu proză.

## Cum funcționează

1. **Baza de cunoștințe (o singură dată, cu Jev).** `build_kb.py` îi dă lui Jev fiecare cuvânt din
   `data/cuvinte.txt` și toate întrebările da/nu din `data/intrebari.json`. Jev răspunde one-shot cu
   P(da) pentru fiecare pereche cuvânt × întrebare. Rezultatul se salvează în `data/kb.json`.
2. **Jocul (fără model, în Python).** `game.py` ține pentru fiecare cuvânt cât de probabil e,
   actualizează după fiecare răspuns (regula lui Bayes) și alege întrebarea care împarte cel mai bine
   cuvintele rămase (câștig maxim de informație). Când un cuvânt trece de 60%, ghicește.
   Dacă ghicirea e greșită, cuvântul e eliminat și jocul continuă.
3. **Răspunsuri libere (live, cu Jev).** Când scrii „nu cred”, „de obicei da” sau „habar n-am”, Jev
   clasifică răspunsul în da / probabil / nu știu / probabil nu / nu, iar probabilitățile lui intră
   direct în calcul.

Fișiere:
- `server.py`: server HTTP mic, fără stare (browserul trimite răspunsurile de până acum la fiecare pas).
- `game.py`: motorul jocului.
- `build_kb.py`: construiește `data/kb.json` cu Jev.
- `public/index.html`: interfața de chat, JavaScript simplu.
- `test_game.py`: teste pentru motor, cu jucători simulați.

## Pornire

Ai nevoie de Python 3.10+ și de o cheie API TypeSafe.

```bash
pip install -r requirements.txt
export TYPESAFE_API_KEY=...
python3 build_kb.py      # o singură dată; din nou după ce adaugi cuvinte sau întrebări
python3 server.py
# deschide http://localhost:8000
```

Fără `TYPESAFE_API_KEY`, jocul pornește și merge cu butoanele (dacă ai deja `data/kb.json`),
dar răspunsurile scrise liber nu vor funcționa.

Variabile opționale: `PORT` (implicit 8000), `TYPESAFE_DEFAULT_MODEL` (implicit `jev-latest`).

## Cum îl faci mai bun

- **Mai multe cuvinte:** adaugă-le în `data/cuvinte.txt` și rulează `python3 build_kb.py`.
  Se calculează doar perechile noi.
- **Mai multe întrebări:** adaugă-le în `data/intrebari.json` (un `id` unic și textul) și rulează din nou
  `build_kb.py`. Întrebările care separă bine grupuri mari de cuvinte ajută cel mai mult.
- Pragurile (când ghicește, câte întrebări pune maxim) sunt la începutul lui `game.py`.

## Teste

```bash
python3 -m unittest test_game -v
```
