import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ============================================================
# ACTUALIZADOR CICLÓN POLO V6.1
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
                "viento": cells[3],
                "categoria": cells[4],
                "ubicacion": cells[5],
            })
        if candidate:
            rows = candidate
            break
    return rows

def extract_map(soup, webaviso):
    for img in soup.find_all("img", src=True):
        src = urljoin(webaviso, img["src"])
        alt = clean(img.get("alt", ""))
        if "ImgTray" in src or re.search(r"trayectoria\s+pron[oó]stico", alt, re.I):
            return src
    return ""

def extract_date_from_history(soup, aviso):
    # La fecha se toma de la fila del MISMO aviso dentro del WebAviso actual,
    # no del PDF histórico.
    for tr in soup.find_all("tr"):
        cells = [clean(x.get_text(" ", strip=True))
                 for x in tr.find_all(["td", "th"])]
        if not cells or cells[0] != str(aviso):
            continue
        joined = " ".join(cells)
        m = re.search(r"(20\d{2}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})", joined)
        if m:
            return m.group(1), m.group(2)
    return None, None

def main():
    print("=" * 72)
    print(" ACTUALIZADOR CICLÓN POLO V6.1")
    print(" FUENTE PRIMARIA:", PORTAL)
    print(" PDF HISTÓRICO: NO UTILIZADO")
    print("=" * 72)

    webaviso = discover_webaviso()
    print("IFRAME OFICIAL:", webaviso)

    soup, t = get_current_polo_page(webaviso)

    m = re.search(r"Oc[eé]ano\s+Pac[ií]fico\s*-\s*No\.\s*Aviso:\s*(\d+)", t, re.I)
    if not m:
        raise RuntimeError("No se encontró número de aviso en WebAviso.")
    aviso = int(m.group(1))

    # Delimitadores exactos de la página oficial actual.
    hora_b = field(t, r"Hora\s+local\s*\(hora\s+GMT\)\s*\|?", r"Ubicaci[oó]n\s+del\s+centro")
    coord_b = field(t, r"Ubicaci[oó]n\s+del\s+centro\s*\|?", r"Distancia\s+al\s+lugar\s+m[aá]s\s+cercano")
    referencia = field(t, r"Distancia\s+al\s+lugar\s+m[aá]s\s+cercano\s*\|?", r"Desplazamiento\s+actual")
    movimiento = field(t, r"Desplazamiento\s+actual\s*\|?", r"Vientos\s+m[aá]ximos")
    viento_b = field(t, r"Vientos\s+m[aá]ximos\s*\[km/h\]\s*\|?", r"Presi[oó]n\s+m[ií]nima\s+central")
    presion_b = field(t, r"Presi[oó]n\s+m[ií]nima\s+central\s*\[hpa\]\s*\|?", r"Pron[oó]stico\s+de\s+lluvia")
    lluvia = field(t, r"Pron[oó]stico\s+de\s+lluvia\s*\|?", r"Zona\s+de\s+vigilancia")
    vigilancia = field(t, r"Zona\s+de\s+vigilancia\s*\|?", r"Comentarios\s+adicionales")
    comentarios = field(t, r"Comentarios\s+adicionales\s*\|?", r"Recomendaciones")

    if not all([hora_b, coord_b, referencia, movimiento, viento_b,
                presion_b, lluvia, vigilancia, comentarios]):
        raise RuntimeError("WebAviso no contiene todos los campos esperados; no se publica.")

    m = re.search(r"(\d{1,2}:\d{2})\s+horas?\s*\((\d{1,2}:\d{2})\s+horas?\s+GMT\)", hora_b, re.I)
    if not m:
        raise RuntimeError("No se pudo interpretar hora local/GMT.")
    hora, gmt = m.group(1), m.group(2)

    m = re.search(r"Latitud\s+Norte:\s*(\d+(?:\.\d+)?)\s*\|?\s*Longitud\s+Oeste:\s*(\d+(?:\.\d+)?)", coord_b, re.I)
    if not m:
        raise RuntimeError("No se pudieron interpretar coordenadas.")
    lat, lon = m.group(1), m.group(2)

    m = re.search(r"Sostenidos:\s*(\d{2,3})\s*\|?\s*Rachas:\s*(\d{2,3})", viento_b, re.I)
    if not m:
        raise RuntimeError("No se pudieron interpretar viento/rachas.")
    viento, racha = int(m.group(1)), int(m.group(2))

    m = re.search(r"(\d{3,4})", presion_b)
    if not m:
        raise RuntimeError("No se pudo interpretar presión.")
    presion = f"{m.group(1)} hPa"

    m = re.search(r"HURAC[AÁ]N\s+POLO\s+DE\s+CATEGOR[IÍ]A\s+([1-5])", t, re.I)
    if m:
        clasificacion = f"Huracán categoría {m.group(1)}"
    elif re.search(r"TORMENTA\s+TROPICAL\s+POLO", t, re.I):
        clasificacion = "Tormenta tropical"
    elif re.search(r"DEPRESI[ÓO]N\s+TROPICAL\s+POLO", t, re.I):
        clasificacion = "Depresión tropical"
    else:
        raise RuntimeError("No se pudo interpretar la clasificación de Polo.")

    fecha, hora_hist = extract_date_from_history(soup, aviso)
    if not fecha:
        raise RuntimeError("No se encontró fecha del aviso vigente en WebAviso.")

    pronostico = extract_forecast(soup)
    if not pronostico:
        raise RuntimeError("No se pudo extraer el pronóstico vigente desde WebAviso.")

    mapa = extract_map(soup, webaviso)
    if not mapa:
        raise RuntimeError("No se pudo extraer la trayectoria vigente desde WebAviso.")

    # Separa del comentario oficial el viento costero y el oleaje.
    # Se conserva el texto oficial completo en cada bloque para no perder
    # combinaciones estado/rango.
    viento_costero = comentarios
    oleaje_partes = re.findall(
        r"oleaje\s+de\s+\d+(?:\.\d+)?\s+a\s+\d+(?:\.\d+)?\s+metros?"
        r"(?:\s+de\s+altura)?\s+en\s+costas\s+de\s+[^.;]+",
        comentarios, re.I
    )
    oleaje = "; ".join(clean(x) for x in oleaje_partes)
    if not oleaje:
        oleaje = comentarios

    data = {
        "ciclon": "Polo",
        "fuente": "SMN / CONAGUA",
        "url_oficial": PORTAL,
        "url_datos": webaviso,
        "aviso": aviso,
        "fecha": fecha,
        "hora_publicacion": hora,
        "hora": hora,
        "gmt": gmt,
        "lat": lat,
        "lon": lon,
        "referencia": referencia,
        "movimiento": movimiento,
        "viento": viento,
        "racha": racha,
        "presion": presion,
        "clasificacion": clasificacion,
        "lluvia": lluvia,
        "vigilancia": vigilancia,
        "viento_costero": viento_costero,
        "oleaje": oleaje,
        "mapa": mapa,
        "pronostico": pronostico,
    }

    if racha < viento:
        raise RuntimeError("Validación fallida: racha menor que viento sostenido.")

    # Impide retroceder accidentalmente de aviso.
    if DATOS.exists():
        try:
            old = json.loads(DATOS.read_text(encoding="utf-8"))
            old_no = int(old.get("aviso", 0))
            if aviso < old_no:
                raise RuntimeError(
                    f"WebAviso devolvió aviso {aviso}; el tablero ya tiene {old_no}."
                )
        except json.JSONDecodeError:
            pass

    tmp = Path("datos_polo.json.tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )
    tmp.replace(DATOS)

    print()
    print("ACTUALIZACIÓN CORRECTA DESDE WEBAVISO")
    print("Aviso:", aviso)
    print("Fecha/Hora:", fecha, hora, "GMT:", gmt)
    print("Clasificación:", clasificacion)
    print("Posición:", lat, "N /", lon, "O")
    print("Referencia:", referencia)
    print("Movimiento:", movimiento)
    print("Viento/Rachas:", viento, "/", racha, "km/h")
    print("Presión:", presion)
    print("Lluvia:", lluvia)
    print("Vigilancia:", vigilancia)
    print("Pronóstico:", len(pronostico), "filas")
    print("Mapa:", mapa)
    print("PDF HISTÓRICO: NO UTILIZADO")
    print("datos_polo.json actualizado; index.html intacto.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERROR:", e, file=sys.stderr)
        print("No se modificó el dashboard con datos parciales.", file=sys.stderr)
        sys.exit(1)
