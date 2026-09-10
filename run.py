"""One-shot pipeline: geocode -> travel times -> calibrate -> solve -> export.

    python3 run.py              # real Google APIs (needs .env); spends money on
                                # the full 63x63 matrix - travel.py prints the
                                # element count + cost first
    python3 run.py --dry        # no API calls: Nominatim geocoding + straight-line times
    python3 run.py --haversine  # real geocode cache, straight-line travel times

travel.py refuses to spend without --yes; run.py passes it through on a real run.
"""
import importlib.util, subprocess, sys

DRY = "--dry" in sys.argv
HAVERSINE = "--haversine" in sys.argv or DRY

missing = [m for m in ("numpy", "openpyxl", "certifi") if not importlib.util.find_spec(m)]
if missing:
    print("Saknade paket:", ", ".join(missing))
    print(f"Installera med:  {sys.executable} -m pip install " + " ".join(missing))
    sys.exit(1)


def step(title, cmd):
    print(f"\n=== {title} " + "=" * (60 - len(title)))
    r = subprocess.run([sys.executable] + cmd)
    if r.returncode != 0:
        sys.exit(f"\nfailed at: {title}")


step("1/5  Geocoding", ["geocode.py"] + (["--fallback"] if DRY else []))
step("2/5  Restider", ["travel.py"] + (["--haversine"] if HAVERSINE else ["--yes"]))
step("3/5  Kalibrering", ["solve.py", "--calibrate"])
step("4/5  Schemaläggning", ["solve.py"])
step("5/5  Export", ["export.py"])

print("\nKlart. Starta kartan med:  python3 serve.py")
