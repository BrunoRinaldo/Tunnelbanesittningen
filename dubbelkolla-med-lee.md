# Dubbelkolla med Lee – innan ny gruppfil laddas upp

Genomgång att göra tillsammans med Lee (TBS-ansvarig i år) innan den nya
gruppfilen laddas upp och pipelinen körs på riktigt.

## 1. Måste raderas/nollställas manuellt

Allt annat skriver pipelinen över automatiskt (se längst ner) – de här tre
gör det **inte**, och om de lämnas kvar läcker gammal data in i den nya
sittningen:

- [ ] **`data/send_log.json`** – SMS-loggen är nyckel:ad på Grupp-ID, inte
  person. Om nya filen återanvänder samma ID:n (väldigt troligt) visar
  comms-sidan en helt ny person som "redan skickat"/"levererat" fast hen
  aldrig fått något SMS – risk att man missar att skicka till riktiga
  mottagare.
- [ ] **`data/baseline.json`** – återanvänds av `solve.py` så fort
  datakälla + SEED matchar, oavsett om adresserna faktiskt ändrats. Med ny
  data blir före/efter-jämförelsen missvisande, och om antal par ändras kan
  det krascha.
- [ ] **`addresses.py` → `MANUAL_FIXES`** – knuten till *förra* filens
  Grupp-ID-nummer, inte till personer. Läs igenom manuellt och bygg om
  utifrån de fel `geocode.py` listar för den nya filen, annars kan en
  adressfix hamna på fel par.

## 2. Inställningar att gå igenom tillsammans

- [ ] **`.env`**: `GOOGLE_API_KEY`, `ELKS_API_USERNAME`/`PASSWORD`,
  `ELKS_FROM` (max 11 tecken – redan fixat till `Kultur`),
  `DUBBLE_CHECK_TEXTS_TO_NUMBER` (rätt person/telefon för testutskick i år?).
- [ ] **`config.py`**: `EVENT_DATE` (2026-11-14), `REACHOUT_DATE`
  (2026-11-08), `ARRIVE_STARTER/MAIN/DESSERT/AFTERPARTY`,
  `AFTERPARTY_ADDRESS` – stämmer allt med årets upplägg och bokad lokal?
- [ ] **Google Cloud**: rätt API:er (Geocoding, Distance Matrix, Maps
  JavaScript, ev. Directions) påslagna + billing aktiverat.
- [ ] **Efter körning**: läs `solve.py`s utskrift – "hosts over cap" ska
  vara 0, ring-violations 0, brute-force-verifieringen ska gå igenom.
- [ ] **SMS-mallarna** i `comms.html` – läs igenom allt, kör "Skicka
  testutskick" och läs alla 9 texter innan låsreglaget öppnas för riktiga
  mottagare.

## 3. Skrivs över automatiskt – rör inte för hand

`data/participants.json` / `.csv`, `data/geocoded.json`, `data/travel.json`,
`data/schedule.json`, `web/data.json`, `out/*`. `import_participants.py`
tar dessutom automatiskt en backup av gamla `participants.json` till
`.bak`. `cache/`-mappen är säker att behålla (nycklad på adress/
koordinater, inte person) och sparar pengar på geokodning/restider.

Fullständig steg-för-steg-checklista för hela kvällen finns i
[`CHECKLIST.md`](CHECKLIST.md).
