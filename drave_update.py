# -*- coding: utf-8 -*-
# drave_update.py - Dravenlock update-melding.
# Copyright (C) 2026 Dravenlock (Roger & Claudio). Vrije software onder de GNU GPL v3.0.
"""Kijkt bij het opstarten stil op GitHub of er een nieuwere versie van de app is.

- Er gaat NIETS van de gebruiker mee: de app vraagt alleen "wat is de nieuwste versie?".
- Geen internet? Dan gebeurt er niets (geen foutmelding).
- Uit te zetten: vinkje "Niet meer automatisch controleren" in de melding.
- Altijd met de hand: Ctrl+Shift+U (in Qt-apps). Daar kun je het ook weer aanzetten.
- De keuze staat in %APPDATA%\\Dravenlock\\updates.json (per app).

Gebruik (één regel na het tonen van het hoofdvenster):
    import drave_update; drave_update.start(venster, "DraveNote", VERSIE)
"""
import json
import os
import re
import sys
import threading
import urllib.request
import webbrowser

EIGENAAR = "mbrv4ever"
_TIMEOUT = 6


# ------------------------------------------------------------------ instellingen
def _cfg_pad():
    basis = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    map_ = os.path.join(basis, "Dravenlock")
    try:
        os.makedirs(map_, exist_ok=True)
    except Exception:
        pass
    return os.path.join(map_, "updates.json")


def _lees():
    try:
        with open(_cfg_pad(), encoding="utf-8-sig") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def automatisch(repo):
    return _lees().get(repo, {}).get("automatisch", True) is not False


def zet_automatisch(repo, aan):
    d = _lees()
    d.setdefault(repo, {})["automatisch"] = bool(aan)
    try:
        with open(_cfg_pad(), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


# ------------------------------------------------------------------ GitHub
def _als_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:4]) or (0,)


