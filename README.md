# Tunnelbanesittning – logistik

63 par (126 personer) (eller något annat nummer y=3x + 3), tre rätter, 21 bord per rätt, 3 par per bord.
Varje par är värd exakt en gång. **Inget par träffar ett annat par mer än en gång
under hela kvällen** – det är garanterat av konstruktionen, inte hoppats fram.

Paren delas i tre ringar om 21 – ring 0 håller förrätt, ring 1 varmrätt, ring 2
efterrätt. Vilket par som hamnar i vilken ring är en beslutsvariabel med en mjuk
preferens mot Issy-avstånd (`ALPHA` i `config.py`); stort `ALPHA` ger tillbaka
den gamla hårda "längst bort = förrätt"-splitten. Restiden per par pressas ner
med en exakt linjär tilldelning per ring (`scipy.optimize.linear_sum_assignment`,
alternerad) plus simulated annealing ovanpå för de icke-linjära straffen.

---

## 0. Indata: deltagarlistan

Lägg **en Excel-fil** som `data/Grupper.xlsx` (kolumnerna nedan) – den råa
exporten från anmälningsformuläret, en rad per **par**. `import_participants.py`
läser den och skriver `data/participants.json`, som resten av pipelinen använder:

```bash
python3 import_participants.py               # läser data/Grupper.xlsx
python3 import_participants.py svar.xlsx     # eller valfri sökväg
```

`run.py` importerar `data/Grupper.xlsx` vid varje körning, eller filen du anger med
`python3 run.py --participants svar.xlsx`. Om deltagarlistan ändrats tas allt som
genererats från den gamla listan bort (kartdata, schema, restidsmatris, `out/`).
Cacharna behålls, så oförändrade adresser kostar inget att köra om.

### Så ska kalkylbladet se ut

Första raden är rubriker. En rad per par därefter. Kolumnordningen spelar ingen
roll och rubrikernas versaler/mellanslag på slutet ignoreras. Extra kolumner
(`Tidstämpel`, `Övrigt`) lämnas kvar orörda – de läses inte.

| Kolumn | Krav | Format |
|---|---|---|
| `Grupp-ID` | frivilligt | heltal, unika. Används som gruppnummer rakt igenom (kartan, meddelanden, xlsx). Saknas det får paret lägsta lediga nummer, i radordning |
| `Namn 1`, `Namn 2` | obligatoriskt | de två personerna i paret, ett namn i varje cell |
| `Adress` | obligatoriskt | fritext, precis som paret skrev den. Stavfel och tvetydiga gator rättas i kalkylbladet eller i `data/address_fixes.json` (§5). Alla adresser i Stockholms län fungerar |
| `Telefonnummer 1` | obligatoriskt | svenskt format, t.ex. `070-123 45 67`. `export.py` normaliserar till `+46` för SMS-gatewayen. SMS:en går hit |
| `Telefonnummer 2` | frivilligt | samma format. Visas bara i exporterna |
| `Mailadress` | frivilligt | en adress för paret. Visas bara i exporterna |
| `Allergier` | frivilligt | fritext. Tom = inga allergier |
| `Alkoholpreferenser` | frivilligt | hur många i paret som dricker alkohol: `0` = Två alkfri, `1` = En alkfri, en alkfull, `2` = Två alkfull (`ALCOHOL_BY_COUNT` i `config.py`). Fritext används som den står, tom = Två alkfull. Andra siffror stoppar importen |

Antal par: den här sittningen är gjord för **63 par (126 personer)**, men koden
räknar ringstorleken från antalet. Kravet är att antalet par är en **udda
multipel av 3** – …, 51, 57, **63**, 69, 75, … Då blir det tre lika stora ringar
med udda storlek (`N/3`), vilket krävs för att "inget par möts två gånger" ska
hålla (§6). `import_participants.py` varnar om antalet inte går jämnt upp i tre
ringar eller om ringstorleken blir jämn; `solve.py` avbryter i samma lägen.

`import_participants.py` avbryter med radnummer om en obligatorisk cell är tom,
ett `Grupp-ID` inte är ett heltal eller ett `Grupp-ID` förekommer två gånger.
Namn/adresser trimmas på blanksteg (inklusive `\xa0`). En befintlig
`data/participants.json` kopieras till `participants.json.bak` innan den skrivs
över.

### Vad pipelinen faktiskt läser

