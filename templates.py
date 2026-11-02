"""Editable SMS message templates, shared by export.py (xlsx/meddelanden.csv)
and comms.py (the web comms page + live sending), so an edit made in the web
UI changes what actually gets sent and what export.py writes out - there is
only one copy of the wording.

A template is plain text with [token] placeholders. DEFAULTS below is the
copy shipped in this repo; edits made from the web UI are stored as
overrides in data/message_templates.json (one entry per moment, holding the
full list of role variants so role order/count always matches DEFAULTS).
Falls back to the default text for any role that has not been customised,
or if the override file is missing/corrupt.
"""
import json, os, re

import config

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "data", "message_templates.json")

# moment key -> [(role, default text)]. role "" = only variant for that moment.
DEFAULTS = {
    "dubbelkolla": [("", (
        "Hej [name1] & [name2]!\n"
        "Grattis till er plats i tunnelbanesittningen den [datum]. \n\n"
        "Dubbelkolla att denna info stämmer innan tunnelbanesittningen:\n\n"
        "Er adress: [adress]\n"
        "Allergier: [allergier]\n"
        "Alkoholpreferens: [alkoholpreferens]\n"
        "Sekundärt nummer: [telefon2]\n"
        "E-post: [epost]\n\n"
        "Svara på detta meddelande senast [sista_svarsdag] om något är fel eller saknas.\n\n"
        "Ses på TBS och vi älskar er!\n"
        "Kulturnämnden"
    ))],
    "schema": [("", (
        "Hej igen [name1] & [name2], nu bär det snart av!\n\n"
        "De ni besöker hålls hemligt och kommer skickas ut 1h innan rätten serveras.\n\n"
        "Kvällens schema:\n"
        "FÖRRÄTT kl [tid1]\n"
        "VARMRÄTT kl [tid2]\n"
        "EFTERRÄTT kl [tid3]\n"
        "EFTERFEST kl [tid4]\n\n"
        "Ni är ansvariga för [er_rätt]. Den lagar och serverar ni hemma hos er.\n"
        "När ni lagar mat måste ni ta hänsyn till:\n"
        "Allergier: [gästers_allergier]\n"
        "Alkoholpreferens: [gästers_alkoholpreferens]\n\n"
        f"Ses snart på {config.AFTERPARTY_NAME}!\n"
        "Puss Puss,\nKulturnämnden"
    ))],
    "starter": [
        ("Värd", (
            "Tjenare [name1] och [name2]!\n\n"
            "FÖRRÄTT, NI ÄR VÄRDAR\n\n"
            "Gästerna är framme kl [tid1]. Ni blir totalt 6 personer.\n\n"
            "Era gästers allergier:\n[gästallergier]\n"
            "Era gästers alkoholpreferenser:\n[gästalkohol]\n\n"
            "Drink Responsibally (or dont)...\nKulturnämnden"
        )),
        ("Gäst", (
            "Tjenare [name1] och [name2]!\n\n"
            "FÖRRÄTT startar kl [tid1], åk till adressen: [värd_adress].\n"
            "Ring värden: [värdens_telefon]\n\n"
            "Drink Responsibally (or dont)...\nKulturnämnden"
        )),
    ],
    "main": [
        ("Värd", (
            "Tjenare [name1] och [name2]!\n\n"
            "VARMRÄTT, NI ÄR VÄRDAR, hemma hos er:\n"
            "[er_adress]\n"
            "Gästerna är framme kl [tid1]. Ni blir 6 personer (3 par inkl. er).\n\n"
            "Era gästers allergier / kostönskemål:\n[gästallergier]\n"
            "Era gästers alkoholpreferenser:\n[gästalkohol]\n\n"
            "Kom inte sent!!!\nKulturnämnden"
        )),
        ("Gäst", (
            "Tjenare [name1] och [name2]!\n\n"
            "Snart dags för varmrätten, åk till adressen: [värd_adress]. Ni ska vara "
            "framme kl [tid1] (vårt script estimerar ~[minuter_hit] min [färdsätt_hit], "
            "men dubbelkolla er exakta restid).\n"
            "Ring värden: [värdens_telefon]\n\n"
            "Kom inte sent!!!\nKulturnämnden"
        )),
    ],
    "dessert": [
        ("Värd", (
            "Tjenare [name1] och [name2]!\n\n"
            "EFTERRÄTT, NI ÄR VÄRDAR, hemma hos er:\n"
            "[er_adress]\n"
            "Gästerna är framme kl [tid1]. Ni blir 6 personer (3 par inkl. er).\n\n"
            "Era gästers allergier / kostönskemål:\n[gästallergier]\n"
            "Era gästers alkoholpreferenser:\n[gästalkohol]\n\n"
            f"Efter efterrätten: efterfest kl [tid2] på {config.AFTERPARTY_NAME}.\n\n"
            "Det är snart dags för sötsaker och drinkar!\nKulturnämnden"
        )),
        ("Gäst", (
            "Tjenare [name1] och [name2]!\n\n"
            "Snart dags för efterrätten, åk till adressen: [värd_adress]. Ni ska vara "
            "framme kl [tid1] (vårt script estimerar ~[minuter_hit] min [färdsätt_hit], "
            "men dubbelkolla er exakta restid).\n"
            "Ring värden: [värdens_telefon]\n\n"
            f"Efter efterrätten: efterfest kl [tid2] på {config.AFTERPARTY_NAME}.\n\n"
            "Det är snart dags för sötsaker och drinkar!\nKulturnämnden"
        )),
    ],
    "efterfest": [("", (
        "Dags för efterfest [name1] och [name2]!!!\n\n"
        f"Rätterna är avklarade, nu rullar vi vidare mot {config.AFTERPARTY_NAME}. Ingen matlagning, inga "
        "adresser att pricka av; bara ni, alla andra och en taggad kulturnämnd som väntar.\n\n"
        "Efterfest börjar kl [tid1] på adressen: [issy-adress].\n\n"
        "Vi ses i dimman!\nKulturnämnden"
    ))],
}

