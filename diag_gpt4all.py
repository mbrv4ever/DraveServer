# -*- coding: utf-8 -*-
"""Diagnose: waarom laadt gpt4all's DLL niet? Draai dit met je gewone Python
(dezelfde waarmee DraveChat/de server werkt). Het print de gpt4all-versie, de
inhoud van de build-map en probeert elke DLL te laden met de exacte foutcode.
Maak van de uitvoer een screenshot en stuur die."""
import os
import sys
import ctypes
import importlib.util

print("=" * 60)
print("Python     :", sys.version.split()[0], "(64-bit)" if sys.maxsize > 2**32 else "(32-bit)")
print("Platform   :", sys.platform)

try:
    import gpt4all
    print("gpt4all    :", getattr(gpt4all, "__version__", "?"))
except Exception as e:
    print("gpt4all IMPORT FAALDE:", e)

spec = importlib.util.find_spec("gpt4all")
if not spec or not spec.submodule_search_locations:
    print("Kon gpt4all-map niet vinden. Is gpt4all wel geinstalleerd?")
    input("\nEnter om te sluiten...")
    sys.exit(0)

base = list(spec.submodule_search_locations)[0]
build = os.path.join(base, "llmodel_DO_NOT_MODIFY", "build")
print("build-map  :", build)
print("bestaat    :", os.path.isdir(build))
print("-" * 60)

if os.path.isdir(build):
    print("Bestanden in build-map:")
    dlls = []
    for f in sorted(os.listdir(build)):
        full = os.path.join(build, f)
        size = os.path.getsize(full)
        print("   %-45s %8d bytes" % (f, size))
        if f.lower().endswith(".dll"):
            dlls.append(full)

    print("-" * 60)
    # map aan het zoekpad toevoegen (zoals de app ook doet)
    try:
        os.add_dll_directory(build)
        print("add_dll_directory: OK")
    except Exception as e:
        print("add_dll_directory faalde:", e)

    print("-" * 60)
    print("Probeer elke DLL te laden (fout = de dader / ontbrekende dep):")
    for p in dlls:
        name = os.path.basename(p)
        try:
            ctypes.CDLL(p)
            print("   OK    :", name)
        except OSError as e:
            print("   FOUT  :", name, "->", e)
else:
    print("De build-map ontbreekt. gpt4all is dan niet compleet geinstalleerd.")

print("=" * 60)
print("Klaar. Maak a.u.b. een screenshot van dit venster.")
input("Enter om te sluiten...")
