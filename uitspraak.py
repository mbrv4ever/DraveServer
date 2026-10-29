# -*- coding: utf-8 -*-
# Copyright (C) 2026 Dravenlock (Roger & Claudio). Licensed under the GNU GPL v3.0 or later - see LICENSE.
"""uitspraak.py - zorgt dat de Nederlandse stem alles goed uitspreekt.

Nieuw (DraveLeon, 28-10-2026): eerst gaan de eigen verbeteringen voor. Die staan in de lijst die je met
DraveLeon maakt (het pad staat in het register: HKCU\\Software\\Dravenlock, waarde LeonUitspraak), plus de
ingebouwde lijst INGEBOUWD hieronder (die zet DraveLeon erin bij een nieuwe bouwronde, voor iedereen).

Websites, e-mailadressen, eenheden en afkortingen worden voluit geschreven voordat de stem ze
uitspreekt: dravenlock.nl -> "dravenlock punt en el", 80 km/u -> "80 kilometer per uur".
Voor andere talen blijft de tekst zoals hij is.
"""
import re

# Woorden en tekens die de stem anders verkeerd uitspreekt (Nederlands).
_DOMEIN = {"nl": "punt en el", "com": "punt com", "be": "punt bee ee", "org": "punt org",
           "net": "punt net", "eu": "punt ee uu", "de": "punt dee ee", "io": "punt ie oo"}
_AFKORTING = [
    (r"\bkm/u\b", "kilometer per uur"), (r"\bkm/h\b", "kilometer per uur"),
    (r"(\d)\s?km\b", r"\1 kilometer"), (r"(\d)\s?mm\b", r"\1 millimeter"),
    (r"(\d)\s?cm\b", r"\1 centimeter"), (r"(\d)\s?kg\b", r"\1 kilo"),
    (r"(\d)\s?°C\b", r"\1 graden"), (r"(\d)\s?°", r"\1 graden"), (r"(\d)\s?%", r"\1 procent"),
    (r"(\d)\s?MB\b", r"\1 megabyte"), (r"(\d)\s?GB\b", r"\1 gigabyte"),
    (r"€\s?(\d+(?:,\d+)?)", r"\1 euro"), (r"\bt/m\b", "tot en met"), (r"\bbijv\.", "bijvoorbeeld"),
    (r"\bbv\.", "bijvoorbeeld"), (r"\benz\.", "enzovoort"), (r"\bo\.a\.", "onder andere"),
    (r"\bi\.p\.v\.", "in plaats van"), (r"\bz\.s\.m\.", "zo snel mogelijk"), (r"\bnr\.", "nummer"),
    (r"\bca\.", "ongeveer"), (r"\bmin\.", "minuten"), (r"\bAI\b", "aa ie"), (r"\bPC\b|\bpc\b", "pee see"),
    (r"\bUSB\b", "uu es bee"), (r"\bPDF\b|\bpdf\b", "pee dee ef"), (r"\bexe\b", "ex ee"),
    (r"\bGitHub\b", "Git hub"), (r"\be-mail\b", "iemeel"), (r"\bWi-?Fi\b|\bwifi\b", "waaifaai"),
    (r"@", " apenstaartje "),
]


def _domein(m):
    """www.dravenlock.nl/x -> dravenlock punt en el"""
    naam, ext = m.group(1), m.group(2).lower()
    naam = re.sub(r"^www\.", "", naam, flags=re.I).replace(".", " punt ")
    return "%s %s" % (naam, _DOMEIN.get(ext, "punt " + " ".join(ext)))


# ------------------------------------------------------------------ eigen verbeteringen (DraveLeon)
PAD = None              # (DraveLeon zet hier zelf het pad neer; andere apps gebruiken het register)
INGEBOUWD = {"dravenavi": "DraveNavigator"}          # woord (kleine letters) -> zo spreek je het uit; wordt gevuld vanuit DraveLeon
_eigen = {"pad": None, "tijd": 0, "woorden": {}, "regex": None}


def lijst_pad():
    """Waar staat de DraveLeon-lijst? (register, alleen op Windows)"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Dravenlock") as k:
            return winreg.QueryValueEx(k, "LeonUitspraak")[0]
    except Exception:
        return None


def eigen_woorden():
    """De verbeteringen: ingebouwd + de lijst van DraveLeon (wordt opnieuw gelezen als het bestand verandert)."""
    import json
    import os
    pad = PAD or lijst_pad()
    tijd = 0
    try:
        tijd = os.path.getmtime(pad) if pad else 0
    except OSError:
        pad = None
    if pad != _eigen["pad"] or tijd != _eigen["tijd"] or _eigen["regex"] is None:
        w = {k.lower(): v for k, v in INGEBOUWD.items()}
        if pad:
            try:
                with open(pad, encoding="utf-8-sig") as f:
                    w.update({k.lower(): v for k, v in (json.load(f).get("woorden") or {}).items() if k and v})
            except Exception:
                pass
        _eigen.update(pad=pad, tijd=tijd, woorden=w)
        if w:
            sleutels = sorted(w, key=len, reverse=True)       # langste eerst (zinnetjes voor losse woorden)
            _eigen["regex"] = re.compile(r"(?<![\w])(" + "|".join(re.escape(k) for k in sleutels) + r")(?![\w])", re.I)
        else:
            _eigen["regex"] = False
    return _eigen["woorden"]


def pas_eigen_toe(t):
    w = eigen_woorden()
    rx = _eigen["regex"]
    if not rx:
        return t
    return rx.sub(lambda m: w.get(m.group(0).lower(), m.group(0)), t)


def uitspraak(t, taal="nl"):
    """Tekst klaarmaken voor de stem. Alleen Nederlands wordt aangepast."""
    if not isinstance(t, str) or not str(taal or "").lower().startswith("nl"):
        return t
    t = pas_eigen_toe(t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)       # [tekst](link) -> tekst
    t = re.sub(r"https?://", "", t)
    t = re.sub(r"\b((?:[\w-]+\.)*[\w-]+)\.(nl|com|be|org|net|eu|de|io)\b(?:/\S*)?", _domein, t, flags=re.I)
    for p, n in _AFKORTING:
        t = re.sub(p, n, t)
    return re.sub(r"[ \t]+", " ", t)