`data/participants.json` – en JSON-array med ett objekt per par, fälten
`group_id` (heltal), `name1`, `name2`, `address_raw`, `phone1`, `phone2`,
`email`, `allergies`, `alkoholpreferenser` (resten är strängar, tom sträng när
inget angavs). Du kan handredigera den direkt om du hellre vill. `data/*.xlsx`,
`participants.json` och `participants.csv` är gitignorerade – de innehåller
personuppgifter och stannar lokalt.

---

## 1. Nyckel och localhost

Kartan körs lokalt på **http://localhost:8000** (`serve.py`).

### Enklaste vägen: en enda nyckel

Skapa filen `.env` i samma mapp som `config.py` och lägg en rad i den:

```
GOOGLE_API_KEY=AIza...din nyckel...
ELKS_API_USERNAME= ...din nyckel...
ELKS_API_PASSWORD= ...din nyckel...
ELKS_FROM=Kulturnämnden
```

Klart. Den nyckeln används både av Python-skripten och av kartan.
Sätt Application restrictions till **None** och API restrictions till:
Maps JavaScript API, Geocoding API, Distance Matrix API
(+ Directions API om du vill ha knappen "Visa verklig rutt").

Eftersom allt kör på din egen dator räcker det. Enda regeln: lägg inte
upp nyckeln på nätet. `.env` är gitignorerad.

### Om du vill dela upp den (frivilligt)

Koden gör två olika sorters anrop. Python-skripten anropar Google från din
dator. Webbsidan anropar Google från webbläsaren – och där syns nyckeln i
sidkällan för alla som öppnar sidan. Därför kan man låsa en webbnyckel till
vissa URL:er. Men en nyckel som är låst till URL:er slutar fungera från Python,
så då behövs två. Bara värt det om du någon gång lägger kartan på en riktig
server.

**Webbnyckel** (`GOOGLE_BROWSER_KEY`) – Application restrictions → *Websites*:

```
http://localhost:8000/*
http://127.0.0.1:8000/*
```

API restrictions: **Maps JavaScript API** (+ **Directions API** om du vill att
knappen "Visa verklig rutt" ska rita faktiska gångvägar/tunnelbanelinjer).

**Servernyckel** (`GOOGLE_SERVER_KEY`) – Application restrictions → *None*
(eller *IP addresses* om du har fast IP). API restrictions: **Geocoding API**
och **Distance Matrix API**.

APIer att aktivera i projektet: Maps JavaScript API, Geocoding API,
Distance Matrix API, (Directions API).

Lägg nycklarna i en fil `.env` bredvid `config.py`:

```
GOOGLE_SERVER_KEY=AIza...
GOOGLE_BROWSER_KEY=AIza...
```

`.env` är gitignorerad.

### Vad det kostar

| Anrop | Antal element |
|---|---|
| Geocoding | 64 adresser, en gång (cachas) |
| Distance Matrix – gång (63×63, tidsoberoende) | ~3 900 |
| Distance Matrix – kollektivt (63×63 × ankomst 18:30 + 20:30) | ~6 900 |
| Distance Matrix – alla→Issy (ankomst 22:00) | 63 |

Sedan ringtillhörigheten blev en beslutsvariabel kan vilket par som helst hamna
intill vilket som helst, så hela 63×63-matrisen hämtas. `travel.py` skriver ut
elementantal och en uppskattad kostnad **innan** något anrop görs och kräver
`--yes` för att faktiskt spendera. Par där gångtiden ≤ `TRANSIT_SKIP_MIN`
(12 min) hoppar kollektivanropet. Allt cachas i `cache/` med oförändrad
nyckelstruktur, så omkörningar och redan hämtade delmatriser kostar noll.

---

## 2. Kör

```bash
python3 -m pip install openpyxl numpy scipy   # om de saknas
cp .env.example .env                           # fyll i nycklarna

python3 import_participants.py Grupper.xlsx     # deltagarlistan -> data/participants.json (§0)
python3 run.py --dry     # ingen API-nyckel: OpenStreetMap-geokodning + fågelvägsrestider
python3 run.py           # riktiga Google-restider (hämtar hela 63×63, kräver --yes internt)
python3 serve.py         # kartan på http://localhost:8000
```

`run.py` kör importsteget åt dig varje gång, från `data/Grupper.xlsx` eller med
`python3 run.py --participants Grupper.xlsx`.

