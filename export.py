"""Write the master schedule to out/tunnelbanesittning.xlsx + CSVs."""
import csv, json, os, re

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

import config

HERE = os.path.dirname(os.path.abspath(__file__))
SCH = os.path.join(HERE, "data", "schedule.json")
OUTDIR = os.path.join(HERE, "out")

FONT = "Arial"
COURSE_SV = {"starter": "Förrätt", "main": "Varmrätt", "dessert": "Efterrätt"}
FILL = {"starter": "FFE3D4", "main": "D6E8F5", "dessert": "E2DAF0"}
HDR_FILL = PatternFill("solid", fgColor="1F3B57")
HDR_FONT = Font(name=FONT, bold=True, color="FFFFFF", size=10)
BASE = Font(name=FONT, size=10)
BOLD = Font(name=FONT, size=10, bold=True)
THIN = Side(style="thin", color="D0D0D0")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def sheet(wb, title, headers, rows, widths=None, freeze="A2", fills=None):
    ws = wb.create_sheet(title)
    ws.append(headers)
    for c in range(1, len(headers) + 1):
        cell = ws.cell(1, c)
        cell.font, cell.fill = HDR_FONT, HDR_FILL
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        cell.border = BOX
    ws.row_dimensions[1].height = 28
    for r, row in enumerate(rows, start=2):
        for c, v in enumerate(row, start=1):
            cell = ws.cell(r, c, v)
            cell.font = BASE
            cell.border = BOX
            cell.alignment = Alignment(vertical="top", wrap_text=isinstance(v, str) and len(str(v)) > 30)
        if fills:
            f = fills(rows[r - 2])
            if f:
                for c in range(1, len(headers) + 1):
                    ws.cell(r, c).fill = PatternFill("solid", fgColor=f)
    for i, w in enumerate(widths or [], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = freeze
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(rows) + 1}"
    return ws


# Messages per group per moment: an info double-check, a schedule sent early in
# the day, then one per course. Guests never see names - only addresses - and
# hosts see their guests' allergies / alcohol preferences without names.
COURSE_KEYS = ["starter", "main", "dessert"]
COURSE_UP = {"starter": "FÖRRÄTT", "main": "VARMRÄTT", "dessert": "EFTERRÄTT"}
MSG_TABS = [
    ("dubbelkolla", "Dubbelkolla info"),
    ("schema", "Schema"),
    ("starter", "Förrätt"),
    ("main", "Varmrätt"),
    ("dessert", "Efterrätt"),
    ("efterfest", "Efterfest"),
]

# Course-specific sign-off appended to the end of each course SMS.
COURSE_CLOSING = {
    "starter": "Drink Responsibally (or dont)...\nKulturnämnden",
    "main": "Kom inte sent!!!\nKulturnämnden",
    "dessert": "Det är snart dags för sötsaker och drinkar!\nKulturnämnden",
}

def _clean_note(v):
    v = (v or "").strip()
    return "" if v in (".", "-") else v


def first_name(name):
    parts = (name or "").split()
    return parts[0] if parts else (name or "")


def intl_phone(p):
    """Swedish local number -> E.164 (+46...), for SMS automation tooling."""
    d = re.sub(r"[^\d+]", "", p or "")
    if not d:
        return ""
    if d.startswith("+"):
        return d
    if d.startswith("00"):
        return "+" + d[2:]
    if d.startswith("0"):
        return "+46" + d[1:]
    if d.startswith("46"):
        return "+" + d
    return d


def alcohol_of(gg):
    return _clean_note(gg.get("alkoholpreferenser")) or config.ALCOHOL_DEFAULT


_PC = re.compile(r"\b(\d{3})\s?(\d{2})\b")
_ADMIN = re.compile(r"(kommun|län|stadsdel|innerstad|distrikt|församling)", re.I)


