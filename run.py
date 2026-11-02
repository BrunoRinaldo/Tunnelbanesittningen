"""One-shot pipeline: geocode -> travel times -> calibrate -> solve -> export.

    python3 run.py              # real Google APIs (needs .env); spends money on
                                # the full 63x63 matrix - travel.py prints the
                                # element count + cost first
    python3 run.py --dry        # no API calls: Nominatim geocoding + straight-line times
    python3 run.py --haversine  # real geocode cache, straight-line travel times

    python3 run.py --participants svar.xlsx
                                # import that spreadsheet to data/participants.json
                                # first (format: README section 0). Without the
                                # flag, data/Grupper.xlsx is imported on every run;
                                # data/participants.json is only used as it is
                                # when that file does not exist.

travel.py refuses to spend without --yes; run.py passes it through on a real run.
"""
import importlib.util, os, subprocess, sys

DRY = "--dry" in sys.argv
HAVERSINE = "--haversine" in sys.argv or DRY

HERE = os.path.dirname(os.path.abspath(__file__))
PARTICIPANTS = None
if "--participants" in sys.argv:
    i = sys.argv.index("--participants")
    PARTICIPANTS = sys.argv[i + 1] if i + 1 < len(sys.argv) else os.path.join(HERE, "data", "Grupper.xlsx")

missing = [m for m in ("numpy", "scipy", "openpyxl", "certifi") if not importlib.util.find_spec(m)]
if missing:
    print("Saknade paket:", ", ".join(missing))
    print(f"Installera med:  {sys.executable} -m pip install " + " ".join(missing))
    sys.exit(1)


def step(title, cmd):
    print(f"\n=== {title} " + "=" * (60 - len(title)))
    r = subprocess.run([sys.executable] + cmd)
    if r.returncode != 0:
        sys.exit(f"\nfailed at: {title}")


PARTS_JSON = os.path.join(HERE, "data", "participants.json")
src = PARTICIPANTS or os.path.join(HERE, "data", "Grupper.xlsx")
if PARTICIPANTS or os.path.exists(src) or not os.path.exists(PARTS_JSON):
    step("0/5  Deltagarlista", ["import_participants.py", src])
else:
    print("data/Grupper.xlsx saknas - använder befintlig data/participants.json")

step("1/5  Geocoding", ["geocode.py"] + (["--fallback"] if DRY else []))
step("2/5  Restider", ["travel.py"] + (["--haversine"] if HAVERSINE else ["--yes"]))
step("3/5  Kalibrering", ["solve.py", "--calibrate"])
step("4/5  Schemaläggning", ["solve.py"])
step("5/5  Export", ["export.py"])

print("\nKlart. Starta kartan med:  python3 serve.py")