Stegen var för sig: `import_participants.py`, `geocode.py`, `travel.py --yes`,
`solve.py --calibrate`, `solve.py`, `export.py`. `solve.py` skriver ut en
före/efter-tabell (medel, std,
p50, p90, max, längsta etapp, etapper över `LEG_CAP`, längsta värdetapp,
värdar över `HOST_ARRIVE_CAP`, ringordningsbrott).

`--dry` finns för att du ska kunna se att adresserna geokodas rätt innan du
sätter upp billing. Restiderna därifrån är uppskattningar och ska inte skickas
till 126 personer.

---

## 3. Filer ut

| Fil | Innehåll |
|---|---|
| `out/tunnelbanesittning.xlsx` | Översikt · Grupper · **Schema per grupp** · Bord · Värdinfo · **Dubbelkolla info · Schema · Förrätt · Varmrätt · Efterrätt** |
| `out/meddelanden.csv` | `group, moment, role, name1, name2, phone1, phone2, email, message` – rakt in i en SMS-gateway |
| `out/schema.csv` | maskinläsbart schema, en rad per par (inkl. allergier + alkoholpreferenser, egna och gästernas) |
| `web/data.json` | matas till kartan |

Varje grupp får **fem** meddelanden: *Dubbelkolla info* (adress, allergier,
alkoholpreferens), *Schema* (skickas tidigt på dagen – alla adresser kvällen
igenom, med tider, och vilken rätt gruppen är värd för), och sedan ett per rätt.
I rättmeddelandet ser värden gästernas allergier/alkoholpreferenser (utan namn)
och gästerna bara adressen de ska till. Adresser skrivs som `gata nr, postnr
stad`. **Ingen angiven alkoholpreferens = paret vill ha alkohol.** De fem
flikarna i xlsx:en matchar `moment`-kolumnen i `meddelanden.csv`.

Bladet **Värdinfo** är det du skickar till värdarna: vilka som kommer, när, med
telefonnummer och allergierna vid just det bordet.

---

## 4. Kartan

- En pin per par, på deras adress, färgad efter vilken rätt de är värd för:
  orange = förrätt, blå = varmrätt, lila = efterrätt. Grön = Issy.
- Klick på en pin (eller en rad i listan) ritar det parets rutt
  förrätt → varmrätt → efterrätt → Issy och tonar ner alla andra pins till 35 %.
- Sidopanelen visar tider, adresser, vilka de äter med och avgångstid per etapp.
- "Visa verklig rutt" byter de raka linjerna mot faktiska gång-/kollektivrutter
  (Directions API, ett anrop per etapp, bara för valt par).
- "Kopiera SMS" lägger parets färdiga meddelande i urklipp.
- Esc eller klick på kartan rensar valet.

---

## 5. Adresser

Formuläret är fritext. Stavfel rättas enklast direkt i kalkylbladet. Vill du behålla
originalet: skapa `data/address_fixes.json` (gitignorerad, innehåller hemadresser),
med adressen som den står i arket som nyckel:

```json
{"Storgatn 1": "Storgatan 1, 111 22 Stockholm"}
```

En adress utan postnummer och ortnamn antas ligga i Stockholm, så skriv ut orten
om gatunamnet finns på flera ställen. Sökningen föredrar träffar i `GEO_BOUNDS`
(`config.py`, Stockholms län).

`geocode.py` flaggar allt som hamnar utanför Stockholmsområdet eller som Google
markerar som approximativt. **Läs igenom den listan innan du skickar ut något** –
en pin på fel sida stan förstör kvällen för sex personer.

Ändrar någon adress: uppdatera `data/Grupper.xlsx`, kör `run.py` igen.
Cachen gör att bara den nya adressen kostar något.

---

## 6. Hur "inget par träffas två gånger" garanteras

Paren delas i tre ringar om 21. Ring 0 håller förrätt, ring 1 varmrätt, ring 2
efterrätt. Vilket par som hamnar i vilken ring bestäms av sökningen (mjuk
Issy-preferens, se §7) – konstruktionen nedan gäller för **godtycklig**
ringtillhörighet. Numrera paren i ring *k* som `p_k[0..20]`, index i Z₂₁.
För rätt `r ∈ {0,1,2}` är borden

```
B_r(x) = { p0[x], p1[x+r], p2[2x+r] },   x ∈ Z₂₁
```

Eftersom 2 är inverterbart mod 21 (2·11 = 22 ≡ 1) är `2x+r` en bijektion, så
varje rätt är en perfekt partition av alla 63 par i 21 bord om tre.