def short_addr(g):
    """Just street + number, postcode and city - drop the geocoder's
    neighbourhood / municipality / county / country tail.

    Street + number is taken from the cleaned input address (curated, incl. the
    MANUAL_FIXES). Postcode + city come from the cleaned address when it carries
    them, otherwise from the geocoder's formatted string.
    """
    def strip_country(s):
        return re.sub(r",?\s*(sweden|sverige)\s*$", "", (s or ""), flags=re.I).strip().rstrip(",")

    a, f = strip_country(g.get("address")), strip_country(g.get("formatted"))

    first = a.split(",")[0].strip()
    if re.search(r"\d", first):
        street = re.sub(r"\s+", " ", first)
    else:
        fp = [p.strip() for p in f.split(",") if p.strip()]
        if len(fp) > 1 and re.fullmatch(r"\d+[A-Za-zÅÄÖåäö]?", fp[0]):
            street = f"{fp[1]} {fp[0]}"
        else:
            street = fp[0] if fp else (first or "?")

    def city_after(src):
        m = _PC.search(src)
        mm = re.match(r"[,\s]*([A-Za-zÅÄÖåäö.\-/ ]+?)\s*(?:,|$)", src[m.end():]) if m else None
        return mm.group(1).strip() if mm and mm.group(1).strip() else ""

    def city_before(src):
        m = _PC.search(src)
        if not m:
            return ""
        toks = [p.strip() for p in src[:m.start()].split(",") if p.strip()]
        toks = [p for p in toks if not _ADMIN.search(p)
                and not re.fullmatch(r"\d+[A-Za-zÅÄÖåäö]?", p)
                and p.lower() != street.lower()]
        return toks[-1] if toks else ""

    ma, mf = _PC.search(a), _PC.search(f)
    pc = f"{ma.group(1)} {ma.group(2)}" if ma else (f"{mf.group(1)} {mf.group(2)}" if mf else "")
    city = city_after(a) or city_after(f) or city_before(f) or city_before(a)

    tail = " ".join(x for x in (pc, city) if x)
    return f"{street}, {tail}" if tail else street


def _addr(gmap, i):
    return short_addr(gmap[i])


def course_role(g, r, course):
    return "VÄRD" if r["stops"][COURSE_KEYS.index(course)]["host"] == g else "gäst"


def pre_message(g, gmap):
    gg = gmap[g]
    al = _clean_note(gg.get("allergies")) or "inga allergier"
    return (
        f"Hej {gg['name1']} & {gg['name2']}!\n"
        f"Grattis till er plats i tunnelbanesittningen den {config.EVENT_DATE}. \n\n"
        f"Dubbelkolla att denna info stämmerinnan tunnelbanesittningen:\n\n"
        f"Er adress: {_addr(gmap, g)}\n"
        f"Allergier / kostönskemål: {al}\n"
        f"Alkoholpreferens: {alcohol_of(gg)}\n"
        f"Secundärt nummer: {gg['phone2']}\n"
        f"E-post: {gg['email']}\n\n"
        f"Svara på detta meddelande senast {config.REACHOUT_DATE} om något är fel eller saknas.\n\n"
        f"Ses på TBS och vi älskar er!\n"
        f"Kulturnämnden"
    )


def schema_message(g, r, gmap, issy_addr):
    gg = gmap[g]
    out = [f"Hej igen {first_name(gg['name1'])} & {first_name(gg['name2'])}, nu bär det snart av!\n",
           "Dessa adresser kommer ni besöka under kvällen.\n\n"
           f"Er kväll ser ut som följande"]
    for ci, course in enumerate(COURSE_KEYS):
        stop = r["stops"][ci]
        out.append(f"{COURSE_UP[course]} kl {stop['arrive']}: {_addr(gmap, stop['host'])}")
    out.append(f"EFTERFEST kl {config.ARRIVE_AFTERPARTY}: {issy_addr}")
    out.append("")
    out.append(f"Ni är ansvariga för {COURSE_UP[r['hosts']]} – den lagar och serverar ni hemma hos er.")
    hosted = r["stops"][COURSE_KEYS.index(r["hosts"])]
    g_al = "; ".join(x for x in (_clean_note(gmap[i].get("allergies")) for i in hosted["co"]) if x) or "inga"
    g_dr = "; ".join(alcohol_of(gmap[i]) for i in hosted["co"])
    out.append(f"Era gäster har OSAt Allergier: {g_al} och Alkoholpreferens: {g_dr}")
    out.append("")
    out.append("Ses snart på issy!")
    out.append("Puss Puss,\nKulturnämnden")
    return "\n".join(out)


