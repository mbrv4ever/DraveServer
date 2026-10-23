# -*- coding: utf-8 -*-
"""DraveServer tray-app - draait de AI-chatserver in het systeemvak (bij de klok).

Geen zwart venster meer: een draken-icoontje naast de klok met een menu. Er is
ook een beheerscherm om een model te kiezen of te downloaden, en om status/token
te bekijken. De server draait in een achtergrond-thread; logregels gaan naar
cache/server.log.
"""
import os
import sys
import time
import threading
import webbrowser


# --- Zonder console (pythonw / --windowed) zijn stdout/stderr None. Veel
#     libraries (huggingface-download-balk, gpt4all) schrijven daar toch naar en
#     crashen dan met "'NoneType' object has no attribute 'write'". Vang dat af. ---
class _NullIO:
    def write(self, *a, **k):
        return 0

    def flush(self):
        pass

    def isatty(self):
        return False


if sys.stdout is None:
    sys.stdout = _NullIO()
if sys.stderr is None:
    sys.stderr = _NullIO()

# geen voortgangsbalken/telemetrie (die willen ook naar de console schrijven)
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import server  # onze eigen server.py (zelfde map)

DL_REPO = "bartowski/Llama-3.2-3B-Instruct-GGUF"
DL_FILE = "Llama-3.2-3B-Instruct-Q4_K_M.gguf"

_panel_lock = threading.Lock()
_panel_open = False


def _asset(*names):
    base = server.app_dir()
    for n in names:
        p = os.path.join(base, n)
        if os.path.exists(p):
            return p
    return None


def load_icon():
    from PIL import Image
    p = _asset(os.path.join("assets", "icon.ico"),
               os.path.join("assets", "logo.png"), "icon.ico", "logo.png")
    if p:
        try:
            return Image.open(p).convert("RGBA")
        except Exception:
            pass
    return Image.new("RGBA", (64, 64), (127, 119, 221, 255))


def copy_to_clipboard(text):
    try:
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        r.clipboard_clear()
        r.clipboard_append(text)
        r.update()
        r.destroy()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- beheerscherm
def open_panel():
    global _panel_open
    with _panel_lock:
        if _panel_open:
            return
        _panel_open = True
    threading.Thread(target=_panel_thread, daemon=True).start()


def _panel_thread():
    global _panel_open
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox
    except Exception:
        _panel_open = False
        return

    BG, FG, ACC = "#16131f", "#e8e6f0", "#b59cff"
    root = tk.Tk()
    root.title("DraveServer - beheer")
    root.configure(bg=BG)
    root.geometry("470x330")
    try:
        icop = _asset(os.path.join("assets", "icon.ico"))
        if icop:
            root.iconbitmap(icop)
    except Exception:
        pass

    port = int(server.config.get("port", 8808)) if server.config else 8808
    token = server.config.get("token", "") if server.config else ""
    url = "http://127.0.0.1:%d/" % port

    tk.Label(root, text="DraveServer - AI-chatserver", bg=BG, fg=ACC,
             font=("Segoe UI", 13, "bold")).pack(pady=(12, 6), padx=14)

    status_var = tk.StringVar()
    tk.Label(root, textvariable=status_var, bg=BG, fg=FG, justify="left",
             wraplength=440, font=("Segoe UI", 10)).pack(padx=14, anchor="w")

    def refresh():
        mp = server.config.get("model_path", "") if server.config else ""
        name = os.path.basename(mp) if mp else "(geen model)"
        loaded = "JA" if getattr(server, "_model", None) is not None else "NEE"
        status_var.set("Model:   %s\nGeladen: %s\nWebchat: %s\nToken:   %s"
                       % (name, loaded, url, token))

    refresh()

    prog_var = tk.StringVar(value="")
    tk.Label(root, textvariable=prog_var, bg=BG, fg="#8fd0ff", justify="left",
             wraplength=440, font=("Segoe UI", 10)).pack(padx=14, pady=(8, 0), anchor="w")

    def set_prog(msg):
        try:
            root.after(0, lambda: prog_var.set(msg))
        except Exception:
            pass

    def choose():
        p = filedialog.askopenfilename(
            title="Kies een .gguf-model",
            filetypes=[("GGUF-model", "*.gguf"), ("Alle bestanden", "*.*")])
        if not p:
            return
        set_prog("Model laden...")

        def work():
            ok, info = server.set_model(p, log=set_prog)
            set_prog(("Klaar: " + info) if ok else ("Fout: " + info))
            root.after(0, refresh)
        threading.Thread(target=work, daemon=True).start()

    def download():
        if not messagebox.askyesno(
                "Model downloaden",
                "Een klein model downloaden (~2 GB, Llama-3.2-3B)?\n"
                "Dit kan een tijdje duren."):
            return
        set_prog("Downloaden... (dit duurt even, venster blijft reageren)")

        def work():
            # Alles PORTABLE: dwing huggingface om in de app-map te cachen,
            # niet in ~/.cache of een andere standaardmap.
            hf_cache = os.path.join(server.cache_dir(), "hf")
            os.makedirs(hf_cache, exist_ok=True)
            os.environ["HF_HOME"] = hf_cache
            os.environ["HF_HUB_CACHE"] = os.path.join(hf_cache, "hub")
            os.environ["HUGGINGFACE_HUB_CACHE"] = os.path.join(hf_cache, "hub")
            try:
                from huggingface_hub import hf_hub_download
            except Exception:
                set_prog("huggingface_hub ontbreekt. Gebruik 'Model kiezen', of "
                         "installeer met: pip install huggingface_hub")
                return
            try:
                dest = os.path.join(server.cache_dir(), "models")
                os.makedirs(dest, exist_ok=True)
                kw = dict(repo_id=DL_REPO, filename=DL_FILE, local_dir=dest,
                          cache_dir=os.path.join(hf_cache, "hub"))
                try:
                    path = hf_hub_download(local_dir_use_symlinks=False, **kw)
                except TypeError:
                    path = hf_hub_download(**kw)  # nieuwere hub zonder die param
                set_prog("Gedownload. Model laden...")
                ok, info = server.set_model(path, log=lambda m: None)
                set_prog(("Klaar: " + info) if ok else ("Fout: " + info))
                root.after(0, refresh)
            except Exception as e:
                set_prog("Download mislukt: " + str(e))
        threading.Thread(target=work, daemon=True).start()

    def mkbtn(parent, text, cmd):
        return tk.Button(parent, text=text, command=cmd, bg="#2a2440",
                         fg="#efeaff", activebackground="#3a3358",
                         activeforeground="#fff", relief="flat", padx=10, pady=6)

    row1 = tk.Frame(root, bg=BG)
    row1.pack(pady=(14, 4), padx=14, fill="x")
    mkbtn(row1, "Model kiezen (.gguf)", choose).pack(side="left", padx=(0, 6))
    mkbtn(row1, "Klein model downloaden", download).pack(side="left", padx=(0, 6))

    row2 = tk.Frame(root, bg=BG)
    row2.pack(pady=(0, 4), padx=14, fill="x")
    mkbtn(row2, "Webchat openen", lambda: webbrowser.open(url)).pack(side="left", padx=(0, 6))
    mkbtn(row2, "Demo openen", lambda: webbrowser.open(url + "demo")).pack(side="left", padx=(0, 6))
    mkbtn(row2, "Token kopieren", lambda: copy_to_clipboard(token)).pack(side="left", padx=(0, 6))

    def open_diag():
        p = os.path.join(server.cache_dir(), "gpt4all_diag.txt")
        if os.path.exists(p):
            try:
                os.startfile(p)
            except Exception:
                pass
        else:
            set_prog("Nog geen diagnose - probeer eerst een model te laden.")

    row3 = tk.Frame(root, bg=BG)
    row3.pack(pady=(0, 4), padx=14, fill="x")
    mkbtn(row3, "Diagnose tonen (bij laadfout)", open_diag).pack(side="left", padx=(0, 6))

    tk.Label(root, text="Tip: model in ..\\DraveChat\\cache\\models wordt "
             "automatisch gevonden.", bg=BG, fg="#9a90bb",
             font=("Segoe UI", 9)).pack(padx=14, pady=(10, 0), anchor="w")

    def on_close():
        global _panel_open
        _panel_open = False
        try:
            root.destroy()
        except Exception:
            pass

    root.protocol("WM_DELETE_WINDOW", on_close)
    try:
        root.mainloop()
    finally:
        _panel_open = False


