"""Address cleaning for the participant sheet.

The form was free-text, so a handful of entries have typos, missing
municipalities or a postcode glued to the front. Anything listed in
MANUAL_FIXES replaces the raw string before geocoding; everything else gets
light normalisation plus ", Sweden".
"""
import re

# group_id -> corrected address (typos, ambiguous streets, missing municipality)
MANUAL_FIXES = {
    4:  "Mjölnarvägen 32, 131 74 Nacka",
    15: "Sveavägen 19, 182 60 Djursholm",          # Djursholm has its own Sveavägen
    17: "Johan Enbergs väg 5, 171 62 Solna",
    20: "Källängsvägen 59, 181 44 Lidingö",
    24: "Tallkrogsvägen 99, 122 60 Enskede",
    25: "Lundagatan 2A, 171 63 Solna",
    34: "Kinnekullevägen 26, 167 43 Bromma",
    35: "Kungshamravägen 48, 170 70 Solna",
    44: "Norra Stationsgatan 99, 113 64 Stockholm",   # "Statsionsgatan" -> Stationsgatan
    45: "Lundagatan 53, 117 28 Stockholm",            # "Srtockholm"
    49: "Stationsvägen 13, 187 48 Täby",              # underscores in form
    50: "Baggensgatan 16A, 111 31 Stockholm",         # postcode was first
    55: "Fredrikslundsvägen 17, 168 34 Bromma",       # "Fredrikskundsvägen"
    56: "Vintergaloppsgatan 30, 183 41 Täby",
    6:  "Mörbydalen 28, 182 31 Danderyd",
    2:  "Gärdesvägen 8, 181 61 Lidingö",
    11: "Parkallén 46, 181 43 Lidingö",
    63: "Sandfjärdsgatan 88, 120 56 Årsta",
}

# Address strings that are already unambiguous get the default locality.
DEFAULT_LOCALITY = "Stockholm"


def clean(group_id: int, raw: str) -> str:
    if group_id in MANUAL_FIXES:
        base = MANUAL_FIXES[group_id]
    else:
        base = re.sub(r"[_ ]+", " ", raw).strip()
        base = re.sub(r"\s{2,}", " ", base)
        # "Polhemsgatan 6 11236" -> "Polhemsgatan 6, 112 36"
        base = re.sub(r"\s(\d{3})\s?(\d{2})\b", r", \1 \2", base)
        base = re.sub(r",\s*,", ",", base)
        if not re.search(r"(stockholm|solna|lidingö|täby|danderyd|bromma|nacka|årsta|"
                         r"djursholm|enskede|sundbyberg|hägersten|johanneshov)",
                         base, re.I):
            base = f"{base}, {DEFAULT_LOCALITY}"
    if not base.lower().rstrip().endswith("sweden"):
        base += ", Sweden"
    return base
