import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ============================================================
# ACTUALIZADOR CICLÓN POLO V6.2
# FUENTE PRIMARIA:
# https://smn.conagua.gob.mx/es/pronosticos/avisos/
# aviso-de-ciclon-tropical-en-el-oceano-pacifico
#
# El portal oficial contiene un iframe a WebAviso. El script
# descubre ese iframe y extrae TODO desde el WebAviso vigente.
# NO usa PDF histórico.
# NO modifica index.html.
# ============================================================

PORTAL = (
    "https://smn.conagua.gob.mx/es/pronosticos/avisos/"
    "aviso-de-ciclon-tropical-en-el-oceano-pacifico"
)
DEFAULT_WEBAVISO = (
    "https://smn.conagua.gob.mx/tools/GUI/PortalLaravel/public/WebAviso"
)
DATOS = Path("datos_polo.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153 Safari/537.36"
    ),
    "Accept-Language": "es-MX,es;q=0.9",
    "Cache-Control": "no-cache",
}

def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()

def get(url):
    r = requests.get(url, headers=HEADERS, timeout=45)
    r.raise_for_status()
    return r

def discover_webaviso():
    r = get(PORTAL)
    soup = BeautifulSoup(r.text, "html.parser")
    for iframe in soup.find_all("iframe", src=True):
        src = urljoin(PORTAL, iframe["src"])
        if "WebAviso" in src:
            return src
    # Respaldo técnico: es el iframe oficial conocido del mismo portal.
    return DEFAULT_WEBAVISO

def field(text, start, end):
    m = re.search(start + r"\s*(.+?)(?=\s*" + end + r")", text, re.I | re.S)
    return clean(m.group(1)) if m else None

def get_current_polo_page(webaviso):
    # WebAviso puede mostrar varios ciclones activos. La vista inicial actual
    # contiene Polo; si en el futuro cambia la navegación, se cancela antes
    # de publicar datos de otro ciclón.
    r = get(webaviso)
    soup = BeautifulSoup(r.text, "html.parser")
    text = clean(soup.get_text(" ", strip=True))
    if not re.search(r"\bPolo\b", text, re.I):
        raise RuntimeError("WebAviso vigente no muestra a Polo.")
    if not re.search(r"HURAC[AÁ]N\s+POLO|TORMENTA\s+TROPICAL\s+POLO|DEPRESI[ÓO]N\s+TROPICAL\s+POLO", text, re.I):
        raise RuntimeError("No se confirmó que el detalle abierto corresponda a Polo.")
    return soup, text

def extract_forecast(soup):
    rows = []
    for table in soup.find_all("table"):
        header = clean(table.get_text(" ", strip=True))
        if not (re.search(r"D[ií]a/Hora", header, re.I)
                and re.search(r"Vientos", header, re.I)
                and re.search(r"Categor[ií]a", header, re.I)
                and re.search(r"Ubicaci[oó]n", header, re.I)):
            continue
        candidate = []
        for tr in table.find_all("tr"):
            cells = [clean(x.get_text(" ", strip=True))
                     for x in tr.find_all(["td", "th"])]
            if len(cells) < 6:
                continue
            if not re.fullmatch(r"\d{1,2}/\d{1,2}h?", cells[0]):
                continue
            candidate.append({
                "dia_hora": cells[0],
                "lat": cells[1],
                "lon": cells[2],
