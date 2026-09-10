# Tunnelbanesittning – logistik

63 par (126 personer), tre rätter, 21 bord per rätt, 3 par per bord.
Varje par är värd exakt en gång. **Inget par träffar ett annat par mer än en gång
under hela kvällen** – det är garanterat av konstruktionen, inte hoppats fram.

Paren delas i tre ringar om 21 – ring 0 håller förrätt, ring 1 varmrätt, ring 2
efterrätt. Vilket par som hamnar i vilken ring är en beslutsvariabel med en mjuk
preferens mot Issy-avstånd (`ALPHA` i `config.py`); stort `ALPHA` ger tillbaka
den gamla hårda "längst bort = förrätt"-splitten. Restiden per par pressas ner
med en exakt linjär tilldelning per ring (`scipy.optimize.linear_sum_assignment`,
alternerad) plus simulated annealing ovanpå för de icke-linjära straffen.

---

## 1. Nyckel och localhost

Kartan körs lokalt på **http://localhost:8000** (`serve.py`).

### Enklaste vägen: en enda nyckel

Skapa filen `.env` i samma mapp som `config.py` och lägg en rad i den:

```
GOOGLE_API_KEY=AIza...din nyckel...
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

python3 run.py --dry     # ingen API-nyckel: OpenStreetMap-geokodning + fågelvägsrestider
python3 run.py           # riktiga Google-restider (hämtar hela 63×63, kräver --yes internt)
python3 serve.py         # kartan på http://localhost:8000
```

Stegen var för sig: `geocode.py`, `travel.py --yes`, `solve.py --calibrate`,
`solve.py`, `export.py`. `solve.py` skriver ut en före/efter-tabell (medel, std,
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

Formuläret var fritext, så `addresses.py` innehåller en `MANUAL_FIXES`-tabell för
de 18 rader som behövde municipality, stavningsfix eller postnummerflytt
(t.ex. `Fredrikskundsvägen` → `Fredrikslundsvägen`, `Norra Statsionsgatan` →
`Norra Stationsgatan`, `Stationsvägen_13` → `Stationsvägen 13, Täby`).

`geocode.py` flaggar allt som hamnar utanför Stockholmsområdet eller som Google
markerar som approximativt. **Läs igenom den listan innan du skickar ut något** –
en pin på fel sida stan förstör kvällen för sex personer.

Ändrar någon adress: uppdatera `data/participants.csv`, kör `run.py` igen.
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

Två par från olika ringar hamnar vid samma bord precis när en kongruens håller:

```
p0[x] & p1[y]  ⟺  r = y − x
p0[x] & p2[z]  ⟺  r = z − 2x
p1[y] & p2[z]  ⟺  r = 2y − z
```

Var och en har exakt **en** lösning i Z₂₁, och bara r = 0, 1, 2 spelas. Alltså
träffas två par högst en gång. Par inom samma ring delar aldrig bord alls.
189 distinkta möten, noll upprepningar – oavsett hur paren numreras.

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
| `ALCOHOL_DEFAULT` | texten som används när ett par inte angett någon alkoholpreferens. Ingen angiven preferens = paret vill ha alkohol |
| `MODES` | `["walking","transit"]` – varje etapp kostas som den snabbaste av de två`["Driving", "Walking", "Bicycling", "Transit", "Two-Wheeler"]` kan väljas|
| `ALPHA` | mjuk ringpreferens mot Issy-avstånd. 0 = strunt i ringrang, ~1 = default, ≥500 = exakt den gamla hårda splitten |
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
