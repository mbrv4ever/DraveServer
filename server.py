# -*- coding: utf-8 -*-
"""DraveServer - een lokale AI-chatserver van Dravenlock.

Laadt hetzelfde lokale taalmodel als DraveChat (via gpt4all) en biedt:
  - een webpagina-chat op  http://<pc>:8808/
  - een API:  POST /api/chat   (JSON {"message": "..."} + token)
              POST /api/reset   (nieuw gesprek)
              GET  /api/health

Zo kan de chat op een site of in andere apps/scripts gebruikt worden.

BEVEILIGING (lees dit!):
  - De API vereist een TOKEN (staat in cache/server_config.json en wordt in de
    console getoond). Zonder token -> geweigerd.
  - Persoonlijk geheugen staat STANDAARD UIT (use_memory=false) zodat je privé-
    feiten niet worden blootgesteld. Kennisnotities (knowledge) kun je wel zetten.
  - De server luistert op je hele netwerk (LAN). Wil je 'm vanaf internet
    bereiken, dan moet je zelf port-forwarding op je router doen OF een tunnel
    gebruiken (bv. Cloudflare Tunnel / Tailscale). Zie README. Doe dit met
    beleid: een open AI-server kan misbruikt worden.

Puur Python-standaardbibliotheek (behalve gpt4all). Portable, Donationware.
"""
import html as _html
import json
import os
import secrets
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# --- oude AMD/NVIDIA env-var die naar niet-bestaande map wijst opruimen
# (anders crasht gpt4all/llama bij het laden) ---
for _v in ("HIP_PATH", "HIP_PATH_57", "CUDA_PATH", "ROCM_PATH"):
    _p = os.environ.get(_v)
    if _p and not os.path.isdir(os.path.join(_p, "bin")):
        os.environ.pop(_v, None)


# --- gpt4all in een EXE (PyInstaller): de map met libllmodel.dll + backend-DLL's
# staat niet automatisch in het DLL-zoekpad -> "dynlib not found when frozen".
# Zet die map er expliciet bij, VOORDAT gpt4all geimporteerd wordt. ---
def _gpt4all_dirs():
    """Mogelijke gpt4all-mappen; in een EXE via sys._MEIPASS (find_spec faalt daar
    vaak), anders via de geinstalleerde package."""
    dirs = []
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        dirs.append(os.path.join(mei, "gpt4all"))
        dirs.append(os.path.join(os.path.dirname(sys.executable), "gpt4all"))
        dirs.append(os.path.join(os.path.dirname(sys.executable), "_internal", "gpt4all"))
    try:
        import importlib.util
        spec = importlib.util.find_spec("gpt4all")
        for b in list(getattr(spec, "submodule_search_locations", None) or []):
            dirs.append(b)
    except Exception:
        pass
    # dedup, alleen bestaande
    out = []
    for d in dirs:
        if d and d not in out and os.path.isdir(d):
            out.append(d)
    return out


def _gpt4all_build_dir():
    for base in _gpt4all_dirs():
        cand = os.path.join(base, "llmodel_DO_NOT_MODIFY", "build")
        if os.path.isdir(cand):
            return cand
    return None


