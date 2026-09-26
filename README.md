# Ghicește cuvântul

Un joc de tip „20 de întrebări”: te gândești la un cuvânt, iar Claude încearcă să-l ghicească
doar din conversație. **Cuvântul nu e scris nicăieri**: nici în cod, nici în prompt, nici în browser.
Tu doar răspunzi la întrebări (Da / Nu / Nu știu / Probabil / Probabil nu, sau liber, cu text).

## Cum funcționează

- `server.js`: un server Node mic, fără stare. La fiecare răspuns trimite toată conversația la
  Claude API (`claude-opus-5`, adaptive thinking, efort `medium`) și primește înapoi un JSON
  structurat: o întrebare, o ghicire sau finalul jocului, plus lista de cuvinte candidate și cât de sigur e.
- `public/index.html`: interfața de chat. Istoria conversației e ținută doar în memoria paginii.
- Modelul pune întrebări care împart spațiul de cuvinte cât mai egal, apoi ghicește. Dacă greșește, continuă.
- Bifează „Arată la ce cuvinte mă gândesc” ca să vezi candidații după fiecare întrebare.
- Sunt activate fallback-urile server-side (`fallbacks: "default"`): dacă modelul refuză o cerere,
  API-ul o reîncearcă automat pe alt model.

## Pornire

```bash
npm install
export ANTHROPIC_API_KEY=sk-ant-...
npm start
# deschide http://localhost:3000
```

Variabile opționale: `PORT` (implicit 3000), `CLAUDE_MODEL` (implicit `claude-opus-5`).