def nieuwer(nieuw, huidig):
    a, b = _als_tuple(nieuw), _als_tuple(huidig)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def nieuwste(repo):
    """(versie, link) van de nieuwste release, of None (geen internet / niets gevonden)."""
    url = "https://api.github.com/repos/%s/%s/releases/latest" % (EIGENAAR, repo)
    req = urllib.request.Request(url, headers={"User-Agent": "Dravenlock-update", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            d = json.loads(r.read().decode("utf-8"))
        tag = (d.get("tag_name") or "").lstrip("vV")
        link = d.get("html_url") or "https://github.com/%s/%s/releases/latest" % (EIGENAAR, repo)
        return (tag, link) if tag else None
    except Exception:
        return None


def _tekst(app, huidig, nieuw):
    return ("Er is een nieuwe versie van %s!\n\nJij hebt versie %s.\nNieuw: versie %s.\n\n"
            "Wil je de nieuwe versie downloaden?" % (app, huidig, nieuw))


# ------------------------------------------------------------------ Qt (PyQt6 / PySide6 / PyQt5)
def _qt():
    for naam in ("PyQt6", "PySide6", "PyQt5"):
        if naam in sys.modules:
            try:
                core = __import__(naam + ".QtCore", fromlist=["QTimer"])
                widgets = __import__(naam + ".QtWidgets", fromlist=["QMessageBox"])
                gui = __import__(naam + ".QtGui", fromlist=["QKeySequence"])
                return core, widgets, gui
            except Exception:
                return None
    return None


def _qt_melding(venster, app, repo, huidig, uitkomst, met_hand):
    core, w, gui = _qt()
    if uitkomst is None:
        if met_hand:
            w.QMessageBox.information(venster, "Updates", "Kon niet controleren op updates.\n"
                                      "Is er internet?")
        return
    nieuw, link = uitkomst
    if not nieuwer(nieuw, huidig):
        if met_hand:
            vak = w.QMessageBox(venster)
            vak.setWindowTitle("Updates")
            vak.setText("%s is helemaal bij: je hebt de nieuwste versie (%s)." % (app, huidig))
            vinkje = w.QCheckBox("Automatisch controleren bij het opstarten")
            vinkje.setChecked(automatisch(repo))
            vak.setCheckBox(vinkje)
            vak.exec()
            zet_automatisch(repo, vinkje.isChecked())
        return
    vak = w.QMessageBox(venster)
    vak.setWindowTitle("Nieuwe versie van %s" % app)
    vak.setText(_tekst(app, huidig, nieuw))
    ja = vak.addButton("Downloaden", w.QMessageBox.ButtonRole.AcceptRole if hasattr(w.QMessageBox, "ButtonRole")
                       else w.QMessageBox.AcceptRole)
    vak.addButton("Later", w.QMessageBox.ButtonRole.RejectRole if hasattr(w.QMessageBox, "ButtonRole")
                  else w.QMessageBox.RejectRole)
    vinkje = w.QCheckBox("Niet meer automatisch controleren")
    vinkje.setChecked(not automatisch(repo))
    vak.setCheckBox(vinkje)
    vak.exec()
    zet_automatisch(repo, not vinkje.isChecked())
    if vak.clickedButton() is ja:
        webbrowser.open(link)


def _qt_start(venster, app, repo, huidig, met_hand):
    core, w, gui = _qt()
    bak = {}

    def werk():
        bak["r"] = nieuwste(repo)

    t = threading.Thread(target=werk, daemon=True)
    t.start()
    timer = core.QTimer(venster)

    def kijk():
        if t.is_alive():
            return
        timer.stop()
        try:
            _qt_melding(venster, app, repo, huidig, bak.get("r"), met_hand)
        except Exception:
            pass

    timer.timeout.connect(kijk)
    timer.start(400)
    venster._drave_update_timer = timer  # niet laten opruimen


# ------------------------------------------------------------------ tkinter / overige (Windows-melding)
def _win_melding(app, repo, huidig, uitkomst, met_hand):
    try:
        import ctypes
        box = ctypes.windll.user32.MessageBoxW
    except Exception:
        return
    if uitkomst is None:
        if met_hand:
            box(None, "Kon niet controleren op updates. Is er internet?", "Updates", 0x40)
        return
    nieuw, link = uitkomst
    if not nieuwer(nieuw, huidig):
        if met_hand:
            box(None, "%s is helemaal bij: je hebt de nieuwste versie (%s)." % (app, huidig), "Updates", 0x40)
        return
    tekst = (_tekst(app, huidig, nieuw) + "\n\nJa = nu downloaden\nNee = later\n"
             "Annuleren = niet meer automatisch controleren")
    k = box(None, tekst, "Nieuwe versie van %s" % app, 0x3 | 0x40 | 0x40000)  # ja/nee/annuleren, info, bovenop
    if k == 6:
        webbrowser.open(link)
    elif k == 2:
        zet_automatisch(repo, False)


def _achtergrond(app, repo, huidig, met_hand):
    threading.Thread(target=lambda: _win_melding(app, repo, huidig, nieuwste(repo), met_hand), daemon=True).start()


# ------------------------------------------------------------------ openbaar
def start(venster, repo, huidig, app=None, met_hand=False):
    """Start de stille update-check. Veilig: doet nooit iets kapot, ook zonder internet."""
    app = app or repo
    try:
        if not met_hand and not automatisch(repo):
            pass
        elif venster is not None and _qt():
            _qt_start(venster, app, repo, huidig, met_hand)
        else:
            _achtergrond(app, repo, huidig, met_hand)
    except Exception:
        pass
    # Ctrl+Shift+U = met de hand controleren (alleen Qt)
    if not met_hand and venster is not None:
        try:
            core, w, gui = _qt()
            sc_cls = getattr(gui, "QShortcut", None) or getattr(w, "QShortcut")
            sc = sc_cls(gui.QKeySequence("Ctrl+Shift+U"), venster)
            sc.activated.connect(lambda: start(venster, repo, huidig, app, met_hand=True))
            venster._drave_update_sneltoets = sc
        except Exception:
            pass