def course_message(g, r, gmap, course, issy_addr):
    ci = COURSE_KEYS.index(course)
    stop = r["stops"][ci]
    legs = r["legs"]
    label = COURSE_UP[course]
    gg = gmap[g]
    out = [f"Tjenare {first_name(gg['name1'])} och {first_name(gg['name2'])}!", ""]

    if stop["host"] == g:
        out.append(f"{label}, NI ÄR VÄRDAR, hemma hos er:")
        out.append(f"{_addr(gmap, g)}")
        out.append(f"Gästerna är framme kl {stop['arrive']}. Ni blir 6 personer (3 par inkl. er).")
        al = [x for x in (_clean_note(gmap[i].get("allergies")) for i in stop["co"]) if x]
        out.append("")
        out.append("Era gästers allergier / kostönskemål:")
        out += [f"- {x}" for x in al] or ["- inga"]
        out.append("Era gästers alkoholpreferenser:")
        prefs = []
        for i in stop["co"]:
            p = _clean_note(gmap[i].get("alkoholpreferenser")) or config.ALCOHOL_DEFAULT
            if p not in prefs:
                prefs.append(p)
        out += prefs if len(prefs) == 1 else [f"- {p}" for p in prefs]
    else:
        if ci == 0:
            out.append(f"{label} kl {stop['arrive']}, kom till adressen:")
        else:
            lg = legs[ci - 1]
            out.append(f"Snart dags för {label.lower()}. Avgång ca {lg['depart']}, "
                       f"framme kl {stop['arrive']} (vårt script estimerar "
                       f"~{round(lg['min'] or 0)} min {lg['mode']}, men dubbelkolla "
                       f"er exakta restid).")
            out.append("Ni ska till adressen:")
        out.append(f"{_addr(gmap, stop['host'])}")
        out.append(f"Ring värden: {gmap[stop['host']]['phone1']}")

    out.append("")
    if course == "dessert":
        lg = legs[2]
        out.append(f"Efter efterrätten: efterfest kl {config.ARRIVE_AFTERPARTY} "
                   f"på issy, avgång ca {lg['depart']}:")
        out.append(f"{issy_addr}")
    else:
        nxt = r["stops"][ci + 1]
        lg = legs[ci]
        out.append(f"Efter {label.lower()}en: åk vidare till {_addr(gmap, nxt['host'])}.")
        if ci == 0:
            out.append(f"Ni ska vara framme kl {nxt['arrive']} (avgång ca {lg['depart']}, "
                       f"vårt script estimerar ~{round(lg['min'] or 0)} min {lg['mode']}, "
                       f"men dubbelkolla er exakta restid):")
        else:
            out.append(f"Ni ska vara framme kl {nxt['arrive']} "
                       f"(avgång ca {lg['depart']}, ~{round(lg['min'] or 0)} min {lg['mode']}):")

    out.append("")
    out.append(COURSE_CLOSING[course])
    return "\n".join(out)


def afterparty_message(g, gmap, issy_addr):
    gg = gmap[g]
    return "\n".join([
        f"Dags för efterfest {first_name(gg['name1'])} och {first_name(gg['name2'])}!!!",
        "",
        f"Rätterna är avklarade, nu rullar hela tunnelbanesittningen vidare "
        f"mot {config.AFTERPARTY_NAME}. Ingen matlagning, inga adresser att "
        f"pricka av, bara ni, alla andra och en taggad kulturnämnd som väntar.",
        "",
        f"Efterfest börjar kl {config.ARRIVE_AFTERPARTY} på adressen:",
        f"{issy_addr}",
        "",
        "Vi ses i dimman!",
        "Kulturnämnden",
    ])


def group_messages(g, r, gmap, issy_addr):
    """(tab_key, role, message) for every moment a group is contacted."""
    yield ("dubbelkolla", "", pre_message(g, gmap))
    yield ("schema", "", schema_message(g, r, gmap, issy_addr))
    for c in COURSE_KEYS:
        yield (c, course_role(g, r, c), course_message(g, r, gmap, c, issy_addr))
    yield ("efterfest", "", afterparty_message(g, gmap, issy_addr))


