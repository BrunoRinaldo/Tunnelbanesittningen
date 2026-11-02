"""Address cleaning for the participant sheet.

The form is free text, so entries can have typos, missing municipalities or a
postcode glued to the front. Fixes for one sheet live in data/address_fixes.json
(gitignored, it holds home addresses), a JSON object mapping the address as
written in the sheet to the corrected address:

    {"Storgatn 1": "Storgatan 1, 111 22 Stockholm"}

Keyed on the text, not the group number, so a new sheet can never pick up a fix
meant for someone else. Whitespace runs are collapsed before the lookup, so write
keys with single spaces. Everything else gets light normalisation plus ", Sweden".
"""
import json, os, re

FIXES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "address_fixes.json")
MANUAL_FIXES = json.load(open(FIXES, encoding="utf-8")) if os.path.exists(FIXES) else {}

# A bare "Storgatan 1" with neither postcode nor place name gets this locality.
DEFAULT_LOCALITY = "Stockholm"


def clean(raw: str) -> str:
    key = " ".join(raw.split())
    if key in MANUAL_FIXES:
        base = MANUAL_FIXES[key]
    else:
        base = re.sub(r"[_ ]+", " ", raw).strip()
        base = re.sub(r"\s{2,}", " ", base)
        has_postcode = re.search(r"\s\d{3}\s?\d{2}\b", base)
        # "Storgatan 1 11122" -> "Storgatan 1, 111 22"
        base = re.sub(r"\s(\d{3})\s?(\d{2})\b", r", \1 \2", base)
        base = re.sub(r",\s*,", ",", base)
        if not has_postcode and re.search(r"\d\s*[A-Za-z]?$", base):
            base = f"{base}, {DEFAULT_LOCALITY}"
    if not base.lower().rstrip().endswith("sweden"):
        base += ", Sweden"
    return base
