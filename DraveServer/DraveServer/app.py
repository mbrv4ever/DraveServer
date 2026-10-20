# -*- coding: utf-8 -*-
"""DraveServer - eenvoudige webserver-beheerder (Dravenlock).

Apache-versie: DraveServer beheert een Apache-webserver met een simpele
tab-interface. Het schrijft de configuratie (vhosts) ZELF, zodat de gebruiker
nooit een configbestand hoeft aan te raken. DraveServer draait Apache met een
eigen kopie van de configuratie; je eigen Apache-config blijft onaangeroerd.

Lokaal en offline. Windows-app: het starten van Apache werkt alleen op Windows
met een geinstalleerde Apache (of XAMPP). Op andere systemen draait de app in
demonstratiestand, zodat de interface en de gegenereerde config te bekijken zijn.
"""
import os
import sys
import re
import json
import zipfile
import urllib.request
import subprocess
import time
import traceback

APP_NAAM = "DraveServer"
APP_VERSIE = "0.31"
DONATIE_URL = "https://paypal.me/roger076"
CONTACT = "service@dravenlock.nl"

WINDOWS = (os.name == "nt")

# BASIS = map voor portable data (config, DraveServer-data). In de .exe is dat
# de map NAAST de .exe (niet de interne bundel) zodat je data mee kunt nemen.
# Gebundelde, alleen-lezen bestanden (logo.png, bouwer.html, app.ico) laad je
# via _bundel_bestand() -> sys._MEIPASS.
if getattr(sys, "frozen", False):
    BASIS = os.path.dirname(sys.executable)
else:
    BASIS = os.path.dirname(os.path.abspath(__file__))
FOUT_BESTAND = os.path.join(BASIS, "app-fout.txt")
CONFIG_BESTAND = os.path.join(BASIS, "config.json")
# Portable: alles naast de app in DraveServer-data.
DATA_MAP = os.path.join(BASIS, "DraveServer-data")
HTDOCS = os.path.join(DATA_MAP, "htdocs")            # hier komen de websites
CERT_MAP = os.path.join(DATA_MAP, "certificaten")    # hier komen de certificaten
LOG_MAP = os.path.join(DATA_MAP, "logs")
VHOST_MAP = os.path.join(DATA_MAP, "conf", "vhosts")
RUN_CONFIG = os.path.join(DATA_MAP, "conf", "httpd-draveserver.conf")
# Zelf gedownloade onderdelen (portable, naast de app).
APACHE_INSTALL = os.path.join(DATA_MAP, "apache")   # uitgepakte Apache
PHP_BASIS = os.path.join(DATA_MAP, "php")           # uitgepakte PHP-versie(s)

# Downloadbronnen.
PHP_LIJST_URL = "https://windows.php.net/downloads/releases/"
# Apache Lounge (let op: domein is apachelounge.com, zonder koppelteken).
APACHE_PAGINA = "https://www.apachelounge.com/download/"
# Bekende, geldige terugval-URL (wordt zo nodig bijgewerkt). DraveServer probeert
# eerst de nieuwste op de pagina te vinden.
APACHE_AUTO = {
    "versie": "2.4 (VS17, win64)",
    "url": "https://www.apachelounge.com/download/VS17/binaries/"
           "httpd-2.4.65-250724-win64-VS17.zip",
}

# Handige downloadlinks (voor wie nog geen webserver heeft).
DOWNLOADS = [
    ("Apache Lounge - Apache voor Windows (aanbevolen)",
     "https://www.apachelounge.com/download/"),
    ("Apache httpd - officiele site",
     "https://httpd.apache.org/download.cgi"),
]


def zorg_voor_mappen():
    """Maak de portable mappenstructuur naast de app aan."""
    for d in (DATA_MAP, HTDOCS, CERT_MAP, LOG_MAP, VHOST_MAP):
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# ---- huisstijl ----
BG = "#0e0e11"
PANEL = "#16161b"
PANEL2 = "#1c1c22"
TEXT = "#d4d4d4"
MUTED = "#8a8a94"
ACCENT = "#6fa3d6"
LINE = "#23232b"
WARN = "#d68a6f"
GOED = "#7fb069"


def _excepthook(soort, waarde, tb):
    try:
        with open(FOUT_BESTAND, "w", encoding="utf-8") as f:
            f.write("DraveServer startfout\n\n")
            f.write("".join(traceback.format_exception(soort, waarde, tb)))
    except Exception:
        pass
    sys.__excepthook__(soort, waarde, tb)


sys.excepthook = _excepthook


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
STANDAARD_CONFIG = {
    "taal": "auto",
    "apache_dir": "",
    "httpd_exe": "",
    "httpd_conf": "",
    "php_aan": False,
    "php_dir": "",
    "php_versie": "",
    "db_exe": "",
    "db_versie": "",
    "db_wachtwoord": "",
    "https_poort": 443,
    "db_poort": 3306,
    "sites": [],          # [{naam, map, servernaam, poort, aan}]
    "toon_welkom": True,
    "auto_start": True,   # server/PHP/database automatisch starten bij openen
    "naar_systeemvak": True,   # bij sluiten naar systeemvak i.p.v. afsluiten
    "start_met_windows": False,  # met Windows meestarten
    "systeemvak_uitleg_getoond": False,  # eenmalige uitleg bij sluiten naar vak
}


def laad_config():
    cfg = dict(STANDAARD_CONFIG)
    try:
        with open(CONFIG_BESTAND, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            cfg.update(data)
    except Exception:
        pass
    return cfg


def bewaar_config(cfg):
    try:
        tmp = CONFIG_BESTAND + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        os.replace(tmp, CONFIG_BESTAND)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Apache vinden
# ---------------------------------------------------------------------------
APACHE_ZOEK = [
    r"C:\xampp\apache",
    r"C:\Apache24",
    r"C:\Program Files\Apache24",
    r"C:\Program Files\Apache Software Foundation\Apache2.4",
    r"C:\Program Files (x86)\Apache24",
    r"C:\wamp64\bin\apache",
    r"C:\wamp\bin\apache",
]


def detecteer_apache():
    """Zoek een Apache-installatie. Geeft dict(dir, httpd_exe, httpd_conf) of None."""
    kandidaten = list(APACHE_ZOEK)
    # wamp heeft submappen apacheX.Y.Z
    for wamp in (r"C:\wamp64\bin\apache", r"C:\wamp\bin\apache"):
        try:
            for sub in os.listdir(wamp):
                kandidaten.append(os.path.join(wamp, sub))
        except OSError:
            pass
    for d in kandidaten:
        exe = os.path.join(d, "bin", "httpd.exe")
        conf = os.path.join(d, "conf", "httpd.conf")
        if os.path.isfile(exe):
            return {"dir": d, "httpd_exe": exe,
                    "httpd_conf": conf if os.path.isfile(conf) else ""}
    return None


def apache_uit_config(cfg):
    """Apache-gegevens uit config, of de zelf-gedownloade, of autodetectie."""
    exe = (cfg.get("httpd_exe") or "").strip()
    if exe and os.path.isfile(exe):
        d = cfg.get("apache_dir") or os.path.dirname(os.path.dirname(exe))
        conf = cfg.get("httpd_conf") or os.path.join(d, "conf", "httpd.conf")
        return {"dir": d, "httpd_exe": exe,
                "httpd_conf": conf if os.path.isfile(conf) else ""}
    # zelf gedownloade Apache?
    eigen = vind_httpd(APACHE_INSTALL)
    if eigen:
        d = os.path.dirname(os.path.dirname(eigen))
        conf = os.path.join(d, "conf", "httpd.conf")
        return {"dir": d, "httpd_exe": eigen,
                "httpd_conf": conf if os.path.isfile(conf) else ""}
    return detecteer_apache()


# ---------------------------------------------------------------------------
# Configuratie genereren (vhosts + runconfig)
# ---------------------------------------------------------------------------
def _ap(pad):
    """Pad in Apache-stijl (forward slashes)."""
    return (pad or "").replace("\\", "/")


def genereer_vhost(site):
    """Bouw het <VirtualHost>-blok voor een site."""
    naam = site.get("naam", "site")
    veilig = "".join(c if c.isalnum() or c in "-_" else "_" for c in naam)[:40] or "site"
    docroot = _ap(site.get("map", ""))
    servernaam = site.get("servernaam") or "localhost"
    poort = int(site.get("poort") or 80)
    log = _ap(LOG_MAP)
    regels = [
        "# DraveServer - site: %s" % naam,
        "<VirtualHost *:%d>" % poort,
        "    ServerName %s" % servernaam,
        '    DocumentRoot "%s"' % docroot,
        '    <Directory "%s">' % docroot,
        "        Options Indexes FollowSymLinks",
        "        AllowOverride All",
        "        Require all granted",
        "    </Directory>",
        '    ErrorLog "%s/%s-error.log"' % (log, veilig),
        '    CustomLog "%s/%s-access.log" common' % (log, veilig),
        "</VirtualHost>",
        "",
    ]
    return "\n".join(regels)


def schrijf_vhosts(sites):
    """Schrijf per actieve site een .conf-bestand in de vhost-map."""
    os.makedirs(VHOST_MAP, exist_ok=True)
    # oude opruimen
    for f in os.listdir(VHOST_MAP):
        if f.endswith(".conf"):
            try:
                os.remove(os.path.join(VHOST_MAP, f))
            except OSError:
                pass
    aantal = 0
    for site in sites:
        if not site.get("aan", True):
            continue
        if not site.get("map"):
            continue
        veilig = "".join(c if c.isalnum() or c in "-_" else "_"
                         for c in site.get("naam", "site"))[:40] or "site"
        with open(os.path.join(VHOST_MAP, veilig + ".conf"), "w",
                  encoding="utf-8") as f:
            f.write(genereer_vhost(site))
        aantal += 1
    # https-vhosts
    for site in ssl_sites(sites):
        if not site.get("aan", True):
            continue
        veilig = "".join(c if c.isalnum() or c in "-_" else "_"
                         for c in site.get("naam", "site"))[:40] or "site"
        with open(os.path.join(VHOST_MAP, veilig + "-ssl.conf"), "w",
                  encoding="utf-8") as f:
            f.write(genereer_ssl_vhost(site))
    return aantal


def poorten_in_gebruik(sites):
    poorten = set()
    for s in sites:
        if s.get("aan", True) and s.get("map"):
            poorten.add(int(s.get("poort") or 80))
    return sorted(poorten) or [80]


def _patch_serverroot(inhoud, apache_dir):
    """Zorg dat ServerRoot/SRVROOT naar de ECHTE Apache-map wijzen. De gedownloade
    Apache heeft standaard 'c:/Apache24' staan, maar staat bij ons in
    DraveServer-data\\apache -> anders 'ServerRoot must be a valid directory'."""
    sr = _ap(apache_dir)
    # Define SRVROOT "..."  -> echte map (lost ook ${SRVROOT}-paden op)
    inhoud, n = re.subn(r'(?im)^(\s*Define\s+SRVROOT\s+).*$',
                        r'\1"%s"' % sr, inhoud)

    # ServerRoot "..."  -> echte map, tenzij het al ${SRVROOT} gebruikt
    def _vervang(m):
        if "${SRVROOT}" in m.group(0):
            return m.group(0)
        return '%sServerRoot "%s"' % (m.group(1), sr)
    inhoud = re.sub(r'(?im)^(\s*)ServerRoot\s+.*$', _vervang, inhoud)
    return inhoud


ACTIEVE_HTTPS_POORT = 443
ACTIEVE_DB_POORT = 3306


def zet_actieve_poorten(https_poort, db_poort):
    global ACTIEVE_HTTPS_POORT, ACTIEVE_DB_POORT
    try:
        ACTIEVE_HTTPS_POORT = int(https_poort) or 443
    except (TypeError, ValueError):
        ACTIEVE_HTTPS_POORT = 443
    try:
        ACTIEVE_DB_POORT = int(db_poort) or 3306
    except (TypeError, ValueError):
        ACTIEVE_DB_POORT = 3306


def poort_vrij(poort):
    """True als de poort vrij is (niets luistert erop)."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("0.0.0.0", int(poort)))
        return True
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def intern_ip():
    """Het lokale (LAN) IP-adres van deze pc."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return ""


EXTERN_IP_DIENSTEN = ["https://api.ipify.org", "https://ifconfig.me/ip",
                      "https://ipinfo.io/ip", "https://icanhazip.com"]


def extern_ip():
    """Het publieke IP-adres (via een externe dienst). '' bij geen internet."""
    for url in EXTERN_IP_DIENSTEN:
        try:
            tekst = _haal_tekst(url).strip().splitlines()
            if not tekst:
                continue
            eerste = tekst[0].strip()
            if re.match(r"^[0-9a-fA-F:.]{3,45}$", eerste):
                return eerste
        except Exception:
            continue
    return ""


# ---------------------------------------------------------------------------
# Website-bouwer (ingebouwde DraveEdit-editor via QtWebEngine)
# ---------------------------------------------------------------------------
def bouwer_html_pad():
    """Pad naar bouwer.html (werkt vanuit broncode en als .exe)."""
    basis = getattr(sys, "_MEIPASS",
                    os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(basis, "bouwer.html")


def _bundel_bestand(naam):
    basis = getattr(sys, "_MEIPASS",
                    os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(basis, naam)


def app_icoon():
    """Venster-/taakbalk-icoon, frozen-veilig: app.ico, anders logo.png."""
    for naam in ("app.ico", "logo.png"):
        pad = _bundel_bestand(naam)
        if os.path.exists(pad):
            ico = QIcon(pad)
            if not ico.isNull():
                return ico
    return QIcon()


SW_JS = """const CACHE = 'draveserver-v1';
const ASSETS = ['./', './index.html', './icons/icon-192.png', './icons/icon-512.png'];
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)));
  self.skipWaiting();
});
self.addEventListener('activate', e => { e.waitUntil(self.clients.claim()); });
self.addEventListener('fetch', e => {
  e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
});
"""


def manifest_json(naam):
    data = {
        "name": naam, "short_name": naam[:12], "start_url": ".",
        "display": "standalone", "background_color": "#ffffff",
        "theme_color": ACCENT,
        "icons": [
            {"src": "icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "icons/icon-512.png", "sizes": "512x512", "type": "image/png",
             "purpose": "any maskable"},
        ],
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def inject_pwa(doc):
    head = ('  <link rel="manifest" href="manifest.json">\n'
            '  <meta name="theme-color" content="%s">\n'
            '  <meta name="apple-mobile-web-app-capable" content="yes">\n'
            '  <link rel="apple-touch-icon" href="icons/icon-192.png">\n' % ACCENT)
    if "</head>" in doc:
        doc = doc.replace("</head>", head + "</head>", 1)
    reg = ('<script>if("serviceWorker" in navigator){'
           'window.addEventListener("load",function(){'
           'navigator.serviceWorker.register("sw.js");});}</script>\n')
    if "</body>" in doc:
        doc = doc.replace("</body>", reg + "</body>", 1)
    return doc


def _pwa_icon_png(grootte):
    """PWA-icoon (PNG-bytes) uit logo.png; anders een effen donker vlak."""
    from PyQt6.QtCore import QBuffer, QByteArray
    from PyQt6.QtGui import QPixmap, QPainter, QColor
    pm = QPixmap(grootte, grootte)
    pm.fill(QColor("#0e0e11"))
    bron = QPixmap(_bundel_bestand("logo.png"))
    if not bron.isNull():
        sc = bron.scaled(grootte, grootte, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
        p = QPainter(pm)
        p.drawPixmap((grootte - sc.width()) // 2,
                     (grootte - sc.height()) // 2, sc)
        p.end()
    ba = QByteArray(); buf = QBuffer(ba)
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    pm.toImage().save(buf, "PNG")
    return bytes(ba)


def site_bestanden(naam, parts_json):
    """HTML + CSS + PWA-bestanden als {pad: bytes} (uit DE.getExportParts())."""
    try:
        d = json.loads(parts_json or "{}")
    except Exception:
        d = {}
    html = d.get("html", ""); css = d.get("css", "")
    files = {
        "index.html": inject_pwa(html).encode("utf-8"),
        "css/index_style.css": css.encode("utf-8"),
        "manifest.json": manifest_json(naam).encode("utf-8"),
        "sw.js": SW_JS.encode("utf-8"),
    }
    for sz in (192, 512):
        files["icons/icon-%d.png" % sz] = _pwa_icon_png(sz)
    # Werkend contactformulier: als de site naar contact.php verwijst, schrijf
    # een PHP-handler mee die inzendingen opslaat (werkt met PHP aan op de server).
    if "contact.php" in html:
        files["contact.php"] = CONTACT_PHP.encode("utf-8")
    return files


CONTACT_PHP = (
    "<?php\n"
    "// Door DraveServer gegenereerde contactformulier-handler.\n"
    "// Slaat inzendingen op in contact-inzendingen.txt naast dit bestand.\n"
    "if ($_SERVER['REQUEST_METHOD'] === 'POST') {\n"
    "    $regel = date('Y-m-d H:i:s');\n"
    "    foreach ($_POST as $k => $v) {\n"
    "        if (is_array($v)) { $v = implode(', ', $v); }\n"
    "        $regel .= ' | ' . $k . ': ' . str_replace([\"\\r\", \"\\n\"], ' ', (string)$v);\n"
    "    }\n"
    "    @file_put_contents(__DIR__ . '/contact-inzendingen.txt',\n"
    "                       $regel . \"\\n\", FILE_APPEND | LOCK_EX);\n"
    "}\n"
    "?><!DOCTYPE html>\n"
    "<html lang=\"nl\"><head><meta charset=\"utf-8\">\n"
    "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
    "<title>Bedankt</title>\n"
    "<style>body{font-family:system-ui,Segoe UI,sans-serif;max-width:560px;"
    "margin:64px auto;padding:0 20px;text-align:center;line-height:1.6}"
    "a{color:#2563aa}</style></head><body>\n"
    "<h1>Bedankt!</h1>\n"
    "<p>Je bericht is ontvangen.</p>\n"
    "<p><a href=\"index.html\">&larr; Terug naar de site</a></p>\n"
    "</body></html>\n"
)

def bouw_runconfig(apache, sites, php_dir=""):
    """Maak een eigen kopie van de Apache-config met onze vhosts (en eventueel
    PHP) erin. De originele httpd.conf van de gebruiker blijft onaangeroerd."""
    os.makedirs(os.path.dirname(RUN_CONFIG), exist_ok=True)
    os.makedirs(LOG_MAP, exist_ok=True)
    schrijf_vhosts(sites)
    basis_conf = apache.get("httpd_conf") or ""
    if basis_conf and os.path.isfile(basis_conf):
        try:
            with open(basis_conf, encoding="utf-8", errors="replace") as f:
                inhoud = f.read()
        except Exception:
            inhoud = ""
    else:
        inhoud = _minimale_conf(apache)
    # ServerRoot naar de echte Apache-map laten wijzen
    if apache.get("dir"):
        inhoud = _patch_serverroot(inhoud, apache["dir"])
    extra = ["", "# ====== toegevoegd door DraveServer ======"]
    # Globale ServerName voorkomt de onschuldige AH00558-waarschuwing
    # ("Could not reliably determine the server's fully qualified domain name").
    if not re.search(r"(?im)^\s*ServerName\s+\S", inhoud):
        extra.append("ServerName localhost")
    # welke poorten staan al in de basis-config? (geen dubbele Listen!)
    bestaande = set()
    for regel in inhoud.splitlines():
        m = re.match(r"\s*Listen\s+(?:[\d.]+:)?(\d+)", regel)
        if m:
            bestaande.add(int(m.group(1)))
    for p in poorten_in_gebruik(sites):
        if p not in bestaande:
            extra.append("Listen %d" % p)
    # https aanzetten als er ssl-sites zijn
    ssl = ssl_sites(sites)
    if ssl:
        if ACTIEVE_HTTPS_POORT not in bestaande:
            extra.append("Listen %d" % ACTIEVE_HTTPS_POORT)
        # mod_ssl + sessiecache laden als ze nog niet actief zijn
        if not re.search(r"(?im)^\s*LoadModule\s+ssl_module", inhoud):
            extra.append("LoadModule ssl_module modules/mod_ssl.so")
        if not re.search(r"(?im)^\s*LoadModule\s+socache_shmcb_module", inhoud):
            extra.append("LoadModule socache_shmcb_module "
                         "modules/mod_socache_shmcb.so")
        extra.append("<IfModule ssl_module>")
        extra.append('    SSLSessionCache "shmcb:%s/ssl_scache(512000)"'
                     % _ap(LOG_MAP))
        extra.append("    SSLSessionCacheTimeout 300")
        extra.append("</IfModule>")
    # PHP inschakelen?
    if php_dir and os.path.isdir(php_dir):
        regels = php_conf_regels(php_dir)
        if regels:
            extra.append(regels)
    extra.append('Include "%s/*.conf"' % _ap(VHOST_MAP))
    extra.append("")
    with open(RUN_CONFIG, "w", encoding="utf-8") as f:
        f.write(inhoud.rstrip() + "\n" + "\n".join(extra))
    return RUN_CONFIG


def _minimale_conf(apache):
    """Zeer eenvoudige config voor als er geen httpd.conf gevonden is."""
    d = _ap(apache.get("dir", ""))
    return "\n".join([
        'ServerRoot "%s"' % d,
        "Listen 80",
        "LoadModule mpm_winnt_module modules/mod_mpm_winnt.so",
        "LoadModule authz_core_module modules/mod_authz_core.so",
        "LoadModule mime_module modules/mod_mime.so",
        "LoadModule dir_module modules/mod_dir.so",
        "LoadModule autoindex_module modules/mod_autoindex.so",
        "LoadModule log_config_module modules/mod_log_config.so",
        'ServerName localhost:80',
        'DocumentRoot "%s/htdocs"' % d,
        '<Directory />',
        "    AllowOverride none",
        "    Require all denied",
        "</Directory>",
        'LogFormat "%h %l %u %t \\"%r\\" %>s %b" common',
        "",
    ])


def maak_teststartpagina(site):
    """Zet een vriendelijke index.html in een lege sitemap, zodat de gebruiker
    meteen iets ziet."""
    docroot = site.get("map", "")
    if not docroot:
        return
    try:
        os.makedirs(docroot, exist_ok=True)
    except OSError:
        return
    index = os.path.join(docroot, "index.html")
    if os.path.exists(index):
        return
    naam = site.get("naam", "site")
    html = (
        "<!doctype html><html lang='nl'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>%s - DraveServer</title>"
        "<style>body{font-family:system-ui,Arial,sans-serif;background:#0e0e11;"
        "color:#d4d4d4;display:flex;min-height:100vh;align-items:center;"
        "justify-content:center;margin:0}.kaart{max-width:560px;padding:32px;"
        "background:#16161b;border:1px solid #23232b;border-radius:14px;"
        "text-align:center}h1{color:#6fa3d6;font-size:30px;margin:.2em 0}"
        "p{font-size:18px;line-height:1.5}code{background:#1c1c22;padding:2px 6px;"
        "border-radius:6px}</style></head><body><div class='kaart'>"
        "<h1>Het werkt! &#128075;</h1>"
        "<p>Je website <b>%s</b> draait nu via DraveServer.</p>"
        "<p>Vervang dit bestand (<code>index.html</code>) in je sitemap door je "
        "eigen website.</p></div></body></html>"
    ) % (naam, naam)
    try:
        with open(index, "w", encoding="utf-8") as f:
            f.write(html)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# SSL / https
# ---------------------------------------------------------------------------
def genereer_self_signed(domein, cert_pad, key_pad, dagen=825):
    """Maak zelf een certificaat + sleutel (voor eigen pc/netwerk/testen).
    Geeft (ok, fout)."""
    try:
        import ipaddress
        import datetime
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
    except Exception as e:
        return False, "cryptography ontbreekt: %s" % e
    try:
        domein = (domein or "localhost").strip() or "localhost"
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        naam = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, domein)])
        san = []
        for d in dict.fromkeys([domein, "localhost"]):
            san.append(x509.DNSName(d))
        san.append(x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")))
        nu = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder()
                .subject_name(naam).issuer_name(naam)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(nu - datetime.timedelta(days=1))
                .not_valid_after(nu + datetime.timedelta(days=dagen))
                .add_extension(x509.SubjectAlternativeName(san), critical=False)
                .add_extension(x509.BasicConstraints(ca=False, path_length=None),
                               critical=True)
                .sign(key, hashes.SHA256()))
        os.makedirs(os.path.dirname(cert_pad), exist_ok=True)
        with open(key_pad, "wb") as f:
            f.write(key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption()))
        with open(cert_pad, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        return True, ""
    except Exception as e:
        return False, str(e)


def lees_cert_info(cert_pad):
    """Lees onderwerp + vervaldatum van een certificaat. Geeft dict of None."""
    try:
        import datetime
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        with open(cert_pad, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())
        try:
            vervalt = cert.not_valid_after_utc
        except AttributeError:
            vervalt = cert.not_valid_after.replace(tzinfo=datetime.timezone.utc)
        nu = datetime.datetime.now(datetime.timezone.utc)
        dagen = (vervalt - nu).days
        cn = ""
        try:
            cn = cert.subject.get_attributes_for_oid(
                NameOID.COMMON_NAME)[0].value
        except Exception:
            pass
        return {"cn": cn, "vervalt": vervalt, "dagen": dagen}
    except Exception:
        return None


def genereer_ssl_vhost(site):
    """Bouw het https-<VirtualHost>-blok voor een site (poort instelbaar)."""
    naam = site.get("naam", "site")
    veilig = "".join(c if c.isalnum() or c in "-_" else "_" for c in naam)[:40] or "site"
    docroot = _ap(site.get("map", ""))
    servernaam = site.get("servernaam") or "localhost"
    cert = _ap(site.get("ssl_cert", ""))
    key = _ap(site.get("ssl_key", ""))
    log = _ap(LOG_MAP)
    return "\n".join([
        "# DraveServer - https - %s" % naam,
        "<VirtualHost *:%d>" % ACTIEVE_HTTPS_POORT,
        "    ServerName %s" % servernaam,
        '    DocumentRoot "%s"' % docroot,
        "    SSLEngine on",
        '    SSLCertificateFile "%s"' % cert,
        '    SSLCertificateKeyFile "%s"' % key,
        '    <Directory "%s">' % docroot,
        "        Options Indexes FollowSymLinks",
        "        AllowOverride All",
        "        Require all granted",
        "    </Directory>",
        '    ErrorLog "%s/%s-ssl-error.log"' % (log, veilig),
        "</VirtualHost>",
        "",
    ])


def ssl_sites(sites):
    """Sites met geldige https-instellingen (aan + cert + key bestaan)."""
    uit = []
    for s in sites:
        if (s.get("ssl_aan") and s.get("map") and s.get("ssl_cert")
                and s.get("ssl_key") and os.path.isfile(s["ssl_cert"])
                and os.path.isfile(s["ssl_key"])):
            uit.append(s)
    return uit


# ---- Let's Encrypt (gratis, vertrouwd certificaat - geen Certbot nodig) ----
LE_DIR_PROD = "https://acme-v02.api.letsencrypt.org/directory"
LE_DIR_STAGING = "https://acme-staging-v02.api.letsencrypt.org/directory"


def le_account_sleutel():
    """Laad of maak de Let's Encrypt-accountsleutel (hergebruikt bij vernieuwen)."""
    import josepy
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    pad = os.path.join(CERT_MAP, "le-account.key")
    os.makedirs(CERT_MAP, exist_ok=True)
    if os.path.isfile(pad):
        with open(pad, "rb") as f:
            key = serialization.load_pem_private_key(f.read(), password=None)
    else:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with open(pad, "wb") as f:
            f.write(key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption()))
    return josepy.JWKRSA(key=key)


def le_haal_certificaat(domein, email, docroot, cert_pad, key_pad,
                        staging=True, log=None):
    """Haal (of vernieuw) een Let's Encrypt-certificaat via http-01. Het
    verificatiebestand wordt in de site-map geplaatst; Apache serveert het op
    poort 80. Vereist: domein wijst naar deze pc, poort 80 bereikbaar, server
    draait. Geeft (ok, fout)."""
    def melding(t):
        if log:
            log(t)
    try:
        from acme import client, messages, challenges
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography import x509
        from cryptography.x509.oid import NameOID
    except Exception as e:
        return False, "Let's Encrypt-bibliotheek ontbreekt: %s" % e
    try:
        acc_key = le_account_sleutel()
        dir_url = LE_DIR_STAGING if staging else LE_DIR_PROD
        melding("Verbinden met Let's Encrypt%s..." %
                (" (teststand)" if staging else ""))
        net = client.ClientNetwork(acc_key,
                                   user_agent="DraveServer/%s" % APP_VERSIE)
        directory = client.ClientV2.get_directory(dir_url, net)
        acme_client = client.ClientV2(directory, net=net)
        melding("Account registreren...")
        reg = messages.NewRegistration.from_data(
            email=email, terms_of_service_agreed=True)
        try:
            regr = acme_client.new_account(reg)
            net.account = regr
        except Exception as e:
            if "already" not in str(e).lower():
                raise
        # site-sleutel + CSR
        site_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        csr = (x509.CertificateSigningRequestBuilder()
               .subject_name(x509.Name([
                   x509.NameAttribute(NameOID.COMMON_NAME, domein)]))
               .add_extension(x509.SubjectAlternativeName([x509.DNSName(domein)]),
                              critical=False)
               .sign(site_key, hashes.SHA256()))
        csr_pem = csr.public_bytes(serialization.Encoding.PEM)
        melding("Aanvraag indienen voor %s..." % domein)
        order = acme_client.new_order(csr_pem)
        geplaatst = []
        for authz in order.authorizations:
            challb = None
            for c in authz.body.challenges:
                if isinstance(c.chall, challenges.HTTP01):
                    challb = c
                    break
            if challb is None:
                return False, "Geen http-01 verificatie beschikbaar."
            response, validatie = challb.response_and_validation(acc_key)
            relpad = challb.chall.path.lstrip("/")  # .well-known/acme-challenge/..
            doel = os.path.join(docroot, *relpad.split("/"))
            os.makedirs(os.path.dirname(doel), exist_ok=True)
            with open(doel, "w") as f:
                f.write(validatie)
            geplaatst.append(doel)
            melding("Verificatiebestand geplaatst, Let's Encrypt controleert...")
            acme_client.answer_challenge(challb, response)
        order = acme_client.poll_and_finalize(order)
        os.makedirs(os.path.dirname(cert_pad), exist_ok=True)
        with open(cert_pad, "w") as f:
            f.write(order.fullchain_pem)
        with open(key_pad, "wb") as f:
            f.write(site_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption()))
        for g in geplaatst:
            try:
                os.remove(g)
            except OSError:
                pass
        melding("Certificaat opgehaald en opgeslagen!")
        return True, ""
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Database (MariaDB)
# ---------------------------------------------------------------------------
MARIADB_BASIS = os.path.join(DATA_MAP, "mariadb")        # uitgepakte MariaDB
MARIADB_DATA = os.path.join(DATA_MAP, "mariadb-data")    # datamap
MARIADB_INDEX = "https://downloads.mariadb.org/rest-api/mariadb/"
DB_POORT = 3306
MARIADB_FALLBACK = ("https://downloads.mariadb.org/rest-api/mariadb/"
                    "11.4.5/mariadb-11.4.5-winx64.zip")


def _haal_tekst(url):
    verzoek = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    with urllib.request.urlopen(verzoek, timeout=20) as bron:
        return bron.read().decode("utf-8", "replace")


def mariadb_download_url():
    """Zoek de nieuwste stabiele LTS winx64-zip via de MariaDB REST-API. Valt
    terug op een bekende URL."""
    try:
        idx = json.loads(_haal_tekst(MARIADB_INDEX))
        release = ""
        for r in idx.get("major_releases", []):
            if (r.get("release_status") == "Stable"
                    and "Long Term" in str(r.get("release_support_type"))):
                release = r.get("release_id")
                break
        if not release:
            return MARIADB_FALLBACK
        tekst = _haal_tekst(MARIADB_INDEX + release + "/")
        versies = re.findall(r"mariadb-(\d+\.\d+\.\d+)-winx64\.zip", tekst)
        if not versies:
            return MARIADB_FALLBACK
        v = sorted(set(versies), key=lambda s: [int(x) for x in s.split(".")])[-1]
        return ("https://downloads.mariadb.org/rest-api/mariadb/"
                "%s/mariadb-%s-winx64.zip" % (v, v))
    except Exception:
        return MARIADB_FALLBACK


def vind_mariadbd(wortel):
    """Zoek bin/mariadbd.exe (of mysqld.exe) onder wortel."""
    for naam in ("mariadbd.exe", "mysqld.exe"):
        for hoofd, _m, best in os.walk(wortel):
            if os.path.basename(hoofd).lower() == "bin" and naam in best:
                return os.path.join(hoofd, naam)
    return ""


def mariadbd_uit_config(cfg):
    exe = (cfg.get("db_exe") or "").strip()
    if exe and os.path.isfile(exe):
        return exe
    return vind_mariadbd(MARIADB_BASIS)


def db_init(mariadbd_exe, datadir):
    """Initialiseer de datamap (eenmalig). Geeft (ok, fout)."""
    bin_dir = os.path.dirname(mariadbd_exe)
    install = ""
    for n in ("mariadb-install-db.exe", "mysql_install_db.exe"):
        p = os.path.join(bin_dir, n)
        if os.path.isfile(p):
            install = p
            break
    if not install:
        return False, "mariadb-install-db.exe niet gevonden."
    os.makedirs(datadir, exist_ok=True)
    try:
        r = subprocess.run([install, "--datadir=%s" % datadir], cwd=bin_dir,
                           capture_output=True, timeout=180,
                           creationflags=NO_WINDOW)
    except Exception as e:
        return False, str(e)
    if r.returncode != 0:
        uit = (r.stdout or b"").decode("utf-8", "replace")
        return False, uit[-600:] or "Initialiseren mislukt."
    return True, ""


def _start_proces(args, logpad, wacht=3.0):
    """Start een voorgrond-serverproces met uitvoer naar een LOGBESTAND
    (geen onbeheerde pipe -> geen deadlock als het proces veel logt).
    Detecteert een vroege crash en leest dan het log terug.
    Geeft (proc_of_None, fouttekst)."""
    try:
        os.makedirs(os.path.dirname(logpad), exist_ok=True)
    except Exception:
        pass
    try:
        logf = open(logpad, "wb")
    except Exception:
        logf = None
    try:
        proc = subprocess.Popen(
            args,
            stdout=(logf or subprocess.DEVNULL),
            stderr=subprocess.STDOUT,
            creationflags=NO_WINDOW)
    except Exception as e:
        try:
            if logf:
                logf.close()
        except Exception:
            pass
        return None, str(e)
    # Ouder-handle mag dicht: het kindproces heeft een eigen geerfde handle.
    try:
        if logf:
            logf.close()
    except Exception:
        pass
    stappen = int(max(1, wacht / 0.25))
    for _ in range(stappen):
        time.sleep(0.25)
        if proc.poll() is not None:
            tekst = ""
            try:
                with open(logpad, "rb") as f:
                    tekst = f.read().decode("utf-8", "replace").strip()
            except Exception:
                pass
            return None, (tekst[-1000:] if tekst else "")
    return proc, ""


def vind_db_tool(namen):
    """Zoek een MariaDB-hulpprogramma (bv. mariadb-dump.exe) in de bin-map."""
    exe = vind_mariadbd(MARIADB_BASIS)
    if not exe:
        return ""
    bin_dir = os.path.dirname(exe)
    for n in namen:
        p = os.path.join(bin_dir, n)
        if os.path.isfile(p):
            return p
    return ""


def maak_qr_pixmap(tekst, grootte=320):
    """Maak een QR-code als QPixmap (puur via qrcode-matrix, geen Pillow nodig)."""
    import qrcode
    from PyQt6.QtGui import QPixmap, QPainter, QColor
    qr = qrcode.QRCode(border=2, box_size=10,
                       error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(tekst); qr.make(fit=True)
    m = qr.get_matrix()
    n = len(m)
    pm = QPixmap(grootte, grootte); pm.fill(QColor("#ffffff"))
    cell = grootte / float(n)
    p = QPainter(pm)
    p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor("#000000"))
    for y, row in enumerate(m):
        for x, val in enumerate(row):
            if val:
                p.drawRect(int(x * cell), int(y * cell),
                           int(cell) + 1, int(cell) + 1)
    p.end()
    return pm


def zet_autostart_windows(aan):
    """Voeg DraveServer toe aan/uit de Windows-autostart (HKCU Run)."""
    if not WINDOWS:
        return False
    try:
        import winreg
        sleutel = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE)
        if aan:
            doel = sys.executable
            if not getattr(sys, "frozen", False):
                # bron-modus: start via pythonw + scriptpad
                script = os.path.abspath(__file__)
                doel = '"%s" "%s" --systeemvak' % (sys.executable, script)
            else:
                doel = '"%s" --systeemvak' % doel
            winreg.SetValueEx(sleutel, "DraveServer", 0, winreg.REG_SZ, doel)
        else:
            try:
                winreg.DeleteValue(sleutel, "DraveServer")
            except FileNotFoundError:
                pass
        winreg.CloseKey(sleutel)
        return True
    except Exception:
        return False


