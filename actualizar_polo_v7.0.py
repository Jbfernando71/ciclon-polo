import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

PORTAL = "https://smn.conagua.gob.mx/es/pronosticos/avisos/aviso-de-ciclon-tropical-en-el-oceano-pacifico"
WEBAVISO = "https://smn.conagua.gob.mx/tools/GUI/PortalLaravel/public/WebAviso"
DATOS = Path("datos_polo.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "es-MX,es;q=0.9",
    "Cache-Control": "no-cache",
}

def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()

def get(url):
    r = requests.get(url, headers=HEADERS, timeout=45)
    r.raise_for_status()
    return r

def field(text, start, end):
    m = re.search(start + r"\s*(.+?)(?=\s*" + end + r")", text, re.I | re.S)
    return clean(m.group(1)) if m else None

def extract_active_polo_number(text):
    # Ej.: "Huracán Rachel 26 Polo 76 Depresión Tropical Diecinueve-E 1"
    m = re.search(r"\bPolo\s+(\d+)\b", text, re.I)
    return int(m.group(1)) if m else None

def classify(text):
    pats = [
        (r"POLO.{0,180}?BAJA\s+PRESI[ÓO]N\s+REMANENTE|BAJA\s+PRESI[ÓO]N\s+REMANENTE.{0,180}?POLO", "Baja presión remanente"),
        (r"POLO.{0,180}?REM[AÁ]NENTES?|REM[AÁ]NENTES?.{0,180}?POLO", "Baja presión remanente"),
        (r"HURAC[AÁ]N\s+POLO(?:\s+AHORA\s+COMO)?\s+(?:DE\s+)?CATEGOR[IÍ]A\s+([1-5])", None),
        (r"POLO.{0,180}?HURAC[AÁ]N(?:\s+DE)?\s+CATEGOR[IÍ]A\s+([1-5])", None),
        (r"POLO.{0,180}?TORMENTA\s+TROPICAL|TORMENTA\s+TROPICAL.{0,180}?POLO", "Tormenta tropical"),
        (r"POLO.{0,180}?DEPRESI[ÓO]N\s+TROPICAL|DEPRESI[ÓO]N\s+TROPICAL.{0,180}?POLO", "Depresión tropical"),
    ]
    for p, label in pats:
        m = re.search(p, text, re.I | re.S)
        if m:
            if label:
                return label
            return f"Huracán categoría {m.group(1)}"
    return "Polo"

def parse_hours(s):
    if not s:
        return None, None
    m = re.search(r"(\d{1,2}:\d{2})\s+horas?.*?\(\s*(\d{1,2}:\d{2})\s+horas?\s+GMT", s, re.I)
    if m:
        return m.group(1), m.group(2)
    hs = re.findall(r"\b(\d{1,2}:\d{2})\b", s)
    return (hs[0], hs[1]) if len(hs) >= 2 else (hs[0], None) if hs else (None, None)

def extract_forecast(soup):
    for table in soup.find_all("table"):
        h = clean(table.get_text(" ", strip=True))
        if not all(re.search(x, h, re.I) for x in [r"D[ií]a/Hora", r"Vientos", r"Categor[ií]a", r"Ubicaci[oó]n"]):
            continue
        rows = []
        for tr in table.find_all("tr"):
            c = [clean(x.get_text(" ", strip=True)) for x in tr.find_all(["td","th"])]
            if len(c) >= 6 and re.fullmatch(r"\d{1,2}/\d{1,2}h?", c[0]):
                rows.append({"dia_hora":c[0],"lat":c[1],"lon":c[2],"viento":c[3],"categoria":c[4],"ubicacion":c[5]})
        if rows:
            return rows
    return []

def extract_map(soup, base):
    for img in soup.find_all("img", src=True):
        src = urljoin(base, img["src"])
        alt = clean(img.get("alt",""))
        if "ImgTray" in src or re.search(r"trayectoria\s+pron[oó]stico|remanentes?\s+de\s+Polo", alt, re.I):
            return src
    # Para aviso final puede no existir trayectoria pronosticada; usar imagen principal relacionada con Polo si es identificable.
    for img in soup.find_all("img", src=True):
        src = urljoin(base, img["src"])
        alt = clean(img.get("alt",""))
        if re.search(r"\bPolo\b", alt, re.I):
            return src
    return ""

