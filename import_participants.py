"""Turn the sign-up spreadsheet into data/participants.json.

The rest of the pipeline reads data/participants.json (see README section 0).
This script builds that file from an .xlsx that looks like data/Grupper.xlsx -
the raw Google Forms export, Swedish column headers, one row per pair:

    Tidstämpel | Grupp-ID | Namn 1 | Namn 2 | Adress | Telefonnummer 1 |
    Telefonnummer 2 | Mailadress | Allergier | Alkoholpreferenser | Övrigt

Required: Namn 1, Namn 2, Adress, Telefonnummer 1 (the SMS goes there). Everything
else may be missing or blank. A pair without a Grupp-ID gets the lowest free number,
so a sheet with no such column is numbered 1..N in row order.

Extra columns (Tidstämpel, Övrigt) are ignored. Alkoholpreferenser is how many in
the pair drink alcohol: 0, 1 or 2 become the wording in ALCOHOL_BY_COUNT (config.py),
any other number stops the import. Free text is kept as written, and blank means
ALCOHOL_DEFAULT.

    python3 import_participants.py                     # reads data/Grupper.xlsx
    python3 import_participants.py path/to/svar.xlsx   # reads that file instead

An existing data/participants.json is copied to .json.bak before it is replaced.
If the participants changed, everything generated from the old list is deleted
(DERIVED below), so a map or sendout can never show the previous people's data.
data/send_log.json is a record of SMS actually sent, so it only gets a warning.
"""
import itertools, json, os, shutil, sys

from openpyxl import load_workbook

import config

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SRC = os.path.join(HERE, "data", "Grupper.xlsx")
OUT = os.path.join(HERE, "data", "participants.json")
SEND_LOG = os.path.join(HERE, "data", "send_log.json")
DERIVED = [os.path.join(HERE, *p) for p in (
    ("data", "geocoded.json"), ("data", "travel.json"), ("data", "schedule.json"),
    ("data", "baseline.json"), ("data", "calibration.json"), ("web", "data.json"),
    ("out", "tunnelbanesittning.xlsx"), ("out", "meddelanden.csv"), ("out", "schema.csv"),
)]

# Accepted header -> field name. Keys are lowercased and stripped before lookup,
# so trailing spaces and capitalisation in the sheet do not matter. The field
# names themselves are accepted too, so an already-cleaned sheet also imports.
HEADER_MAP = {
    "grupp-id": "group_id", "group_id": "group_id",
    "namn 1": "name1", "name1": "name1",
    "namn 2": "name2", "name2": "name2",
    "adress": "address_raw", "address_raw": "address_raw",
    "telefonnummer 1": "phone1", "phone1": "phone1",
    "telefonnummer 2": "phone2", "phone2": "phone2",
    "mailadress": "email", "e-post": "email", "email": "email",
    "allergier": "allergies", "allergies": "allergies",
    "alkoholpreferenser": "alkoholpreferenser",
}
REQUIRED = ["name1", "name2", "address_raw", "phone1"]