def stop_strays():
    """Beeindig achtergebleven EIGEN httpd.exe/mariadbd.exe (bv. na een crash
    of harde afsluiting) die nog poorten vasthouden. Alleen processen waarvan
    de exe onder onze DATA_MAP staat -> raakt geen andere Apache/MariaDB."""
    if not WINDOWS:
        return
    basis = os.path.abspath(DATA_MAP).replace("'", "''")
    for naam in ("httpd.exe", "mariadbd.exe"):
        ps = ("Get-CimInstance Win32_Process -Filter \"Name='%s'\" | "
              "Where-Object { $_.ExecutablePath -like '%s\\*' } | "
              "ForEach-Object { Stop-Process -Id $_.ProcessId -Force "
              "-ErrorAction SilentlyContinue }") % (naam, basis)
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, timeout=15,
                           creationflags=NO_WINDOW)
        except Exception:
            pass


def verklaar_poortfout(fout, dienst="server"):
    """Maak van een ruwe bind-fout (poort bezet) een begrijpelijke melding."""
    f = fout or ""
    laag = f.lower()
    if ("10048" in f or "could not bind" in laag or "make_sock" in laag
            or "no listening sockets" in laag or "address already in use" in laag
            or "in use" in laag):
        uitleg = ("De %s kon niet starten omdat de poort al in gebruik is.\n\n"
                  "Meestal draait er nog een vorige server (bijv. een achtergebleven "
                  "Apache/MariaDB na een herstart), of een ander programma gebruikt de "
                  "poort. Sluit DraveServer volledig af en open het opnieuw — "
                  "achtergebleven eigen servers worden dan automatisch opgeruimd. Helpt "
                  "dat niet, kies dan een andere poort bij Beveiliging / Database, of "
                  "sluit het andere programma.\n\nTechnische details:\n") % dienst
        return uitleg + f
    return f


class DatabaseBeheer:
    """Beheert het mariadbd-proces (foreground), net als de webserver."""
    def __init__(self):
        self.proc = None
        self.laatste_fout = ""

    def draait(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, exe, datadir, port=None):
        port = int(port or ACTIEVE_DB_POORT)
        if self.draait():
            return True, ""
        if not WINDOWS:
            self.proc = _DemoProc()
            return True, "(demo) MariaDB zou nu starten"
        if not exe or not os.path.isfile(exe):
            return False, "MariaDB (mariadbd.exe) niet gevonden."
        if not os.path.isdir(os.path.join(datadir, "mysql")):
            ok, fout = db_init(exe, datadir)
            if not ok:
                return False, "Initialiseren mislukt: " + fout
        logpad = os.path.join(LOG_MAP, "mariadb.log")
        proc, fout = _start_proces(
            [exe, "--datadir=%s" % datadir, "--port=%d" % port, "--console"],
            logpad, wacht=4.0)
        if proc is None:
            self.laatste_fout = fout
            return False, (fout or
                           "MariaDB stopte direct (zie DraveServer-data/logs/mariadb.log).")
        self.proc = proc
        return True, ""

    def stop(self):
        if not self.draait():
            self.proc = None
            return
        try:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=6)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        except Exception:
            pass
        self.proc = None


def db_verbind(wachtwoord, database=None, port=None):
    import pymysql
    return pymysql.connect(host="127.0.0.1", port=int(port or ACTIEVE_DB_POORT), user="root",
                           password=wachtwoord or "", database=database,
                           connect_timeout=5, autocommit=True,
                           charset="utf8mb4")


def db_wacht_klaar(wachtwoord, timeout=30):
    """Wacht tot MariaDB verbindingen accepteert. Geeft (ok, fout)."""
    import time
    laatste = ""
    eind = time.time() + timeout
    while time.time() < eind:
        try:
            con = db_verbind(wachtwoord)
            con.close()
            return True, ""
        except Exception as e:
            laatste = str(e)
            time.sleep(1)
    return False, laatste


def _veilige_naam(naam):
    return "".join(c for c in (naam or "") if c.isalnum() or c in "_$")[:64]


def db_lijst_databases(wachtwoord):
    con = db_verbind(wachtwoord)
    try:
        cur = con.cursor()
        cur.execute("SHOW DATABASES")
        stelsel = {"information_schema", "performance_schema", "mysql", "sys"}
        return [r[0] for r in cur.fetchall() if r[0] not in stelsel]
    finally:
        con.close()


def db_maak_database(naam, wachtwoord):
    veilig = _veilige_naam(naam)
    if not veilig:
        return False, "Ongeldige naam."
    con = db_verbind(wachtwoord)
    try:
        cur = con.cursor()
        cur.execute("CREATE DATABASE IF NOT EXISTS `%s` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci" % veilig)
        return True, ""
    except Exception as e:
        return False, str(e)
    finally:
        con.close()


def db_verwijder_database(naam, wachtwoord):
    veilig = _veilige_naam(naam)
    if not veilig:
        return False, "Ongeldige naam."
    con = db_verbind(wachtwoord)
    try:
        con.cursor().execute("DROP DATABASE IF EXISTS `%s`" % veilig)
        return True, ""
    except Exception as e:
        return False, str(e)
    finally:
        con.close()


def db_zet_root_wachtwoord(oud, nieuw):
    con = db_verbind(oud)
    try:
        cur = con.cursor()
        cur.execute("SET PASSWORD FOR 'root'@'localhost' = PASSWORD(%s)", (nieuw,))
        try:
            cur.execute("SET PASSWORD FOR 'root'@'127.0.0.1' = PASSWORD(%s)",
                        (nieuw,))
        except Exception:
            pass
        return True, ""
    except Exception as e:
        return False, str(e)
    finally:
        con.close()


# ---- tabellen en velden (de veld-bouwer) ----
DB_TYPES = ["INT", "BIGINT", "VARCHAR", "TEXT", "DATE", "DATETIME", "TIME",
            "DECIMAL", "FLOAT", "BOOLEAN"]


def _kolom_sql(k):
    """Bouw 1 kolomdefinitie uit een veld-dict {naam,type,lengte,pk,auto,nn}."""
    naam = _veilige_naam(k.get("naam", ""))
    if not naam:
        return ""
    t = str(k.get("type", "VARCHAR")).upper()
    lengte = str(k.get("lengte", "")).strip()
    if t == "BOOLEAN":
        decl = "TINYINT(1)"
    elif t == "VARCHAR":
        decl = "VARCHAR(%s)" % (lengte if lengte.isdigit() else "255")
    elif t == "DECIMAL":
        decl = "DECIMAL(%s)" % (lengte if re.match(r"^\d+(,\d+)?$", lengte)
                                else "10,2")
    elif t in DB_TYPES:
        decl = t
    else:
        decl = "VARCHAR(255)"
    deel = "`%s` %s" % (naam, decl)
    if k.get("nn") or k.get("pk"):
        deel += " NOT NULL"
    if k.get("auto"):
        deel += " AUTO_INCREMENT"
    return deel


def bouw_create_table(naam, kolommen):
    """Bouw een CREATE TABLE-statement (zonder uit te voeren)."""
    tnaam = _veilige_naam(naam)
    delen = []
    pk = []
    for k in kolommen:
        sql = _kolom_sql(k)
        if not sql:
            continue
        delen.append(sql)
        if k.get("pk"):
            pk.append("`%s`" % _veilige_naam(k.get("naam", "")))
    if pk:
        delen.append("PRIMARY KEY (%s)" % ", ".join(pk))
    return ("CREATE TABLE `%s` (\n  %s\n) CHARACTER SET utf8mb4 "
            "COLLATE utf8mb4_unicode_ci" % (tnaam, ",\n  ".join(delen)))


def db_lijst_tabellen(database, wachtwoord):
    con = db_verbind(wachtwoord, database=database)
    try:
        cur = con.cursor()
        cur.execute("SHOW TABLES")
        return [r[0] for r in cur.fetchall()]
    finally:
        con.close()


def db_maak_tabel(database, naam, kolommen, wachtwoord):
    if not _veilige_naam(naam):
        return False, "Ongeldige tabelnaam."
    if not any(_veilige_naam(k.get("naam", "")) for k in kolommen):
        return False, "Geen geldige velden."
    con = db_verbind(wachtwoord, database=database)
    try:
        con.cursor().execute(bouw_create_table(naam, kolommen))
        return True, ""
    except Exception as e:
        return False, str(e)
    finally:
        con.close()


def db_verwijder_tabel(database, naam, wachtwoord):
    veilig = _veilige_naam(naam)
    if not veilig:
        return False, "Ongeldige naam."
    con = db_verbind(wachtwoord, database=database)
    try:
        con.cursor().execute("DROP TABLE IF EXISTS `%s`" % veilig)
        return True, ""
    except Exception as e:
        return False, str(e)
    finally:
        con.close()


def db_lijst_kolommen(database, tabel, wachtwoord):
    """Geef [(naam, type, null, key, default), ...] van een tabel."""
    veilig = _veilige_naam(tabel)
    con = db_verbind(wachtwoord, database=database)
    try:
        cur = con.cursor()
        cur.execute("SHOW COLUMNS FROM `%s`" % veilig)
        rijen = []
        for r in cur.fetchall():
            rijen.append((r[0], r[1], r[2], r[3], r[4]))
        return rijen
    finally:
        con.close()


def _parse_kolomtype(t):
    """Zet een MySQL-type ('varchar(255)') om naar (TYPE, lengte) voor de bouwer."""
    t = (t or "").lower()
    m = re.match(r"([a-z]+)(?:\(([^)]*)\))?", t)
    basis = m.group(1) if m else "varchar"
    arg = (m.group(2) if m and m.group(2) else "").strip()
    if basis == "tinyint" and arg == "1":
        return ("BOOLEAN", "")
    kaart = {"int": "INT", "bigint": "BIGINT", "varchar": "VARCHAR",
             "text": "TEXT", "date": "DATE", "datetime": "DATETIME",
             "time": "TIME", "decimal": "DECIMAL", "float": "FLOAT",
             "tinyint": "INT", "smallint": "INT", "mediumint": "INT"}
    typ = kaart.get(basis, "VARCHAR")
    lengte = arg if typ in ("VARCHAR", "DECIMAL") else ""
    return (typ, lengte)


def db_voeg_kolom_toe(database, tabel, kolom, wachtwoord):
    veilig = _veilige_naam(tabel)
    sql = _kolom_sql(kolom)
    if not sql:
        return False, "Ongeldig veld."
    con = db_verbind(wachtwoord, database=database)
    try:
        con.cursor().execute("ALTER TABLE `%s` ADD COLUMN %s" % (veilig, sql))
        return True, ""
    except Exception as e:
        return False, str(e)
    finally:
        con.close()


def db_wijzig_kolom(database, tabel, oude_naam, kolom, wachtwoord):
    """Wijzig een bestaand veld (naam en/of type) via ALTER TABLE CHANGE."""
    veilig = _veilige_naam(tabel)
    oud = _veilige_naam(oude_naam)
    sql = _kolom_sql(kolom)
    if not oud or not sql:
        return False, "Ongeldig veld."
    con = db_verbind(wachtwoord, database=database)
    try:
        con.cursor().execute("ALTER TABLE `%s` CHANGE `%s` %s"
                             % (veilig, oud, sql))
        return True, ""
    except Exception as e:
        return False, str(e)
    finally:
        con.close()


def db_verwijder_kolom(database, tabel, kolomnaam, wachtwoord):
    veilig = _veilige_naam(tabel)
    knaam = _veilige_naam(kolomnaam)
    con = db_verbind(wachtwoord, database=database)
    try:
        con.cursor().execute("ALTER TABLE `%s` DROP COLUMN `%s`"
                             % (veilig, knaam))
        return True, ""
    except Exception as e:
        return False, str(e)
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Onderdelen downloaden en installeren (Apache, PHP)
# ---------------------------------------------------------------------------
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) DraveServer/" + APP_VERSIE)


def download_bestand(url, doel, voortgang=None):
    """Download url naar doel. voortgang(gedaan, totaal) wordt aangeroepen.
    Geeft (ok, fout)."""
    try:
        os.makedirs(os.path.dirname(doel), exist_ok=True)
        verzoek = urllib.request.Request(
            url, headers={"User-Agent": BROWSER_UA, "Referer": APACHE_PAGINA})
        with urllib.request.urlopen(verzoek, timeout=30) as bron:
            totaal = int(bron.headers.get("Content-Length", 0) or 0)
            gedaan = 0
            with open(doel, "wb") as uit:
                while True:
                    brok = bron.read(65536)
                    if not brok:
                        break
                    uit.write(brok)
                    gedaan += len(brok)
                    if voortgang:
                        voortgang(gedaan, totaal)
        return True, ""
    except Exception as e:
        return False, str(e)


def pak_uit(zip_pad, doel_map):
    """Pak een zip uit in doel_map. Geeft (ok, fout)."""
    try:
        os.makedirs(doel_map, exist_ok=True)
        with zipfile.ZipFile(zip_pad, "r") as z:
            z.extractall(doel_map)
        return True, ""
    except Exception as e:
        return False, str(e)


def vind_httpd(wortel):
    """Zoek bin/httpd.exe ergens onder wortel (Apache-zip pakt soms in een
    submap uit, bv. Apache24/)."""
    for hoofd, _mappen, best in os.walk(wortel):
        if os.path.basename(hoofd).lower() == "bin" and "httpd.exe" in best:
            return os.path.join(hoofd, "httpd.exe")
    return ""


def vind_php_map(wortel):
    """Zoek de map met php.exe onder wortel."""
    for hoofd, _mappen, best in os.walk(wortel):
        if "php.exe" in best:
            return hoofd
    return ""


def vind_php_apache_dll(php_map):
    """Zoek de Apache-module-dll (phpXapache2_4.dll) in een PHP-map."""
    try:
        for f in os.listdir(php_map):
            m = re.match(r"php(\d+)apache2_4\.dll$", f, re.I)
            if m:
                return os.path.join(php_map, f), m.group(1)
    except OSError:
        pass
    return "", ""


def apache_download_url():
    """Zoek de nieuwste Apache Lounge win64-zip (VS17 heeft voorkeur). Valt terug
    op de bekende URL als zoeken niet lukt."""
    try:
        verzoek = urllib.request.Request(
            APACHE_PAGINA, headers={"User-Agent": BROWSER_UA})
        with urllib.request.urlopen(verzoek, timeout=20) as bron:
            html = bron.read().decode("utf-8", "replace")
        treffers = re.findall(
            r"download/VS\d+/binaries/httpd-[\d.]+-\d+-win64-VS\d+\.zip",
            html, re.I)
        vs17 = [t for t in treffers if "vs17" in t.lower()]
        keuze = vs17 or treffers
        if keuze:
            return "https://www.apachelounge.com/" + keuze[0]
    except Exception:
        pass
    return APACHE_AUTO["url"]


def geinstalleerde_php_versies():
    """Lijst van gedownloade PHP-versies: [(naam, php_map), ...], nieuwste eerst."""
    out = []
    try:
        for naam in sorted(os.listdir(PHP_BASIS), reverse=True):
            mp = vind_php_map(os.path.join(PHP_BASIS, naam))
            if mp:
                out.append((naam, mp))
    except Exception:
        pass
    return out


def php_versies_ophalen():
    """Haal beschikbare PHP-versies (Thread Safe, x64) op van windows.php.net.
    Geeft een lijst van dicts {versie, vs, bestand, url}, nieuwste eerst."""
    try:
        verzoek = urllib.request.Request(
            PHP_LIJST_URL, headers={"User-Agent": BROWSER_UA})
        with urllib.request.urlopen(verzoek, timeout=30) as bron:
            html = bron.read().decode("utf-8", "replace")
    except Exception:
        return []
    return _parse_php_lijst(html)


def _parse_php_lijst(html):
    """Parse de maplijst-HTML naar PHP TS x64-versies."""
    gevonden = {}
    # bv: php-8.3.14-Win32-vs16-x64.zip  (TS = zonder 'nts')
    patroon = re.compile(
        r"php-(\d+\.\d+\.\d+)-Win32-(vs\d+|vc\d+)-x64\.zip", re.I)
    for m in patroon.finditer(html):
        bestand = m.group(0)
        if "-nts-" in bestand.lower() or "debug" in bestand.lower():
            continue
        if "-src" in bestand.lower() or "devel" in bestand.lower():
            continue
        versie = m.group(1)
        vs = m.group(2).lower()
        sleutel = (versie, vs)
        if sleutel not in gevonden:
            gevonden[sleutel] = {
                "versie": versie, "vs": vs, "bestand": bestand,
                "url": PHP_LIJST_URL + bestand,
            }

    def sorteersleutel(d):
        delen = [int(x) for x in d["versie"].split(".")]
        return (delen, d["vs"])
    return sorted(gevonden.values(), key=sorteersleutel, reverse=True)