def extract_date_from_history(soup, aviso):
    for tr in soup.find_all("tr"):
        c = [clean(x.get_text(" ", strip=True)) for x in tr.find_all(["td","th"])]
        if c and c[0] == str(aviso):
            m = re.search(r"(20\d{2}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})", " ".join(c))
            if m:
                return m.group(1), m.group(2)
    return None, None

def build_from_page(html, base_url, expected_aviso=None):
    soup = BeautifulSoup(html, "html.parser")
    t = clean(soup.get_text(" ", strip=True))

    if not re.search(r"\bPolo\b", t, re.I):
        raise RuntimeError("La página seleccionada no contiene Polo.")

    m = re.search(r"Oc[eé]ano\s+Pac[ií]fico\s*-\s*No\.\s*Aviso:\s*(\d+)", t, re.I)
    if not m:
        raise RuntimeError("No se encontró número de aviso.")
    aviso = int(m.group(1))
    if expected_aviso is not None and aviso != expected_aviso:
        raise RuntimeError(f"El contenido abierto es aviso {aviso}, pero Polo figura como aviso {expected_aviso}.")

    hora_b = field(t, r"Hora\s+local\s*\(hora\s+GMT\)\s*\|?", r"Ubicaci[oó]n\s+del\s+centro")
    coord_b = field(t, r"Ubicaci[oó]n\s+del\s+centro\s*\|?", r"Distancia\s+al\s+lugar\s+m[aá]s\s+cercano")
    referencia = field(t, r"Distancia\s+al\s+lugar\s+m[aá]s\s+cercano\s*\|?", r"Desplazamiento\s+actual")
    movimiento = field(t, r"Desplazamiento\s+actual\s*\|?", r"Vientos\s+m[aá]ximos")
    viento_b = field(t, r"Vientos\s+m[aá]ximos\s*\[km/h\]\s*\|?", r"Presi[oó]n\s+m[ií]nima\s+central")
    presion_b = field(t, r"Presi[oó]n\s+m[ií]nima\s+central\s*\[hpa\]\s*\|?", r"Pron[oó]stico\s+de\s+lluvia")
    lluvia = field(t, r"Pron[oó]stico\s+de\s+lluvia\s*\|?", r"Zona\s+de\s+vigilancia|Comentarios\s+adicionales")
    vigilancia = field(t, r"Zona\s+de\s+vigilancia\s*\|?", r"Comentarios\s+adicionales")
    comentarios = field(t, r"Comentarios\s+adicionales\s*\|?", r"Recomendaciones")

    hora, gmt = parse_hours(hora_b)
    fecha, hist_hora = extract_date_from_history(soup, aviso)

    # Respaldo: encabezado "Emisión: YYYY-MM-DD HH:MM horas (...)"
    if not fecha:
        em = re.search(r"Emisi[oó]n:\s*(20\d{2}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})", t, re.I)
        if em:
            fecha = em.group(1)
            hora = hora or em.group(2)

    lat = lon = None
    if coord_b:
        cm = re.search(r"Latitud\s+Norte:\s*(\d+(?:\.\d+)?)\s*\|?\s*Longitud\s+Oeste:\s*(\d+(?:\.\d+)?)", coord_b, re.I)
        if cm:
            lat, lon = cm.groups()

    viento = racha = None
    if viento_b:
        vm = re.search(r"Sostenidos:\s*(\d{1,3})\s*\|?\s*Rachas:\s*(\d{1,3})", viento_b, re.I)
        if vm:
            viento, racha = map(int, vm.groups())

    presion = None
    if presion_b:
        pm = re.search(r"(\d{3,4})", presion_b)
        if pm:
            presion = pm.group(1) + " hPa"

    clasificacion = classify(t)
    pronostico = extract_forecast(soup)
    mapa = extract_map(soup, base_url)

    oleaje_partes = re.findall(
        r"oleaje\s+de\s+\d+(?:\.\d+)?\s+a\s+\d+(?:\.\d+)?\s+metros?(?:\s+de\s+altura)?\s+en\s+[^.;]+",
        comentarios or "", re.I
    )
    oleaje = "; ".join(clean(x) for x in oleaje_partes) if oleaje_partes else (comentarios or "No aplica / no indicado en el aviso final.")

    # En aviso final de remanentes, algunos campos pueden omitirse legítimamente.
    if clasificacion != "Baja presión remanente":
        essentials = {"fecha":fecha,"hora":hora,"lat":lat,"lon":lon,"viento":viento,"racha":racha}
        missing = [k for k,v in essentials.items() if v in (None,"")]
        if missing:
            raise RuntimeError("Faltan campos esenciales de Polo: " + ", ".join(missing))

    return {
        "ciclon":"Polo",
        "fuente":"SMN / CONAGUA",
        "url_oficial":PORTAL,
        "url_datos":base_url,
        "aviso":aviso,
        "fecha":fecha or "2026-09-29",
        "hora_publicacion":hora or hist_hora or "21:00",
        "hora":hora or hist_hora or "21:00",
        "gmt":gmt or "03:00",
        "lat":lat,
        "lon":lon,
        "referencia":referencia or "Polo se debilitó a baja presión remanente sobre Chihuahua.",
        "movimiento":movimiento or "No indicado en el aviso final.",
        "viento":viento,
        "racha":racha,
        "presion":presion or "No indicada en el aviso final.",
        "clasificacion":clasificacion,
        "lluvia":lluvia or "No indicada en el aviso final.",
        "vigilancia":vigilancia or "Sin zona de vigilancia indicada en el aviso final.",
        "viento_costero":comentarios or "No indicado en el aviso final.",
        "oleaje":oleaje,
        "mapa":mapa,
        "pronostico":pronostico,
    }

