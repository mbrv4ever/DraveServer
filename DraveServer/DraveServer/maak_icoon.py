# -*- coding: utf-8 -*-
"""Maakt app.ico (en logo.ico) uit logo.png. Vereist Pillow."""
import os
BASIS = os.path.dirname(os.path.abspath(__file__))
try:
    from PIL import Image
except Exception:
    print("Pillow ontbreekt. Installeer met: pip install pillow")
    raise SystemExit(1)

bron = os.path.join(BASIS, "logo.png")
if not os.path.exists(bron):
    print("logo.png niet gevonden.")
    raise SystemExit(1)

afb = Image.open(bron).convert("RGBA")
maten = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
afb.save(os.path.join(BASIS, "app.ico"), sizes=maten)
afb.save(os.path.join(BASIS, "logo.ico"), sizes=maten)
print("app.ico en logo.ico gemaakt.")