def php_conf_regels(php_dir):
    """Genereer de Apache-regels om PHP (mod_php) in te schakelen."""
    dll, major = vind_php_apache_dll(php_dir)
    if not dll:
        return ""
    php = _ap(php_dir)
    return "\n".join([
        "",
        "# ====== PHP (door DraveServer) ======",
        'LoadModule php_module "%s"' % _ap(dll),
        "AddHandler application/x-httpd-php .php",
        'PHPIniDir "%s"' % php,
        "<IfModule dir_module>",
        "    DirectoryIndex index.php index.html",
        "</IfModule>",
        "",
    ])


def scan_php(cfg):
    """Vind een al-geinstalleerde PHP in de php-map als de config er nog geen
    (geldige) heeft. Geeft True als er een nieuwe is gevonden."""
    huidig = cfg.get("php_dir", "")
    if huidig and os.path.isfile(os.path.join(huidig, "php.exe")):
        return False
    if not os.path.isdir(PHP_BASIS):
        return False
    for naam in sorted(os.listdir(PHP_BASIS), reverse=True):
        php_map = vind_php_map(os.path.join(PHP_BASIS, naam))
        if php_map:
            cfg["php_dir"] = php_map
            cfg["php_versie"] = naam
            maak_php_ini(php_map)
            return True
    return False


def scan_sites(cfg):
    """Voeg mappen in htdocs die nog geen site zijn toe aan de lijst.
    Geeft het aantal nieuw gevonden sites."""
    if not os.path.isdir(HTDOCS):
        return 0
    bestaand = set()
    for s in cfg.get("sites", []):
        m = s.get("map", "")
        if m:
            bestaand.add(os.path.normcase(os.path.abspath(m)))
    nieuw = 0
    for naam in sorted(os.listdir(HTDOCS)):
        sub = os.path.join(HTDOCS, naam)
        if not os.path.isdir(sub):
            continue
        if os.path.normcase(os.path.abspath(sub)) in bestaand:
            continue
        cfg.setdefault("sites", []).append({
            "naam": naam, "map": sub, "servernaam": "localhost",
            "poort": 80, "aan": True,
        })
        nieuw += 1
    return nieuw


# handige extensies om standaard aan te zetten (alleen als de DLL aanwezig is)
PHP_EXTENSIES = ["mysqli", "pdo_mysql", "pdo_sqlite", "sqlite3", "openssl",
                 "curl", "mbstring", "fileinfo", "gd", "exif", "intl", "gettext"]


def maak_php_ini(php_dir):
    """Maak een php.ini (op basis van php.ini-production) en zet handige extensies
    aan - alleen die waarvan de DLL echt in ext\\ staat. Een bestaande php.ini
    wordt met rust gelaten. Geeft True als er een nieuwe is gemaakt."""
    if not php_dir or not os.path.isdir(php_dir):
        return False
    ini = os.path.join(php_dir, "php.ini")
    if os.path.isfile(ini):
        return False
    bron = ""
    for kandidaat in ("php.ini-production", "php.ini-development"):
        p = os.path.join(php_dir, kandidaat)
        if os.path.isfile(p):
            bron = p
            break
    if not bron:
        return False
    try:
        with open(bron, encoding="utf-8", errors="replace") as f:
            tekst = f.read()
    except Exception:
        return False
    # welke extensie-DLL's zijn aanwezig?
    aanwezig = set()
    try:
        for f in os.listdir(os.path.join(php_dir, "ext")):
            m = re.match(r"php_([a-z0-9_]+)\.dll$", f, re.I)
            if m:
                aanwezig.add(m.group(1).lower())
    except OSError:
        pass
    # extension_dir = "ext"
    if re.search(r'(?im)^\s*;?\s*extension_dir\s*=', tekst):
        tekst = re.sub(r'(?im)^\s*;?\s*extension_dir\s*=.*$',
                       'extension_dir = "ext"', tekst, count=1)
    else:
        tekst += '\nextension_dir = "ext"\n'
    # extensies aanzetten
    for ext in PHP_EXTENSIES:
        if ext not in aanwezig:
            continue
        patroon = re.compile(r'(?im)^\s*;\s*extension\s*=\s*%s\s*$' % re.escape(ext))
        if patroon.search(tekst):
            tekst = patroon.sub('extension=%s' % ext, tekst)
        else:
            tekst += '\nextension=%s\n' % ext
    try:
        with open(ini, "w", encoding="utf-8") as f:
            f.write(tekst)
    except Exception:
        return False
    return True


# ---------------------------------------------------------------------------
# Server starten/stoppen
# ---------------------------------------------------------------------------
class ServerBeheer:
    """Beheert het Apache-proces (foreground), zodat we geen Windows-service
    nodig hebben en geen admin-rechten."""
    def __init__(self):
        self.proc = None
        self.laatste_fout = ""

    def draait(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, apache, sites, php_dir=""):
        if self.draait():
            return True, ""
        if not WINDOWS:
            # demonstratiestand: doen alsof
            self.proc = _DemoProc()
            self.laatste_fout = ""
            return True, "(demo) Apache zou nu starten"
        exe = apache.get("httpd_exe")
        if not exe or not os.path.isfile(exe):
            return False, "Geen Apache (httpd.exe) gevonden."
        runconf = bouw_runconfig(apache, sites, php_dir)
        logpad = os.path.join(LOG_MAP, "apache-start.log")
        proc, fout = _start_proces([exe, "-f", runconf, "-DFOREGROUND"],
                                   logpad, wacht=2.0)
        if proc is None:
            self.laatste_fout = fout
            return False, (fout or "Apache stopte direct (zie logboek).")
        self.proc = proc
        return True, ""

    def stop(self):
        if not self.draait():
            self.proc = None
            return
        try:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        except Exception:
            pass
        self.proc = None


class _DemoProc:
    def poll(self):
        return None

    def terminate(self):
        pass

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


# ===========================================================================
# GUI
# ===========================================================================
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QStatusBar, QMessageBox, QDialog, QTextBrowser,
    QComboBox, QFormLayout, QDialogButtonBox, QTabWidget, QListWidget,
    QListWidgetItem, QSpinBox, QCheckBox, QFileDialog, QProgressBar, QInputDialog,
    QScrollArea,
)

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWebEngineCore import QWebEnginePage
    WEBENGINE = True
except Exception:
    WEBENGINE = False
from PyQt6.QtGui import (
    QAction, QIcon, QDesktopServices, QColor, QPixmap, QPalette,
)
from PyQt6.QtCore import Qt, QUrl, QLocale, QSize, QTimer, QThread, pyqtSignal


def detecteer_taal():
    try:
        return "nl" if QLocale.system().name().lower().startswith("nl") else "en"
    except Exception:
        return "en"


class PhpLijstThread(QThread):
    klaar = pyqtSignal(list)

    def run(self):
        try:
            lijst = php_versies_ophalen()
        except Exception:
            lijst = []
        self.klaar.emit(lijst)


class OpstartThread(QThread):
    """Ruimt strays op en start (indien aan) server + database op de achtergrond,
    zodat de UI niet bevriest tijdens het opstarten."""
    klaar = pyqtSignal()

    def __init__(self, venster):
        super().__init__()
        self.v = venster

    def run(self):
        try:
            stop_strays()
        except Exception:
            pass
        v = self.v
        if v.cfg.get("auto_start", True):
            try:
                if v.apache and v.apache.get("httpd_exe") and not v.server.draait():
                    actieve = [s for s in v.cfg.get("sites", [])
                               if s.get("aan", True) and s.get("map")]
                    if actieve:
                        v.server.start(v.apache, v.cfg.get("sites", []),
                                       v._actieve_php_dir())
            except Exception:
                pass
            try:
                exe = mariadbd_uit_config(v.cfg)
                if exe and not v.db.draait():
                    ok, _ = v.db.start(exe, MARIADB_DATA)
                    if ok:
                        db_wacht_klaar(v.cfg.get("db_wachtwoord", ""), timeout=15)
            except Exception:
                pass
        self.klaar.emit()


class DownloadThread(QThread):
    voortgang = pyqtSignal(int, int)      # gedaan, totaal
    klaar = pyqtSignal(bool, str)         # ok, fout-of-uitpakmap

    def __init__(self, url, doel_zip, uitpak_map):
        super().__init__()
        self.url = url
        self.doel_zip = doel_zip
        self.uitpak_map = uitpak_map

    def run(self):
        url = self.url() if callable(self.url) else self.url
        ok, fout = download_bestand(
            url, self.doel_zip,
            lambda g, t: self.voortgang.emit(g, t))
        if not ok:
            self.klaar.emit(False, fout)
            return
        ok, fout = pak_uit(self.doel_zip, self.uitpak_map)
        try:
            os.remove(self.doel_zip)
        except OSError:
            pass
        if not ok:
            self.klaar.emit(False, fout)
            return
        self.klaar.emit(True, self.uitpak_map)


class LetsEncryptThread(QThread):
    logregel = pyqtSignal(str)
    klaar = pyqtSignal(bool, str)

    def __init__(self, domein, email, docroot, cert_pad, key_pad, staging):
        super().__init__()
        self.domein = domein
        self.email = email
        self.docroot = docroot
        self.cert_pad = cert_pad
        self.key_pad = key_pad
        self.staging = staging

    def run(self):
        ok, fout = le_haal_certificaat(
            self.domein, self.email, self.docroot, self.cert_pad, self.key_pad,
            staging=self.staging, log=lambda t: self.logregel.emit(t))
        self.klaar.emit(ok, fout)


class ExterneIPThread(QThread):
    klaar = pyqtSignal(str)

    def run(self):
        self.klaar.emit(extern_ip())


