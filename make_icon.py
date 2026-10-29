# -*- coding: utf-8 -*-
"""Bouwt assets/icon.ico (en assets/logo.png) uit het Dravenlock-draaklogo."""
import os
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "assets")
os.makedirs(OUT, exist_ok=True)


def find_logo():
    for p in (os.path.join(HERE, "..", "assets", "logo.png"),
              os.path.join(HERE, "assets", "logo.png"),
              os.path.join(HERE, "..", "assets", "logo_t.png")):
        if os.path.exists(p):
            return p
    return None


def main():
    src = find_logo()
    if not src:
        # nood-icoon
        im = Image.new("RGBA", (256, 256), (127, 119, 221, 255))
    else:
        im = Image.open(src).convert("RGBA")
        w, h = im.size
        s = min(w, h)
        im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
    im.resize((256, 256), Image.LANCZOS).save(os.path.join(OUT, "logo.png"))
    im.resize((256, 256), Image.LANCZOS).save(
        os.path.join(OUT, "icon.ico"), format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("icon.ico + logo.png geschreven in", OUT)


if __name__ == "__main__":
    main()