def _prep_gpt4all_dll():
    if sys.platform != "win32":
        return
    try:
        import ctypes
        import glob
        import shutil
        build = _gpt4all_build_dir()
        if not build:
            return
        # In de EXE heet de DLL 'llmodel.dll' (MSVC), maar gpt4all probeert eerst
        # 'libllmodel.dll' te laden; die "niet gevonden"-fout wordt door de
        # PyInstaller-ctypes-wrapper NIET als FileNotFoundError gegooid, dus
        # gpt4all's terugval naar 'llmodel.dll' slaat over -> crash. Fix: maak een
        # kopie 'libllmodel.dll' zodat de eerste poging meteen slaagt.
        try:
            libname = os.path.join(build, "libllmodel.dll")
            msvcname = os.path.join(build, "llmodel.dll")
            if not os.path.exists(libname) and os.path.exists(msvcname):
                shutil.copy2(msvcname, libname)
        except Exception:
            pass
        try:
            os.add_dll_directory(build)
        except Exception:
            pass
        os.environ["PATH"] = build + os.pathsep + os.environ.get("PATH", "")
        # Alle DLL's in de map alvast laden zodat libllmodel.dll straks zijn
        # afhankelijkheden (MinGW/runtime/backends) al in het geheugen vindt.
        # Meerdere passes vanwege onderlinge laadvolgorde.
        pending = glob.glob(os.path.join(build, "*.dll"))
        for _ in range(6):
            still = []
            for d in pending:
                try:
                    ctypes.CDLL(d)
                except Exception:
                    still.append(d)
            if not still or still == pending:
                break
            pending = still
    except Exception:
        pass


_prep_gpt4all_dll()

SYS_PROMPT = ("Je bent Draven, een behulpzame, beknopte AI-assistent van "
              "Dravenlock. Antwoord kort en feitelijk in de taal van de "
              "gebruiker. Verzin geen details die niet gegeven of gevraagd zijn. "
              "Stel geen tegenvragen tenzij nodig. Weet je iets niet, zeg dat kort.")
STOPS = ("<|", "\nJij:", "\nUser:", "\nHuman:", "\nAntwoord:", "\n###", "###")

_model = None
_session = None
_lock = threading.Lock()
config = {}
_srv = None


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def cache_dir():
    d = os.path.join(app_dir(), "cache")
    os.makedirs(d, exist_ok=True)
    return d


def cfg_path():
    return os.path.join(cache_dir(), "server_config.json")


def load_config():
    global config
    config = {"token": "", "port": 8808, "model_path": "",
              "use_memory": False, "memory": [], "knowledge": [],
              "voice": "Cem", "voice_speed": 1.0, "voice_pitch": 1.0}
    try:
        with open(cfg_path(), "r", encoding="utf-8") as f:
            config.update(json.load(f))
    except Exception:
        pass
    if not config.get("token"):
        config["token"] = secrets.token_urlsafe(12)
    save_config()
    return config