TEKST = {
    "nl": {
        "ondertitel": "Eenvoudige webserver - lokaal en offline",
        "menu_inst": "Instellingen", "menu_help": "Help",
        "instellingen": "Instellingen", "sluiten": "Sluiten",
        "snelgids": "Snelgids", "welkom_menu": "Welkom / uitleg",
        "over": "Over DraveServer", "donatie": "Donatie",
        "opslaan": "Opslaan", "annuleren": "Annuleren", "sluit": "Sluiten",
        "taal": "Taal", "taal_auto": "Automatisch (computertaal)",
        "auto_start": "Automatisch starten", "auto_start_uitleg": "Server, PHP en database automatisch starten bij openen (als ze al aanwezig zijn)",
        # tabs
        "tab_server": "Server", "tab_sites": "Sites",
        # server-tab
        "server_status": "Status",
        "status_uit": "Gestopt", "status_aan": "Draait", "status_bezig": "Wordt gestart\u2026",
        "opstart_bezig": "Server en database worden gestart \u2014 een moment geduld\u2026",
        "server_apache": "Apache",
        "apache_gevonden": "Gevonden: {pad}",
        "apache_niet": "Nog geen Apache. DraveServer kan Apache zelf voor je "
                       "downloaden - ga naar het tabblad Onderdelen. Of wijs "
                       "hieronder je eigen httpd.exe aan.",
        "naar_onderdelen": "Apache zelf downloaden (tab Onderdelen)",
        "apache_kiezen": "httpd.exe kiezen...",
        "start": "Server starten", "stop": "Server stoppen",
        "open_browser": "Openen in browser",
        "server_demo": "Demonstratiestand: dit is geen Windows, dus de server "
                       "draait niet echt. De interface en de gegenereerde config "
                       "kun je wel bekijken.",
        "config_tonen": "Gemaakte configuratie tonen",
        "geen_sites": "Je hebt nog geen site. Ga naar het tabblad 'Sites' en "
                      "voeg er een toe.",
        "start_mislukt": "Starten lukte niet:\n\n{fout}",
        # sites-tab
        "sites_intro": "Elke 'site' is een website die DraveServer serveert. "
                       "DraveServer schrijft de configuratie voor je - je hoeft "
                       "zelf niets in te stellen.",
        "site_toevoegen": "Site toevoegen", "site_bewerken": "Bewerken",
        "site_verwijderen": "Verwijderen",
        "site_item": "{naam}  -  {servernaam}:{poort}  -  {map}",
        "site_uit": "  (uit)",
        # site-dialoog
        "sd_titel": "Site",
        "sd_naam": "Naam (voor jezelf)",
        "sd_map": "Mapje met je website",
        "sd_map_kiezen": "Kiezen...",
        "sd_server": "Adres (domein of localhost)",
        "sd_poort": "Poort",
        "sd_aan": "Deze site aanzetten",
        "sd_test": "Maak een testpagina als de map leeg is",
        "sd_naam_leeg": "Geef de site een naam.",
        "sd_map_leeg": "Kies het mapje met je website.",
        "sd_map_uitleg": "(niet meer gebruikt)",
        "sd_map_auto": "Je website komt automatisch in deze map (portable):\n{map}\nLeg je bestanden (met een index.html) hier neer. Open de map met de knop 'Sites-map openen'.",
        "sites_open_map": "Sites-map openen (htdocs)",
        "site_openen": "Openen in browser",
        "site_website": "Website bouwen...",
        "blok_kop": "Kop", "blok_tekst": "Tekst", "blok_knop": "Knop",
        "blok_link": "Link", "blok_afbeelding": "Afbeelding", "blok_invoer": "Tekstvak",
        "blok_tekstgebied": "Groot tekstvak", "blok_audio": "Audio", "blok_video": "Video",
        "blok_lijst": "Lijst", "blok_lijn": "Lijn", "blok_citaat": "Citaat",
        "blok_keuzelijst": "Keuzelijst", "blok_vinkje": "Vinkje", "blok_datum": "Datum",
        "wb_niveau": "Kop-niveau",
        "wb_titel": "Website-bouwer",
        "wb_standaard": "Standaard", "wb_formulier": "Formulier", "wb_extra": "Extra",
        "wb_pagina": "Pagina", "wb_ptitel": "Titel", "wb_header": "Kopbalk-tekst",
        "wb_footer": "Voetbalk-tekst", "wb_accent": "Accentkleur", "wb_kleur": "Kies...",
        "wb_sjabloon": "Sjabloon", "wb_leeg": "Leeg", "wb_zakelijk": "Zakelijk",
        "wb_eigenschappen": "Geselecteerd blok", "wb_inhoud": "Tekst/inhoud",
        "wb_url": "Link/adres (url)", "wb_breedte": "Breedte", "wb_hoogte": "Hoogte",
        "wb_kop_h": "Kopbalk-hoogte", "wb_voet_h": "Voetbalk-hoogte",
        "wb_bg_kleur": "Achtergrondkleur", "wb_bg_afb": "Achtergrond-afbeelding",
        "wb_kies_best": "Kies...", "wb_fontgrootte": "Lettergrootte (0=standaard)",
        "wb_vet": "Vet", "wb_tekstkleur": "Tekstkleur", "wb_kies_afb": "Afbeelding kiezen...",
        "wb_verwijder_blok": "Blok verwijderen", "wb_export": "Opslaan / exporteren",
        "wb_open": "Opslaan + openen", "wb_sluiten": "Klaar",
        "wb_geen_webengine": "De ingebouwde editor heeft PyQt6-WebEngine nodig. Sluit de app, start run.bat opnieuw (die installeert het) en open de bouwer dan opnieuw.",
        "wb_geen_map": "Deze site heeft geen map.",
        "wb_ongedaan": "Ongedaan", "wb_opnieuw": "Opnieuw", "wb_nieuw": "Nieuw",
        "wb_nieuw_bevestig": "Nieuwe (lege) website beginnen? Het huidige ontwerp op het scherm gaat verloren (het opgeslagen bestand pas bij Exporteren).",
        "wb_klaar": "Website opgeslagen in de site-map (index.html + PWA). Start de server en bekijk hem.",
        "kies_site": "Welke site wil je openen?",
        "kies_eerst": "Selecteer eerst een site in de lijst.",
        "sites_scannen": "Mappen scannen",
        "scan_sites_n": "{n} site(s) gevonden in htdocs en toegevoegd.",
        "scan_geen_sites": "Geen nieuwe sites gevonden in htdocs.",
        "scan_php_n": "PHP {versie} gevonden en ingesteld.",
        "downloads_menu": "Apache / XAMPP downloaden...",
        "downloads_titel": "Een webserver downloaden",
        "downloads_intro": "Tip: DraveServer kan Apache en PHP zelf voor je downloaden (tabblad Onderdelen). Wil je het liever handmatig of heb je geen internet in de app? Hier zijn de officiele downloadpaginas.",
        "apache_download": "Apache / XAMPP downloaden...",
        "tab_onderdelen": "Onderdelen",
        "tab_ssl": "Beveiliging (https)",
        "tab_database": "Database",
        "tab_poorten": "Poorten / IP",
        "tab_logboek": "Logboek",
        "log_intro": "Hier zie je de logbestanden van de server en database. Handig om te zien wat er gebeurt of misgaat.",
        "log_kies": "Logbestand", "log_ververs": "Vernieuwen", "log_map": "Map openen",
        "log_leeg": "(nog geen logbestanden)", "log_wis": "Wissen",
        "db_backup": "Back-up maken", "db_herstel": "Herstellen",
        "db_backup_kop": "Back-up & herstel",
        "db_backup_klaar": "Back-up opgeslagen:\n{pad}",
        "db_backup_mislukt": "Back-up mislukt:\n\n{fout}",
        "db_herstel_klaar": "Database hersteld uit:\n{pad}",
        "db_herstel_mislukt": "Herstellen mislukt:\n\n{fout}",
        "db_herstel_bevestig": "Dit overschrijft/voegt toe aan database '{naam}'. Doorgaan?",
        "db_geen_draait": "Start eerst de database.",
        "db_geen_tool": "Het hulpprogramma (mariadb-dump) is niet gevonden.",
        "db_kies_db": "Kies eerst een database in de lijst.",
        "qr_knop": "QR-code", "qr_titel": "QR-code voor mobiel",
        "qr_uitleg": "Scan met je telefoon (zelfde wifi/netwerk) om de site te openen.",
        "tray_tonen": "DraveServer tonen", "tray_afsluiten": "Afsluiten",
        "tray_srv_start": "Server starten", "tray_srv_stop": "Server stoppen",
        "tray_db_start": "Database starten", "tray_db_stop": "Database stoppen",
        "tray_actief": "DraveServer draait door in het systeemvak. Rechtsklik het icoon en kies Afsluiten om echt te stoppen.",
        "tray_uitleg": "DraveServer is niet afgesloten, maar draait door in het systeemvak (rechtsonder bij de klok), zodat je server en database actief blijven. Klik het icoon om het venster terug te halen; rechtsklik en kies Afsluiten om echt te stoppen. Dit kun je wijzigen in Instellingen.",
        "set_systeemvak": "Bij sluiten naar systeemvak", "set_meestarten": "Met Windows meestarten",
        "set_systeemvak_uitleg": "Sluiten verbergt het venster in het systeemvak; de server blijft draaien.",
        "set_meestarten_uitleg": "DraveServer automatisch starten als je inlogt op Windows (op de achtergrond, in het systeemvak).",
        "po_intro": "Hier stel je in op welke poorten alles draait. Per site de HTTP-poort, plus de HTTPS-poort en de MariaDB-poort. Met Controleren zie je of een poort vrij of bezet is.",
        "ip_kop": "IP-adressen",
        "ip_intern": "Intern (op je netwerk):",
        "ip_extern": "Extern (publiek):",
        "ip_vernieuw": "Vernieuwen",
        "ip_bezig": "ophalen...",
        "ip_geen": "(geen internet?)",
        "ip_uitleg": "Intern: zo bereik je je sites op je eigen netwerk, bijv. http://192.168.x.x. Extern: je publieke adres, nodig voor port-forwarding, DNS en Let's Encrypt. Je externe IP kan veranderen (tenzij je een vast IP hebt).",
        "po_sites_kop": "HTTP-poort per site",
        "po_geen_sites": "Nog geen sites.",
        "po_globaal_kop": "Algemeen",
        "po_https": "HTTPS-poort (alle https-sites):",
        "po_mariadb": "MariaDB-poort:",
        "po_controleer": "Poorten controleren",
        "po_opslaan": "Opslaan",
        "po_vrij": "vrij",
        "po_bezet": "bezet",
        "po_opgeslagen": "Poorten opgeslagen. Herstart de server/database om ze toe te passen.",
        "po_uitleg": "Standaard: HTTP 80, HTTPS 443, MariaDB 3306. Tip: draait de server of database al, dan staat die poort logisch op 'bezet' (door DraveServer zelf). 'Bezet' terwijl alles stilstaat betekent dat een ander programma de poort gebruikt.",
        "db_intro": "DraveServer kan een database (MariaDB) zelf voor je downloaden en opzetten. Daarmee kunnen je websites gegevens opslaan. Alles blijft portable naast de app.",
        "db_kop": "MariaDB (de database)",
        "db_status_uit": "Nog niet geinstalleerd.",
        "db_status_gestopt": "Geinstalleerd (versie {versie}) - gestopt.",
        "db_status_draait": "Draait (versie {versie}) op poort 3306.",
        "db_download": "Automatisch downloaden",
        "db_zip": "Ik heb al een MariaDB-zip...",
        "db_geen_exe": "In deze map zit geen mariadbd.exe.",
        "db_klaar_install": "MariaDB is gedownload en klaar. Klik op Database starten.",
        "db_start": "Database starten",
        "db_stop": "Database stoppen",
        "db_bezig_download": "Downloaden en uitpakken...",
        "db_bezig_start": "MariaDB starten (eerste keer kan even duren)...",
        "db_start_mislukt": "Starten lukte niet:\n\n{fout}",
        "db_wachtwoord_kop": "Root-wachtwoord",
        "db_wachtwoord_uitleg": "Het hoofdwachtwoord van de database. De eerste keer is het leeg - vul een nieuw wachtwoord in en klik op Instellen. Onthoud het goed.",
        "db_wachtwoord_zet": "Wachtwoord instellen",
        "db_wachtwoord_klaar": "Root-wachtwoord ingesteld.",
        "db_databases_kop": "Databases",
        "db_nieuwe_naam": "naam van nieuwe database",
        "db_aanmaken": "Database aanmaken",
        "db_verwijderen": "Verwijderen",
        "db_vernieuwen": "Lijst vernieuwen",
        "db_verwijder_bevestig": "Database {naam} echt verwijderen? Alle gegevens erin gaan verloren.",
        "db_eerst_starten": "Start eerst de database (knop Database starten).",
        "db_geen_pymysql": "De database-bibliotheek (PyMySQL) ontbreekt. Start run.bat opnieuw, dan installeert die hem bij.",
        "db_verbind_fout": "Kon de bewerking niet uitvoeren:\n\n{fout}",
        "db_tabellen_knop": "Tabellen / velden...",
        "db_kies_database": "Kies eerst een database in de lijst.",
        "veld_naam": "veldnaam",
        "veld_lengte": "lengte",
        "veld_pk": "sleutel",
        "veld_auto": "auto-nr",
        "veld_nn": "verplicht",
        "annuleer": "Annuleren",
        "vb_titel": "Nieuwe tabel maken",
        "vb_tabelnaam": "Tabelnaam:",
        "vb_velden": "Velden (kolommen)",
        "vb_veld_toevoegen": "+ Veld toevoegen",
        "vb_voorbeeld": "Voorbeeld (de SQL die wordt uitgevoerd)",
        "vb_maak": "Tabel maken",
        "vb_naam_leeg": "Vul een geldige tabelnaam in.",
        "vt_titel": "Veld toevoegen",
        "td_titel": "Tabellen in {db}",
        "td_tabellen": "Tabellen",
        "td_nieuwe_tabel": "Nieuwe tabel...",
        "td_verwijder_tabel": "Tabel verwijderen",
        "td_velden": "Velden van de tabel",
        "td_veld_toevoegen": "Veld toevoegen...",
        "td_veld_aanpassen": "Veld aanpassen...",
        "td_veld_verwijderen": "Veld verwijderen",
        "td_geen_velden": "(deze tabel heeft nog geen velden)",
        "td_kies_tabel": "Kies eerst een tabel.",
        "td_verwijder_bevestig": "Tabel {naam} echt verwijderen? Alle gegevens erin gaan verloren.",
        "td_veld_bevestig": "Veld {naam} verwijderen? De gegevens in dat veld gaan verloren.",
        "ssl_intro": "Geef je site https (het slotje). Voor je eigen pc of netwerk maakt DraveServer zelf een certificaat. Heb je een domein, dan kun je een bestaand certificaat aanwijzen (automatisch Let's Encrypt komt in de volgende versie).",
        "ssl_site": "Site:",
        "ssl_status_uit": "https staat UIT voor deze site.",
        "ssl_status_self": "https AAN - eigen certificaat (self-signed).",
        "ssl_status_bestaand": "https AAN - eigen certificaatbestanden.",
        "ssl_cert_dagen": "Certificaat verloopt over {dagen} dagen (op {datum}).",
        "ssl_cert_verlopen": "LET OP: certificaat is VERLOPEN - vernieuw het.",
        "ssl_cert_binnenkort": "Let op: certificaat verloopt binnenkort ({dagen} dagen).",
        "ssl_self_maken": "Certificaat zelf maken (eigen pc/netwerk)",
        "ssl_bestaand": "Bestaand certificaat kiezen...",
        "ssl_uit": "https uitzetten",
        "ssl_letsencrypt": "Let's Encrypt (volgende versie)",
        "ssl_letsencrypt_info": "Automatisch een gratis Let's Encrypt-certificaat ophalen komt in de volgende versie. Dan hoef je alleen je domein en e-mail in te vullen; DraveServer regelt de rest (geen Certbot-kennis nodig).",
        "ssl_geen_sites": "Voeg eerst een site toe (tabblad Sites).",
        "ssl_self_klaar": "Certificaat gemaakt en https aangezet. Herstart de server om het toe te passen.",
        "ssl_self_uitleg": "Een zelfgemaakt certificaat geeft in de browser een waarschuwing (Niet veilig); dat is normaal voor eigen gebruik - kies 'Toch doorgaan'. Voor een echt vertrouwd slotje heb je een domein + Let's Encrypt nodig.",
        "ssl_cert_titel": "Certificaatbestand kiezen (.crt of .pem)",
        "ssl_key_titel": "Sleutelbestand kiezen (.key of .pem)",
        "ssl_bestaand_klaar": "Certificaat ingesteld en https aangezet. Herstart de server.",
        "ssl_uit_klaar": "https uitgezet voor deze site. Herstart de server.",
        "ssl_verwijderen": "Certificaat verwijderen",
        "ssl_geen_cert": "Deze site heeft geen certificaat.",
        "ssl_verwijder_bevestig": "Het certificaat voor {site} verwijderen en https uitzetten?",
        "ssl_verwijder_klaar": "Certificaat verwijderd en https uitgezet. Herstart de server.",
        "le_intro": "DraveServer haalt een gratis, vertrouwd certificaat op bij Let's Encrypt - geen Certbot nodig. Vul je domein en e-mail in en klik op Ophalen.",
        "le_domein": "Domein (bijv. mijnsite.nl)",
        "le_email": "E-mail (voor verloop-meldingen)",
        "le_staging": "Teststand gebruiken (optioneel) - levert een NIET-vertrouwd testcertificaat op",
        "le_eisen": "Vereist: je domein moet naar deze pc wijzen, poort 80 moet van buiten bereikbaar zijn, en de server moet draaien. Standaard krijg je meteen een echt certificaat; de teststand is alleen voor proberen zonder de limiet te raken.",
        "le_ophalen": "Certificaat ophalen",
        "le_domein_leeg": "Vul een domein in.",
        "le_server_uit": "De server lijkt niet te draaien. Let's Encrypt moet je site over poort 80 kunnen bereiken. Toch doorgaan?",
        "le_gelukt": "Gelukt! Sluit dit venster om https aan te zetten.",
        "le_klaar": "Let's Encrypt-certificaat ingesteld en https aangezet. Herstart de server.",
        "le_vernieuwd": "Let's Encrypt-certificaat automatisch vernieuwd. Herstart de server om het toe te passen.",
        "ond_intro": "DraveServer kan de webserver (Apache) en PHP zelf voor je downloaden en instellen - je hoeft niets ingewikkelds te doen. Alles komt portable naast de app.",
        "ond_apache_kop": "Apache (de webserver)",
        "ond_apache_aan": "Geinstalleerd: {pad}",
        "ond_apache_uit": "Nog niet geinstalleerd.",
        "ond_apache_auto": "Automatisch downloaden",
        "ond_apache_zip": "Ik heb al een Apache-zip...",
        "ond_apache_zip_titel": "Apache-zip kiezen",
        "ond_php_kop": "PHP (voor .php-websites)",
        "ond_php_aan_status": "Geinstalleerd: versie {versie}",
        "ond_php_actief": "Actieve versie:", "ond_php_gebruik": "Deze versie gebruiken",
        "ond_php_gewisseld": "PHP-versie gewijzigd naar {versie}.",
        "ond_php_gewisseld_herstart": "PHP-versie gewijzigd naar {versie}. De server is herstart.",
        "ond_php_uit": "Nog niet geinstalleerd.",
        "ond_php_versies_laden": "Beschikbare versies laden",
        "ond_php_versie": "Versie:",
        "ond_php_install": "Downloaden en instellen",
        "ond_php_inschakelen": "PHP inschakelen (.php-bestanden laten werken)",
        "ond_php_testen": "PHP testen",
        "php_test_geen_site": "Voeg eerst een site toe (tabblad Sites).",
        "php_test_start": "Testpagina geplaatst. Start de server en open dan:\n{url}",
        "ond_geen_versies": "Kon geen PHP-versies ophalen (geen internet?). Probeer opnieuw.",
        "ond_bezig_versies": "PHP-versies ophalen...",
        "ond_bezig_download": "Downloaden en uitpakken... {mb} MB",
        "ond_klaar_apache": "Apache is gedownload en ingesteld.",
        "ond_klaar_php": "PHP {versie} is gedownload en ingeschakeld.",
        "ond_fout": "Mislukt: {fout}",
        "ond_apache_geen_httpd": "In deze zip zit geen httpd.exe.",
        "ond_let_op": "Let op: PHP moet dezelfde VS-versie hebben als Apache (bijv. beide VS17), en je hebt de Microsoft Visual C++ Redistributable (2015-2022) nodig. DraveServer kiest standaard een passende versie.",
        "sd_uitleg_server": "Voor je eigen pc kun je 'localhost' laten staan. "
                            "Heb je een domein (bijv. mijnsite.nl), vul dat hier in.",
        # welkom
        "welkom_titel": "Welkom bij DraveServer",
        "welkom_wat": "Wat is dit?",
        "welkom_wat_t": "Een webserver maakt van een mapje op je pc een echte "
                        "website die je in een browser kunt openen - thuis of, met "
                        "een domein, voor de hele wereld. DraveServer regelt het "
                        "ingewikkelde werk voor je: in het tabblad Onderdelen haalt "
                        "het zelf Apache en PHP op, en het schrijft alle "
                        "configuratie automatisch.",
        "welkom_hoe": "In drie stappen",
        "welkom_stap1": "1. Tabblad 'Sites': voeg je website toe (een naam en het "
                        "mapje waar je bestanden staan).",
        "welkom_stap2": "2. Tabblad 'Server': klik op 'Server starten'.",
        "welkom_stap3": "3. Klik op 'Openen in browser' - je site is live!",
        "welkom_veilig": "Veilig? DraveServer werkt lokaal. Je antivirus kan een "
                         "nieuw programma even waarschuwen (vals alarm); zie de "
                         "Snelgids.",
        "welkom_niet_meer": "Dit venster niet meer tonen bij opstarten",
        "welkom_start": "Aan de slag",
        "over_tekst": "DraveServer - eenvoudige webserver in de Dravenlock-"
                      "huisstijl. Lokaal, offline, toegankelijk, donationware.\n\n"
                      "Versie {versie}\nContact: {contact}\nDonatie: {donatie}",
    },
    "en": {
        "ondertitel": "Simple web server - local and offline",
        "menu_inst": "Settings", "menu_help": "Help",
        "instellingen": "Settings", "sluiten": "Close",
        "snelgids": "Quick guide", "welkom_menu": "Welcome / help",
        "over": "About DraveServer", "donatie": "Donate",
        "opslaan": "Save", "annuleren": "Cancel", "sluit": "Close",
        "taal": "Language", "taal_auto": "Automatic (system language)",
        "auto_start": "Auto-start", "auto_start_uitleg": "Automatically start server, PHP and database on launch (if already present)",
        "tab_server": "Server", "tab_sites": "Sites",
        "server_status": "Status",
        "status_uit": "Stopped", "status_aan": "Running",
        "status_bezig": "Starting\u2026",
        "opstart_bezig": "Starting server and database \u2014 one moment\u2026",
        "server_apache": "Apache",
        "apache_gevonden": "Found: {pad}",
        "apache_niet": "No Apache yet. DraveServer can download Apache for you - "
                       "go to the Components tab. Or point to your own httpd.exe "
                       "below.",
        "naar_onderdelen": "Download Apache yourself (Components tab)",
        "apache_kiezen": "Choose httpd.exe...",
        "start": "Start server", "stop": "Stop server",
        "open_browser": "Open in browser",
        "server_demo": "Demo mode: this is not Windows, so the server does not "
                       "really run. You can still view the interface and the "
                       "generated config.",
        "config_tonen": "Show generated configuration",
        "geen_sites": "You have no site yet. Go to the 'Sites' tab and add one.",
        "start_mislukt": "Starting failed:\n\n{fout}",
        "sites_intro": "Each 'site' is a website DraveServer serves. DraveServer "
                       "writes the configuration for you - you set up nothing "
                       "yourself.",
        "site_toevoegen": "Add site", "site_bewerken": "Edit",
        "site_verwijderen": "Remove",
        "site_item": "{naam}  -  {servernaam}:{poort}  -  {map}",
        "site_uit": "  (off)",
        "sd_titel": "Site",
        "sd_naam": "Name (for yourself)",
        "sd_map": "Folder with your website",
        "sd_map_kiezen": "Choose...",
        "sd_server": "Address (domain or localhost)",
        "sd_poort": "Port",
        "sd_aan": "Enable this site",
        "sd_test": "Make a test page if the folder is empty",
        "sd_naam_leeg": "Give the site a name.",
        "sd_map_leeg": "Choose the folder with your website.",
        "sd_map_uitleg": "(unused)",
        "sd_map_auto": "Your website goes automatically in this folder (portable):\n{map}\nPut your files (with an index.html) there. Open it with the 'Open sites folder' button.",
        "sites_open_map": "Open sites folder (htdocs)",
        "site_openen": "Open in browser",
        "site_website": "Build website...",
        "blok_kop": "Heading", "blok_tekst": "Text", "blok_knop": "Button",
        "blok_link": "Link", "blok_afbeelding": "Image", "blok_invoer": "Text field",
        "blok_tekstgebied": "Text area", "blok_audio": "Audio", "blok_video": "Video",
        "blok_lijst": "List", "blok_lijn": "Line", "blok_citaat": "Quote",
        "blok_keuzelijst": "Dropdown", "blok_vinkje": "Checkbox", "blok_datum": "Date",
        "wb_niveau": "Heading level",
        "wb_titel": "Website builder",
        "wb_standaard": "Standard", "wb_formulier": "Form", "wb_extra": "Extra",
        "wb_pagina": "Page", "wb_ptitel": "Title", "wb_header": "Header text",
        "wb_footer": "Footer text", "wb_accent": "Accent color", "wb_kleur": "Pick...",
        "wb_sjabloon": "Template", "wb_leeg": "Empty", "wb_zakelijk": "Business",
        "wb_eigenschappen": "Selected block", "wb_inhoud": "Text/content",
        "wb_url": "Link/address (url)", "wb_breedte": "Width", "wb_hoogte": "Height",
        "wb_kop_h": "Header height", "wb_voet_h": "Footer height",
        "wb_bg_kleur": "Background color", "wb_bg_afb": "Background image",
        "wb_kies_best": "Pick...", "wb_fontgrootte": "Font size (0=default)",
        "wb_vet": "Bold", "wb_tekstkleur": "Text color", "wb_kies_afb": "Choose image...",
        "wb_verwijder_blok": "Delete block", "wb_export": "Save / export",
        "wb_open": "Save + open", "wb_sluiten": "Done",
        "wb_geen_webengine": "The built-in editor needs PyQt6-WebEngine. Close the app, run run.bat again (it installs it), then reopen the builder.",
        "wb_geen_map": "This site has no folder.",
        "wb_ongedaan": "Undo", "wb_opnieuw": "Redo", "wb_nieuw": "New",
        "wb_nieuw_bevestig": "Start a new (empty) website? The current design on screen will be lost (the saved file only changes on Export).",
        "wb_klaar": "Website saved to the site folder (index.html + PWA). Start the server and view it.",
        "kies_site": "Which site do you want to open?",
        "kies_eerst": "Select a site in the list first.",
        "sites_scannen": "Scan folders",
        "scan_sites_n": "Found and added {n} site(s) in htdocs.",
        "scan_geen_sites": "No new sites found in htdocs.",
        "scan_php_n": "Found and set PHP {versie}.",
        "downloads_menu": "Download Apache / XAMPP...",
        "downloads_titel": "Download a web server",
        "downloads_intro": "Tip: DraveServer can download Apache and PHP for you (Components tab). Prefer to do it manually, or no internet in the app? Here are the official download pages.",
        "apache_download": "Download Apache / XAMPP...",
        "tab_onderdelen": "Components",
        "tab_ssl": "Security (https)",
        "tab_database": "Database",
        "tab_poorten": "Ports / IP",
        "tab_logboek": "Logs",
        "log_intro": "Here you see the log files of the server and database. Handy to see what is happening or going wrong.",
        "log_kies": "Log file", "log_ververs": "Refresh", "log_map": "Open folder",
        "log_leeg": "(no log files yet)", "log_wis": "Clear",
        "db_backup": "Make backup", "db_herstel": "Restore",
        "db_backup_kop": "Backup & restore",
        "db_backup_klaar": "Backup saved:\n{pad}",
        "db_backup_mislukt": "Backup failed:\n\n{fout}",
        "db_herstel_klaar": "Database restored from:\n{pad}",
        "db_herstel_mislukt": "Restore failed:\n\n{fout}",
        "db_herstel_bevestig": "This overwrites/adds to database '{naam}'. Continue?",
        "db_geen_draait": "Start the database first.",
        "db_geen_tool": "The tool (mariadb-dump) was not found.",
        "db_kies_db": "Pick a database in the list first.",
        "qr_knop": "QR code", "qr_titel": "QR code for mobile",
        "qr_uitleg": "Scan with your phone (same wifi/network) to open the site.",
        "tray_tonen": "Show DraveServer", "tray_afsluiten": "Quit",
        "tray_srv_start": "Start server", "tray_srv_stop": "Stop server",
        "tray_db_start": "Start database", "tray_db_stop": "Stop database",
        "tray_actief": "DraveServer keeps running in the system tray. Right-click the icon and choose Quit to really stop it.",
        "tray_uitleg": "DraveServer was not closed, but keeps running in the system tray (bottom-right near the clock) so your server and database stay active. Click the icon to bring the window back; right-click and choose Quit to really stop it. You can change this in Settings.",
        "set_systeemvak": "On close, minimize to tray", "set_meestarten": "Start with Windows",
        "set_systeemvak_uitleg": "Closing hides the window in the system tray; the server keeps running.",
        "set_meestarten_uitleg": "Start DraveServer automatically when you log in to Windows (in the background, in the system tray).",
        "po_intro": "Set which ports everything runs on. Per site the HTTP port, plus the HTTPS port and the MariaDB port. Use Check to see whether a port is free or busy.",
        "ip_kop": "IP addresses",
        "ip_intern": "Internal (on your network):",
        "ip_extern": "External (public):",
        "ip_vernieuw": "Refresh",
        "ip_bezig": "fetching...",
        "ip_geen": "(no internet?)",
        "ip_uitleg": "Internal: how you reach your sites on your own network, e.g. http://192.168.x.x. External: your public address, needed for port forwarding, DNS and Let's Encrypt. Your external IP can change (unless you have a static IP).",
        "po_sites_kop": "HTTP port per site",
        "po_geen_sites": "No sites yet.",
        "po_globaal_kop": "General",
        "po_https": "HTTPS port (all https sites):",
        "po_mariadb": "MariaDB port:",
        "po_controleer": "Check ports",
        "po_opslaan": "Save",
        "po_vrij": "free",
        "po_bezet": "busy",
        "po_opgeslagen": "Ports saved. Restart the server/database to apply them.",
        "po_uitleg": "Defaults: HTTP 80, HTTPS 443, MariaDB 3306. Tip: if the server or database is already running, that port shows as busy (used by DraveServer itself). Busy while everything is stopped means another program uses the port.",
        "db_intro": "DraveServer can download and set up a database (MariaDB) for you. It lets your websites store data. Everything stays portable next to the app.",
        "db_kop": "MariaDB (the database)",
        "db_status_uit": "Not installed yet.",
        "db_status_gestopt": "Installed (version {versie}) - stopped.",
        "db_status_draait": "Running (version {versie}) on port 3306.",
        "db_download": "Download automatically",
        "db_zip": "I already have a MariaDB zip...",
        "db_geen_exe": "This folder has no mariadbd.exe.",
        "db_klaar_install": "MariaDB downloaded and ready. Click Start database.",
        "db_start": "Start database",
        "db_stop": "Stop database",
        "db_bezig_download": "Downloading and extracting...",
        "db_bezig_start": "Starting MariaDB (first time can take a moment)...",
        "db_start_mislukt": "Starting failed:\n\n{fout}",
        "db_wachtwoord_kop": "Root password",
        "db_wachtwoord_uitleg": "The main database password. The first time it is empty - enter a new password and click Set. Remember it well.",
        "db_wachtwoord_zet": "Set password",
        "db_wachtwoord_klaar": "Root password set.",
        "db_databases_kop": "Databases",
        "db_nieuwe_naam": "name of new database",
        "db_aanmaken": "Create database",
        "db_verwijderen": "Remove",
        "db_vernieuwen": "Refresh list",
        "db_verwijder_bevestig": "Really delete database {naam}? All data in it will be lost.",
        "db_eerst_starten": "Start the database first (Start database button).",
        "db_geen_pymysql": "The database library (PyMySQL) is missing. Run run.bat again to install it.",
        "db_verbind_fout": "Could not perform the operation:\n\n{fout}",
        "db_tabellen_knop": "Tables / fields...",
        "db_kies_database": "Pick a database in the list first.",
        "veld_naam": "field name",
        "veld_lengte": "length",
        "veld_pk": "key",
        "veld_auto": "auto-nr",
        "veld_nn": "required",
        "annuleer": "Cancel",
        "vb_titel": "Create new table",
        "vb_tabelnaam": "Table name:",
        "vb_velden": "Fields (columns)",
        "vb_veld_toevoegen": "+ Add field",
        "vb_voorbeeld": "Preview (the SQL that will run)",
        "vb_maak": "Create table",
        "vb_naam_leeg": "Enter a valid table name.",
        "vt_titel": "Add field",
        "td_titel": "Tables in {db}",
        "td_tabellen": "Tables",
        "td_nieuwe_tabel": "New table...",
        "td_verwijder_tabel": "Delete table",
        "td_velden": "Fields of the table",
        "td_veld_toevoegen": "Add field...",
        "td_veld_aanpassen": "Edit field...",
        "td_veld_verwijderen": "Delete field",
        "td_geen_velden": "(this table has no fields yet)",
        "td_kies_tabel": "Pick a table first.",
        "td_verwijder_bevestig": "Really delete table {naam}? All data in it will be lost.",
        "td_veld_bevestig": "Delete field {naam}? The data in that field will be lost.",
        "ssl_intro": "Give your site https (the padlock). For your own PC or network DraveServer makes a certificate itself. With a domain you can point to an existing certificate (automatic Let's Encrypt comes next version).",
        "ssl_site": "Site:",
        "ssl_status_uit": "https is OFF for this site.",
        "ssl_status_self": "https ON - own certificate (self-signed).",
        "ssl_status_bestaand": "https ON - your own certificate files.",
        "ssl_cert_dagen": "Certificate expires in {dagen} days (on {datum}).",
        "ssl_cert_verlopen": "WARNING: certificate has EXPIRED - renew it.",
        "ssl_cert_binnenkort": "Note: certificate expires soon ({dagen} days).",
        "ssl_self_maken": "Make certificate yourself (own PC/network)",
        "ssl_bestaand": "Choose existing certificate...",
        "ssl_uit": "Turn https off",
        "ssl_letsencrypt": "Let's Encrypt (next version)",
        "ssl_letsencrypt_info": "Getting a free Let's Encrypt certificate automatically comes next version. You only fill in your domain and email; DraveServer does the rest (no Certbot knowledge needed).",
        "ssl_geen_sites": "Add a site first (Sites tab).",
        "ssl_self_klaar": "Certificate made and https enabled. Restart the server to apply.",
        "ssl_self_uitleg": "A self-made certificate shows a browser warning (Not secure); that is normal for your own use - choose 'Proceed anyway'. For a truly trusted padlock you need a domain + Let's Encrypt.",
        "ssl_cert_titel": "Choose certificate file (.crt or .pem)",
        "ssl_key_titel": "Choose key file (.key or .pem)",
        "ssl_bestaand_klaar": "Certificate set and https enabled. Restart the server.",
        "ssl_uit_klaar": "https turned off for this site. Restart the server.",
        "ssl_verwijderen": "Remove certificate",
        "ssl_geen_cert": "This site has no certificate.",
        "ssl_verwijder_bevestig": "Remove the certificate for {site} and turn https off?",
        "ssl_verwijder_klaar": "Certificate removed and https turned off. Restart the server.",
        "le_intro": "DraveServer gets a free, trusted certificate from Let's Encrypt - no Certbot needed. Fill in your domain and email and click Get.",
        "le_domein": "Domain (e.g. mysite.com)",
        "le_email": "Email (for expiry notices)",
        "le_staging": "Use staging (optional) - gives an UNTRUSTED test certificate",
        "le_eisen": "Required: your domain must point to this PC, port 80 must be reachable from outside, and the server must be running. You get a real certificate by default; staging is only for trying without hitting the limit.",
        "le_ophalen": "Get certificate",
        "le_domein_leeg": "Enter a domain.",
        "le_server_uit": "The server does not seem to be running. Let's Encrypt must reach your site over port 80. Continue anyway?",
        "le_gelukt": "Success! Close this window to enable https.",
        "le_klaar": "Let's Encrypt certificate set and https enabled. Restart the server.",
        "le_vernieuwd": "Let's Encrypt certificate renewed automatically. Restart the server to apply.",
        "ond_intro": "DraveServer can download and set up the web server (Apache) and PHP for you - nothing complicated needed. Everything stays portable next to the app.",
        "ond_apache_kop": "Apache (the web server)",
        "ond_apache_aan": "Installed: {pad}",
        "ond_apache_uit": "Not installed yet.",
        "ond_apache_auto": "Download automatically",
        "ond_apache_zip": "I already have an Apache zip...",
        "ond_apache_zip_titel": "Choose Apache zip",
        "ond_php_kop": "PHP (for .php websites)",
        "ond_php_aan_status": "Installed: version {versie}",
        "ond_php_actief": "Active version:", "ond_php_gebruik": "Use this version",
        "ond_php_gewisseld": "PHP version changed to {versie}.",
        "ond_php_gewisseld_herstart": "PHP version changed to {versie}. The server has restarted.",
        "ond_php_uit": "Not installed yet.",
        "ond_php_versies_laden": "Load available versions",
        "ond_php_versie": "Version:",
        "ond_php_install": "Download and set up",
        "ond_php_inschakelen": "Enable PHP (make .php files work)",
        "ond_php_testen": "Test PHP",
        "php_test_geen_site": "Add a site first (Sites tab).",
        "php_test_start": "Test page placed. Start the server, then open:\n{url}",
        "ond_geen_versies": "Could not fetch PHP versions (no internet?). Try again.",
        "ond_bezig_versies": "Fetching PHP versions...",
        "ond_bezig_download": "Downloading and extracting... {mb} MB",
        "ond_klaar_apache": "Apache downloaded and set up.",
        "ond_klaar_php": "PHP {versie} downloaded and enabled.",
        "ond_fout": "Failed: {fout}",
        "ond_apache_geen_httpd": "This zip has no httpd.exe.",
        "ond_let_op": "Note: PHP must have the same VS version as Apache (e.g. both VS17), and you need the Microsoft Visual C++ Redistributable (2015-2022). DraveServer picks a matching version by default.",
        "sd_uitleg_server": "For your own PC you can leave 'localhost'. If you "
                            "have a domain (e.g. mysite.com), enter it here.",
        "welkom_titel": "Welcome to DraveServer",
        "welkom_wat": "What is this?",
        "welkom_wat_t": "A web server turns a folder on your PC into a real "
                        "website you can open in a browser - at home or, with a "
                        "domain, for the whole world. DraveServer handles the hard "
                        "part: in the Components tab it downloads Apache and PHP "
                        "itself, and writes all configuration automatically.",
        "welkom_hoe": "In three steps",
        "welkom_stap1": "1. 'Sites' tab: add your website (a name and the folder "
                        "with your files).",
        "welkom_stap2": "2. 'Server' tab: click 'Start server'.",
        "welkom_stap3": "3. Click 'Open in browser' - your site is live!",
        "welkom_veilig": "Safe? DraveServer works locally. Your antivirus may warn "
                         "about a new program (false alarm); see the Quick guide.",
        "welkom_niet_meer": "Do not show this window at startup",
        "welkom_start": "Get started",
        "over_tekst": "DraveServer - simple web server in the Dravenlock style. "
                      "Local, offline, accessible, donationware.\n\n"
                      "Version {versie}\nContact: {contact}\nDonate: {donatie}",
    },
}


SNELGIDS_NL = """
<h2>DraveServer - Snelgids</h2>
<p>DraveServer maakt van je pc een echte webserver - met website, https en database -
en regelt het ingewikkelde (de configuratie) zelf. Jij vult alleen simpele velden in.</p>
<h3>1. Onderdelen ophalen</h3>
<p>Tabblad <b>Onderdelen</b>: DraveServer downloadt en installeert zelf <b>Apache</b>
(de webserver) en <b>PHP</b> - jij kiest alleen de PHP-versie. Heb je al Apache of
XAMPP, dan vindt DraveServer die ook.</p>
<h3>2. Site toevoegen en starten</h3>
<ul>
<li><b>Sites</b> -&gt; <b>Site toevoegen</b>. Geef een naam; laat het mapje leeg, dan
maakt DraveServer er zelf een in zijn <code>htdocs</code> (portable). Adres
<code>localhost</code> is voor je eigen pc; een domein voor de buitenwereld.</li>
<li><b>Server</b> -&gt; <b>Server starten</b>, daarna <b>Openen in browser</b>.</li>
</ul>
<h3>3. Website bouwen (optioneel)</h3>
<p>Op <b>Sites</b> -&gt; <b>Website bouwen...</b> opent de ingebouwde <b>visuele editor</b>:
sleep blokken op de pagina, geef ze stijl, gebruik eigen CSS, bibliotheken (jQuery,
Bootstrap...) en bekijk de code. Klik <b>Opslaan / exporteren</b> en er komt een
complete <b>HTML5 + PWA</b>-site in je site-map (installeerbaar op telefoon).</p>
<h3>4. https (het slotje)</h3>
<p>Tabblad <b>Beveiliging (https)</b>: kies per site <b>zelf een certificaat</b>
(eigen pc/netwerk), een <b>bestaand</b> certificaat, of <b>Let's Encrypt</b> (gratis,
vertrouwd - vul domein + e-mail in, DraveServer haalt en vernieuwt het). Geen
Certbot-kennis nodig.</p>
<h3>5. Database</h3>
<p>Tabblad <b>Database</b>: DraveServer downloadt <b>MariaDB</b> zelf, start hem, en
je stelt een root-wachtwoord in. Maak databases aan; via <b>Tabellen / velden...</b>
(of dubbelklik) bouw je tabellen met velden (de veld-bouwer).</p>
<h3>6. Poorten / IP</h3>
<p>Tabblad <b>Poorten / IP</b>: zie je interne en externe IP, en stel de poorten in
(HTTP per site, HTTPS, MariaDB). <b>Controleren</b> laat zien of een poort vrij of
bezet is.</p>
<h3>Goed om te weten</h3>
<ul>
<li>DraveServer raakt je eigen Apache-instellingen <b>niet</b> aan: het draait met een
eigen kopie van de configuratie.</li>
<li>Draait er al iets op poort 80 (XAMPP, Skype)? Stop dat, of geef de site een andere
poort.</li>
<li>Voor de buitenwereld: een <b>domein</b> dat naar je pc wijst en poort 80 (en 443)
bereikbaar. Antivirus/SmartScreen kan waarschuwen omdat het programma niet
ondertekend is - <b>Meer informatie -&gt; Toch uitvoeren</b>.</li>
</ul>
<p>Donatie (vrijwillig): <b>paypal.me/roger076</b> &middot; Contact:
service@dravenlock.nl</p>
"""