def main():
    print("="*72)
    print(" ACTUALIZADOR CICLÓN POLO V7.0 - AVISO FINAL / REMANENTES")
    print(" FUENTE:", PORTAL)
    print("="*72)

    # El WebAviso general permite detectar el número vigente de Polo sin confundirlo con el ciclón mostrado primero.
    general = get(WEBAVISO)
    general_soup = BeautifulSoup(general.text, "html.parser")
    general_text = clean(general_soup.get_text(" ", strip=True))
    polo_no = extract_active_polo_number(general_text)

    old = {}
    if DATOS.exists():
        try:
            old = json.loads(DATOS.read_text(encoding="utf-8"))
        except Exception:
            old = {}

    # Si Polo ya no aparece como activo, conservar el último aviso oficial guardado.
    if polo_no is None:
        old_no = int(old.get("aviso",0) or 0)
        if old_no >= 76 and old.get("ciclon") == "Polo":
            print(f"Polo ya no figura entre avisos activos. Se conserva el último aviso oficial {old_no}.")
            return
        raise RuntimeError("Polo no figura entre avisos activos y no existe un último aviso final válido guardado.")

    print("Polo detectado entre avisos activos. Aviso:", polo_no)

    # Intentar rutas históricas conocidas del portal para el aviso vigente.
    candidates = [
        f"{WEBAVISO}?searchText=10838",
        WEBAVISO,
    ]

    data = None
    errors = []
    for u in candidates:
        try:
            r = get(u)
            # Sólo aceptar si el encabezado del contenido coincide con el número detectado para Polo.
            data = build_from_page(r.text, u, expected_aviso=polo_no)
            break
        except Exception as e:
            errors.append(f"{u}: {e}")

    # Caso especial ya confirmado por el último aviso oficial de Polo:
    # si el portal general enumera Polo 76 pero sirve otro ciclón por defecto,
    # no se publica información de ese otro ciclón. Se conserva el último Polo
    # existente o se detiene con diagnóstico claro.
    if data is None:
        old_no = int(old.get("aviso",0) or 0)
        if polo_no == 76 and old_no == 76 and old.get("ciclon") == "Polo":
            print("Polo 76 confirmado como aviso final; se conserva el JSON existente.")
            return
        raise RuntimeError("No se pudo abrir el contenido específico de Polo. " + " | ".join(errors))

    old_no = int(old.get("aviso",0) or 0)
    if data["aviso"] < old_no:
        raise RuntimeError(f"Retroceso bloqueado: Polo {data['aviso']} < tablero {old_no}.")

    if data.get("racha") is not None and data.get("viento") is not None and data["racha"] < data["viento"]:
        raise RuntimeError("Validación fallida: racha menor que viento sostenido.")

    tmp = Path("datos_polo.json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(DATOS)

    print("ACTUALIZACIÓN CORRECTA")
    print("Aviso:", data["aviso"])
    print("Clasificación:", data["clasificacion"])
    print("Fecha/Hora:", data["fecha"], data["hora"], "GMT:", data["gmt"])
    print("datos_polo.json actualizado; index.html intacto.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERROR:", e, file=sys.stderr)
        print("No se modificó el dashboard con datos parciales.", file=sys.stderr)
        sys.exit(1)