def save_config():
    try:
        with open(cfg_path(), "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    except Exception:
        pass


def find_model():
    """Zoek een .gguf-modelbestand: config, eigen map, of naast DraveChat."""
    mp = config.get("model_path", "")
    if mp and os.path.exists(mp):
        return mp
    dirs = [os.path.join(cache_dir(), "models"),
            os.path.join(app_dir(), "..", "DraveChat", "cache", "models")]
    for d in dirs:
        try:
            for fn in sorted(os.listdir(d)):
                if fn.lower().endswith(".gguf"):
                    return os.path.abspath(os.path.join(d, fn))
        except Exception:
            pass
    return ""


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ---------------------------------------------------------------- model / chat
def load_model():
    global _model
    path = find_model()
    if not path:
        return False, "Geen .gguf-model gevonden (download er een in DraveChat)."
    try:
        from gpt4all import GPT4All
        _model = GPT4All(os.path.basename(path),
                         model_path=os.path.dirname(path),
                         allow_download=False, device="cpu",
                         n_ctx=4096, verbose=False)
        config["model_path"] = path
        save_config()
        return True, os.path.basename(path)
    except Exception as e:
        _write_gpt4all_diag(e)
        return False, str(e)


def _write_gpt4all_diag(err):
    """Schrijf uitgebreide diagnose naar cache/gpt4all_diag.txt bij een laadfout,
    zodat we (in de EXE) precies zien welke DLL's er staan en wat er misgaat."""
    import traceback
    lines = []
    try:
        lines.append("=== gpt4all laadfout-diagnose ===")
        lines.append("frozen (EXE): %s" % bool(getattr(sys, "frozen", False)))
        lines.append("_MEIPASS: %s" % getattr(sys, "_MEIPASS", "(geen)"))
        lines.append("executable: %s" % sys.executable)
        lines.append("fout: %r" % (err,))
        # bouw-map van gpt4all zoeken (ook als import gedeeltelijk faalde)
        try:
            lines.append("gpt4all-mappen: %s" % _gpt4all_dirs())
        except Exception as e2:
            lines.append("_gpt4all_dirs faalde: %r" % (e2,))
        build = _gpt4all_build_dir()
        lines.append("build-map: %s" % build)
        if build and os.path.isdir(build):
            lines.append("inhoud build-map:")
            for f in sorted(os.listdir(build)):
                try:
                    sz = os.path.getsize(os.path.join(build, f))
                except Exception:
                    sz = -1
                lines.append("   %-45s %10d" % (f, sz))
        lines.append("--- traceback ---")
        lines.append(traceback.format_exc())
    except Exception as e3:
        lines.append("diagnose zelf faalde: %r" % (e3,))
    try:
        with open(os.path.join(cache_dir(), "gpt4all_diag.txt"), "w",
                  encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception:
        pass


def _open_session():
    global _session
    if _model is None:
        return
    if _session is not None:
        try:
            _session.__exit__(None, None, None)
        except Exception:
            pass
        _session = None
    mp = config.get("model_path", "").lower()
    if "llama" in mp:
        sysp = ("<|start_header_id|>system<|end_header_id|>\n\n"
                + SYS_PROMPT + "<|eot_id|>")
        tmpl = ("<|start_header_id|>user<|end_header_id|>\n\n%1<|eot_id|>"
                "<|start_header_id|>assistant<|end_header_id|>\n\n")
        kw = {"system_prompt": sysp, "prompt_template": tmpl}
    elif "qwen" in mp:
        kw = {"system_prompt": "<|im_start|>system\n" + SYS_PROMPT + "<|im_end|>\n",
              "prompt_template": "<|im_start|>user\n%1<|im_end|>\n"
                                 "<|im_start|>assistant\n"}
    else:
        kw = {"system_prompt": SYS_PROMPT}
    try:
        _session = _model.chat_session(**kw)
        _session.__enter__()
    except Exception:
        try:
            _session = _model.chat_session(system_prompt=SYS_PROMPT)
            _session.__enter__()
        except Exception:
            _session = None


def reset_session():
    with _lock:
        _open_session()


def set_model(path, log=print):
    """Kies expliciet een .gguf en laad het (gebruikt door de tray-beheerscherm)."""
    config["model_path"] = path
    save_config()
    ok, info = load_model()
    if ok:
        reset_session()
        log("Model geladen: %s" % info)
    else:
        log("Model NIET geladen: %s" % info)
    return ok, info


def _retrieve(query, notes, k=3):
    import re
    q = set(w for w in re.findall(r"\w+", query.lower()) if len(w) > 3)
    if not q:
        return []
    scored = []
    for n in notes:
        ws = set(w for w in re.findall(r"\w+", n.lower()) if len(w) > 3)
        sc = len(q & ws)
        if sc > 0:
            scored.append((sc, n))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [n for _, n in scored[:k]]


def _stop_cut(text):
    idx = None
    for m in STOPS:
        p = text.find(m)
        if p != -1:
            idx = p if idx is None else min(idx, p)
    return idx


def _build(message):
    parts = []
    if config.get("use_memory") and config.get("memory"):
        parts.append("Over de gebruiker: " + "; ".join(config["memory"]))
    hits = _retrieve(message, config.get("knowledge", []))
    if hits:
        parts.append("Relevante kennis: " + " | ".join(hits))
    if parts:
        return ("Gebruik onderstaande context als die klopt. Antwoord kort.\n"
                + "\n".join(parts) + "\n\n" + message)
    return message


def chat(message):
    with _lock:
        if _model is None:
            return "(geen model geladen)"
        if _session is None:
            _open_session()
        prompt = _build(message)
        text = ""
        try:
            for tok in _model.generate(prompt, max_tokens=400, temp=0.35,
                                       top_p=0.9, repeat_penalty=1.2,
                                       streaming=True):
                text += tok
                idx = _stop_cut(text)
                if idx is not None:
                    text = text[:idx]
                    break
        except Exception as e:
            return "(fout bij genereren: %s)" % e
        return text.strip()


# ---------------------------------------------------------------- stem (neuvoice)
class TtsEngine:
    def __init__(self):
        self._tts = None
        self.sample_rate = 24000
        self.voices = []
        self.ready = False
        self.last_error = ""

    def ensure_ready(self):
        if self.ready and self._tts is not None:
            return True
        try:
            import neuvoice  # noqa: F401
        except Exception:
            if not getattr(sys, "frozen", False):
                import subprocess
                for pkg in ("onnxruntime", "neuvoice"):
                    try:
                        __import__(pkg)
                    except Exception:
                        try:
                            subprocess.run([sys.executable, "-m", "pip",
                                            "install", "--only-binary=:all:",
                                            pkg], check=False)
                        except Exception:
                            pass
        try:
            from neuvoice import TTS
            self._tts = TTS(auto_download=True)
            self.sample_rate = int(getattr(self._tts, "sample_rate", 24000))
            self.voices = list(self._tts.voice_style_names)
            self.ready = True
            return True
        except Exception as e:
            self.last_error = str(e)
            self.ready = False
            return False

    def pick(self, name):
        if not self.voices:
            return name or ""
        return name if name in self.voices else self.voices[0]

    def synth(self, text, voice, speed, lang):
        import numpy as np
        style = self._tts.get_voice_style(self.pick(voice))
        wav, _d = self._tts.synthesize(text, voice_style=style, total_steps=8,
                                       speed=float(speed), lang=lang)
        arr = np.asarray(wav, dtype="float32").squeeze()
        return np.clip(arr, -1.0, 1.0)


_tts = TtsEngine()
_tts_lock = threading.Lock()


def tts_wav(text):
    """Maak WAV-bytes van tekst via neuvoice; pitch via afspeel-rate."""
    with _tts_lock:
        if not _tts.ensure_ready():
            return None
        try:
            import wave
            import io
            voice = config.get("voice") or "Cem"
            speed = float(config.get("voice_speed", 1.0))
            pitch = max(0.7, min(1.4, float(config.get("voice_pitch", 1.0))))
            gen = max(0.5, min(1.8, speed / pitch))
            arr = _tts.synth(text[:1000], voice, gen, "nl")
            pcm = (arr * 32767.0).astype("<i2")
            fr = int(_tts.sample_rate * pitch)
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(fr)
                w.writeframes(pcm.tobytes())
            return buf.getvalue()
        except Exception:
            return None


# ---------------------------------------------------------------- webpagina
PAGE = """<!doctype html><html lang="nl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DraveChat</title><style>
*{box-sizing:border-box;} body{margin:0;background:#16131f;color:#e8e6f0;
font-family:'Segoe UI',system-ui,sans-serif;font-size:17px;}
.wrap{max-width:820px;margin:0 auto;padding:16px;display:flex;flex-direction:column;
height:100vh;}
h1{color:#b59cff;margin:6px 0;font-size:26px;}
#log{flex:1;overflow-y:auto;background:#0e0c16;border:1px solid #4a3d66;
border-radius:12px;padding:14px;line-height:1.5;}
.msg{margin:8px 0;} .you b{color:#8fd0ff;} .drv b{color:#b59cff;}
.row{display:flex;gap:8px;margin-top:10px;}
input,button{font-size:17px;border-radius:10px;border:1px solid #4a3d66;
background:#0e0c16;color:#e8e6f0;padding:11px;}
#msg{flex:1;} button{background:#2a2440;font-weight:bold;cursor:pointer;}
button:hover{background:#463a6e;}
.top{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px;}
#token{width:180px;} .hint{color:#9b90c0;font-size:14px;}
</style></head><body><div class="wrap">
<h1>🐉 DraveChat</h1>
<div class="top">
  <span class="hint">Toegangssleutel:</span>
  <input id="token" placeholder="token" />
  <button onclick="saveTok()">Opslaan</button>
  <button onclick="resetChat()">Nieuw gesprek</button>
</div>
<div id="log"></div>
<div class="row">
  <input id="msg" placeholder="Typ je bericht en druk op Enter..." />
  <button onclick="send()">Verstuur</button>
</div></div>
<script>
const log=document.getElementById('log'), msg=document.getElementById('msg'),
      tokin=document.getElementById('token');
tokin.value=localStorage.getItem('draven_token')||'';
function saveTok(){localStorage.setItem('draven_token',tokin.value.trim());}
function add(cls,who,txt){const d=document.createElement('div');
 d.className='msg '+cls; d.innerHTML='<b>'+who+':</b> '+
 txt.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/\\n/g,'<br>');
 log.appendChild(d); log.scrollTop=log.scrollHeight;}
async function send(){const t=msg.value.trim(); if(!t)return; msg.value='';
 add('you','Jij',t); const d=add('drv','Draven','...');
 try{const r=await fetch('/api/chat',{method:'POST',headers:{
   'Content-Type':'application/json','X-Token':tokin.value.trim()},
   body:JSON.stringify({message:t})});
  const j=await r.json();
  log.lastChild.innerHTML='<b>Draven:</b> '+((j.reply||j.error||'?')
   .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/\\n/g,'<br>'));
 }catch(e){log.lastChild.innerHTML='<b>Draven:</b> (server onbereikbaar)';}
 log.scrollTop=log.scrollHeight;}
async function resetChat(){await fetch('/api/reset',{method:'POST',
  headers:{'X-Token':tokin.value.trim()}}); log.innerHTML='';}
msg.addEventListener('keydown',e=>{if(e.key==='Enter')send();});
</script></body></html>"""


# ---------------------------------------------------------------- widget
WIDGET_JS = r"""(function(){
  var script = document.currentScript;
  var origin = new URL(script.src, location.href).origin;
  var token = script.getAttribute('data-token') || '';
  var accent = script.getAttribute('data-color') || '#7F77DD';
  var title = script.getAttribute('data-title') || 'Draven';
  var voiceOn = (script.getAttribute('data-voice') || '') === '1';
  var host = document.createElement('div');
  host.style.setProperty('--dv-accent', accent);
  document.body.appendChild(host);
  var root = host.attachShadow({mode:'open'});
  root.innerHTML = `
  <style>
    :host{ all:initial; }
    .btn{ position:fixed; right:20px; bottom:20px; width:60px; height:60px;
      border-radius:50%; background:var(--dv-accent,#7F77DD); border:none;
      color:#fff; font-size:28px; cursor:pointer; z-index:2147483000;
      display:flex; align-items:center; justify-content:center;
      box-shadow:0 6px 18px rgba(0,0,0,.4); font-family:sans-serif; }
    .panel{ position:fixed; right:20px; bottom:20px; width:340px; height:470px;
      max-width:92vw; max-height:80vh; background:#16131f; color:#e8e6f0;
      border:1px solid #4a3d66; border-radius:14px; z-index:2147483000;
      display:none; flex-direction:column; overflow:hidden;
      box-shadow:0 8px 26px rgba(0,0,0,.5);
      font-family:'Segoe UI',system-ui,sans-serif; font-size:15px; }
    .hd{ background:#2a2440; color:var(--dv-accent,#b59cff); font-weight:bold;
      padding:12px 14px;
      display:flex; justify-content:space-between; align-items:center; }
    .hd .x{ cursor:pointer; color:#cfc7e6; }
    .log{ flex:1; overflow-y:auto; padding:12px; line-height:1.45; }
    .m{ margin:7px 0; } .m.u b{ color:#8fd0ff; } .m.d b{ color:#b59cff; }
    .row{ display:flex; gap:6px; padding:10px; border-top:1px solid #4a3d66; }
    .row input{ flex:1; background:#0e0c16; color:#e8e6f0; font-size:15px;
      border:1px solid #4a3d66; border-radius:9px; padding:9px; }
    .row button{ background:#2a2440; color:#efeaff;
      border:1px solid var(--dv-accent,#5a4d86);
      border-radius:9px; padding:0 14px; cursor:pointer; font-size:16px; }
  </style>
  <div class="btn">🐉</div>
  <div class="panel">
    <div class="hd"><span class="ttl">Draven</span><span class="x">✕</span></div>
    <div class="log"></div>
    <div class="row"><input class="msg" placeholder="Vraag iets..."><button class="snd">➤</button></div>
  </div>`;
  var q=function(s){return root.querySelector(s);};
  var btn=q('.btn'), panel=q('.panel'), log=q('.log'), msg=q('.msg');
  q('.ttl').textContent = (voiceOn ? '🔊 ' : '') + title;
  btn.title = title + (voiceOn ? ' (praat hardop mee)' : '');
  var audio=null;
  async function speak(txt){ if(!voiceOn||!txt)return;
    try{ var r=await fetch(origin+'/api/tts',{method:'POST',headers:{
      'Content-Type':'application/json','X-Token':token},
      body:JSON.stringify({text:txt})});
      if(!r.ok)return; var b=await r.blob();
      if(audio){ try{audio.pause();}catch(e){} }
      audio=new Audio(URL.createObjectURL(b)); audio.play();
    }catch(e){} }
  function esc(t){return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/\n/g,'<br>');}
  function add(cls,who,txt){var d=document.createElement('div');d.className='m '+cls;
    d.innerHTML='<b>'+who+':</b> '+esc(txt); log.appendChild(d);
    log.scrollTop=log.scrollHeight; return d;}
  btn.onclick=function(){panel.style.display='flex'; btn.style.display='none'; msg.focus();};
  q('.x').onclick=function(){panel.style.display='none'; btn.style.display='flex';};
  async function send(){var t=msg.value.trim(); if(!t)return; msg.value='';
    add('u','Jij',t); var d=add('d','Draven','...');
    try{ var r=await fetch(origin+'/api/chat',{method:'POST',headers:{
      'Content-Type':'application/json','X-Token':token},
      body:JSON.stringify({message:t})});
      var j=await r.json(); d.innerHTML='<b>'+esc(title)+':</b> '+esc(j.reply||j.error||'?');
      speak(j.reply||'');
    }catch(e){ d.innerHTML='<b>'+esc(title)+':</b> (server onbereikbaar)'; }
    log.scrollTop=log.scrollHeight; }
  q('.snd').onclick=send;
  msg.addEventListener('keydown',function(e){if(e.key==='Enter')send();});
})();"""


def demo_page():
    return ("<!doctype html><html><head><meta charset='utf-8'><title>Widget demo"
            "</title></head><body style='font-family:sans-serif;background:#eee;"
            "padding:30px'><h1>Voorbeeldpagina</h1><p>Rechtsonder zie je de "
            "Draven-chatbubbel (de widget). Zo ziet het eruit op een site "
            "(eigen kleur en titel).</p>"
            "<p>\U0001F50A <b>Deze widget praat hardop mee:</b> elk antwoord "
            "wordt ook voorgelezen met een stem. Stel je vraag in het venster "
            "en luister mee. (Handig voor slechtziende bezoekers.)</p>"
            "<script src='/widget.js' data-token='%s' data-color='#7F77DD' "
            "data-title='Draven' data-voice='1'></script>"
            "</body></html>" % config.get("token", ""))


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Token")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj), "application/json")

    def _authed(self):
        tok = self.headers.get("X-Token", "")
        if not tok:
            q = self.path.split("?", 1)
            if len(q) > 1:
                for part in q[1].split("&"):
                    if part.startswith("token="):
                        tok = part[6:]
        return tok == config.get("token")

    def do_OPTIONS(self):
        self._send(204, b"", "text/plain")

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif path == "/widget.js":
            self._send(200, WIDGET_JS,
                       "application/javascript; charset=utf-8")
        elif path == "/demo":
            self._send(200, demo_page(), "text/html; charset=utf-8")
        elif path == "/api/health":
            self._json(200, {"ok": _model is not None,
                             "model": os.path.basename(
                                 config.get("model_path", "")) or None})
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if not self._authed():
            self._json(401, {"error": "ongeldige of ontbrekende token"})
            return
        if path == "/api/reset":
            reset_session()
            self._json(200, {"ok": True})
            return
        if path == "/api/chat":
            try:
                n = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(n).decode("utf-8"))
                message = (data.get("message") or "").strip()[:2000]
            except Exception:
                self._json(400, {"error": "ongeldige aanvraag"})
                return
            if not message:
                self._json(400, {"error": "leeg bericht"})
                return
            reply = chat(message)
            self._json(200, {"reply": reply})
            return
        if path == "/api/tts":
            try:
                n = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(n).decode("utf-8"))
                text = (data.get("text") or "").strip()
            except Exception:
                self._json(400, {"error": "ongeldige aanvraag"})
                return
            wav = tts_wav(text) if text else None
            if wav is None:
                self._json(503, {"error": "stem niet beschikbaar"})
                return
            self._send(200, wav, "audio/wav")
            return
        self._json(404, {"error": "onbekend eindpunt"})