SNELGIDS_EN = """
<h2>DraveServer - Quick guide</h2>
<p>DraveServer turns your PC into a real web server - with website, https and database
- and writes the complicated part (the configuration) itself. You only fill in simple
fields.</p>
<h3>1. Get the components</h3>
<p><b>Components</b> tab: DraveServer downloads and installs <b>Apache</b> (the web
server) and <b>PHP</b> for you - you only pick the PHP version. If you already have
Apache or XAMPP, DraveServer finds it too.</p>
<h3>2. Add a site and start</h3>
<ul>
<li><b>Sites</b> -&gt; <b>Add site</b>. Give it a name; leave the folder empty and
DraveServer makes one in its <code>htdocs</code> (portable). Address
<code>localhost</code> is for your own PC; a domain for the outside world.</li>
<li><b>Server</b> -&gt; <b>Start server</b>, then <b>Open in browser</b>.</li>
</ul>
<h3>3. Build a website (optional)</h3>
<p>On <b>Sites</b> -&gt; <b>Build website...</b> opens the built-in <b>visual editor</b>:
drag blocks onto the page, style them, use custom CSS, libraries (jQuery,
Bootstrap...) and view the code. Click <b>Save / export</b> and a complete
<b>HTML5 + PWA</b> site is written to your site folder (installable on phone).</p>
<h3>4. https (the padlock)</h3>
<p><b>Security (https)</b> tab: per site choose a <b>self-made</b> certificate (own
PC/network), an <b>existing</b> one, or <b>Let's Encrypt</b> (free, trusted - enter
domain + email, DraveServer gets and renews it). No Certbot knowledge needed.</p>
<h3>5. Database</h3>
<p><b>Database</b> tab: DraveServer downloads <b>MariaDB</b> itself, starts it, and you
set a root password. Create databases; via <b>Tables / fields...</b> (or double-click)
you build tables with fields (the field builder).</p>
<h3>6. Ports / IP</h3>
<p><b>Ports / IP</b> tab: see your internal and external IP, and set the ports (HTTP
per site, HTTPS, MariaDB). <b>Check</b> shows whether a port is free or busy.</p>
<h3>Good to know</h3>
<ul>
<li>DraveServer does <b>not</b> touch your own Apache settings: it runs with its own
copy of the configuration.</li>
<li>Is something already using port 80 (XAMPP, Skype)? Stop it, or give the site
another port.</li>
<li>For the outside world: a <b>domain</b> pointing to your PC and port 80 (and 443)
reachable. Antivirus/SmartScreen may warn because the program is unsigned -
<b>More info -&gt; Run anyway</b>.</li>
</ul>
<p>Donate (voluntary): <b>paypal.me/roger076</b> &middot; Contact:
service@dravenlock.nl</p>
"""


def STIJL():
    return """
* { font-size: 15px; }
QMainWindow, QWidget { background: %(bg)s; color: %(text)s; }
QLabel { color: %(text)s; }
QLabel#titel { font-size: 26px; font-weight: bold; }
QLabel#ondertitel { color: %(muted)s; }
QLabel#uitleg { color: %(muted)s; }
QLabel#kop { font-size: 18px; font-weight: bold; }
QLabel#statusaan { color: %(goed)s; font-weight: bold; font-size: 18px; }
QLabel#statusuit { color: %(muted)s; font-weight: bold; font-size: 18px; }
QLabel#strook { background: %(panel2)s; color: %(warn)s; border: 1px solid %(line)s;
    border-radius: 8px; padding: 8px 10px; }
QLabel#info { background: %(panel2)s; color: %(text)s; border: 1px solid %(line)s;
    border-radius: 8px; padding: 8px 10px; }
QWidget#opstartbalk { background: %(accent)s; border-radius: 10px; }
QLabel#opstarttekst { color: #0e0e11; font-size: 17px; font-weight: bold; background: transparent; }
QProgressBar#opstartbar { background: #4f7fb3; border: none; border-radius: 4px; max-height: 6px; }
QProgressBar#opstartbar::chunk { background: #0e0e11; border-radius: 4px; }
QPushButton { background: %(panel2)s; color: %(text)s; border: 1px solid %(line)s;
    border-radius: 8px; padding: 8px 14px; }
QPushButton:hover { border-color: %(accent)s; }
QPushButton:disabled { color: %(muted)s; }
QPushButton#primair { background: %(accent)s; color: #0e0e11; font-weight: bold; border: none; }
QPushButton#primair:hover { background: #84b4e0; }
QPushButton#stop { background: %(warn)s; color: #0e0e11; font-weight: bold; border: none; }
QPushButton#stop:hover { background: #e0a085; }
QLineEdit, QSpinBox { background: %(panel2)s; color: %(text)s; border: 1px solid %(line)s;
    border-radius: 8px; padding: 8px 10px;
    selection-background-color: %(accent)s; selection-color: #0e0e11; }
QLineEdit:focus, QSpinBox:focus { border-color: %(accent)s; }
QListWidget { background: %(panel)s; color: %(text)s; border: 1px solid %(line)s;
    border-radius: 8px; outline: none; }
QListWidget::item { padding: 8px 6px; }
QListWidget::item:selected { background: %(accent)s; color: #0e0e11; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 18px; height: 18px; border: 1px solid %(accent)s;
    border-radius: 4px; background: %(panel2)s; }
QCheckBox::indicator:checked { background: %(accent)s; border-color: %(accent)s; }
QTabWidget::pane { border: 1px solid %(line)s; border-radius: 8px; }
QTabBar::tab { background: %(panel2)s; color: %(muted)s; padding: 8px 16px;
    border: 1px solid %(line)s; border-bottom: none;
    border-top-left-radius: 8px; border-top-right-radius: 8px; }
QTabBar::tab:selected { background: %(panel)s; color: %(text)s; }
QTextBrowser { background: %(bg)s; color: %(text)s; border: 1px solid %(line)s;
    border-radius: 8px; }
QComboBox { background: %(panel2)s; color: %(text)s; border: 1px solid %(line)s;
    border-radius: 6px; padding: 6px 8px; }
QComboBox QAbstractItemView { background: %(panel2)s; color: %(text)s;
    selection-background-color: %(accent)s; selection-color: #0e0e11; }
QStatusBar { background: %(panel)s; color: %(muted)s; }
QMenuBar { background: %(panel)s; color: %(text)s; }
QMenuBar::item:selected { background: %(panel2)s; }
QMenu { background: %(panel2)s; color: %(text)s; border: 1px solid %(line)s; }
QMenu::item:selected { background: %(accent)s; color: #0e0e11; }
QScrollBar:vertical { background: %(panel)s; width: 13px; margin: 0; border: none; }
QScrollBar::handle:vertical { background: %(line)s; min-height: 30px;
    border-radius: 6px; margin: 2px; }
QScrollBar::handle:vertical:hover { background: %(accent)s; }
QScrollBar:horizontal { background: %(panel)s; height: 13px; margin: 0; border: none; }
QScrollBar::handle:horizontal { background: %(line)s; min-width: 30px;
    border-radius: 6px; margin: 2px; }
QScrollBar::handle:horizontal:hover { background: %(accent)s; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; background: none; border: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QScrollBar::corner, QAbstractScrollArea::corner { background: %(panel)s; }
QScrollArea { border: none; background: %(bg)s; }
""" % {"bg": BG, "panel": PANEL, "panel2": PANEL2, "text": TEXT, "muted": MUTED,
       "accent": ACCENT, "line": LINE, "warn": WARN, "goed": GOED}


def _pas_palet_toe(app):
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(BG))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Base, QColor(PANEL))
    pal.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Button, QColor(PANEL2))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(BG))
    app.setPalette(pal)