Generellt: med `N` par blir ringstorleken `R = N/3`, och beviset nedan kräver att
`2x+r` är en bijektion i Z_R – alltså att 2 är inverterbart mod `R`, dvs att `R`
är udda. Därför måste `N` vara en udda multipel av 3 (§0). `solve.py` räknar `R`
och `2⁻¹ mod R` ur antalet par; en jämn `R` skulle låta två par mötas två
gånger och avvisas därför.

Två par från olika ringar hamnar vid samma bord precis när en kongruens håller:

```
p0[x] & p1[y]  ⟺  r = y − x
p0[x] & p2[z]  ⟺  r = z − 2x
p1[y] & p2[z]  ⟺  r = 2y − z
```

Var och en har exakt **en** lösning i Z₂₁, och bara r = 0, 1, 2 spelas. Alltså
träffas två par högst en gång. Par inom samma ring delar aldrig bord alls.
`3N` distinkta möten (189 vid 63 par), noll upprepningar – oavsett hur paren
numreras.

Det lämnar 21!³ omnumreringar **per** ringtillsättning som alla uppfyller
villkoren. Tillsammans med det fria valet av vilka 21 par som bemannar varje
ring är det sökrymden `solve.py` använder för att jämna ut restiden. `solve.py`
verifierar resultatet brute force innan det skrivs ut och avbryter högljutt om
ett upprepat möte någonsin dyker upp.

---

## 7. Skruva på det

Allt i `config.py`:

| | |
|---|---|
| `EVENT_DATE` | datum – styr kollektivtrafikens tidtabell |
| `ARRIVE_STARTER/ARRIVE_MAIN/DESSERT/AFTERPARTY` | 17:00 / 18:30 / 20:30 / 22:00. Tiden då varje rätt ska påbörjas|
| `REACHOUT_DATE` | datum (YYYY-MM-DD) som visas i *Dubbelkolla info*-meddelandet – sista dagen för paren att höra av sig om fel i adress/allergier/alkoholpreferens |
| `MIN_TRAVEL_MIN` | par vars hem ligger närmare än så här många minuter (samma adress, samma kvarter) hamnar aldrig vid samma bord och ingen reser direkt mellan deras hem. 0 = av. `solve.py` skriver ut antalet brott, det ska vara 0 |
| `ALCOHOL_DEFAULT` | texten som används när ett par inte angett någon alkoholpreferens. Ingen angiven preferens = paret vill ha alkohol |
| `MODES` | `["walking","transit"]` – varje etapp kostas som den snabbaste av de två`["Driving", "Walking", "Bicycling", "Transit", "Two-Wheeler"]` kan väljas|
| `ALPHA` | mjuk ringpreferens mot Issy-avstånd. 0 = strunt i ringrang, ~1 = default, ≥500 = exakt den gamla hårda splitten |
| `LOCK_DESSERT_RING` | `True` (default): efterrättsringen (ring 2) låses hårt till den tredjedel par som har kortast restid till Issy – varje efterrättsvärd garanterat nära efterfesten. Förrätt vs varmrätt (ring 0/1) är fortfarande fri och optimeras på restid, oberoende av `ALPHA`. `False` = helt fri ringtilldelning som innan, styrd enbart av `ALPHA` |
| `W_MEAN`, `W_TAIL`, `W_MAX`, `W_LEG` | målfunktionen: `W_MEAN·medel + W_TAIL·Σ max(0,T−T_TARGET)² + W_MAX·max + W_LEG·Σ max(0,etapp−LEG_CAP)² + W_HOST·Σ max(0,värdetapp−HOST_ARRIVE_CAP)² + ring_cost`. Ingen std – ensidiga straff |
| `T_TARGET`, `SLACK` | `python3 solve.py --calibrate` minimerar först bara medelvärdet och sätter `T_TARGET = medel·(1+SLACK)` i `data/calibration.json` |
| `LEG_CAP` | längsta enskilda etapp innan den straffas (40 min) |
| `HOST_ARRIVE_CAP`, `W_HOST` | den enda etapp en varm- eller efterrättsvärd reser hem till sin egen rätt får inte vara längre än så (30 min) – de måste hinna laga mat. Förrättsvärden är redan hemma. Stort `W_HOST` gör det till ett näst intill hårt villkor: annealern nekar dessutom varje drag som ökar antalet värdar över taket, och det exakta linjärlagret väger in samma term. `solve.py` skriver ut "hosts over HOST_ARRIVE_CAP" – den siffran ska vara 0 |
| `TRANSIT_SKIP_MIN` | hoppa kollektivanropet när gången är kortare än så (12 min) |
| `SEED`, `ANNEAL_ITERS`, `RESTARTS` | reproducerbar sökning. 1.0M/8 + linjärlagret tar ~2 min; kör `--calibrate` en gång först |
| `AFTERPARTY_ADDRESS` | Brinellvägen 23 |

