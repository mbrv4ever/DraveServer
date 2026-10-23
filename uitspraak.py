# -*- coding: utf-8 -*-
# Copyright (C) 2026 Dravenlock (Roger & Claudio). Licensed under the GNU GPL v3.0 or later - see LICENSE.
"""uitspraak.py - zorgt dat de Nederlandse stem alles goed uitspreekt.

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


def uitspraak(t, taal="nl"):
    """Tekst klaarmaken voor de stem. Alleen Nederlands wordt aangepast."""
    if not isinstance(t, str) or not str(taal or "").lower().startswith("nl"):
        return t
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)       # [tekst](link) -> tekst
    t = re.sub(r"https?://", "", t)
    t = re.sub(r"\b((?:[\w-]+\.)*[\w-]+)\.(nl|com|be|org|net|eu|de|io)\b(?:/\S*)?", _domein, t, flags=re.I)
    for p, n in _AFKORTING:
        t = re.sub(p, n, t)
    return re.sub(r"[ \t]+", " ", t)
