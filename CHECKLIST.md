# Checklista – innan du kör sittningen

Allt du (operatören) faktiskt behöver fylla i, dubbelkolla eller trycka på
innan utskick går till 126 riktiga personer. Ordning uppifrån och ner.

## 1. Data in

- [ ] `data/Grupper.xlsx` är årets riktiga export, inte en gammal/test-fil.
  Kör `python3 import_participants.py Grupper.xlsx` och läs igenom felen
  skriptet ger (saknade fält, dubbla Grupp-ID).
- [ ] Antal par är en **udda multipel av 3** (63, 69, …). Skriptet varnar
  annars.
- [ ] **`addresses.py` → `MANUAL_FIXES`** är hårdkodad mot *förra* årets
  Grupp-ID:n (18 adresser). Dessa stämmer nästan garanterat inte mot en ny
  deltagarlista – rensa tabellen och bygg om den från de fel `geocode.py`
  faktiskt listar för i år, annars rättas fel adresser för fel par.

### Innan en ny/uppdaterad gruppfil laddas upp (samma eller nytt år)

De flesta genererade filerna (`participants.json`, `geocoded.json`,
`travel.json`, `schedule.json`, `web/data.json`, `out/*`) skrivs över
automatiskt när pipelinen körs igen – rör dem inte för hand. Två filer gör
**inte** det och måste nollställas manuellt, annars läcker gammal data in i
den nya sittningen:

- [ ] **`data/send_log.json`** – raderas/töms. Den är nyckel:ad på
  Grupp-ID, inte person. Om nya filen återanvänder samma ID:n som förra
  körningen visar comms-sidan annars en helt ny person som "redan
  skickat/levererat" trots att hen aldrig fått något SMS – risk att man
  missar att skicka till riktiga mottagare.
- [ ] **`data/baseline.json`** – raderas. `solve.py` återanvänder den filen
  så fort `source` (google/haversine) och `SEED` matchar – den kollar
  **inte** om antal par eller adresserna faktiskt ändrats. Med ny data blir
  före/efter-jämförelsen annars missvisande, och om antalet par ändras kan
  det krascha (permutationerna är dimensionerade för förra årets ringstorlek).

## 2. Nycklar och konton (`.env`)

- [x] `GOOGLE_API_KEY` ifylld.
- [x] `ELKS_API_USERNAME` / `ELKS_API_PASSWORD` ifyllda.
- [x] `ELKS_FROM=Kultur` – inom 46elks gräns på 11 tecken (det gamla
  `Kulturnämnden`, 13 tecken + åäö, gjorde att **alla** riktiga SMS-utskick
  skulle misslyckats tyst).
- [x] `DUBBLE_CHECK_TEXTS_TO_NUMBER` ifylld (ditt testnummer).
- [ ] Dubbelkolla i Google Cloud Console att **Geocoding API**, **Distance
  Matrix API**, **Maps JavaScript API** (+ **Directions API** om "Visa
  verklig rutt"/alla-rutter-switchen ska funka) är påslagna och att
  projektet har billing aktiverat.

## 3. Datum och adress (`config.py`)

- [x] `REACHOUT_DATE = "2026-11-08"` – deadline för deltagare att rapportera
  fel i Dubbelkolla-SMS:et.
- [ ] `EVENT_DATE = "2026-11-14"` – rätt datum för i år?
- [ ] `ARRIVE_STARTER/MAIN/DESSERT/AFTERPARTY` (17:00/18:30/20:30/22:00) –
  stämmer tiderna med årets upplägg?
- [ ] `AFTERPARTY_ADDRESS` (Brinellvägen 23 – Issy) – rätt lokal bokad för
  i år, rätt adress?
- [ ] REACHOUT_DATE ligger tillräckligt tidigt före EVENT_DATE för att
  faktiskt hinna rätta fel innan Schema-SMS:et går ut.

## 4. Kör pipelinen

- [ ] `python3 run.py --dry` först – kontrollera att adresserna geokodas
  rimligt (ingen pin i fel stad) innan något kostar pengar.
- [ ] Läs **"NEEDS ATTENTION"**-listan `geocode.py` skriver ut (adresser
  utanför Stockholmsområdet eller markerade som ungefärliga av Google) och
  fixa dem i `addresses.py` innan nästa steg.
- [ ] Kör fristående `python3 travel.py` (utan `--yes`) och läs
  kostnadsuppskattningen **innan** du kör `python3 run.py` på riktigt –
  `run.py` skickar `--yes` automatiskt och frågar inte en gång till.
- [ ] Efter `solve.py`: kontrollera utskriften –
  **"hosts over HOST_ARRIVE_CAP" ska vara 0**, ring-violations 0, och
  brute-force-verifieringen ("inget par träffas två gånger") ska gå igenom
  utan avbrott.
- [ ] Bläddra igenom `out/tunnelbanesittning.xlsx` (särskilt
  Dubbelkolla-fliken) innan utskick.

## 5. Meddelandetexter

- [ ] Läs igenom alla 9 mallvarianter på `comms.html` (de nya standardtexterna
  är nu inbakade i `templates.py`, men läs ändå igenom – ordval, "Issy",
  klockslag, undertecknare "Kulturnämnden" m.m. ska stämma för i år).
- [ ] Tryck **"Skicka testutskick (alla mallar)"** och läs alla 9 SMS på din
  egen telefon innan du låser upp riktiga utskick.

## 6. Skicka på riktigt

- [ ] Skicka **Dubbelkolla info** i god tid före `REACHOUT_DATE` så folk hinner
  svara på fel.
- [ ] Om någon rapporterar fel adress/allergi/alkoholpreferens: uppdatera
  `data/participants.csv`, kör `python3 run.py` igen (cachen gör att bara
  det ändrade kostar något), skicka inte Dubbelkolla-SMS:et igen till alla.
- [ ] Skicka **Schema** tidigt på kvällsdagen.
- [ ] Skicka **Förrätt / Varmrätt / Efterrätt / Efterfest** vid respektive
  tidpunkt.
- [ ] Lås upp SMS-reglaget på `comms.html` **precis innan** varje utskick,
  inte i förväg – det nollställs vid omladdning men inte annars.

## 7. Under kvällen

- [ ] `serve.py` kör och kartan är nåbar om du behöver slå upp något
  (adress, telefonnummer) under kvällen.
- [ ] Håll koll på **"Visa mottagare"**-varningarna på comms-sidan efter
  varje utskick – grupper med `failed`/`skipped` måste kontaktas manuellt.