# ---------------------------------------------------------------- tray
def main():
    try:  # Dravenlock: stille update-check (uit te zetten in de melding)
        import drave_update
        drave_update.start(None, 'DraveServer', '0.31.2')
    except Exception:
        pass
    try:
        logpath = os.path.join(server.cache_dir(), "server.log")
        logf = open(logpath, "a", encoding="utf-8")
    except Exception:
        logf = None

    def log(msg):
        line = time.strftime("[%H:%M:%S] ") + str(msg)
        if logf:
            try:
                logf.write(line + "\n")
                logf.flush()
            except Exception:
                pass

    threading.Thread(target=server.run, kwargs={"log": log}, daemon=True).start()

    for _ in range(100):
        if getattr(server, "config", None) and server.config.get("token"):
            break
        time.sleep(0.1)
    port = int(server.config.get("port", 8808)) if server.config else 8808
    token = server.config.get("token", "") if server.config else ""
    url = "http://127.0.0.1:%d/" % port

    import pystray
    from pystray import MenuItem as Item

    def on_panel(icon, item):
        open_panel()

    def on_open(icon, item):
        webbrowser.open(url)

    def on_demo(icon, item):
        webbrowser.open(url + "demo")

    def on_token(icon, item):
        if copy_to_clipboard(token):
            try:
                icon.notify("Token gekopieerd naar klembord.", "DraveServer")
            except Exception:
                pass

    def on_log(icon, item):
        try:
            os.startfile(os.path.join(server.cache_dir(), "server.log"))
        except Exception:
            pass

    def on_quit(icon, item):
        log("Afsluiten via tray.")
        try:
            server.stop()
        except Exception:
            pass
        icon.stop()
        os._exit(0)

    menu = pystray.Menu(
        Item("Model / instellingen...", on_panel, default=True),
        Item("Webchat openen", on_open),
        Item("Widget-demo openen", on_demo),
        Item("Token kopieren", on_token),
        Item("Logboek openen", on_log),
        pystray.Menu.SEPARATOR,
        Item("Afsluiten", on_quit),
    )
    icon = pystray.Icon("DraveServer", load_icon(),
                        "DraveServer - AI-chatserver", menu)

    # geen model? open meteen het beheerscherm zodat je er een kunt laden
    try:
        if not server.find_model():
            open_panel()
    except Exception:
        pass

    icon.run()


if __name__ == "__main__":
    main()