---

## 8. Om något strular

**`CERTIFICATE_VERIFY_FAILED` / `unable to get local issuer certificate`**

Python från python.org på macOS installerar inga rot-certifikat, så alla
HTTPS-anrop dör. Fixa med en av:

```bash
python3 -m pip install certifi          # skripten hittar den automatiskt
# eller, en gång för hela datorn:
open "/Applications/Python 3.14/Install Certificates.command"
```

**`GOOGLE_API_KEY ser ut som platshållaren`**

`.env` innehåller fortfarande exempeltexten. Öppna filen och klistra in den
riktiga nyckeln – den börjar med `AIza` och är ungefär 39 tecken, utan
citattecken och utan `...`.

```bash
cat .env          # kolla vad som faktiskt står där
```

**`REQUEST_DENIED` från Google**

Antingen är API:et inte aktiverat i projektet (Geocoding API, Distance Matrix
API, Maps JavaScript API) eller så saknar projektet billing. Felmeddelandet från
Google säger vilket.

**Kartan är tom och sidan säger "Ingen GOOGLE_BROWSER_KEY hittad"**

`serve.py` lästes innan `.env` fanns. Ctrl+C och starta om `python3 serve.py`.

**`web/data.json saknas`**

`run.py` gick inte igenom. Kör den igen och läs felet högst upp, inte längst ner.

---

## 9. Kommunikationssidan – SMS-utskick

`http://localhost:8000/comms.html` (länkad från kartan) visar de sex
utskicken (samma `moment` som flikarna i `meddelanden.csv`: dubbelkolla,
schema, förrätt, varmrätt, efterrätt, efterfest), med en mall per utskick
(platshållare som `[name1]`, `[tid1]` istället för riktiga värden – de
riktiga meddelandena byggs från `data/schedule.json` med samma funktioner
som `export.py` använder).

Per utskick: en **Skicka till alla**-knapp (skickar det riktiga,
personliga meddelandet till alla 63 grupper via [46elks](https://46elks.se)),
en **Uppdatera status**-knapp (pollar 46elks för leveransstatus) och en
**Visa mottagare**-tabell med status per grupp. Grupper vars SMS inte gick
fram (misslyckades eller hoppades över) listas som varningar direkt under
utskicket, med telefonnummer så de kan följas upp manuellt.

**Låsreglaget** högst upp på sidan måste slås om till "olåst" innan någon
**Skicka till alla**-knapp går att klicka på – sidan öppnas alltid låst, så
ett feltryck inte skickar 63 SMS av misstag. Reglaget nollställs varje gång
sidan laddas om. Ett klick på **Skicka till alla** (när upplåst) öppnar
dessutom alltid en bekräftelseruta med mottagarantal innan något skickas.

**Mallarna är redigerbara.** Varje utskick har en eller två mallar (värd/gäst
för förrätt/varmrätt/efterrätt) med `[token]`-platshållare. **Redigera** gör
mallen om till ett textfält, **Spara mall** skriver ändringen till
`data/message_templates.json` – det är samma fil både `export.py` (xlsx/
`meddelanden.csv`) och comms-sidans **Skicka till alla** läser från, så en
ändring i webbgränssnittet slår igenom överallt meddelandet genereras, direkt
och utan omstart. **Återställ till standard** tar bort ändringen för just den
mallen. Ett borttaget eller felstavat `[token]` gör att den platsen i det
riktiga meddelandet lämnas som bokstavlig text (`[token]`) istället för att
tyst försvinna – syns direkt i förhandsgranskningen.

Sätt `ELKS_API_USERNAME`, `ELKS_API_PASSWORD` och valfritt `ELKS_FROM`
(avsändarnamn, max 11 tecken) i `.env` och starta om `serve.py`. Utan dem
kör sidan i "ej konfigurerat"-läge – knapparna funkar men varje utskick
loggas som `skipped` istället för att gå ut, så gränssnittet går att testa
innan ett 46elks-konto finns.

Skickstatus per grupp sparas i `data/send_log.json` (gitignorad – innehåller
namn, telefonnummer och meddelandetext). Radera filen för att nollställa allt.
