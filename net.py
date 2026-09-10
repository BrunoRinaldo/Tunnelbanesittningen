"""HTTPS helper with a working certificate store.

Python installed from python.org on macOS ships without root certificates, so
every HTTPS call fails with CERTIFICATE_VERIFY_FAILED until you either run
"Install Certificates.command" or point Python at certifi's bundle. This module
uses certifi when it is importable and falls back to the system store, so the
scripts work either way.
"""
import json, ssl, sys, urllib.error, urllib.request

UA = {"User-Agent": "tunnelbanesittning/1.0 (KTH I-sektionen)"}

CERT_HELP = """
HTTPS misslyckades: Python hittar inga rot-certifikat.

Det här drabbar Python installerat från python.org på macOS. Fixa med EN av dessa:

  1)  python3 -m pip install certifi
      (skripten hittar den automatiskt - kör sedan om python3 run.py)

  2)  Kör en gång, sedan är det löst för all Python på datorn:
      "/Applications/Python 3.14/Install Certificates.command"
"""


def _ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


CTX = _ctx()


def get_json(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            return json.loads(r.read().decode("utf-8"))
    except ssl.SSLCertVerificationError:
        sys.exit(CERT_HELP)
    except urllib.error.URLError as e:
        if isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError):
            sys.exit(CERT_HELP)
        raise


def check_key(key, name="GOOGLE_API_KEY"):
    """Catch the placeholder before spending a round trip on it."""
    if not key:
        sys.exit(f"Ingen {name} hittad. Lägg en rad i .env:\n\n    {name}=AIza...\n")
    if "din nyckel" in key or key.endswith("...") or not key.startswith("AIza"):
        sys.exit(
            f"{name} ser ut som platshållaren, inte en riktig nyckel:\n\n    {key}\n\n"
            "Google-nycklar börjar med AIza och är ~39 tecken. Öppna .env och klistra in\n"
            "din riktiga nyckel, utan citattecken och utan ...\n"
        )