def _text(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    # normalise non-breaking spaces and collapse runs of whitespace
    return " ".join(str(v).replace("\xa0", " ").split())


def _alcohol(v):
    """0/1/2 -> wording from config, free text kept; raises ValueError on other numbers."""
    s = _text(v)
    if s in config.ALCOHOL_BY_COUNT:
        return config.ALCOHOL_BY_COUNT[s]
    if s.replace(".", "", 1).isdigit():
        raise ValueError(s)
    return s


def _normalised(people):
    """Comparable form: runs of whitespace are not a change in the list."""
    return [{k: " ".join(v.split()) if isinstance(v, str) else v for k, v in p.items()}
            for p in people]


def _clear_derived():
    removed = [p for p in DERIVED if os.path.exists(p)]
    for p in removed:
        os.remove(p)
    if removed:
        print(f"  deltagarlistan ändrad: {len(removed)} genererade filer från den gamla listan borttagna")
    if os.path.exists(SEND_LOG):
        print(f"  VARNING: {os.path.relpath(SEND_LOG, HERE)} hör till den gamla listan och är nyckel:ad på "
              "Grupp-ID.\n  Radera den om det är en ny sittning, annars visas nya par som redan kontaktade.")


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC
    if not os.path.exists(src):
        sys.exit(f"Hittar inte {src}\n"
                 "Ange sökväg till formulärexporten, eller lägg den som data/Grupper.xlsx")

    ws = load_workbook(src, read_only=True, data_only=True).active
    rows = [r for r in ws.iter_rows(values_only=True) if any(c is not None for c in r)]
    if len(rows) < 2:
        sys.exit(f"{src}: inga datarader under rubrikraden")

    header = [_text(c).lower() for c in rows[0]]
    col = {}
    for i, h in enumerate(header):
        field = HEADER_MAP.get(h)
        if field and field not in col:
            col[field] = i

    missing_cols = [f for f in REQUIRED if f not in col]
    if missing_cols:
        sys.exit(f"{src}: saknar kolumn(er) {', '.join(missing_cols)}\n"
                 f"Hittade rubriker: {', '.join(rows[0][i] and str(rows[0][i]) or '' for i in range(len(header)))}")

    people, problems, seen = [], [], {}
    for n, row in enumerate(rows[1:], start=2):   # n = spreadsheet row number
        def cell(field):
            i = col.get(field)
            return row[i] if i is not None and i < len(row) else None

        gid_raw = _text(cell("group_id"))
        gid = None
        if gid_raw:
            try:
                gid = int(float(gid_raw))
            except ValueError:
                problems.append(f"  rad {n}: Grupp-ID {gid_raw!r} är inte ett heltal")
                continue
            if gid in seen:
                problems.append(f"  rad {n}: Grupp-ID {gid} finns redan på rad {seen[gid]}")
                continue
            seen[gid] = n

        rec = {"group_id": gid}
        for f in ("name1", "name2", "address_raw", "phone1", "phone2", "email"):
            rec[f] = _text(cell(f))
        rec["allergies"] = _text(cell("allergies"))
        try:
            rec["alkoholpreferenser"] = _alcohol(cell("alkoholpreferenser"))
        except ValueError as e:
            problems.append(f"  rad {n}: Alkoholpreferenser {e} ska vara 0, 1, 2 eller fritext")
            continue

        empty = [f for f in REQUIRED if not rec[f]]
        if empty:
            problems.append(f"  rad {n}: tomt fält {', '.join(empty)}")
            continue
        people.append(rec)

    free = (i for i in itertools.count(1) if i not in seen)
    for p in people:
        if p["group_id"] is None:
            p["group_id"] = next(free)

    people.sort(key=lambda p: p["group_id"])
    ids = [p["group_id"] for p in people]

    if problems:
        sys.exit("Avbryter - rätta i kalkylbladet och kör om:\n" + "\n".join(problems))
    if not people:
        sys.exit(f"{src}: inga giltiga rader")

    # solve.py needs three equal rings of an ODD size: the pair count must be an
    # odd multiple of 3 (..., 57, 63, 69, ...), or the "no pair meets twice"
    # construction breaks. These are warnings, not hard errors - the import file
    # itself is still valid and you may be mid-edit.
    n = len(people)
    warn = []
    if n % 3 != 0:
        warn.append(f"{n} par går inte jämnt upp i tre ringar (måste vara delbart med 3) "
                    f"- solve.py kommer att vägra")
    elif (n // 3) % 2 == 0:
        warn.append(f"{n} par ger ringar om {n // 3} (jämnt); ringstorleken måste vara udda "
                    f"annars kan par mötas två gånger - prova {n - 3} eller {n + 3} par. "
                    f"solve.py kommer att vägra")
    if ids != list(range(1, len(ids) + 1)):
        gaps = sorted(set(range(1, ids[-1] + 1)) - set(ids))
        warn.append(f"Grupp-ID inte 1..{len(ids)} i följd; hål: {gaps or 'inga'}, högsta: {ids[-1]}")
    for w in warn:
        print(f"  varning: {w}")

    if os.path.exists(OUT):
        shutil.copyfile(OUT, OUT + ".bak")
        if _normalised(json.load(open(OUT, encoding="utf-8"))) != _normalised(people):
            _clear_derived()
    else:
        _clear_derived()
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(people, f, ensure_ascii=False, indent=1)

    n_al = sum(1 for p in people if p["allergies"])
    n_alk = sum(1 for p in people if p["alkoholpreferenser"])
    print(f"\n{len(people)} par -> data/participants.json"
          + (" (gammal fil sparad som participants.json.bak)" if os.path.exists(OUT + ".bak") else ""))
    print(f"  {n_al} med allergianmärkning, {n_alk} med angiven alkoholpreferens")
    print("Kör vidare med:  python3 run.py")


if __name__ == "__main__":
    main()