# ---- dialogen ----
class Dialoog(QDialog):
    """QDialog die standaard maximaliseerbaar is (schermvullend kan) en netjes
    op het hoofdvenster/scherm gecentreerd opent."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._gecentreerd = False
        try:
            self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
            self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)
        except Exception:
            pass

    def showEvent(self, e):
        super().showEvent(e)
        if self._gecentreerd:
            return
        self._gecentreerd = True
        try:
            par = self.parent()
            if par is not None and par.isVisible():
                g = par.frameGeometry()
            else:
                g = self.screen().availableGeometry()
            self.move(g.center().x() - self.width() // 2,
                      g.center().y() - self.height() // 2)
        except Exception:
            pass


class SnelgidsDialoog(Dialoog):
    def __init__(self, venster):
        super().__init__(venster)
        self.setWindowTitle(venster.t("snelgids"))
        self.resize(660, 600)
        lay = QVBoxLayout(self)
        b = QTextBrowser()
        b.setOpenExternalLinks(True)
        b.setHtml(SNELGIDS_NL if venster.taal == "nl" else SNELGIDS_EN)
        lay.addWidget(b)


class OverDialoog(Dialoog):
    def __init__(self, venster):
        super().__init__(venster)
        self.setWindowTitle(venster.t("over"))
        self.resize(440, 240)
        lay = QVBoxLayout(self)
        lab = QLabel(venster.t("over_tekst").format(
            versie=APP_VERSIE, contact=CONTACT, donatie=DONATIE_URL))
        lab.setWordWrap(True)
        lay.addWidget(lab)
        knop = QPushButton("\u2665 " + venster.t("donatie"))
        knop.setObjectName("primair")
        knop.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(DONATIE_URL)))
        lay.addWidget(knop)


class LinksDialoog(Dialoog):
    def __init__(self, venster):
        super().__init__(venster)
        self.setWindowTitle(venster.t("downloads_titel"))
        self.resize(520, 260)
        lay = QVBoxLayout(self)
        intro = QLabel(venster.t("downloads_intro"))
        intro.setObjectName("uitleg"); intro.setWordWrap(True)
        lay.addWidget(intro)
        lay.addSpacing(6)
        for label, url in DOWNLOADS:
            knop = QPushButton(label)
            knop.clicked.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            lay.addWidget(knop)
        lay.addStretch(1)
        sluit = QPushButton(venster.t("sluit"))
        sluit.clicked.connect(self.accept)
        lay.addWidget(sluit)


class InstellingenDialoog(Dialoog):
    def __init__(self, venster):
        super().__init__(venster)
        self.v = venster
        self.setWindowTitle(venster.t("instellingen"))
        self.resize(500, 260)
        lay = QFormLayout(self)
        self.taal = QComboBox()
        self.taal.addItem(venster.t("taal_auto"), "auto")
        self.taal.addItem("Nederlands", "nl")
        self.taal.addItem("English", "en")
        self.taal.setCurrentIndex({"auto": 0, "nl": 1, "en": 2}.get(
            venster.cfg.get("taal", "auto"), 0))
        lay.addRow(venster.t("taal"), self.taal)
        self.chk_auto = QCheckBox(venster.t("auto_start_uitleg"))
        self.chk_auto.setChecked(bool(venster.cfg.get("auto_start", True)))
        lay.addRow(venster.t("auto_start"), self.chk_auto)
        self.chk_tray = QCheckBox(venster.t("set_systeemvak_uitleg"))
        self.chk_tray.setChecked(bool(venster.cfg.get("naar_systeemvak", False)))
        lay.addRow(venster.t("set_systeemvak"), self.chk_tray)
        self.chk_win = QCheckBox(venster.t("set_meestarten_uitleg"))
        self.chk_win.setChecked(bool(venster.cfg.get("start_met_windows", False)))
        self.chk_win.setEnabled(WINDOWS)
        lay.addRow(venster.t("set_meestarten"), self.chk_win)
        kn = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                              QDialogButtonBox.StandardButton.Cancel)
        kn.button(QDialogButtonBox.StandardButton.Save).setText(venster.t("opslaan"))
        kn.button(QDialogButtonBox.StandardButton.Cancel).setText(venster.t("annuleren"))
        kn.accepted.connect(self._ok)
        kn.rejected.connect(self.reject)
        lay.addRow(kn)

    def _ok(self):
        self.v.cfg["taal"] = self.taal.currentData()
        self.v.cfg["auto_start"] = self.chk_auto.isChecked()
        self.v.cfg["naar_systeemvak"] = self.chk_tray.isChecked()
        self.v.cfg["start_met_windows"] = self.chk_win.isChecked()
        zet_autostart_windows(self.chk_win.isChecked())
        bewaar_config(self.v.cfg)
        self.accept()


class WelkomDialoog(Dialoog):
    def __init__(self, venster):
        super().__init__(venster)
        self.v = venster
        self.setWindowTitle(venster.t("welkom_titel"))
        self.resize(560, 560)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        kop = QHBoxLayout()
        lg = QLabel()
        p = _bundel_bestand("logo.png")
        if os.path.exists(p):
            pm = QPixmap(p)
            if not pm.isNull():
                lg.setPixmap(pm.scaled(QSize(56, 56),
                             Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation))
        kop.addWidget(lg)
        titel = QLabel(venster.t("welkom_titel")); titel.setObjectName("titel")
        kop.addWidget(titel); kop.addStretch(1)
        lay.addLayout(kop)
        for kop_sleutel, tekst_sleutel in (("welkom_wat", "welkom_wat_t"),):
            k = QLabel(venster.t(kop_sleutel)); k.setObjectName("kop")
            lay.addWidget(k)
            t = QLabel(venster.t(tekst_sleutel)); t.setWordWrap(True)
            lay.addWidget(t)
        k2 = QLabel(venster.t("welkom_hoe")); k2.setObjectName("kop")
        lay.addWidget(k2)
        for s in ("welkom_stap1", "welkom_stap2", "welkom_stap3"):
            lab = QLabel(venster.t(s)); lab.setWordWrap(True)
            lay.addWidget(lab)
        veilig = QLabel(venster.t("welkom_veilig"))
        veilig.setObjectName("uitleg"); veilig.setWordWrap(True)
        lay.addWidget(veilig)
        lay.addStretch(1)
        self.chk = QCheckBox(venster.t("welkom_niet_meer"))
        lay.addWidget(self.chk)
        rij = QHBoxLayout(); rij.addStretch(1)
        start = QPushButton(venster.t("welkom_start")); start.setObjectName("primair")
        start.clicked.connect(self.accept)
        rij.addWidget(start)
        lay.addLayout(rij)

    def accept(self):
        if self.chk.isChecked():
            self.v.cfg["toon_welkom"] = False
            bewaar_config(self.v.cfg)
        super().accept()


class SiteDialoog(Dialoog):
    def __init__(self, venster, site=None):
        super().__init__(venster)
        self.v = venster
        self.setWindowTitle(venster.t("sd_titel"))
        self.resize(560, 360)
        site = site or {}
        self._bestaande_map = site.get("map", "")
        lay = QFormLayout(self)
        self.naam = QLineEdit(site.get("naam", ""))
        self.naam.textChanged.connect(self._toon_map)
        lay.addRow(venster.t("sd_naam"), self.naam)
        # geen mapkeuze meer: portable -> automatisch in htdocs
        self.lbl_map = QLabel("")
        self.lbl_map.setObjectName("uitleg"); self.lbl_map.setWordWrap(True)
        lay.addRow("", self.lbl_map)
        self.server = QLineEdit(site.get("servernaam", "localhost"))
        lay.addRow(venster.t("sd_server"), self.server)
        uit = QLabel(venster.t("sd_uitleg_server"))
        uit.setObjectName("uitleg"); uit.setWordWrap(True)
        lay.addRow("", uit)
        self.poort = QSpinBox(); self.poort.setRange(1, 65535)
        self.poort.setValue(int(site.get("poort", 80)))
        lay.addRow(venster.t("sd_poort"), self.poort)
        self.aan = QCheckBox(venster.t("sd_aan"))
        self.aan.setChecked(site.get("aan", True))
        lay.addRow("", self.aan)
        self.test = QCheckBox(venster.t("sd_test"))
        self.test.setChecked(not site)   # standaard aan bij nieuw
        lay.addRow("", self.test)
        kn = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                              QDialogButtonBox.StandardButton.Cancel)
        kn.button(QDialogButtonBox.StandardButton.Save).setText(venster.t("opslaan"))
        kn.button(QDialogButtonBox.StandardButton.Cancel).setText(venster.t("annuleren"))
        kn.accepted.connect(self._ok)
        kn.rejected.connect(self.reject)
        lay.addRow(kn)
        self._toon_map()

    def _doelmap(self, naam):
        if self._bestaande_map:
            return self._bestaande_map
        veilig = "".join(c if c.isalnum() or c in "-_" else "_"
                         for c in naam.strip())[:40] or "site"
        return os.path.join(HTDOCS, veilig)

    def _toon_map(self, *_):
        pad = self._doelmap(self.naam.text())
        self.lbl_map.setText(self.v.t("sd_map_auto").format(map=pad))

    def _ok(self):
        naam = self.naam.text().strip()
        if not naam:
            QMessageBox.information(self, APP_NAAM, self.v.t("sd_naam_leeg"))
            return
        mappad = self._doelmap(naam)
        try:
            os.makedirs(mappad, exist_ok=True)
        except OSError:
            pass
        self.resultaat = {
            "naam": naam,
            "map": mappad,
            "servernaam": self.server.text().strip() or "localhost",
            "poort": int(self.poort.value()),
            "aan": self.aan.isChecked(),
        }
        if self.test.isChecked():
            maak_teststartpagina(self.resultaat)
        self.accept()


class ConfigDialoog(Dialoog):
    def __init__(self, venster, tekst):
        super().__init__(venster)
        self.setWindowTitle(venster.t("config_tonen"))
        self.resize(680, 560)
        lay = QVBoxLayout(self)
        b = QTextBrowser()
        b.setPlainText(tekst)
        lay.addWidget(b)


class LetsEncryptDialoog(Dialoog):
    def __init__(self, venster, site):
        super().__init__(venster)
        self.v = venster
        self.site = site
        self.gelukt = False
        self.setWindowTitle("Let's Encrypt")
        self.resize(580, 500)
        domein = site.get("servernaam", "")
        veilig = "".join(c if c.isalnum() or c in "-_." else "_"
                         for c in domein)[:50] or "site"
        self.cert_pad = os.path.join(CERT_MAP, veilig + "-le.crt")
        self.key_pad = os.path.join(CERT_MAP, veilig + "-le.key")
        lay = QVBoxLayout(self)
        intro = QLabel(venster.t("le_intro"))
        intro.setObjectName("uitleg"); intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QFormLayout()
        self.domein = QLineEdit(domein)
        form.addRow(venster.t("le_domein"), self.domein)
        self.email = QLineEdit(site.get("ssl_email", ""))
        form.addRow(venster.t("le_email"), self.email)
        lay.addLayout(form)
        self.staging = QCheckBox(venster.t("le_staging"))
        self.staging.setChecked(False)
        lay.addWidget(self.staging)
        eisen = QLabel(venster.t("le_eisen"))
        eisen.setObjectName("uitleg"); eisen.setWordWrap(True)
        lay.addWidget(eisen)
        self.knop = QPushButton(venster.t("le_ophalen"))
        self.knop.setObjectName("primair")
        self.knop.clicked.connect(self._ophalen)
        lay.addWidget(self.knop)
        self.log = QTextBrowser()
        lay.addWidget(self.log, 1)
        sluit = QPushButton(venster.t("sluit"))
        sluit.clicked.connect(self.accept)
        lay.addWidget(sluit)

    def _log(self, t):
        self.log.append(t)

    def _ophalen(self):
        dom = self.domein.text().strip()
        if not dom:
            QMessageBox.information(self, APP_NAAM, self.v.t("le_domein_leeg"))
            return
        if not self.v.server.draait():
            if QMessageBox.question(
                    self, APP_NAAM, self.v.t("le_server_uit")
            ) != QMessageBox.StandardButton.Yes:
                return
        self.knop.setEnabled(False)
        self._t = LetsEncryptThread(
            dom, self.email.text().strip(), self.site.get("map", ""),
            self.cert_pad, self.key_pad, self.staging.isChecked())
        self._t.logregel.connect(self._log)
        self._t.klaar.connect(self._klaar)
        self._t.start()

    def _klaar(self, ok, fout):
        self.knop.setEnabled(True)
        if ok:
            self.gelukt = True
            self.site["ssl_staging"] = self.staging.isChecked()
            self.site["ssl_email"] = self.email.text().strip()
            self._log(self.v.t("le_gelukt"))
        else:
            self._log("FOUT: " + fout)


class KolomRij(QWidget):
    """Een rij in de veld-bouwer: naam, type, lengte, opties, verwijderknop."""
    verwijderd = pyqtSignal(object)
    gewijzigd = pyqtSignal()

    def __init__(self, vert):
        super().__init__()
        self.vert = vert
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        self.naam = QLineEdit(); self.naam.setPlaceholderText(vert("veld_naam"))
        lay.addWidget(self.naam, 3)
        self.type = QComboBox(); self.type.addItems(DB_TYPES)
        self.type.setCurrentText("VARCHAR")
        lay.addWidget(self.type, 2)
        self.lengte = QLineEdit("255")
        self.lengte.setPlaceholderText(vert("veld_lengte"))
        self.lengte.setMaximumWidth(80)
        lay.addWidget(self.lengte)
        self.pk = QCheckBox(vert("veld_pk")); lay.addWidget(self.pk)
        self.auto = QCheckBox(vert("veld_auto")); lay.addWidget(self.auto)
        self.nn = QCheckBox(vert("veld_nn")); lay.addWidget(self.nn)
        x = QPushButton("X"); x.setMaximumWidth(34); x.setObjectName("stop")
        x.clicked.connect(lambda: self.verwijderd.emit(self))
        lay.addWidget(x)
        self.type.currentTextChanged.connect(self._type_veranderd)
        for w in (self.naam, self.lengte):
            w.textChanged.connect(lambda *_: self.gewijzigd.emit())
        for c in (self.pk, self.auto, self.nn):
            c.toggled.connect(lambda *_: self.gewijzigd.emit())
        self._type_veranderd(self.type.currentText())

    def _type_veranderd(self, t):
        self.lengte.setEnabled(t in ("VARCHAR", "DECIMAL"))
        if t == "DECIMAL" and self.lengte.text() == "255":
            self.lengte.setText("10,2")
        self.gewijzigd.emit()

    def kolom(self):
        return {"naam": self.naam.text().strip(),
                "type": self.type.currentText(),
                "lengte": self.lengte.text().strip(),
                "pk": self.pk.isChecked(),
                "auto": self.auto.isChecked(),
                "nn": self.nn.isChecked()}


class VeldBouwerDialoog(Dialoog):
    """Nieuwe tabel maken met velden via [+]."""
    def __init__(self, venster, database, wachtwoord):
        super().__init__(venster)
        self.v = venster
        self.database = database
        self.wachtwoord = wachtwoord
        self.gemaakt = False
        self.rijen = []
        self.setWindowTitle(venster.t("vb_titel"))
        self.resize(860, 600)
        lay = QVBoxLayout(self)
        rij = QHBoxLayout()
        rij.addWidget(QLabel(venster.t("vb_tabelnaam")))
        self.tabelnaam = QLineEdit()
        self.tabelnaam.textChanged.connect(self._preview)
        rij.addWidget(self.tabelnaam, 1)
        lay.addLayout(rij)
        # koprij
        kop = QLabel(venster.t("vb_velden")); kop.setObjectName("kop")
        lay.addWidget(kop)
        self.vakje = QWidget(); self.vakje_lay = QVBoxLayout(self.vakje)
        self.vakje_lay.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setWidget(self.vakje)
        lay.addWidget(scroll, 1)
        plus = QPushButton(venster.t("vb_veld_toevoegen"))
        plus.clicked.connect(lambda: self._voeg_rij())
        lay.addWidget(plus)
        prev = QLabel(venster.t("vb_voorbeeld")); prev.setObjectName("kop")
        lay.addWidget(prev)
        self.sql = QTextBrowser(); self.sql.setMaximumHeight(120)
        lay.addWidget(self.sql)
        knoppen = QHBoxLayout()
        maak = QPushButton(venster.t("vb_maak")); maak.setObjectName("primair")
        maak.clicked.connect(self._maak)
        annu = QPushButton(venster.t("annuleer")); annu.clicked.connect(self.reject)
        knoppen.addStretch(1); knoppen.addWidget(annu); knoppen.addWidget(maak)
        lay.addLayout(knoppen)
        # begin met een id-veld en een tekstveld
        self._voeg_rij(naam="id", type_="INT", pk=True, auto=True, nn=True)
        self._voeg_rij(naam="naam", type_="VARCHAR")

    def _voeg_rij(self, naam="", type_="VARCHAR", pk=False, auto=False, nn=False):
        r = KolomRij(self.v.t)
        r.naam.setText(naam); r.type.setCurrentText(type_)
        r.pk.setChecked(pk); r.auto.setChecked(auto); r.nn.setChecked(nn)
        r.verwijderd.connect(self._verwijder_rij)
        r.gewijzigd.connect(self._preview)
        self.rijen.append(r)
        self.vakje_lay.addWidget(r)
        self._preview()

    def _verwijder_rij(self, r):
        if r in self.rijen:
            self.rijen.remove(r)
            r.setParent(None)
            self._preview()

    def _kolommen(self):
        return [r.kolom() for r in self.rijen]

    def _preview(self):
        naam = self.tabelnaam.text().strip() or "tabel"
        self.sql.setPlainText(bouw_create_table(naam, self._kolommen()))

    def _maak(self):
        naam = self.tabelnaam.text().strip()
        if not _veilige_naam(naam):
            QMessageBox.information(self, APP_NAAM, self.v.t("vb_naam_leeg"))
            return
        try:
            ok, fout = db_maak_tabel(self.database, naam, self._kolommen(),
                                     self.wachtwoord)
        except Exception as e:
            self.v._db_fout_tonen(e)
            return
        if not ok:
            QMessageBox.warning(self, APP_NAAM,
                                self.v.t("db_verbind_fout").format(fout=fout))
            return
        self.gemaakt = True
        self.accept()


class VeldToevoegenDialoog(Dialoog):
    """Een veld toevoegen of aanpassen (KolomRij in een venster)."""
    def __init__(self, venster, titel=None, kolom=None):
        super().__init__(venster)
        self.setWindowTitle(titel or venster.t("vt_titel"))
        self.resize(820, 150)
        lay = QVBoxLayout(self)
        self.rij = KolomRij(venster.t)
        if kolom:
            self.rij.naam.setText(kolom.get("naam", ""))
            self.rij.type.setCurrentText(kolom.get("type", "VARCHAR"))
            if kolom.get("lengte"):
                self.rij.lengte.setText(kolom["lengte"])
            self.rij.nn.setChecked(bool(kolom.get("nn")))
        lay.addWidget(self.rij)
        knoppen = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        knoppen.accepted.connect(self.accept)
        knoppen.rejected.connect(self.reject)
        lay.addWidget(knoppen)

    def kolom(self):
        return self.rij.kolom()


class TabellenDialoog(Dialoog):
    """Tabellen van een database beheren + velden bekijken/toevoegen/wissen."""
    def __init__(self, venster, database, wachtwoord):
        super().__init__(venster)
        self.v = venster
        self.database = database
        self.wachtwoord = wachtwoord
        self.setWindowTitle(venster.t("td_titel").format(db=database))
        self.resize(760, 520)
        lay = QHBoxLayout(self)
        # links: tabellen
        links = QVBoxLayout()
        links.addWidget(QLabel(venster.t("td_tabellen")))
        self.lijst_tab = QListWidget()
        self.lijst_tab.currentItemChanged.connect(lambda *_: self._toon_kolommen())
        links.addWidget(self.lijst_tab, 1)
        b_nieuw = QPushButton(venster.t("td_nieuwe_tabel"))
        b_nieuw.setObjectName("primair"); b_nieuw.clicked.connect(self._nieuwe_tabel)
        links.addWidget(b_nieuw)
        b_verw = QPushButton(venster.t("td_verwijder_tabel"))
        b_verw.clicked.connect(self._verwijder_tabel)
        links.addWidget(b_verw)
        lay.addLayout(links, 1)
        # rechts: velden
        rechts = QVBoxLayout()
        rechts.addWidget(QLabel(venster.t("td_velden")))
        self.lijst_kol = QListWidget()
        rechts.addWidget(self.lijst_kol, 1)
        b_vt = QPushButton(venster.t("td_veld_toevoegen"))
        b_vt.clicked.connect(self._veld_toevoegen)
        rechts.addWidget(b_vt)
        b_va = QPushButton(venster.t("td_veld_aanpassen"))
        b_va.clicked.connect(self._veld_aanpassen)
        rechts.addWidget(b_va)
        b_vw = QPushButton(venster.t("td_veld_verwijderen"))
        b_vw.clicked.connect(self._veld_verwijderen)
        rechts.addWidget(b_vw)
        lay.addLayout(rechts, 1)
        self._ververs()

    def _ververs(self):
        self.lijst_tab.clear()
        try:
            tabellen = db_lijst_tabellen(self.database, self.wachtwoord)
        except Exception as e:
            self.v._db_fout_tonen(e)
            return
        for t in tabellen:
            self.lijst_tab.addItem(t)
        if self.lijst_tab.count():
            self.lijst_tab.setCurrentRow(0)

    def _selecteer_tabel(self, naam):
        for i in range(self.lijst_tab.count()):
            if self.lijst_tab.item(i).text() == naam:
                self.lijst_tab.setCurrentRow(i)
                return

    def _huidige_tabel(self):
        it = self.lijst_tab.currentItem()
        return it.text() if it else ""

    def _toon_kolommen(self):
        self.lijst_kol.clear()
        tabel = self._huidige_tabel()
        if not tabel:
            return
        try:
            kolommen = db_lijst_kolommen(self.database, tabel, self.wachtwoord)
        except Exception as e:
            self.v._db_fout_tonen(e)
            return
        if not kolommen:
            self.lijst_kol.addItem(self.v.t("td_geen_velden"))
            return
        for naam, typ, null, key, _std in kolommen:
            merk = ""
            if str(key).upper() == "PRI":
                merk += "  [%s]" % self.v.t("veld_pk")
            if str(null).upper() == "NO":
                merk += "  [%s]" % self.v.t("veld_nn")
            it = QListWidgetItem("%s  -  %s%s" % (naam, typ, merk))
            it.setData(Qt.ItemDataRole.UserRole, (naam, typ))
            self.lijst_kol.addItem(it)

    def _nieuwe_tabel(self):
        d = VeldBouwerDialoog(self.v, self.database, self.wachtwoord)
        if d.exec() and d.gemaakt:
            nieuw = d.tabelnaam.text().strip()
            self._ververs()
            self._selecteer_tabel(_veilige_naam(nieuw))

    def _verwijder_tabel(self):
        tabel = self._huidige_tabel()
        if not tabel:
            return
        if QMessageBox.question(
                self, APP_NAAM, self.v.t("td_verwijder_bevestig").format(naam=tabel)
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            db_verwijder_tabel(self.database, tabel, self.wachtwoord)
        except Exception as e:
            self.v._db_fout_tonen(e); return
        self._ververs(); self.lijst_kol.clear()

    def _veld_toevoegen(self):
        tabel = self._huidige_tabel()
        if not tabel:
            QMessageBox.information(self, APP_NAAM, self.v.t("td_kies_tabel"))
            return
        d = VeldToevoegenDialoog(self.v, self.v.t("td_veld_toevoegen"))
        if d.exec():
            try:
                ok, fout = db_voeg_kolom_toe(self.database, tabel, d.kolom(),
                                             self.wachtwoord)
            except Exception as e:
                self.v._db_fout_tonen(e); return
            if not ok:
                QMessageBox.warning(self, APP_NAAM,
                                    self.v.t("db_verbind_fout").format(fout=fout))
                return
            self._toon_kolommen()

    def _veld_aanpassen(self):
        tabel = self._huidige_tabel()
        it = self.lijst_kol.currentItem()
        if not tabel or not it:
            return
        data = it.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        oude_naam, typ = data
        kolomtype, lengte = _parse_kolomtype(typ)
        begin = {"naam": oude_naam, "type": kolomtype, "lengte": lengte}
        d = VeldToevoegenDialoog(self.v, self.v.t("td_veld_aanpassen"), begin)
        if d.exec():
            try:
                ok, fout = db_wijzig_kolom(self.database, tabel, oude_naam,
                                           d.kolom(), self.wachtwoord)
            except Exception as e:
                self.v._db_fout_tonen(e); return
            if not ok:
                QMessageBox.warning(self, APP_NAAM,
                                    self.v.t("db_verbind_fout").format(fout=fout))
                return
            self._toon_kolommen()

    def _veld_verwijderen(self):
        tabel = self._huidige_tabel()
        it = self.lijst_kol.currentItem()
        if not tabel or not it:
            return
        data = it.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        kolomnaam = data[0]
        if QMessageBox.question(
                self, APP_NAAM,
                self.v.t("td_veld_bevestig").format(naam=kolomnaam)
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            db_verwijder_kolom(self.database, tabel, kolomnaam, self.wachtwoord)
        except Exception as e:
            self.v._db_fout_tonen(e); return
        self._toon_kolommen()


if WEBENGINE:
    class EditorPage(QWebEnginePage):
        """Links naar buiten openen in de echte browser; binnen blijven."""
        def acceptNavigationRequest(self, url, nav_type, is_main_frame):
            if nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
                host = url.host()
                schema = url.scheme()
                if (host and host != "draveserver.local") or schema == "mailto":
                    QDesktopServices.openUrl(url)
                return False
            return super().acceptNavigationRequest(url, nav_type, is_main_frame)


class WebsiteBouwerDialoog(Dialoog):
    """De ingebouwde DraveEdit-editor; exporteert naar de site-map + PWA."""
    def __init__(self, venster, site):
        super().__init__(venster)
        self.v = venster
        self.site = site
        self.doelmap = _ap(site.get("map", ""))
        self._open_na = False
        self.setWindowTitle(venster.t("wb_titel"))
        self.resize(1280, 820)
        lay = QVBoxLayout(self)
        if not WEBENGINE:
            uitleg = QLabel(venster.t("wb_geen_webengine"))
            uitleg.setWordWrap(True)
            lay.addWidget(uitleg)
            knop = QPushButton(venster.t("wb_sluiten"))
            knop.clicked.connect(self.accept)
            lay.addWidget(knop)
            return
        self.view = QWebEngineView()
        self.view.setPage(EditorPage(self.view))
        self.view.loadFinished.connect(self._geladen)
        try:
            with open(bouwer_html_pad(), encoding="utf-8") as f:
                html = f.read()
        except Exception:
            html = "<h2>bouwer.html niet gevonden</h2>"
        self.view.setHtml(html, QUrl("https://draveserver.local/"))
        lay.addWidget(self.view, 1)
        rij = QHBoxLayout()
        b_exp = QPushButton(venster.t("wb_export"))
        b_exp.setObjectName("primair")
        b_exp.clicked.connect(self._export)
        rij.addWidget(b_exp)
        b_open = QPushButton(venster.t("wb_open"))
        b_open.clicked.connect(self._open)
        rij.addWidget(b_open)
        rij.addStretch(1)
        b_klaar = QPushButton(venster.t("wb_sluiten"))
        b_klaar.clicked.connect(self.accept)
        rij.addWidget(b_klaar)
        lay.addLayout(rij)

    def _geladen(self, ok):
        taal = "en" if self.v.cfg.get("taal") == "en" else "nl"
        for js in ('DE.setScheme("dark")', 'DE.setLang(%s)' % json.dumps(taal)):
            try:
                self.view.page().runJavaScript(js)
            except Exception:
                pass
        # 1) Eigen ontwerp-bestand heeft voorrang (volledige getrouwheid).
        if os.path.exists(self._ontwerp_pad()):
            try:
                with open(self._ontwerp_pad(), encoding="utf-8") as f:
                    h = f.read()
                self.view.page().runJavaScript(
                    "DE.loadProjectHTML(%s)" % json.dumps(h))
                return
            except Exception:
                pass
        # 2) Anders: een bestaande, eerder gemaakte site (index.html + css)
        #    inlezen om te bewerken.
        idx = os.path.join(self.doelmap, "index.html")
        if os.path.exists(idx):
            try:
                with open(idx, encoding="utf-8") as f:
                    html = f.read()
            except Exception:
                html = ""
            css = ""
            cpad = os.path.join(self.doelmap, "css", "index_style.css")
            if os.path.exists(cpad):
                try:
                    with open(cpad, encoding="utf-8") as f:
                        css = f.read()
                except Exception:
                    css = ""
            try:
                self.view.page().runJavaScript(
                    "DE.importSite(%s, %s)" % (json.dumps(html), json.dumps(css)))
            except Exception:
                pass

    def _ontwerp_pad(self):
        return os.path.join(self.doelmap, ".draveserver-ontwerp.html")

    def _export(self):
        if not self.doelmap:
            QMessageBox.warning(self, APP_NAAM, self.v.t("wb_geen_map"))
            return
        self.view.page().runJavaScript("DE.getProjectHTML()",
                                       self._bewaar_ontwerp)
        self.view.page().runJavaScript("DE.getExportParts()",
                                       self._schrijf_site)

    def _open(self):
        self._open_na = True
        self._export()

    def _bewaar_ontwerp(self, h):
        try:
            os.makedirs(self.doelmap, exist_ok=True)
            with open(self._ontwerp_pad(), "w", encoding="utf-8") as f:
                f.write(h or "")
        except Exception:
            pass

    def _schrijf_site(self, parts):
        try:
            naam = self.site.get("naam", "Website")
            for rel, data in site_bestanden(naam, parts or "{}").items():
                dest = os.path.join(self.doelmap, *rel.split("/"))
                # Een bestaande, eventueel aangepaste contact.php niet overschrijven.
                if rel == "contact.php" and os.path.isfile(dest):
                    continue
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as f:
                    f.write(data)
        except Exception as e:
            QMessageBox.warning(self, APP_NAAM,
                                self.v.t("ond_fout").format(fout=str(e)))
            return
        if self._open_na:
            self._open_na = False
            QDesktopServices.openUrl(QUrl(self.v._site_url(self.site)))
        else:
            QMessageBox.information(self, APP_NAAM, self.v.t("wb_klaar"))


class QrDialoog(Dialoog):
    """Toont een QR-code voor een (LAN-)URL om op de telefoon te openen."""
    def __init__(self, venster, url):
        super().__init__(venster)
        self.setWindowTitle(venster.t("qr_titel"))
        self.resize(400, 480)
        lay = QVBoxLayout(self)
        uit = QLabel(venster.t("qr_uitleg"))
        uit.setObjectName("uitleg"); uit.setWordWrap(True)
        lay.addWidget(uit)
        beeld = QLabel(); beeld.setAlignment(Qt.AlignmentFlag.AlignCenter)
        try:
            beeld.setPixmap(maak_qr_pixmap(url, 320))
        except Exception as e:
            beeld.setText("QR: " + str(e))
        lay.addWidget(beeld, 1)
        link = QLabel('<a href="%s" style="color:%s">%s</a>' % (url, ACCENT, url))
        link.setOpenExternalLinks(True)
        link.setAlignment(Qt.AlignmentFlag.AlignCenter); link.setWordWrap(True)
        lay.addWidget(link)
        rij = QHBoxLayout()
        b_open = QPushButton(venster.t("site_openen"))
        b_open.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
        rij.addWidget(b_open)
        b_sl = QPushButton(venster.t("sluit")); b_sl.setObjectName("primair")
        b_sl.clicked.connect(self.accept)
        rij.addWidget(b_sl)
        lay.addLayout(rij)


class Hoofdvenster(QMainWindow):
    def __init__(self):
        super().__init__()
        zorg_voor_mappen()
        self.cfg = laad_config()
        zet_actieve_poorten(self.cfg.get("https_poort", 443),
                            self.cfg.get("db_poort", 3306))
        # bestaande onderdelen/sites oppikken die nog niet in de config staan
        veranderd = scan_php(self.cfg)
        if scan_sites(self.cfg):
            veranderd = True
        if veranderd:
            bewaar_config(self.cfg)
        taal = self.cfg.get("taal", "auto")
        self.taal = taal if taal in ("nl", "en") else detecteer_taal()
        self.server = ServerBeheer()
        self.db = DatabaseBeheer()
        self.apache = apache_uit_config(self.cfg)
        self.setWindowTitle("%s  v%s" % (APP_NAAM, APP_VERSIE))
        self.resize(860, 600)
        self.setWindowIcon(app_icoon())
        self.setStyleSheet(STIJL())
        self._bouw()
        self._menu()
        self._ververs_server()
        self._ververs_sites()
        self._ond_ververs()
        self._ssl_vul_combo()
        self._ssl_ververs()
        self._db_ververs()
        self._tray = None
        self._echt_afsluiten = False
        self._maak_tray()

    def _maak_tray(self):
        from PyQt6.QtWidgets import QSystemTrayIcon, QMenu
        try:
            if not QSystemTrayIcon.isSystemTrayAvailable():
                return
        except Exception:
            return
        self._tray = QSystemTrayIcon(app_icoon(), self)
        self._tray.setToolTip("%s v%s" % (APP_NAAM, APP_VERSIE))
        menu = QMenu()
        a_toon = menu.addAction(self.t("tray_tonen"))
        a_toon.triggered.connect(self._tray_toon)
        menu.addSeparator()
        a_ss = menu.addAction(self.t("tray_srv_start"))
        a_ss.triggered.connect(lambda: (self._start(), self._tray_menu_bij()))
        a_sx = menu.addAction(self.t("tray_srv_stop"))
        a_sx.triggered.connect(lambda: (self._stop(), self._tray_menu_bij()))
        a_ds = menu.addAction(self.t("tray_db_start"))
        a_ds.triggered.connect(lambda: (self._db_start(), self._tray_menu_bij()))
        a_dx = menu.addAction(self.t("tray_db_stop"))
        a_dx.triggered.connect(lambda: (self._db_stop(), self._tray_menu_bij()))
        menu.addSeparator()
        a_af = menu.addAction(self.t("tray_afsluiten"))
        a_af.triggered.connect(self._tray_afsluiten)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._tray_activated)
        self._tray.show()

    def _tray_menu_bij(self):
        self._ververs_server(); self._db_ververs()

    def _tray_activated(self, reden):
        from PyQt6.QtWidgets import QSystemTrayIcon
        if reden in (QSystemTrayIcon.ActivationReason.Trigger,
                     QSystemTrayIcon.ActivationReason.DoubleClick):
            self._tray_toon()

    def _tray_toon(self):
        self.showNormal(); self.raise_(); self.activateWindow()

    def _tray_afsluiten(self):
        self._echt_afsluiten = True
        self.close()

    def t(self, sleutel):
        return TEKST.get(self.taal, TEKST["en"]).get(sleutel, sleutel)

    def _bouw(self):
        centraal = QWidget(); self.setCentralWidget(centraal)
        lay = QVBoxLayout(centraal)
        kop = QHBoxLayout()
        logo = QLabel()
        p = _bundel_bestand("logo.png")
        if os.path.exists(p):
            pm = QPixmap(p)
            if not pm.isNull():
                logo.setPixmap(pm.scaled(QSize(48, 48),
                               Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation))
        kop.addWidget(logo)
        titels = QVBoxLayout()
        t1 = QLabel(APP_NAAM); t1.setObjectName("titel")
        t2 = QLabel(self.t("ondertitel")); t2.setObjectName("ondertitel")
        titels.addWidget(t1); titels.addWidget(t2)
        kop.addLayout(titels); kop.addStretch(1)
        lay.addLayout(kop)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_server(), self.t("tab_server"))
        self.tabs.addTab(self._tab_sites(), self.t("tab_sites"))
        self.tabs.addTab(self._tab_onderdelen(), self.t("tab_onderdelen"))
        self.tabs.addTab(self._tab_ssl(), self.t("tab_ssl"))
        self.tabs.addTab(self._tab_database(), self.t("tab_database"))
        self.tabs.addTab(self._tab_poorten(), self.t("tab_poorten"))
        self.tabs.addTab(self._tab_logboek(), self.t("tab_logboek"))
        # Opvallende opstart-banner (boven de tabs, in de accentkleur)
        self.opstart_balk = QWidget(); self.opstart_balk.setObjectName("opstartbalk")
        _ob = QVBoxLayout(self.opstart_balk)
        _ob.setContentsMargins(16, 12, 16, 12); _ob.setSpacing(8)
        self.opstart_tekst = QLabel(self.t("opstart_bezig"))
        self.opstart_tekst.setObjectName("opstarttekst")
        self.opstart_tekst.setWordWrap(True)
        _ob.addWidget(self.opstart_tekst)
        self.opstart_bar = QProgressBar(); self.opstart_bar.setObjectName("opstartbar")
        self.opstart_bar.setRange(0, 0); self.opstart_bar.setTextVisible(False)
        _ob.addWidget(self.opstart_bar)
        self.opstart_balk.setVisible(False)
        lay.addWidget(self.opstart_balk)
        lay.addWidget(self.tabs, 1)

        sb = QStatusBar(); self.setStatusBar(sb)
        self.btn_donatie = QPushButton(" \u2665 " + self.t("donatie"))
        self.btn_donatie.setObjectName("primair")
        self.btn_donatie.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(DONATIE_URL)))
        sb.addPermanentWidget(self.btn_donatie)

    # ---- server-tab ----
    def _tab_server(self):
        w = QWidget(); lay = QVBoxLayout(w)
        if not WINDOWS:
            strook = QLabel(self.t("server_demo"))
            strook.setObjectName("strook"); strook.setWordWrap(True)
            lay.addWidget(strook)
        # status
        rij = QHBoxLayout()
        rij.addWidget(QLabel(self.t("server_status") + ":"))
        self.lbl_status = QLabel(self.t("status_uit"))
        self.lbl_status.setObjectName("statusuit")
        rij.addWidget(self.lbl_status); rij.addStretch(1)
        lay.addLayout(rij)
        # apache-info
        self.lbl_apache = QLabel("")
        self.lbl_apache.setObjectName("info"); self.lbl_apache.setWordWrap(True)
        lay.addWidget(self.lbl_apache)
        self.btn_apache = QPushButton(self.t("apache_kiezen"))
        self.btn_apache.clicked.connect(self._kies_apache)
        lay.addWidget(self.btn_apache)
        self.btn_download = QPushButton(self.t("naar_onderdelen"))
        self.btn_download.setObjectName("primair")
        self.btn_download.clicked.connect(lambda: self.tabs.setCurrentIndex(2))
        lay.addWidget(self.btn_download)
        lay.addSpacing(8)
        # start/stop
        rij2 = QHBoxLayout()
        self.btn_start = QPushButton(self.t("start"))
        self.btn_start.setObjectName("primair")
        self.btn_start.clicked.connect(self._start)
        rij2.addWidget(self.btn_start)
        self.btn_stop = QPushButton(self.t("stop"))
        self.btn_stop.setObjectName("stop")
        self.btn_stop.clicked.connect(self._stop)
        rij2.addWidget(self.btn_stop)
        rij2.addStretch(1)
        lay.addLayout(rij2)
        rij3 = QHBoxLayout()
        self.btn_open = QPushButton(self.t("open_browser"))
        self.btn_open.clicked.connect(self._open_browser)
        rij3.addWidget(self.btn_open)
        self.btn_config = QPushButton(self.t("config_tonen"))
        self.btn_config.clicked.connect(self._toon_config)
        rij3.addWidget(self.btn_config)
        rij3.addStretch(1)
        lay.addLayout(rij3)
        lay.addStretch(1)
        return w

    # ---- sites-tab ----
    def _tab_sites(self):
        w = QWidget(); lay = QVBoxLayout(w)
        intro = QLabel(self.t("sites_intro"))
        intro.setObjectName("uitleg"); intro.setWordWrap(True)
        lay.addWidget(intro)
        self.lijst = QListWidget()
        self.lijst.itemDoubleClicked.connect(lambda *_: self._site_bewerken())
        lay.addWidget(self.lijst, 1)
        rij = QHBoxLayout()
        b1 = QPushButton(self.t("site_toevoegen")); b1.setObjectName("primair")
        b1.clicked.connect(self._site_toevoegen)
        rij.addWidget(b1)
        b2 = QPushButton(self.t("site_bewerken"))
        b2.clicked.connect(self._site_bewerken)
        rij.addWidget(b2)
        b3 = QPushButton(self.t("site_verwijderen"))
        b3.clicked.connect(self._site_verwijderen)
        rij.addWidget(b3)
        b_open = QPushButton(self.t("site_openen"))
        b_open.clicked.connect(self._site_openen)
        rij.addWidget(b_open)
        b_qr = QPushButton(self.t("qr_knop"))
        b_qr.clicked.connect(self._site_qr)
        rij.addWidget(b_qr)
        b_web = QPushButton(self.t("site_website"))
        b_web.setObjectName("primair")
        b_web.clicked.connect(self._site_website)
        rij.addWidget(b_web)
        rij.addStretch(1)
        b_scan = QPushButton(self.t("sites_scannen"))
        b_scan.clicked.connect(self._scan_mappen)
        rij.addWidget(b_scan)
        b_map = QPushButton(self.t("sites_open_map"))
        b_map.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(HTDOCS)))
        rij.addWidget(b_map)
        lay.addLayout(rij)
        return w

    # ---- onderdelen-tab ----
    def _tab_onderdelen(self):
        w = QWidget(); lay = QVBoxLayout(w)
        intro = QLabel(self.t("ond_intro"))
        intro.setObjectName("uitleg"); intro.setWordWrap(True)
        lay.addWidget(intro)
        # Apache
        ka = QLabel(self.t("ond_apache_kop")); ka.setObjectName("kop")
        lay.addWidget(ka)
        self.lbl_ond_apache = QLabel("")
        self.lbl_ond_apache.setObjectName("info"); self.lbl_ond_apache.setWordWrap(True)
        lay.addWidget(self.lbl_ond_apache)
        rij_a = QHBoxLayout()
        self.btn_ond_apache_auto = QPushButton(self.t("ond_apache_auto"))
        self.btn_ond_apache_auto.setObjectName("primair")
        self.btn_ond_apache_auto.clicked.connect(self._ond_apache_auto)
        rij_a.addWidget(self.btn_ond_apache_auto)
        self.btn_ond_apache_zip = QPushButton(self.t("ond_apache_zip"))
        self.btn_ond_apache_zip.clicked.connect(self._ond_apache_zip)
        rij_a.addWidget(self.btn_ond_apache_zip)
        rij_a.addStretch(1)
        lay.addLayout(rij_a)
        # PHP
        kp = QLabel(self.t("ond_php_kop")); kp.setObjectName("kop")
        lay.addWidget(kp)
        self.lbl_ond_php = QLabel("")
        self.lbl_ond_php.setObjectName("info"); self.lbl_ond_php.setWordWrap(True)
        lay.addWidget(self.lbl_ond_php)
        rij_p = QHBoxLayout()
        self.btn_php_laden = QPushButton(self.t("ond_php_versies_laden"))
        self.btn_php_laden.clicked.connect(self._ond_php_laden)
        rij_p.addWidget(self.btn_php_laden)
        rij_p.addWidget(QLabel(self.t("ond_php_versie")))
        self.combo_php = QComboBox()
        self.combo_php.setMinimumWidth(220)
        rij_p.addWidget(self.combo_php)
        rij_p.addStretch(1)
        lay.addLayout(rij_p)
        rij_p2 = QHBoxLayout()
        self.btn_php_install = QPushButton(self.t("ond_php_install"))
        self.btn_php_install.setObjectName("primair")
        self.btn_php_install.clicked.connect(self._ond_php_install)
        rij_p2.addWidget(self.btn_php_install)
        self.chk_php = QCheckBox(self.t("ond_php_inschakelen"))
        self.chk_php.setChecked(self.cfg.get("php_aan", False))
        self.chk_php.toggled.connect(self._ond_php_toggle)
        rij_p2.addWidget(self.chk_php)
        self.btn_php_test = QPushButton(self.t("ond_php_testen"))
        self.btn_php_test.clicked.connect(self._ond_php_test)
        rij_p2.addWidget(self.btn_php_test)
        rij_p2.addStretch(1)
        lay.addLayout(rij_p2)
        # Geinstalleerde versie live kiezen
        rij_p3 = QHBoxLayout()
        rij_p3.addWidget(QLabel(self.t("ond_php_actief")))
        self.combo_php_actief = QComboBox()
        self.combo_php_actief.setMinimumWidth(200)
        rij_p3.addWidget(self.combo_php_actief)
        self.btn_php_gebruik = QPushButton(self.t("ond_php_gebruik"))
        self.btn_php_gebruik.setObjectName("primair")
        self.btn_php_gebruik.clicked.connect(self._php_activeer)
        rij_p3.addWidget(self.btn_php_gebruik)
        rij_p3.addStretch(1)
        lay.addLayout(rij_p3)
        # voortgang + opmerking
        self.lbl_ond_status = QLabel("")
        self.lbl_ond_status.setObjectName("uitleg")
        lay.addWidget(self.lbl_ond_status)
        self.balk_ond = QProgressBar(); self.balk_ond.setVisible(False)
        lay.addWidget(self.balk_ond)
        let_op = QLabel(self.t("ond_let_op"))
        let_op.setObjectName("uitleg"); let_op.setWordWrap(True)
        lay.addWidget(let_op)
        lay.addStretch(1)
        return w

    def _ond_ververs(self):
        if self.apache and self.apache.get("httpd_exe"):
            self.lbl_ond_apache.setText(self.t("ond_apache_aan").format(
                pad=self.apache["httpd_exe"]))
        else:
            self.lbl_ond_apache.setText(self.t("ond_apache_uit"))
        if self.cfg.get("php_dir") and os.path.isdir(self.cfg["php_dir"]):
            self.lbl_ond_php.setText(self.t("ond_php_aan_status").format(
                versie=self.cfg.get("php_versie", "?")))
        else:
            self.lbl_ond_php.setText(self.t("ond_php_uit"))
        self._php_actief_vul()

    def _php_actief_vul(self):
        if not hasattr(self, "combo_php_actief"):
            return
        self.combo_php_actief.blockSignals(True)
        self.combo_php_actief.clear()
        versies = geinstalleerde_php_versies()
        for naam, mp in versies:
            self.combo_php_actief.addItem(naam, mp)
        i = self.combo_php_actief.findText(self.cfg.get("php_versie", ""))
        if i >= 0:
            self.combo_php_actief.setCurrentIndex(i)
        self.combo_php_actief.blockSignals(False)
        self.combo_php_actief.setEnabled(bool(versies))
        self.btn_php_gebruik.setEnabled(bool(versies))

    def _php_activeer(self):
        mp = self.combo_php_actief.currentData()
        naam = self.combo_php_actief.currentText()
        if not mp or not os.path.isdir(mp):
            return
        self.cfg["php_dir"] = mp
        self.cfg["php_versie"] = naam
        self.cfg["php_aan"] = True
        try:
            maak_php_ini(mp)
        except Exception:
            pass
        bewaar_config(self.cfg)
        self.chk_php.setChecked(True)
        self._ond_ververs()
        # draait de server? Dan herstarten zodat de nieuwe PHP-versie actief wordt.
        if self.server.draait():
            self.server.stop()
            self.server.start(self.apache, self.cfg.get("sites", []),
                              self._actieve_php_dir())
            self._ververs_server()
            QMessageBox.information(self, APP_NAAM,
                self.t("ond_php_gewisseld_herstart").format(versie=naam))
        else:
            QMessageBox.information(self, APP_NAAM,
                self.t("ond_php_gewisseld").format(versie=naam))

    def _download_bezig(self, bezig):
        for b in (self.btn_ond_apache_auto, self.btn_ond_apache_zip,
                  self.btn_php_laden, self.btn_php_install):
            b.setEnabled(not bezig)
        self.balk_ond.setVisible(bezig)
        if not bezig:
            self.balk_ond.setRange(0, 100)

    # ---- Apache downloaden / instellen ----
    def _ond_apache_auto(self):
        self._download_bezig(True)
        self.balk_ond.setRange(0, 0)
        self.lbl_ond_status.setText(self.t("ond_bezig_download").format(mb="?"))
        zip_pad = os.path.join(DATA_MAP, "apache-download.zip")
        self._dl = DownloadThread(apache_download_url, zip_pad, APACHE_INSTALL)
        self._dl.voortgang.connect(self._dl_voortgang)
        self._dl.klaar.connect(self._apache_klaar)
        self._dl.start()

    def _ond_apache_zip(self):
        p, _ = QFileDialog.getOpenFileName(self, self.t("ond_apache_zip_titel"),
                                           BASIS, "Zip (*.zip)")
        if not p:
            return
        self._download_bezig(True)
        self.balk_ond.setRange(0, 0)
        ok, fout = pak_uit(p, APACHE_INSTALL)
        self._download_bezig(False)
        if not ok:
            QMessageBox.warning(self, APP_NAAM, self.t("ond_fout").format(fout=fout))
            return
        self._apache_na_uitpakken()

    def _apache_klaar(self, ok, resultaat):
        self._download_bezig(False)
        self.lbl_ond_status.setText("")
        if not ok:
            QMessageBox.warning(self, APP_NAAM,
                                self.t("ond_fout").format(fout=resultaat))
            return
        self._apache_na_uitpakken()

    def _apache_na_uitpakken(self):
        exe = vind_httpd(APACHE_INSTALL)
        if not exe:
            QMessageBox.warning(self, APP_NAAM, self.t("ond_apache_geen_httpd"))
            return
        d = os.path.dirname(os.path.dirname(exe))
        self.cfg["httpd_exe"] = exe
        self.cfg["apache_dir"] = d
        conf = os.path.join(d, "conf", "httpd.conf")
        self.cfg["httpd_conf"] = conf if os.path.isfile(conf) else ""
        bewaar_config(self.cfg)
        self.apache = apache_uit_config(self.cfg)
        self._ond_ververs(); self._ververs_server()
        QMessageBox.information(self, APP_NAAM, self.t("ond_klaar_apache"))

    # ---- PHP versies / downloaden ----
    def _ond_php_laden(self):
        self.btn_php_laden.setEnabled(False)
        self.lbl_ond_status.setText(self.t("ond_bezig_versies"))
        self._phpthread = PhpLijstThread()
        self._phpthread.klaar.connect(self._php_lijst_klaar)
        self._phpthread.start()

    def _php_lijst_klaar(self, lijst):
        self.btn_php_laden.setEnabled(True)
        self.lbl_ond_status.setText("")
        self.combo_php.clear()
        if not lijst:
            QMessageBox.information(self, APP_NAAM, self.t("ond_geen_versies"))
            return
        self._php_lijst = lijst
        for d in lijst:
            self.combo_php.addItem("PHP %s  (%s)" % (d["versie"], d["vs"].upper()),
                                   d)

    def _ond_php_install(self):
        d = self.combo_php.currentData()
        if not d:
            self._ond_php_laden()
            return
        self._download_bezig(True)
        self.balk_ond.setRange(0, 100)
        self.lbl_ond_status.setText(self.t("ond_bezig_download").format(mb="?"))
        doel = os.path.join(PHP_BASIS, d["versie"])
        zip_pad = os.path.join(DATA_MAP, "php-download.zip")
        self._php_keuze = d
        self._dl = DownloadThread(d["url"], zip_pad, doel)
        self._dl.voortgang.connect(self._dl_voortgang)
        self._dl.klaar.connect(self._php_klaar)
        self._dl.start()

    def _php_klaar(self, ok, resultaat):
        self._download_bezig(False)
        self.lbl_ond_status.setText("")
        if not ok:
            QMessageBox.warning(self, APP_NAAM,
                                self.t("ond_fout").format(fout=resultaat))
            return
        php_map = vind_php_map(resultaat) or resultaat
        maak_php_ini(php_map)
        self.cfg["php_dir"] = php_map
        self.cfg["php_versie"] = self._php_keuze["versie"]
        self.cfg["php_aan"] = True
        bewaar_config(self.cfg)
        self.chk_php.setChecked(True)
        self._ond_ververs()
        QMessageBox.information(self, APP_NAAM, self.t("ond_klaar_php").format(
            versie=self._php_keuze["versie"]))

    def _ond_php_toggle(self, aan):
        self.cfg["php_aan"] = bool(aan)
        bewaar_config(self.cfg)

    def _ond_php_test(self):
        if not self.cfg.get("php_dir") or not os.path.isdir(self.cfg["php_dir"]):
            QMessageBox.information(self, APP_NAAM, self.t("ond_php_uit"))
            return
        sites = [s for s in self.cfg.get("sites", [])
                 if s.get("aan", True) and s.get("map")]
        if not sites:
            QMessageBox.information(self, APP_NAAM, self.t("php_test_geen_site"))
            return
        s = sites[0]
        try:
            with open(os.path.join(s["map"], "php-test.php"), "w",
                      encoding="utf-8") as f:
                f.write("<?php phpinfo();\n")
        except OSError as e:
            QMessageBox.warning(self, APP_NAAM, self.t("ond_fout").format(fout=e))
            return
        adres = s.get("servernaam") or "localhost"
        poort = int(s.get("poort") or 80)
        url = "http://%s%s/php-test.php" % (
            adres, "" if poort == 80 else ":%d" % poort)
        if not self.cfg.get("php_aan"):
            self.chk_php.setChecked(True)
        if self.server.draait():
            QDesktopServices.openUrl(QUrl(url))
        else:
            QMessageBox.information(self, APP_NAAM,
                                    self.t("php_test_start").format(url=url))

    def _dl_voortgang(self, gedaan, totaal):
        if totaal > 0:
            self.balk_ond.setRange(0, 100)
            self.balk_ond.setValue(int(gedaan * 100 / totaal))
        mb = "%.1f / %.1f" % (gedaan / 1048576.0, totaal / 1048576.0) if totaal \
            else "%.1f" % (gedaan / 1048576.0)
        self.lbl_ond_status.setText(self.t("ond_bezig_download").format(mb=mb))

    # ---- beveiliging (https) tab ----
    def _tab_ssl(self):
        w = QWidget(); lay = QVBoxLayout(w)
        intro = QLabel(self.t("ssl_intro"))
        intro.setObjectName("uitleg"); intro.setWordWrap(True)
        lay.addWidget(intro)
        rij = QHBoxLayout()
        rij.addWidget(QLabel(self.t("ssl_site")))
        self.ssl_combo = QComboBox(); self.ssl_combo.setMinimumWidth(260)
        self.ssl_combo.currentIndexChanged.connect(lambda *_: self._ssl_ververs())
        rij.addWidget(self.ssl_combo); rij.addStretch(1)
        lay.addLayout(rij)
        self.lbl_ssl_status = QLabel("")
        self.lbl_ssl_status.setObjectName("info"); self.lbl_ssl_status.setWordWrap(True)
        lay.addWidget(self.lbl_ssl_status)
        self.lbl_ssl_cert = QLabel("")
        self.lbl_ssl_cert.setWordWrap(True)
        lay.addWidget(self.lbl_ssl_cert)
        rij2 = QHBoxLayout()
        b_self = QPushButton(self.t("ssl_self_maken")); b_self.setObjectName("primair")
        b_self.clicked.connect(self._ssl_self)
        rij2.addWidget(b_self)
        b_best = QPushButton(self.t("ssl_bestaand"))
        b_best.clicked.connect(self._ssl_bestaand)
        rij2.addWidget(b_best)
        rij2.addStretch(1)
        lay.addLayout(rij2)
        rij3 = QHBoxLayout()
        b_le = QPushButton(self.t("ssl_letsencrypt"))
        b_le.clicked.connect(self._ssl_letsencrypt)
        rij3.addWidget(b_le)
        b_uit = QPushButton(self.t("ssl_uit"))
        b_uit.clicked.connect(self._ssl_uit)
        rij3.addWidget(b_uit)
        b_verw = QPushButton(self.t("ssl_verwijderen"))
        b_verw.clicked.connect(self._ssl_verwijder)
        rij3.addWidget(b_verw)
        rij3.addStretch(1)
        lay.addLayout(rij3)
        uitleg = QLabel(self.t("ssl_self_uitleg"))
        uitleg.setObjectName("uitleg"); uitleg.setWordWrap(True)
        lay.addWidget(uitleg)
        lay.addStretch(1)
        return w

    def _ssl_vul_combo(self):
        self.ssl_combo.blockSignals(True)
        huidig = self.ssl_combo.currentData()
        self.ssl_combo.clear()
        for i, s in enumerate(self.cfg.get("sites", [])):
            self.ssl_combo.addItem(s.get("naam", "site"), i)
        self.ssl_combo.blockSignals(False)
        if huidig is not None and huidig < self.ssl_combo.count():
            self.ssl_combo.setCurrentIndex(huidig)

    def _ssl_site(self):
        idx = self.ssl_combo.currentData()
        if idx is None:
            return None
        sites = self.cfg.get("sites", [])
        if idx < len(sites):
            return sites[idx]
        return None

    def _ssl_ververs(self):
        s = self._ssl_site()
        if not s:
            self.lbl_ssl_status.setText(self.t("ssl_geen_sites"))
            self.lbl_ssl_cert.setText("")
            return
        if s.get("ssl_aan") and s.get("ssl_cert"):
            soort = s.get("ssl_type", "bestaand")
            self.lbl_ssl_status.setText(
                self.t("ssl_status_self") if soort == "self"
                else self.t("ssl_status_bestaand"))
            info = lees_cert_info(s.get("ssl_cert", ""))
            if info:
                datum = info["vervalt"].strftime("%d-%m-%Y")
                if info["dagen"] < 0:
                    self.lbl_ssl_cert.setText(self.t("ssl_cert_verlopen"))
                    self.lbl_ssl_cert.setStyleSheet("color:%s;" % WARN)
                elif info["dagen"] < 30:
                    self.lbl_ssl_cert.setText(
                        self.t("ssl_cert_binnenkort").format(dagen=info["dagen"]))
                    self.lbl_ssl_cert.setStyleSheet("color:%s;" % WARN)
                else:
                    self.lbl_ssl_cert.setText(self.t("ssl_cert_dagen").format(
                        dagen=info["dagen"], datum=datum))
                    self.lbl_ssl_cert.setStyleSheet("color:%s;" % GOED)
            else:
                self.lbl_ssl_cert.setText("")
        else:
            self.lbl_ssl_status.setText(self.t("ssl_status_uit"))
            self.lbl_ssl_cert.setText(""); self.lbl_ssl_cert.setStyleSheet("")

    def _ssl_self(self):
        s = self._ssl_site()
        if not s:
            QMessageBox.information(self, APP_NAAM, self.t("ssl_geen_sites"))
            return
        domein = s.get("servernaam") or "localhost"
        veilig = "".join(c if c.isalnum() or c in "-_." else "_"
                         for c in domein)[:50] or "localhost"
        cert = os.path.join(CERT_MAP, veilig + ".crt")
        key = os.path.join(CERT_MAP, veilig + ".key")
        ok, fout = genereer_self_signed(domein, cert, key)
        if not ok:
            QMessageBox.warning(self, APP_NAAM, self.t("ond_fout").format(fout=fout))
            return
        s["ssl_aan"] = True; s["ssl_type"] = "self"
        s["ssl_cert"] = cert; s["ssl_key"] = key
        bewaar_config(self.cfg)
        self._ssl_ververs()
        QMessageBox.information(self, APP_NAAM, self.t("ssl_self_klaar"))

    def _ssl_bestaand(self):
        s = self._ssl_site()
        if not s:
            QMessageBox.information(self, APP_NAAM, self.t("ssl_geen_sites"))
            return
        cert, _ = QFileDialog.getOpenFileName(
            self, self.t("ssl_cert_titel"), CERT_MAP,
            "Certificaat (*.crt *.pem *.cer)")
        if not cert:
            return
        key, _ = QFileDialog.getOpenFileName(
            self, self.t("ssl_key_titel"), os.path.dirname(cert),
            "Sleutel (*.key *.pem)")
        if not key:
            return
        s["ssl_aan"] = True; s["ssl_type"] = "bestaand"
        s["ssl_cert"] = cert; s["ssl_key"] = key
        bewaar_config(self.cfg)
        self._ssl_ververs()
        QMessageBox.information(self, APP_NAAM, self.t("ssl_bestaand_klaar"))

    def _ssl_uit(self):
        s = self._ssl_site()
        if not s:
            return
        s["ssl_aan"] = False
        bewaar_config(self.cfg)
        self._ssl_ververs()
        QMessageBox.information(self, APP_NAAM, self.t("ssl_uit_klaar"))

    def _ssl_verwijder(self):
        s = self._ssl_site()
        if not s:
            return
        if not s.get("ssl_cert"):
            QMessageBox.information(self, APP_NAAM, self.t("ssl_geen_cert"))
            return
        if QMessageBox.question(
                self, APP_NAAM,
                self.t("ssl_verwijder_bevestig").format(site=s.get("naam", ""))
        ) != QMessageBox.StandardButton.Yes:
            return
        # alleen onze eigen gegenereerde bestanden (in certificaten-map) wissen
        wortel = os.path.normcase(os.path.abspath(CERT_MAP))
        for sleutel in ("ssl_cert", "ssl_key"):
            pad = s.get(sleutel, "")
            if pad and os.path.normcase(os.path.abspath(pad)).startswith(wortel):
                try:
                    os.remove(pad)
                except OSError:
                    pass
        s["ssl_aan"] = False
        s["ssl_cert"] = ""
        s["ssl_key"] = ""
        s.pop("ssl_type", None)
        bewaar_config(self.cfg)
        self._ssl_ververs()
        QMessageBox.information(self, APP_NAAM, self.t("ssl_verwijder_klaar"))

    def _ssl_letsencrypt(self):
        s = self._ssl_site()
        if not s:
            QMessageBox.information(self, APP_NAAM, self.t("ssl_geen_sites"))
            return
        d = LetsEncryptDialoog(self, s)
        d.exec()
        if d.gelukt:
            # adres van de site gelijktrekken aan het domein van het certificaat
            domein = d.domein.text().strip()
            if domein:
                s["servernaam"] = domein
            s["ssl_aan"] = True
            s["ssl_type"] = "letsencrypt"
            s["ssl_cert"] = d.cert_pad
            s["ssl_key"] = d.key_pad
            bewaar_config(self.cfg)
            self._ververs_sites()
            self._ssl_selecteer_site(s)
            self._ssl_ververs()
            QMessageBox.information(self, APP_NAAM, self.t("le_klaar"))

    def _ssl_selecteer_site(self, site):
        """Zet de SSL-combo op de gegeven site."""
        sites = self.cfg.get("sites", [])
        try:
            idx = sites.index(site)
        except ValueError:
            return
        for i in range(self.ssl_combo.count()):
            if self.ssl_combo.itemData(i) == idx:
                self.ssl_combo.setCurrentIndex(i)
                break

    def _le_auto_vernieuw(self):
        """Na serverstart: vernieuw Let's Encrypt-certificaten die binnen 30 dagen
        verlopen (de server draait dan, dus http-01 kan)."""
        for s in ssl_sites(self.cfg.get("sites", [])):
            if s.get("ssl_type") != "letsencrypt":
                continue
            info = lees_cert_info(s.get("ssl_cert", ""))
            if not info or info["dagen"] >= 30:
                continue
            self._le_renew_site = s
            self._le_t = LetsEncryptThread(
                s.get("servernaam", ""), s.get("ssl_email", ""),
                s.get("map", ""), s.get("ssl_cert"), s.get("ssl_key"),
                s.get("ssl_staging", False))
            self._le_t.klaar.connect(self._le_auto_klaar)
            self._le_t.start()
            break

    def _le_auto_klaar(self, ok, fout):
        if ok:
            bewaar_config(self.cfg)
            self._ssl_ververs()
            QMessageBox.information(self, APP_NAAM, self.t("le_vernieuwd"))

    def _ssl_startcheck(self):
        """Waarschuw bij opstarten als een certificaat (bijna) verlopen is."""
        for s in ssl_sites(self.cfg.get("sites", [])):
            info = lees_cert_info(s.get("ssl_cert", ""))
            if info and info["dagen"] < 14:
                sleutel = ("ssl_cert_verlopen" if info["dagen"] < 0
                           else "ssl_cert_binnenkort")
                QMessageBox.warning(self, APP_NAAM, "%s\n(%s)" % (
                    self.t(sleutel).format(dagen=info["dagen"]),
                    s.get("naam", "")))
                break

    # ---- logboek tab ----
    def _tab_logboek(self):
        from PyQt6.QtWidgets import QPlainTextEdit
        from PyQt6.QtGui import QFont
        w = QWidget(); lay = QVBoxLayout(w)
        intro = QLabel(self.t("log_intro"))
        intro.setObjectName("uitleg"); intro.setWordWrap(True)
        lay.addWidget(intro)
        rij = QHBoxLayout()
        self.cmb_log = QComboBox()
        self.cmb_log.currentIndexChanged.connect(lambda *_: self._log_ververs())
        rij.addWidget(self.cmb_log, 1)
        b_ver = QPushButton(self.t("log_ververs"))
        b_ver.clicked.connect(self._log_ververs)
        rij.addWidget(b_ver)
        b_map = QPushButton(self.t("log_map"))
        b_map.clicked.connect(self._log_open_map)
        rij.addWidget(b_map)
        b_wis = QPushButton(self.t("log_wis"))
        b_wis.clicked.connect(self._log_wis)
        rij.addWidget(b_wis)
        lay.addLayout(rij)
        self.txt_log = QPlainTextEdit(); self.txt_log.setReadOnly(True)
        self.txt_log.setFont(QFont("Consolas", 10))
        self.txt_log.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        lay.addWidget(self.txt_log, 1)
        self._log_vul_lijst()
        return w

    def _log_bestanden(self):
        out = []
        try:
            for n in sorted(os.listdir(LOG_MAP)):
                if n.lower().endswith((".log", ".txt", ".err")):
                    out.append(n)
        except Exception:
            pass
        return out

    def _log_vul_lijst(self):
        huidig = self.cmb_log.currentText()
        self.cmb_log.blockSignals(True)
        self.cmb_log.clear()
        best = self._log_bestanden()
        if best:
            self.cmb_log.addItems(best)
            i = self.cmb_log.findText(huidig)
            self.cmb_log.setCurrentIndex(i if i >= 0 else 0)
        self.cmb_log.blockSignals(False)
        self._log_ververs()

    def _log_ververs(self):
        if not hasattr(self, "txt_log"):
            return
        self._log_vul_lijst_stil()
        naam = self.cmb_log.currentText()
        if not naam:
            self.txt_log.setPlainText(self.t("log_leeg"))
            return
        pad = os.path.join(LOG_MAP, naam)
        try:
            with open(pad, "rb") as f:
                try:
                    f.seek(-200000, os.SEEK_END)  # laatste ~200 KB
                except OSError:
                    f.seek(0)
                data = f.read().decode("utf-8", "replace")
        except Exception as e:
            data = "(" + str(e) + ")"
        self.txt_log.setPlainText(data)
        sb = self.txt_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _log_vul_lijst_stil(self):
        best = self._log_bestanden()
        nu = [self.cmb_log.itemText(i) for i in range(self.cmb_log.count())]
        if best != nu:
            huidig = self.cmb_log.currentText()
            self.cmb_log.blockSignals(True)
            self.cmb_log.clear(); self.cmb_log.addItems(best)
            i = self.cmb_log.findText(huidig)
            self.cmb_log.setCurrentIndex(i if i >= 0 else 0)
            self.cmb_log.blockSignals(False)

    def _log_open_map(self):
        try:
            os.makedirs(LOG_MAP, exist_ok=True)
        except Exception:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(LOG_MAP))

    def _log_wis(self):
        naam = self.cmb_log.currentText()
        if not naam:
            return
        if QMessageBox.question(self, APP_NAAM, self.t("log_wis") + " — " + naam + "?") \
                != QMessageBox.StandardButton.Yes:
            return
        try:
            open(os.path.join(LOG_MAP, naam), "w").close()
        except Exception:
            pass
        self._log_ververs()

    # ---- database (MariaDB) tab ----
    def _tab_database(self):
        w = QWidget(); lay = QVBoxLayout(w)
        intro = QLabel(self.t("db_intro"))
        intro.setObjectName("uitleg"); intro.setWordWrap(True)
        lay.addWidget(intro)
        kop = QLabel(self.t("db_kop")); kop.setObjectName("kop")
        lay.addWidget(kop)
        self.lbl_db_status = QLabel("")
        self.lbl_db_status.setObjectName("info"); self.lbl_db_status.setWordWrap(True)
        lay.addWidget(self.lbl_db_status)
        rij = QHBoxLayout()
        self.btn_db_download = QPushButton(self.t("db_download"))
        self.btn_db_download.setObjectName("primair")
        self.btn_db_download.clicked.connect(self._db_download)
        rij.addWidget(self.btn_db_download)
        self.btn_db_zip = QPushButton(self.t("db_zip"))
        self.btn_db_zip.clicked.connect(self._db_zip)
        rij.addWidget(self.btn_db_zip)
        rij.addStretch(1)
        lay.addLayout(rij)
        rij2 = QHBoxLayout()
        self.btn_db_start = QPushButton(self.t("db_start"))
        self.btn_db_start.setObjectName("primair")
        self.btn_db_start.clicked.connect(self._db_start)
        rij2.addWidget(self.btn_db_start)
        self.btn_db_stop = QPushButton(self.t("db_stop"))
        self.btn_db_stop.setObjectName("stop")
        self.btn_db_stop.clicked.connect(self._db_stop)
        rij2.addWidget(self.btn_db_stop)
        rij2.addStretch(1)
        lay.addLayout(rij2)
        self.balk_db = QProgressBar(); self.balk_db.setVisible(False)
        lay.addWidget(self.balk_db)
        self.lbl_db_msg = QLabel(""); self.lbl_db_msg.setObjectName("uitleg")
        lay.addWidget(self.lbl_db_msg)
        # root-wachtwoord
        kw = QLabel(self.t("db_wachtwoord_kop")); kw.setObjectName("kop")
        lay.addWidget(kw)
        wuit = QLabel(self.t("db_wachtwoord_uitleg"))
        wuit.setObjectName("uitleg"); wuit.setWordWrap(True)
        lay.addWidget(wuit)
        rij3 = QHBoxLayout()
        self.veld_db_pw = QLineEdit(self.cfg.get("db_wachtwoord", ""))
        self.veld_db_pw.setPlaceholderText(self.t("db_wachtwoord_kop"))
        rij3.addWidget(self.veld_db_pw, 1)
        b_pw = QPushButton(self.t("db_wachtwoord_zet"))
        b_pw.clicked.connect(self._db_wachtwoord)
        rij3.addWidget(b_pw)
        lay.addLayout(rij3)
        # databases
        kd = QLabel(self.t("db_databases_kop")); kd.setObjectName("kop")
        lay.addWidget(kd)
        rij4 = QHBoxLayout()
        self.veld_db_naam = QLineEdit()
        self.veld_db_naam.setPlaceholderText(self.t("db_nieuwe_naam"))
        rij4.addWidget(self.veld_db_naam, 1)
        b_maak = QPushButton(self.t("db_aanmaken")); b_maak.setObjectName("primair")
        b_maak.clicked.connect(self._db_maak)
        rij4.addWidget(b_maak)
        lay.addLayout(rij4)
        self.lijst_db = QListWidget()
        self.lijst_db.itemDoubleClicked.connect(lambda *_: self._db_tabellen())
        lay.addWidget(self.lijst_db, 1)
        rij5 = QHBoxLayout()
        b_tab = QPushButton(self.t("db_tabellen_knop"))
        b_tab.setObjectName("primair")
        b_tab.clicked.connect(self._db_tabellen)
        rij5.addWidget(b_tab)
        b_verw = QPushButton(self.t("db_verwijderen"))
        b_verw.clicked.connect(self._db_verwijder)
        rij5.addWidget(b_verw)
        b_ver = QPushButton(self.t("db_vernieuwen"))
        b_ver.clicked.connect(self._db_lijst_ververs)
        rij5.addWidget(b_ver)
        rij5.addStretch(1)
        lay.addLayout(rij5)
        # back-up & herstel
        kb = QLabel(self.t("db_backup_kop")); kb.setObjectName("kop")
        lay.addWidget(kb)
        rij6 = QHBoxLayout()
        b_bk = QPushButton(self.t("db_backup")); b_bk.setObjectName("primair")
        b_bk.clicked.connect(self._db_backup)
        rij6.addWidget(b_bk)
        b_hs = QPushButton(self.t("db_herstel"))
        b_hs.clicked.connect(self._db_herstel)
        rij6.addWidget(b_hs)
        rij6.addStretch(1)
        lay.addLayout(rij6)
        return w

    def _db_backup(self):
        if not self.db.draait():
            QMessageBox.information(self, APP_NAAM, self.t("db_geen_draait")); return
        dump = vind_db_tool(["mariadb-dump.exe", "mysqldump.exe"])
        if not dump:
            QMessageBox.warning(self, APP_NAAM, self.t("db_geen_tool")); return
        it = self.lijst_db.currentItem()
        naam = it.text() if it else ""
        if not naam:
            QMessageBox.information(self, APP_NAAM, self.t("db_kies_db")); return
        backup_map = os.path.join(DATA_MAP, "backups")
        try:
            os.makedirs(backup_map, exist_ok=True)
        except Exception:
            pass
        standaard = os.path.join(backup_map,
                                 "%s-%s.sql" % (naam, time.strftime("%Y%m%d-%H%M%S")))
        pad, _ = QFileDialog.getSaveFileName(self, self.t("db_backup"),
                                             standaard, "SQL (*.sql)")
        if not pad:
            return
        pw = self.cfg.get("db_wachtwoord", "")
        args = [dump, "-u", "root", "--host=127.0.0.1",
                "--port=%d" % ACTIEVE_DB_POORT]
        if pw:
            args.append("--password=%s" % pw)
        args += ["--databases", naam]
        try:
            with open(pad, "wb") as f:
                r = subprocess.run(args, stdout=f, stderr=subprocess.PIPE,
                                   timeout=300, creationflags=NO_WINDOW)
            if r.returncode != 0:
                raise RuntimeError((r.stderr or b"").decode("utf-8", "replace")[-600:])
        except Exception as e:
            QMessageBox.warning(self, APP_NAAM,
                                self.t("db_backup_mislukt").format(fout=str(e)))
            return
        QMessageBox.information(self, APP_NAAM, self.t("db_backup_klaar").format(pad=pad))

    def _db_herstel(self):
        if not self.db.draait():
            QMessageBox.information(self, APP_NAAM, self.t("db_geen_draait")); return
        client = vind_db_tool(["mariadb.exe", "mysql.exe"])
        if not client:
            QMessageBox.warning(self, APP_NAAM, self.t("db_geen_tool")); return
        start_map = os.path.join(DATA_MAP, "backups")
        pad, _ = QFileDialog.getOpenFileName(self, self.t("db_herstel"),
                                             start_map, "SQL (*.sql)")
        if not pad:
            return
        it = self.lijst_db.currentItem()
        naam = it.text() if it else ""
        if QMessageBox.question(
                self, APP_NAAM,
                self.t("db_herstel_bevestig").format(naam=naam or "(uit bestand)")) \
                != QMessageBox.StandardButton.Yes:
            return
        pw = self.cfg.get("db_wachtwoord", "")
        args = [client, "-u", "root", "--host=127.0.0.1",
                "--port=%d" % ACTIEVE_DB_POORT]
        if pw:
            args.append("--password=%s" % pw)
        if naam:
            args.append(naam)
        try:
            with open(pad, "rb") as f:
                r = subprocess.run(args, stdin=f, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, timeout=600,
                                   creationflags=NO_WINDOW)
            if r.returncode != 0:
                raise RuntimeError((r.stdout or b"").decode("utf-8", "replace")[-600:])
        except Exception as e:
            QMessageBox.warning(self, APP_NAAM,
                                self.t("db_herstel_mislukt").format(fout=str(e)))
            return
        self._db_lijst_ververs()
        QMessageBox.information(self, APP_NAAM, self.t("db_herstel_klaar").format(pad=pad))

    def _db_ververs(self):
        exe = mariadbd_uit_config(self.cfg)
        draait = self.db.draait()
        if not exe:
            self.lbl_db_status.setText(self.t("db_status_uit"))
        elif draait:
            self.lbl_db_status.setText(self.t("db_status_draait").format(
                versie=self.cfg.get("db_versie", "")))
        else:
            self.lbl_db_status.setText(self.t("db_status_gestopt").format(
                versie=self.cfg.get("db_versie", "")))
        self.btn_db_download.setVisible(not exe)
        self.btn_db_zip.setVisible(not exe)
        self.btn_db_start.setEnabled(bool(exe) and not draait)
        self.btn_db_stop.setEnabled(draait)

    def _db_bezig(self, bezig):
        for b in (self.btn_db_download, self.btn_db_zip):
            b.setEnabled(not bezig)
        self.balk_db.setVisible(bezig)

    def _db_download(self):
        self._db_bezig(True); self.balk_db.setRange(0, 0)
        self.lbl_db_msg.setText(self.t("db_bezig_download"))
        zip_pad = os.path.join(DATA_MAP, "mariadb-download.zip")
        self._dldb = DownloadThread(mariadb_download_url, zip_pad, MARIADB_BASIS)
        self._dldb.voortgang.connect(self._db_dl_voortgang)
        self._dldb.klaar.connect(self._db_dl_klaar)
        self._dldb.start()

    def _db_zip(self):
        p, _ = QFileDialog.getOpenFileName(self, self.t("db_zip"), BASIS,
                                           "Zip (*.zip)")
        if not p:
            return
        self._db_bezig(True); self.balk_db.setRange(0, 0)
        ok, fout = pak_uit(p, MARIADB_BASIS)
        self._db_bezig(False)
        if not ok:
            QMessageBox.warning(self, APP_NAAM, self.t("ond_fout").format(fout=fout))
            return
        self._db_na_uitpakken()

    def _db_dl_voortgang(self, gedaan, totaal):
        if totaal > 0:
            self.balk_db.setRange(0, 100)
            self.balk_db.setValue(int(gedaan * 100 / totaal))
        mb = "%.0f / %.0f MB" % (gedaan / 1048576.0, totaal / 1048576.0) \
            if totaal else "%.0f MB" % (gedaan / 1048576.0)
        self.lbl_db_msg.setText(self.t("db_bezig_download") + " " + mb)

    def _db_dl_klaar(self, ok, resultaat):
        self._db_bezig(False); self.lbl_db_msg.setText("")
        if not ok:
            QMessageBox.warning(self, APP_NAAM,
                                self.t("ond_fout").format(fout=resultaat))
            return
        self._db_na_uitpakken()

    def _db_na_uitpakken(self):
        exe = vind_mariadbd(MARIADB_BASIS)
        if not exe:
            QMessageBox.warning(self, APP_NAAM, self.t("db_geen_exe"))
            return
        self.cfg["db_exe"] = exe
        m = re.search(r"mariadb-([\d.]+)-winx64", exe)
        self.cfg["db_versie"] = m.group(1) if m else ""
        bewaar_config(self.cfg)
        self._db_ververs()
        QMessageBox.information(self, APP_NAAM, self.t("db_klaar_install"))

    def _db_start(self):
        exe = mariadbd_uit_config(self.cfg)
        self.lbl_db_msg.setText(self.t("db_bezig_start"))
        QApplication.processEvents()
        ok, fout = self.db.start(exe, MARIADB_DATA)
        self.lbl_db_msg.setText("")
        if not ok:
            QMessageBox.warning(self, APP_NAAM,
                                self.t("db_start_mislukt").format(
                                    fout=verklaar_poortfout(fout, "database")))
        else:
            db_wacht_klaar(self.cfg.get("db_wachtwoord", ""), timeout=20)
        self._db_ververs()
        self._db_lijst_ververs()

    def _db_stop(self):
        self.db.stop()
        self._db_ververs()
        self.lijst_db.clear()

    def _db_fout_tonen(self, e):
        tekst = str(e)
        if "pymysql" in tekst.lower() or "No module" in tekst:
            QMessageBox.warning(self, APP_NAAM, self.t("db_geen_pymysql"))
        else:
            QMessageBox.warning(self, APP_NAAM,
                                self.t("db_verbind_fout").format(fout=tekst))

    def _db_wachtwoord(self):
        if not self.db.draait():
            QMessageBox.information(self, APP_NAAM, self.t("db_eerst_starten"))
            return
        nieuw = self.veld_db_pw.text()
        try:
            ok, fout = db_zet_root_wachtwoord(self.cfg.get("db_wachtwoord", ""),
                                              nieuw)
        except Exception as e:
            self._db_fout_tonen(e)
            return
        if not ok:
            QMessageBox.warning(self, APP_NAAM,
                                self.t("db_verbind_fout").format(fout=fout))
            return
        self.cfg["db_wachtwoord"] = nieuw
        bewaar_config(self.cfg)
        QMessageBox.information(self, APP_NAAM, self.t("db_wachtwoord_klaar"))

    def _db_maak(self):
        if not self.db.draait():
            QMessageBox.information(self, APP_NAAM, self.t("db_eerst_starten"))
            return
        naam = self.veld_db_naam.text().strip()
        if not naam:
            return
        try:
            ok, fout = db_maak_database(naam, self.cfg.get("db_wachtwoord", ""))
        except Exception as e:
            self._db_fout_tonen(e)
            return
        if not ok:
            QMessageBox.warning(self, APP_NAAM,
                                self.t("db_verbind_fout").format(fout=fout))
            return
        self.veld_db_naam.clear()
        self._db_lijst_ververs()

    def _db_verwijder(self):
        it = self.lijst_db.currentItem()
        if not it or not self.db.draait():
            return
        naam = it.text()
        if QMessageBox.question(
                self, APP_NAAM, self.t("db_verwijder_bevestig").format(naam=naam)
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            db_verwijder_database(naam, self.cfg.get("db_wachtwoord", ""))
        except Exception as e:
            self._db_fout_tonen(e)
            return
        self._db_lijst_ververs()

    def _db_lijst_ververs(self):
        self.lijst_db.clear()
        if not self.db.draait():
            return
        try:
            for naam in db_lijst_databases(self.cfg.get("db_wachtwoord", "")):
                self.lijst_db.addItem(naam)
        except Exception:
            pass

    def _db_tabellen(self):
        if not self.db.draait():
            QMessageBox.information(self, APP_NAAM, self.t("db_eerst_starten"))
            return
        it = self.lijst_db.currentItem()
        if not it:
            QMessageBox.information(self, APP_NAAM, self.t("db_kies_database"))
            return
        TabellenDialoog(self, it.text(),
                        self.cfg.get("db_wachtwoord", "")).exec()

    # ---- poorten tab ----
    def _tab_poorten(self):
        w = QWidget(); lay = QVBoxLayout(w)
        intro = QLabel(self.t("po_intro"))
        intro.setObjectName("uitleg"); intro.setWordWrap(True)
        lay.addWidget(intro)
        # IP-adressen
        ipkop = QLabel(self.t("ip_kop")); ipkop.setObjectName("kop")
        lay.addWidget(ipkop)
        ipform = QFormLayout()
        self.veld_intern_ip = QLineEdit(); self.veld_intern_ip.setReadOnly(True)
        ipform.addRow(self.t("ip_intern"), self.veld_intern_ip)
        rij_e = QHBoxLayout()
        self.veld_extern_ip = QLineEdit(); self.veld_extern_ip.setReadOnly(True)
        rij_e.addWidget(self.veld_extern_ip, 1)
        b_ip = QPushButton(self.t("ip_vernieuw"))
        b_ip.clicked.connect(self._ip_extern_ophalen)
        rij_e.addWidget(b_ip)
        ipform.addRow(self.t("ip_extern"), self._wrap(rij_e))
        lay.addLayout(ipform)
        ip_uit = QLabel(self.t("ip_uitleg"))
        ip_uit.setObjectName("uitleg"); ip_uit.setWordWrap(True)
        lay.addWidget(ip_uit)
        kop = QLabel(self.t("po_sites_kop")); kop.setObjectName("kop")
        lay.addWidget(kop)
        self.poort_vak = QWidget()
        self.poort_vak_lay = QVBoxLayout(self.poort_vak)
        self.poort_vak_lay.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setWidget(self.poort_vak); scroll.setMinimumHeight(150)
        lay.addWidget(scroll, 1)
        kop2 = QLabel(self.t("po_globaal_kop")); kop2.setObjectName("kop")
        lay.addWidget(kop2)
        form = QFormLayout()
        self.spin_https = QSpinBox(); self.spin_https.setRange(1, 65535)
        self.spin_https.setValue(int(self.cfg.get("https_poort", 443)))
        self.lbl_https_status = QLabel("")
        rij_h = QHBoxLayout(); rij_h.addWidget(self.spin_https)
        rij_h.addWidget(self.lbl_https_status); rij_h.addStretch(1)
        form.addRow(self.t("po_https"), self._wrap(rij_h))
        self.spin_db = QSpinBox(); self.spin_db.setRange(1, 65535)
        self.spin_db.setValue(int(self.cfg.get("db_poort", 3306)))
        self.lbl_db_poort_status = QLabel("")
        rij_d = QHBoxLayout(); rij_d.addWidget(self.spin_db)
        rij_d.addWidget(self.lbl_db_poort_status); rij_d.addStretch(1)
        form.addRow(self.t("po_mariadb"), self._wrap(rij_d))
        lay.addLayout(form)
        rij = QHBoxLayout()
        b_check = QPushButton(self.t("po_controleer"))
        b_check.clicked.connect(self._poorten_controleer)
        rij.addWidget(b_check)
        b_op = QPushButton(self.t("po_opslaan")); b_op.setObjectName("primair")
        b_op.clicked.connect(self._poorten_opslaan)
        rij.addWidget(b_op)
        rij.addStretch(1)
        lay.addLayout(rij)
        uit = QLabel(self.t("po_uitleg"))
        uit.setObjectName("uitleg"); uit.setWordWrap(True)
        lay.addWidget(uit)
        self._poorten_vul()
        self._ip_ververs()
        return w

    def _ip_ververs(self):
        self.veld_intern_ip.setText(intern_ip() or "-")
        self._ip_extern_ophalen()

    def _ip_extern_ophalen(self):
        self.veld_extern_ip.setText(self.t("ip_bezig"))
        self._ipt = ExterneIPThread()
        self._ipt.klaar.connect(
            lambda ip: self.veld_extern_ip.setText(ip or self.t("ip_geen")))
        self._ipt.start()

    def _wrap(self, layout):
        h = QWidget(); h.setLayout(layout)
        return h

    def _poorten_vul(self):
        if not hasattr(self, "poort_vak_lay"):
            return
        while self.poort_vak_lay.count():
            it = self.poort_vak_lay.takeAt(0)
            if it.widget():
                it.widget().setParent(None)
        self.poort_spins = []
        sites = self.cfg.get("sites", [])
        if not sites:
            self.poort_vak_lay.addWidget(QLabel(self.t("po_geen_sites")))
            return
        for i, s in enumerate(sites):
            rij = QHBoxLayout()
            naam = QLabel(s.get("naam", "site")); naam.setMinimumWidth(180)
            rij.addWidget(naam)
            rij.addWidget(QLabel("HTTP:"))
            spin = QSpinBox(); spin.setRange(1, 65535)
            spin.setValue(int(s.get("poort") or 80))
            rij.addWidget(spin)
            status = QLabel(""); rij.addWidget(status)
            rij.addStretch(1)
            self.poort_vak_lay.addWidget(self._wrap(rij))
            self.poort_spins.append((i, spin, status))

    def _poort_status_tekst(self, poort):
        if poort_vrij(poort):
            return self.t("po_vrij"), GOED
        return self.t("po_bezet"), WARN

    def _poorten_controleer(self):
        for _i, spin, status in getattr(self, "poort_spins", []):
            tekst, kleur = self._poort_status_tekst(spin.value())
            status.setText(tekst); status.setStyleSheet("color:%s;" % kleur)
        for spin, lbl in ((self.spin_https, self.lbl_https_status),
                          (self.spin_db, self.lbl_db_poort_status)):
            tekst, kleur = self._poort_status_tekst(spin.value())
            lbl.setText(tekst); lbl.setStyleSheet("color:%s;" % kleur)

    def _poorten_opslaan(self):
        sites = self.cfg.get("sites", [])
        for i, spin, _s in getattr(self, "poort_spins", []):
            if i < len(sites):
                sites[i]["poort"] = spin.value()
        self.cfg["https_poort"] = self.spin_https.value()
        self.cfg["db_poort"] = self.spin_db.value()
        zet_actieve_poorten(self.cfg["https_poort"], self.cfg["db_poort"])
        bewaar_config(self.cfg)
        self._ververs_sites()
        QMessageBox.information(self, APP_NAAM, self.t("po_opgeslagen"))

    def _menu(self):
        mb = self.menuBar()
        m1 = mb.addMenu(self.t("menu_inst"))
        a = QAction(self.t("instellingen"), self)
        a.triggered.connect(lambda: (InstellingenDialoog(self).exec(),
                                     self._herstart_hint()))
        m1.addAction(a)
        m1.addSeparator()
        q = QAction(self.t("sluiten"), self); q.setShortcut("Ctrl+Q")
        q.triggered.connect(self.close)
        m1.addAction(q)
        m2 = mb.addMenu(self.t("menu_help"))
        g = QAction(self.t("snelgids"), self); g.setShortcut("F1")
        g.triggered.connect(lambda: SnelgidsDialoog(self).exec())
        m2.addAction(g)
        wk = QAction(self.t("welkom_menu"), self)
        wk.triggered.connect(lambda: WelkomDialoog(self).exec())
        m2.addAction(wk)
        dl = QAction(self.t("downloads_menu"), self)
        dl.triggered.connect(lambda: LinksDialoog(self).exec())
        m2.addAction(dl)
        d = QAction("\u2665 " + self.t("donatie"), self)
        d.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(DONATIE_URL)))
        m2.addAction(d)
        ov = QAction(self.t("over"), self)
        ov.triggered.connect(lambda: OverDialoog(self).exec())
        m2.addAction(ov)

    def _herstart_hint(self):
        taal = self.cfg.get("taal", "auto")
        self.taal = taal if taal in ("nl", "en") else detecteer_taal()

    # ---- server-acties ----
    def _ververs_server(self):
        draait = self.server.draait()
        self.lbl_status.setText(self.t("status_aan") if draait
                                else self.t("status_uit"))
        self.lbl_status.setObjectName("statusaan" if draait else "statusuit")
        self.lbl_status.setStyleSheet(self.styleSheet())
        self.lbl_status.style().unpolish(self.lbl_status)
        self.lbl_status.style().polish(self.lbl_status)
        if self.apache and self.apache.get("httpd_exe"):
            self.lbl_apache.setText(self.t("apache_gevonden").format(
                pad=self.apache["httpd_exe"]))
            self.btn_apache.setVisible(False)
            self.btn_download.setVisible(False)
        else:
            self.lbl_apache.setText(self.t("apache_niet"))
            self.btn_apache.setVisible(True)
            self.btn_download.setVisible(True)
        self.btn_start.setEnabled(not draait)
        self.btn_stop.setEnabled(draait)

    def _kies_apache(self):
        p, _ = QFileDialog.getOpenFileName(self, self.t("apache_kiezen"),
                                           r"C:\\", "httpd.exe (httpd.exe)")
        if p:
            d = os.path.dirname(os.path.dirname(p))
            self.cfg["httpd_exe"] = p
            self.cfg["apache_dir"] = d
            conf = os.path.join(d, "conf", "httpd.conf")
            self.cfg["httpd_conf"] = conf if os.path.isfile(conf) else ""
            bewaar_config(self.cfg)
            self.apache = apache_uit_config(self.cfg)
            self._ververs_server()

    def _actieve_php_dir(self):
        if self.cfg.get("php_aan") and self.cfg.get("php_dir"):
            d = self.cfg["php_dir"]
            if os.path.isdir(d):
                return d
        return ""

    def _start(self):
        actieve = [s for s in self.cfg.get("sites", [])
                   if s.get("aan", True) and s.get("map")]
        if not actieve:
            QMessageBox.information(self, APP_NAAM, self.t("geen_sites"))
            self.tabs.setCurrentIndex(1)
            return
        ok, fout = self.server.start(self.apache, self.cfg.get("sites", []),
                                     self._actieve_php_dir())
        if not ok:
            QMessageBox.warning(self, APP_NAAM,
                                self.t("start_mislukt").format(
                                    fout=verklaar_poortfout(fout, "webserver")))
        self._ververs_server()
        if ok:
            self._le_auto_vernieuw()

    def _stop(self):
        self.server.stop()
        self._ververs_server()

    def _auto_start(self):
        """Opruimen + (indien aan) server/database starten op de achtergrond,
        zodat het venster en het welkomscherm niet bevriezen."""
        heeft_werk = self.cfg.get("auto_start", True) and (
            bool(self.apache and self.apache.get("httpd_exe"))
            or bool(mariadbd_uit_config(self.cfg)))
        if heeft_werk:
            try:
                self.statusBar().showMessage(self.t("opstart_bezig"))
                self.lbl_status.setText(self.t("status_bezig"))
                self.lbl_db_status.setText(self.t("status_bezig"))
                self.opstart_balk.setVisible(True)
            except Exception:
                pass
        self._opstart_thread = OpstartThread(self)
        self._opstart_thread.klaar.connect(self._na_opstart)
        self._opstart_thread.start()

    def _na_opstart(self):
        try:
            self.statusBar().clearMessage()
            self.opstart_balk.setVisible(False)
        except Exception:
            pass
        self._ververs_server()
        self._db_ververs()
        try:
            self._db_lijst_ververs()
        except Exception:
            pass

    def _site_url(self, s):
        adres = s.get("servernaam") or "localhost"
        if (s.get("ssl_aan") and s.get("ssl_cert") and s.get("ssl_key")
                and os.path.isfile(s["ssl_cert"]) and os.path.isfile(s["ssl_key"])):
            hp = ACTIEVE_HTTPS_POORT
            return "https://%s%s/" % (adres, "" if hp == 443 else ":%d" % hp)
        poort = int(s.get("poort") or 80)
        return "http://%s%s/" % (adres, "" if poort == 80 else ":%d" % poort)

    def _open_browser(self):
        sites = [s for s in self.cfg.get("sites", [])
                 if s.get("aan", True) and s.get("map")]
        if not sites:
            QMessageBox.information(self, APP_NAAM, self.t("geen_sites"))
            return
        if len(sites) == 1:
            QDesktopServices.openUrl(QUrl(self._site_url(sites[0])))
            return
        namen = ["%s  (%s)" % (s.get("naam", ""), self._site_url(s)) for s in sites]
        keuze, ok = QInputDialog.getItem(
            self, APP_NAAM, self.t("kies_site"), namen, 0, False)
        if ok and keuze in namen:
            QDesktopServices.openUrl(QUrl(self._site_url(sites[namen.index(keuze)])))

    def _toon_config(self):
        if not self.apache:
            QMessageBox.information(self, APP_NAAM, self.t("apache_niet"))
            return
        try:
            pad = bouw_runconfig(self.apache, self.cfg.get("sites", []),
                                 self._actieve_php_dir())
            with open(pad, encoding="utf-8", errors="replace") as f:
                tekst = f.read()
        except Exception as e:
            tekst = "Fout: %s" % e
        ConfigDialoog(self, tekst).exec()

    # ---- site-acties ----
    def _ververs_sites(self):
        self.lijst.clear()
        for i, s in enumerate(self.cfg.get("sites", [])):
            tekst = self.t("site_item").format(
                naam=s.get("naam", ""), servernaam=s.get("servernaam", "localhost"),
                poort=s.get("poort", 80), map=s.get("map", ""))
            if not s.get("aan", True):
                tekst += self.t("site_uit")
            it = QListWidgetItem(tekst)
            it.setData(Qt.ItemDataRole.UserRole, i)
            self.lijst.addItem(it)
        if hasattr(self, "ssl_combo"):
            self._ssl_vul_combo()
            self._ssl_ververs()
        if hasattr(self, "poort_vak_lay"):
            self._poorten_vul()

    def _site_toevoegen(self):
        d = SiteDialoog(self)
        if d.exec():
            self.cfg.setdefault("sites", []).append(d.resultaat)
            bewaar_config(self.cfg)
            self._ververs_sites()

    def _geselecteerde_index(self):
        it = self.lijst.currentItem()
        if not it:
            return None
        return it.data(Qt.ItemDataRole.UserRole)

    def _site_bewerken(self):
        idx = self._geselecteerde_index()
        if idx is None:
            return
        d = SiteDialoog(self, self.cfg["sites"][idx])
        if d.exec():
            self.cfg["sites"][idx] = d.resultaat
            bewaar_config(self.cfg)
            self._ververs_sites()

    def _site_verwijderen(self):
        idx = self._geselecteerde_index()
        if idx is None:
            return
        del self.cfg["sites"][idx]
        bewaar_config(self.cfg)
        self._ververs_sites()

    def _site_openen(self):
        idx = self._geselecteerde_index()
        if idx is None:
            QMessageBox.information(self, APP_NAAM, self.t("kies_eerst"))
            return
        s = self.cfg["sites"][idx]
        QDesktopServices.openUrl(QUrl(self._site_url(s)))

    def _site_website(self):
        idx = self._geselecteerde_index()
        if idx is None:
            QMessageBox.information(self, APP_NAAM, self.t("kies_eerst"))
            return
        s = self.cfg["sites"][idx]
        if not s.get("map"):
            QMessageBox.information(self, APP_NAAM, self.t("wb_geen_map"))
            return
        WebsiteBouwerDialoog(self, s).exec()

    def _site_lan_url(self, s):
        """Site-URL met het LAN-IP (zodat je telefoon erbij kan)."""
        ip = intern_ip() or "localhost"
        if (s.get("ssl_aan") and s.get("ssl_cert") and s.get("ssl_key")
                and os.path.isfile(s["ssl_cert"]) and os.path.isfile(s["ssl_key"])):
            hp = ACTIEVE_HTTPS_POORT
            return "https://%s%s/" % (ip, "" if hp == 443 else ":%d" % hp)
        poort = int(s.get("poort") or 80)
        return "http://%s%s/" % (ip, "" if poort == 80 else ":%d" % poort)

    def _site_qr(self):
        idx = self._geselecteerde_index()
        if idx is None:
            QMessageBox.information(self, APP_NAAM, self.t("kies_eerst"))
            return
        s = self.cfg["sites"][idx]
        QrDialoog(self, self._site_lan_url(s)).exec()

    def _scan_mappen(self):
        php_nieuw = scan_php(self.cfg)
        aantal = scan_sites(self.cfg)
        bewaar_config(self.cfg)
        self._ververs_sites()
        self.apache = apache_uit_config(self.cfg)
        self._ververs_server()
        self._ond_ververs()
        delen = []
        if aantal:
            delen.append(self.t("scan_sites_n").format(n=aantal))
        else:
            delen.append(self.t("scan_geen_sites"))
        if php_nieuw:
            delen.append(self.t("scan_php_n").format(
                versie=self.cfg.get("php_versie", "?")))
        QMessageBox.information(self, APP_NAAM, "\n".join(delen))

    def closeEvent(self, e):
        # Naar systeemvak i.p.v. afsluiten (als ingesteld en tray beschikbaar).
        if (not self._echt_afsluiten and self._tray
                and self.cfg.get("naar_systeemvak", True)):
            e.ignore()
            if not self.cfg.get("systeemvak_uitleg_getoond", False):
                QMessageBox.information(self, APP_NAAM, self.t("tray_uitleg"))
                self.cfg["systeemvak_uitleg_getoond"] = True
                bewaar_config(self.cfg)
            self.hide()
            try:
                self._tray.showMessage(APP_NAAM, self.t("tray_actief"),
                                       app_icoon(), 4000)
            except Exception:
                pass
            return
        self.server.stop()
        self.db.stop()
        if self._tray:
            try:
                self._tray.hide()
            except Exception:
                pass
        super().closeEvent(e)
        try:
            QApplication.instance().quit()
        except Exception:
            pass


def main():
    # Windows-taakbalk: eigen AppUserModelID, anders pakt de taakbalk het
    # standaard (python/pythonw) icoon i.p.v. dat van DraveServer.
    if WINDOWS:
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "Dravenlock.DraveServer")
        except Exception:
            pass
    # WebEngine (ingebouwde website-bouwer): software-compositing voorkomt
    # witte vlakken op sommige Windows-GPU's; gedeelde GL-context vereist.
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                          "--disable-gpu --disable-gpu-compositing")
    try:
        QApplication.setAttribute(
            Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    except Exception:
        pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAAM)
    app.setWindowIcon(app_icoon())
    _pas_palet_toe(app)
    v = Hoofdvenster()
    naar_vak = ("--systeemvak" in sys.argv) and bool(v._tray)
    if naar_vak:
        # Met Windows meegestart: stilletjes op de achtergrond (systeemvak).
        app.setQuitOnLastWindowClosed(False)
        try:
            v._tray.showMessage(APP_NAAM, v.t("tray_actief"), app_icoon(), 4000)
        except Exception:
            pass
    else:
        v.showMaximized()
        if v.cfg.get("toon_welkom", True):
            QTimer.singleShot(0, lambda: WelkomDialoog(v).exec())
    QTimer.singleShot(300, v._ssl_startcheck)
    QTimer.singleShot(700, v._auto_start)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