_TOKEN = re.compile(r"\[([\w-]+)\]")


def render(text, values):
    """Replace [token] with values[token]; unknown tokens are left as-is so a
    typo in an edited template shows up visibly instead of silently eating
    real message content."""
    return _TOKEN.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), text)


def _load_overrides():
    if not os.path.exists(STORE):
        return {}
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {}


def _save_overrides(overrides):
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(overrides, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STORE)


def get_templates(key):
    """[{role, text, default, customized}] for moment `key`."""
    if key not in DEFAULTS:
        raise ValueError(f"okänt sendout: {key}")
    overrides = _load_overrides().get(key) or []
    out = []
    for i, (role, dtext) in enumerate(DEFAULTS[key]):
        o = overrides[i] if i < len(overrides) else None
        text = o.get("text", dtext) if o else dtext
        out.append({"role": role, "text": text, "default": dtext, "customized": text != dtext})
    return out


def get_template_text(key, role_index):
    return get_templates(key)[role_index]["text"]


def set_template(key, role_index, text):
    if key not in DEFAULTS:
        raise ValueError(f"okänt sendout: {key}")
    n = len(DEFAULTS[key])
    if not (0 <= role_index < n):
        raise ValueError("ogiltigt rollindex")
    overrides = _load_overrides()
    cur = overrides.get(key) or [{"role": r, "text": t} for r, t in DEFAULTS[key]]
    if len(cur) != n:
        cur = [{"role": r, "text": t} for r, t in DEFAULTS[key]]
    cur[role_index] = {"role": DEFAULTS[key][role_index][0], "text": text}
    overrides[key] = cur
    _save_overrides(overrides)
    return get_templates(key)


def reset_template(key, role_index):
    if key not in DEFAULTS:
        raise ValueError(f"okänt sendout: {key}")
    n = len(DEFAULTS[key])
    if not (0 <= role_index < n):
        raise ValueError("ogiltigt rollindex")
    overrides = _load_overrides()
    if key in overrides and role_index < len(overrides[key]):
        overrides[key][role_index] = {"role": DEFAULTS[key][role_index][0],
                                       "text": DEFAULTS[key][role_index][1]}
        _save_overrides(overrides)
    return get_templates(key)
