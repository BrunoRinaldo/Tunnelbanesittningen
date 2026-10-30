"""Comms backend for the web UI: sendout previews, live SMS sending via
46elks (https://46elks.se), and delivery-status polling.

Message text per group is generated on demand from data/schedule.json using
the same functions export.py uses for out/meddelanden.csv, so the comms page
always sends exactly what the xlsx/CSV would contain. Send results are kept
in data/send_log.json (group -> status/sid/error), keyed per sendout, so the
page can show "not delivered" warnings after a send and on every reload.

46elks not configured (no ELKS_API_USERNAME/PASSWORD in .env) -> sends are
recorded as "skipped" instead of calling the gateway, so the page is usable
for reviewing templates/recipients before an account is wired up.
"""
import base64, json, os, time, urllib.error, urllib.parse, urllib.request

import config
import export
import net
import templates

HERE = os.path.dirname(os.path.abspath(__file__))
SCH = os.path.join(HERE, "data", "schedule.json")
LOG = os.path.join(HERE, "data", "send_log.json")

ELKS_URL = "https://api.46elks.com/a1/sms"

SENDOUTS = [
    ("dubbelkolla", "Dubbelkolla info"),
    ("schema", "Schema"),
    ("starter", "Förrätt"),
    ("main", "Varmrätt"),
    ("dessert", "Efterrätt"),
    ("efterfest", "Efterfest"),
]
SENDOUT_TITLES = dict(SENDOUTS)


def _load_log():
    if os.path.exists(LOG):
        return json.load(open(LOG, encoding="utf-8"))
    return {}


def _save_log(log):
    tmp = LOG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    os.replace(tmp, LOG)


def _load_schedule():
    if not os.path.exists(SCH):
        return None
    sch = json.load(open(SCH, encoding="utf-8"))
    gmap = {g["group_id"]: g for g in sch["groups"]}
    routes = {r["group"]: r for r in sch["routes"]}
    issy_addr = config.AFTERPARTY_ADDRESS.replace(", Sweden", "")
    return gmap, routes, issy_addr


def _messages_for_moment(moment):
    loaded = _load_schedule()
    if loaded is None:
        return []
    gmap, routes, issy_addr = loaded
    out = []
    for g in sorted(routes):
        for tab_key, role, msg in export.group_messages(g, routes[g], gmap, issy_addr):
            if tab_key != moment:
                continue
            gg = gmap[g]
            out.append({
                "group_id": g, "role": role, "message": msg,
                "phone1": gg["phone1"], "phone1_intl": export.intl_phone(gg["phone1"]),
                "name1": gg["name1"], "name2": gg["name2"],
            })
    return out


def elks_configured():
    return bool(config.ELKS_API_USERNAME and config.ELKS_API_PASSWORD)


def double_check_configured():
    return bool(config.DOUBLE_CHECK_NUMBER)


def _elks_request(method, url, data=None):
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers=dict(net.UA))
    auth = f"{config.ELKS_API_USERNAME}:{config.ELKS_API_PASSWORD}".encode()
    req.add_header("Authorization", "Basic " + base64.b64encode(auth).decode())
    with urllib.request.urlopen(req, timeout=30, context=net.CTX) as r:
        return json.loads(r.read().decode("utf-8"))


def send_sms(to, message):
    return _elks_request("POST", ELKS_URL, {
        "from": config.ELKS_FROM, "to": to, "message": message,
    })


def check_sms(sid):
    return _elks_request("GET", f"{ELKS_URL}/{sid}")


def _moment_view(key, log):
    msgs = _messages_for_moment(key)
    entries = log.get(key, {})
    groups, counts = [], {}
    for m in msgs:
        e = entries.get(str(m["group_id"]))
        status = e["status"] if e else "unsent"
        counts[status] = counts.get(status, 0) + 1
        groups.append({
            "group_id": m["group_id"], "name1": m["name1"], "name2": m["name2"],
            "role": m["role"], "phone1": m["phone1"], "status": status,
            "error": e.get("error") if e else None,
            "sent_at": e.get("sent_at") if e else None,
        })
    return {
        "key": key, "title": SENDOUT_TITLES[key], "templates": templates.get_templates(key),
        "recipients": len(msgs), "counts": counts, "groups": groups,
    }


