# Pisica și șoarecele

Tu ești **șoarecele**: te gândești la un cuvânt (oricare dintre ~5.000 de substantive românești) și dai indicii,
**fără să-l spui și fără să-l scrii nicăieri**. Jocul e **pisica**: după fiecare indiciu încearcă un cuvânt.
Fiecare indiciu adevărat și util îți aduce un punct, până te prinde. Dar indiciile trebuie să fie cinstite:
la final ești obligat să spui cuvântul, iar pisica le verifică pe toate.

Nu folosește niciun LLM care generează text. În locul lui e **Jev** de la [TypeSafe AI](https://typesafe.ai),
un clasificator one-shot care întoarce probabilități, nu proză.

## Regulile

1. **Cuvântul e doar în capul tău.** Nu-l scrii la început: pisica (serverul, Jev, pagina) nu-l poate vedea.
2. **Dai indicii, contra cronometru.** Ai 30 de secunde pentru fiecare indiciu. Dacă timpul expiră,
   pisica mai încearcă o dată, fără indiciu nou (și tu nu primești punct).
3. **Răspunzi la încercări.** Dacă pisica a ghicit, apeși „Da, m-ai prins!” (sau scrii „da”). Orice indiciu nou
   înseamnă „nu”.
4. **Runda se termină** când pisica te prinde, când renunță (după 20 de încercări greșite) sau când te predai.
5. **Ești obligat să spui cuvântul.** Dacă pisica te-a prins, cuvântul e încercarea confirmată: nu scrii nimic.
   Altfel ai 60 de secunde să-l spui; nu poți începe alt joc până atunci. Dacă timpul expiră, runda e pierdută.
6. **Verificarea.** Jev verifică fiecare indiciu față de cuvânt, în contextul conversației de până la el:
   - **adevărat și util**: +1 punct;
   - **prea general** („e un lucru”): 0 puncte;
   - **poate fi fals** (Jev nu e sigur): 0 puncte, fără descalificare;
   - **fals** sau **conține cuvântul** (și forme ca „tigăiță”): **descalificare, scor 0**;
   - mesajele care nu sunt indicii („hmm”, „da”) nu se judecă.
   În plus, dacă ai spus „nu” la o încercare care era chiar cuvântul tău: **descalificare**.
   Dacă cuvântul nu e în dicționarul pisicii, runda nu se punctează (pisica n-avea cum să te prindă).
   Dacă pisica renunță, primești 5 puncte bonus. Recordul se păstrează în browser.

Asta e tensiunea jocului: fiecare indiciu trebuie să fie adevărat și util, dar să spună cât mai puțin.

**Limită cunoscută:** pentru că nu scrii cuvântul la început, jocul nu poate dovedi că nu l-ai schimbat în timpul
rundei. Indiciile fac asta greu (toate trebuie să fie adevărate pentru cuvântul spus la final), dar nu imposibil.

## Cum vânează pisica

1. **Jev caută în graf.** Jev poate alege între cel mult 255 de variante într-o întrebare, așa că
   cuvintele stau într-un graf: 126 de subcategorii (de exemplu „animale domestice”, „emoții neplăcute”,
   „unelte”), fiecare cu cel mult 254 de cuvinte. Un cuvânt poate fi în mai multe subcategorii.
   La fiecare indiciu, Jev citește toată conversația, în două cereri (~0,6 s în total):
   - care subcategorii se potrivesc (păstrăm pe cele mai probabile, până la 95% din probabilitate);
   - care cuvânt, doar dintre cuvintele subcategoriilor alese, plus „niciunul”.
2. **Pisica încearcă un cuvânt (fără model, în Python).** `game.py` alege cel mai probabil cuvânt. Replica arată
   cât e de sigură: „Poate „câine”?”, „E cumva „câine”?”, „Te gândești la „câine”?”. Pisica ține minte al doilea
   candidat, ca după o încercare greșită să încerce sinonimul („Atunci „reparație”?”).
3. Cuvintele pe care le scrii tu nu pot fi răspunsul (regula e că nu spui cuvântul), așa că pisica nu le încearcă.

Fișiere:
- `server.py`: server HTTP mic, fără stare. `/api/turn` (pisica vânează și vede dacă ai confirmat),
  `/api/judge` (verificarea finală), `/api/words` (dicționarul).
- `game.py`: graful, alegerea pisicii, verdictul pentru fiecare indiciu și scorul.
- `build_words.py`: face vocabularul (`data/cuvinte.txt`) din cele mai frecvente substantive.
- `build_graph.py`: așază cuvintele în subcategorii, cu Jev (`data/graf.json`).
- `data/categorii.json`: grupurile și subcategoriile, scrise de mână.
- `data/cuvinte_extra.txt` / `data/cuvinte_excluse.txt`: cuvinte adăugate sau scoase de mână.
- `public/index.html`: interfața de joc, JavaScript simplu.
- `test_game.py`: teste pentru motor, verdicte, scor și graf, fără Jev.

## Vocabularul

`build_words.py` pornește de la lista de frecvență din subtitrări OpenSubtitles
([hermitdave/FrequencyWords](https://github.com/hermitdave/FrequencyWords), CC BY-SA 4.0).
Păstrează doar cuvintele care sunt substantive în forma de dicționar în
[Lista Oficială de Cuvinte](https://dexonline.ro/scrabble) de la dexonline (LOC 6.0, GNU FDL).
Apoi Jev alege partea de vorbire obișnuită a fiecărui cuvânt și decide dacă e românesc și potrivit
pentru un joc de familie. Rămân primele 5.000 de substantive, în ordinea frecvenței.

## Pornire

Ai nevoie de Python 3.10+ și de o cheie API TypeSafe (fără ea, serverul nu pornește).

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export TYPESAFE_API_KEY=...   # sau pune-o în .env și: set -a; source .env; set +a
.venv/bin/python server.py
# deschide http://localhost:8000
```

`data/cuvinte.txt` și `data/graf.json` sunt deja în repo. Le faci din nou doar când schimbi vocabularul
sau categoriile.

Variabile opționale: `PORT` (implicit 8000), `TYPESAFE_DEFAULT_MODEL` (implicit `jev-latest`).

## Cum îl faci mai bun

- **Mai multe cuvinte:** adaugă-le în `data/cuvinte_extra.txt` sau rulează `build_words.py --count 8000`,
  apoi `build_graph.py` (calculează doar cuvintele noi).
- **Cuvinte greșite:** pune-le în `data/cuvinte_excluse.txt` și rulează din nou cele două scripturi.
- **Alte categorii:** schimbă `data/categorii.json` și rulează `build_graph.py --rebuild`. O subcategorie
  trebuie să aibă cel mult 254 de cuvinte (testele verifică asta); dacă are mai multe, împarte-o.
- Pragurile pisicii, pragurile verificării și punctajul sunt la începutul lui `game.py`.

## Teste

```bash
python3 -m unittest test_game -v
```