def run(log=print):
    """Start de server (blokkeert). Gebruikt door de tray-app; logt via `log`."""
    global _srv
    load_config()
    log("DraveServer start...")
    ok, info = load_model()
    log("Model: %s" % info)
    port = int(config.get("port", 8808))
    ip = lan_ip()
    log("Webchat : http://127.0.0.1:%d/" % port)
    log("Netwerk : http://%s:%d/" % (ip, port))
    log("Demo    : http://127.0.0.1:%d/demo" % port)
    log("Token   : %s" % config.get("token", ""))
    _srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    try:
        _srv.serve_forever()
    except KeyboardInterrupt:
        pass
    try:
        _srv.server_close()
    except Exception:
        pass


def stop():
    """Stop de draaiende server netjes (voor de tray-Afsluiten-knop)."""
    global _srv
    if _srv is not None:
        try:
            _srv.shutdown()
        except Exception:
            pass


def main():
    load_config()
    print("=" * 60)
    print(" DraveServer - lokale AI-chatserver van Dravenlock")
    print("=" * 60)
    print(" Model laden (kan even duren)...")
    ok, info = load_model()
    if not ok:
        print(" LET OP: %s" % info)
        print(" De server start wel, maar antwoordt pas met een model.")
    else:
        print(" Model geladen: %s" % info)
    port = int(config.get("port", 8808))
    ip = lan_ip()
    print("-" * 60)
    print(" Webchat op deze pc :  http://127.0.0.1:%d/" % port)
    print(" Op je thuisnetwerk :  http://%s:%d/" % (ip, port))
    print(" Toegangssleutel    :  %s" % config["token"])
    print("-" * 60)
    print(" Vul die sleutel in op de webpagina (veld 'Toegangssleutel').")
    print(" Widget-voorbeeld   :  http://%s:%d/demo" % (ip, port))
    print(" Widget insluiten op je site (1 regel voor </body>):")
    print('   <script src="http://%s:%d/widget.js" '
          'data-token="%s"></script>' % (ip, port, config["token"]))
    print(" Voor API: stuur header  X-Token: %s" % config["token"])
    print(" Internet-bereik? Zie README - doe dit met beleid.")
    print(" Stoppen: sluit dit venster of druk Ctrl+C.")
    print("=" * 60)
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    srv.server_close()


if __name__ == "__main__":
    main()