def sendout_status():
    if not os.path.exists(SCH):
        return {"elks_configured": elks_configured(), "elks_from": config.ELKS_FROM,
                "double_check_configured": double_check_configured(),
                "schedule_missing": True, "sendouts": []}
    log = _load_log()
    return {
        "elks_configured": elks_configured(), "elks_from": config.ELKS_FROM,
        "double_check_configured": double_check_configured(),
        "schedule_missing": False,
        "sendouts": [_moment_view(k, log) for k, _ in SENDOUTS],
    }


def send_test_all():
    if not double_check_configured():
        raise ValueError("DUBBLE_CHECK_TEXTS_TO_NUMBER saknas i .env")
    if not os.path.exists(SCH):
        raise ValueError("inget schema inläst - kör python3 run.py")
    to = export.intl_phone(config.DOUBLE_CHECK_NUMBER)
    configured = elks_configured()
    results = []
    for moment, title in SENDOUTS:
        seen_roles = {}
        for m in _messages_for_moment(moment):
            seen_roles.setdefault(m["role"], m)
        for role, m in seen_roles.items():
            tag = f"[TEST {title}{' · ' + role if role else ''} · grupp {m['group_id']}]\n"
            text = tag + m["message"]
            rec = {"moment": moment, "title": title, "role": role, "group_id": m["group_id"]}
            if not to:
                rec.update(status="failed", error="inget testnummer")
            elif not configured:
                rec.update(status="skipped", error="46elks ej konfigurerat")
            else:
                try:
                    res = send_sms(to, text)
                    rec.update(status="sent", sid=res.get("id"))
                except urllib.error.HTTPError as e:
                    detail = e.read().decode("utf-8", errors="replace")[:200]
                    rec.update(status="failed", error=f"46elks HTTP {e.code}: {detail}")
                except Exception as e:
                    rec.update(status="failed", error=str(e))
            results.append(rec)
    return {"to": to, "results": results}


def send_moment(moment):
    if moment not in SENDOUT_TITLES:
        raise ValueError(f"okänt sendout: {moment}")
    msgs = _messages_for_moment(moment)
    log = _load_log()
    entries = log.setdefault(moment, {})
    configured = elks_configured()
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    for m in msgs:
        to = m["phone1_intl"]
        rec = {"to": to, "role": m["role"], "sent_at": now}
        if not to:
            rec.update(status="failed", error="inget telefonnummer")
        elif not configured:
            rec.update(status="skipped", error="46elks ej konfigurerat (.env: ELKS_API_USERNAME/ELKS_API_PASSWORD)")
        else:
            try:
                res = send_sms(to, m["message"])
                rec.update(status="sent", sid=res.get("id"), gw_status=res.get("status"))
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", errors="replace")[:200]
                rec.update(status="failed", error=f"46elks HTTP {e.code}: {detail}")
            except Exception as e:
                rec.update(status="failed", error=str(e))
        entries[str(m["group_id"])] = rec
    _save_log(log)
    return _moment_view(moment, log)


def refresh_status(moment):
    if moment not in SENDOUT_TITLES:
        raise ValueError(f"okänt sendout: {moment}")
    log = _load_log()
    entries = log.get(moment, {})
    if elks_configured():
        for rec in entries.values():
            sid = rec.get("sid")
            if not sid or rec.get("status") == "failed":
                continue
            try:
                res = check_sms(sid)
                gw = (res.get("status") or "").lower()
                rec["gw_status"] = gw
                if gw == "delivered":
                    rec["status"] = "delivered"
                elif gw == "failed":
                    rec["status"] = "failed"
                    rec["error"] = "gateway: leverans misslyckades"
                else:
                    rec["status"] = "sent"
            except Exception as e:
                rec["error"] = f"statuskontroll: {e}"
        log[moment] = entries
        _save_log(log)
    return _moment_view(moment, log)


def save_template(moment, role_index, text):
    if moment not in SENDOUT_TITLES:
        raise ValueError(f"okänt sendout: {moment}")
    templates.set_template(moment, role_index, text)
    return _moment_view(moment, _load_log())


def reset_template(moment, role_index):
    if moment not in SENDOUT_TITLES:
        raise ValueError(f"okänt sendout: {moment}")
    templates.reset_template(moment, role_index)
    return _moment_view(moment, _load_log())