def main():
    sch = json.load(open(SCH, encoding="utf-8"))
    os.makedirs(OUTDIR, exist_ok=True)
    gmap = {g["group_id"]: g for g in sch["groups"]}
    routes = {r["group"]: r for r in sch["routes"]}
    issy_addr = config.AFTERPARTY_ADDRESS.replace(", Sweden", "")
    st = sch["meta"]["stats"]
    bl = sch["meta"].get("baseline", {})

    def _b(key):
        v = bl.get(key, "")
        return round(v, 1) if isinstance(v, float) else v

    def _note(g, field):
        v = (g.get(field) or "").strip()
        return "" if v in (".", "-") else v

    n_allerg = sum(1 for g in sch["groups"] if _note(g, "allergies"))
    n_alco = sum(1 for g in sch["groups"] if _note(g, "alkoholpreferenser"))

    wb = Workbook()
    wb.remove(wb.active)

    # ---------------------------------------------------------- 1. Översikt
    ws = wb.create_sheet("Översikt")
    info = [
        ("Tunnelbanesittning – I-sektionen KTH", ""),
        ("Datum", config.EVENT_DATE),
        ("", ""),
        ("Antal grupper (par)", len(sch["groups"])),
        ("Antal personer", len(sch["groups"]) * 2),
        ("Bord per rätt", 21),
        ("Grupper per bord", 3),
        ("", ""),
        ("Förrätt – ankomst", config.ARRIVE_STARTER),
        ("Varmrätt – ankomst", config.ARRIVE_MAIN),
        ("Efterrätt – ankomst", config.ARRIVE_DESSERT),
        (f"Efterfest ({config.AFTERPARTY_NAME}) – ankomst", config.ARRIVE_AFTERPARTY),
        ("Efterfestens adress", issy_addr),
        ("", ""),
        ("Upprepade möten mellan grupper", "0 (garanterat av konstruktionen)"),
        ("Distinkta möten totalt", 189),
        ("", ""),
        ("Grupper med allergi-/kostanmärkning", f"{n_allerg} av {len(sch['groups'])}"),
        ("Grupper med alkoholpreferens angiven", f"{n_alco} av {len(sch['groups'])}"),
        ("", ""),
        ("", "före", "efter"),
        ("Restid per grupp – medel (min)", _b("mean"), round(st["mean"], 1)),
        ("Restid per grupp – standardavvikelse (min)", _b("std"), round(st["sd"], 1)),
        ("Restid per grupp – median p50 (min)", _b("p50"), round(st.get("p50", 0), 1)),
        ("Restid per grupp – p90 (min)", _b("p90"), round(st.get("p90", 0), 1)),
        ("Restid per grupp – längsta (min)", _b("max"), round(st["max"], 1)),
        ("Längsta enskilda etapp (min)", _b("longest_leg"), round(st.get("longest_leg", 0), 1)),
        (f"Etapper över LEG_CAP ({round(sch['meta'].get('leg_cap', 0))} min)",
         _b("legs_over_cap"), st.get("legs_over_cap", 0)),
        ("Längsta värdens restid till egen rätt (min)",
         _b("host_arrive_max"), round(st.get("host_arrive_max", 0), 1)),
        (f"Värdar över {round(sch['meta'].get('host_arrive_cap', 0))} min till egen rätt "
         f"(måste hinna laga mat)",
         _b("host_over_cap"), st.get("host_over_cap", 0)),
        ("Ringordningsbrott (par utanför Issy-rang-ring)",
         _b("ring_violations"), st.get("ring_violations", 0)),
        ("T_TARGET (min)", "", round(sch["meta"].get("t_target", 0), 1)),
        ("Restidskälla", sch["meta"]["travel_source"], ""),
        ("", ""),
        ("Ring 0 = förrätt", "längst från Issy pressas hit (mjuk preferens)"),
        ("Ring 1 = varmrätt", "mellanavstånd"),
        ("Ring 2 = efterrätt", "närmast Issy pressas hit (mjuk preferens)"),
    ]
    for r, row in enumerate(info, start=1):
        k, v = row[0], row[1]
        w3 = row[2] if len(row) > 2 else None
        ws.cell(r, 1, k).font = BOLD if r == 1 or not v else BASE
        ws.cell(r, 2, v).font = BASE
        if w3 is not None:
            ws.cell(r, 3, w3).font = BASE
    ws.cell(1, 1).font = Font(name=FONT, size=14, bold=True)
    ws.column_dimensions["A"].width = 42
    ws.column_dimensions["B"].width = 46
    ws.column_dimensions["C"].width = 14

    # ---------------------------------------------------------- 2. Grupper
    rows = []
    for g in sch["groups"]:
        r = routes[g["group_id"]]
        rows.append([g["group_id"], g["name1"], g["name2"], g["formatted"] or g["address"],
                     g["phone1"], g["phone2"], g["email"],
                     g.get("allergies", ""), g.get("alkoholpreferenser", ""),
                     COURSE_SV[r["hosts"]], round(r["total_min"]),
                     round(r.get("home_to_starter_min", 0))])
    sheet(wb, "Grupper",
          ["Grupp", "Namn 1", "Namn 2", "Adress", "Telefon 1", "Telefon 2", "E-post",
           "Allergier", "Alkoholpreferenser", "Värd för", "Restid tot (min)",
           "Restid hem→förrätt (min)"],
          rows, [7, 22, 22, 42, 15, 15, 30, 20, 22, 12, 15, 20],
          fills=lambda row: FILL[{v: k for k, v in COURSE_SV.items()}[row[9]]])

    # ---------------------------------------------------------- 3. Schema per grupp
    rows = []
    for g in sorted(routes):
        r = routes[g]
        s, m, d = r["stops"]
        L = r["legs"]
        a = lambda i: gmap[i]["formatted"] or gmap[i]["address"]
        co = lambda ids: " | ".join(f"{i}: {gmap[i]['name1']} & {gmap[i]['name2']}" for i in ids)
        rows.append([
            g, f"{gmap[g]['name1']} & {gmap[g]['name2']}", COURSE_SV[r["hosts"]],
            s["host"], a(s["host"]), s["arrive"], co(s["co"]),
            L[0]["depart"], round(L[0]["min"] or 0), L[0]["mode"],
            m["host"], a(m["host"]), m["arrive"], co(m["co"]),
            L[1]["depart"], round(L[1]["min"] or 0), L[1]["mode"],
            d["host"], a(d["host"]), d["arrive"], co(d["co"]),
            L[2]["depart"], round(L[2]["min"] or 0), L[2]["mode"],
            config.ARRIVE_AFTERPARTY, round(r["total_min"]),
        ])
    sheet(wb, "Schema per grupp",
          ["Grupp", "Par", "Värd för",
           "F: värdgrupp", "F: adress", "F: ankomst", "F: äter med",
           "→ avgång", "→ min", "→ färdsätt",
           "V: värdgrupp", "V: adress", "V: ankomst", "V: äter med",
           "→ avgång", "→ min", "→ färdsätt",
           "E: värdgrupp", "E: adress", "E: ankomst", "E: äter med",
           "→ avgång", "→ min", "→ färdsätt",
           "Issy", "Restid tot (min)"],
          rows,
          [7, 30, 11] + ([11, 36, 10, 40, 10, 7, 10] * 3) + [8, 14],
          freeze="C2")

    # ---------------------------------------------------------- 4. Bord
    rows = []
    for course in ("starter", "main", "dessert"):
        for tb in sch["tables"][course]:
            h = tb["host"]
            guests = [m for m in tb["members"] if m != h]
            allerg = [f"{gmap[m]['name1']}/{gmap[m]['name2']}: {gmap[m]['allergies']}"
                      for m in tb["members"] if gmap[m]["allergies"] not in ("", ".", "-")]
            rows.append([COURSE_SV[course], tb["table"] + 1, h,
                         f"{gmap[h]['name1']} & {gmap[h]['name2']}",
                         gmap[h]["formatted"] or gmap[h]["address"],
                         sch["meta"]["arrive"][course],
                         " | ".join(f"{m}: {gmap[m]['name1']} & {gmap[m]['name2']}" for m in guests),
                         "; ".join(allerg)])
    sheet(wb, "Bord",
          ["Rätt", "Bord", "Värdgrupp", "Värdpar", "Adress", "Ankomst", "Gäster (2 par)", "Allergier"],
          rows, [11, 7, 11, 30, 40, 10, 52, 34],
          fills=lambda row: FILL[{v: k for k, v in COURSE_SV.items()}[row[0]]])

    # ---------------------------------------------------------- 5. Värdinfo
    rows = []
    for gid_s, hi in sorted(sch["host_info"].items(), key=lambda kv: int(kv[0])):
        gid = int(gid_s)
        allerg = "; ".join(hi["allergies"]) or "–"
        guests = "\n".join(
            f"{m}: {gmap[m]['name1']} ({gmap[m]['phone1']}) & {gmap[m]['name2']} ({gmap[m]['phone2']})"
            for m in hi["guests"])
        rows.append([gid, f"{gmap[gid]['name1']} & {gmap[gid]['name2']}",
                     COURSE_SV[hi["course"]], hi["arrive"],
                     gmap[gid]["formatted"] or gmap[gid]["address"], guests, allerg, 6])
    sheet(wb, "Värdinfo",
          ["Grupp", "Värdpar", "Rätt", "Gästerna kommer", "Adress",
           "Gäster (namn + telefon)", "Allergier vid bordet", "Antal ätande"],
          rows, [7, 30, 11, 16, 40, 56, 34, 13],
          fills=lambda row: FILL[{v: k for k, v in COURSE_SV.items()}[row[2]]])

    # ---------------------------------------------------------- 6. Meddelanden (4 flikar)
    # tab_key -> list of (group, role, message)
    by_tab = {key: [] for key, _ in MSG_TABS}
    for g in sorted(routes):
        for tab_key, role, msg in group_messages(g, routes[g], gmap, issy_addr):
            by_tab[tab_key].append((g, role, msg))

    for tab_key, tab_title in MSG_TABS:
        rows = [[g, role, gmap[g]["phone1"], intl_phone(gmap[g]["phone1"]),
                 gmap[g]["phone2"], gmap[g]["email"], msg]
                for g, role, msg in by_tab[tab_key]]
        ws = sheet(wb, tab_title,
                   ["Grupp", "Roll", "Telefon 1", "Telefon 1 (+46)", "Telefon 2",
                    "E-post", "Meddelande"],
                   rows, [7, 8, 16, 16, 16, 30, 104])
        for ri in range(2, len(rows) + 2):
            ws.cell(ri, 7).alignment = Alignment(wrap_text=True, vertical="top")
            ws.row_dimensions[ri].height = 170

    path = os.path.join(OUTDIR, "tunnelbanesittning.xlsx")
    wb.save(path)

    # ---------------------------------------------------------- CSVs
    # one row per send: 4 per group (innan + 3 rätter), ordered tab-by-tab
    with open(os.path.join(OUTDIR, "meddelanden.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["group", "moment", "role", "name1", "name2",
                    "phone1", "phone1_intl", "phone2", "email", "message"])
        tab_title = dict(MSG_TABS)
        for tab_key, _ in MSG_TABS:
            for g, role, msg in by_tab[tab_key]:
                w.writerow([g, tab_title[tab_key], role, gmap[g]["name1"], gmap[g]["name2"],
                            gmap[g]["phone1"], intl_phone(gmap[g]["phone1"]),
                            gmap[g]["phone2"], gmap[g]["email"], msg])

    with open(os.path.join(OUTDIR, "schema.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["group", "hosts", "starter_host", "starter_addr", "starter_arrive",
                    "starter_with", "main_host", "main_addr", "main_arrive", "main_with",
                    "dessert_host", "dessert_addr", "dessert_arrive", "dessert_with",
                    "leg1_min", "leg1_mode", "leg2_min", "leg2_mode", "leg3_min", "leg3_mode",
                    "total_min", "home_to_starter_min", "ring", "ring_pref", "ring_violation",
                    "allergies", "alkoholpreferenser",
                    "guests_allergies", "guests_alkoholpreferenser"])
        for g in sorted(routes):
            r = routes[g]
            s, m, d = r["stops"]
            L = r["legs"]
            a = lambda i: gmap[i]["formatted"] or gmap[i]["address"]
            hosted = {"starter": s, "main": m, "dessert": d}[r["hosts"]]

            def _n(i, fld):
                v = (gmap[i].get(fld) or "").strip()
                return "" if v in (".", "-") else v

            g_al = "; ".join(f"{i}: {_n(i, 'allergies')}" for i in hosted["co"] if _n(i, "allergies"))
            g_dr = "; ".join(f"{i}: {_n(i, 'alkoholpreferenser')}" for i in hosted["co"]
                             if _n(i, "alkoholpreferenser"))
            w.writerow([g, r["hosts"],
                        s["host"], a(s["host"]), s["arrive"], "+".join(map(str, s["co"])),
                        m["host"], a(m["host"]), m["arrive"], "+".join(map(str, m["co"])),
                        d["host"], a(d["host"]), d["arrive"], "+".join(map(str, d["co"])),
                        round(L[0]["min"] or 0, 1), L[0]["mode"],
                        round(L[1]["min"] or 0, 1), L[1]["mode"],
                        round(L[2]["min"] or 0, 1), L[2]["mode"],
                        round(r["total_min"], 1), round(r.get("home_to_starter_min", 0), 1),
                        r.get("ring", ""), r.get("ring_pref", ""),
                        int(bool(r.get("ring_violation", False))),
                        _n(g, "allergies"), _n(g, "alkoholpreferenser"), g_al, g_dr])

    # web payload
    with open(os.path.join(HERE, "web", "data.json"), "w", encoding="utf-8") as f:
        json.dump(sch, f, ensure_ascii=False)

    n_msg = sum(len(v) for v in by_tab.values())
    print(f"  out/tunnelbanesittning.xlsx  ({len(wb.sheetnames)} blad)")
    print(f"  out/meddelanden.csv          ({n_msg} meddelanden: {len(routes)} grupper x {len(MSG_TABS)})")
    print(f"  out/schema.csv")
    print(f"  web/data.json")


if __name__ == "__main__":
    main()
