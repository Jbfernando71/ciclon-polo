import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

PORTAL = "https://smn.conagua.gob.mx/es/pronosticos/avisos/aviso-de-ciclon-tropical-en-el-oceano-pacifico"

# V6.7: la fuente de entrada es la página oficial del SMN indicada por el usuario.
# Playwright reproduce la selección del aviso activo "Huracán Polo" como un navegador real.
WEBAVISO_POLO = PORTAL

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

def get_current_polo_page(url):
    """
    Abre el portal oficial con Chromium, localiza el aviso activo de Polo
    (en la página o en cualquiera de sus iframes), lo selecciona y devuelve
    exclusivamente el HTML que contiene los datos de Polo.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1600, "height": 1200},
            user_agent=HEADERS["User-Agent"],
            locale="es-MX",
        )
        page.goto(url, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(5000)

        # Buscar y pulsar el aviso "Polo" en página principal o iframes.
        clicked = False
        for _ in range(4):
            for fr in page.frames:
                try:
                    loc = fr.get_by_text(re.compile(r"\b(?:Huracán\s+)?Polo\b", re.I))
                    if loc.count():
                        # Preferir un elemento visible y clicable.
                        for i in range(min(loc.count(), 10)):
                            item = loc.nth(i)
                            if item.is_visible():
                                try:
                                    item.click(timeout=5000)
                                    clicked = True
                                    break
                                except Exception:
                                    pass
                    if clicked:
                        break
                except Exception:
                    pass
            if clicked:
                page.wait_for_timeout(5000)
                break
            page.wait_for_timeout(2000)

        # Elegir el frame cuyo contenido corresponda realmente al aviso de Polo.
        chosen_html = None
        chosen_url = None
        chosen_text = None

        for _ in range(8):
            for fr in page.frames:
                try:
                    html = fr.content()
                    soup = BeautifulSoup(html, "html.parser")
                    txt = clean(soup.get_text(" ", strip=True))
                    if (
                        re.search(r"\bPolo\b", txt, re.I)
                        and re.search(r"Oc[eé]ano\s+Pac[ií]fico\s*-\s*No\.\s*Aviso:\s*\d+", txt, re.I)
                        and re.search(r"Ubicaci[oó]n\s+del\s+centro", txt, re.I)
                    ):
                        chosen_html = html
                        chosen_url = fr.url or url
                        chosen_text = txt
                        break
                except Exception:
                    pass
            if chosen_html:
                break
            page.wait_for_timeout(2000)

        browser.close()

    if not chosen_html:
        raise RuntimeError(
            "El navegador no encontró un panel de datos de Polo en la página oficial del SMN."
        )

    soup = BeautifulSoup(chosen_html, "html.parser")
    if not re.search(r"\bPolo\b", chosen_text or "", re.I):
        raise RuntimeError("El panel seleccionado no corresponde a Polo; no se publica.")

    # Guardamos la URL real del frame para resolver correctamente la imagen.
    soup._polo_base_url = chosen_url
    return soup, chosen_text


def extract_forecast(soup):
    for table in soup.find_all("table"):
        h = clean(table.get_text(" ", strip=True))
        if not all(re.search(x, h, re.I) for x in [
            r"D[ií]a/Hora", r"Vientos", r"Categor[ií]a", r"Ubicaci[oó]n"
        ]):
            continue

        rows = []
        for tr in table.find_all("tr"):
            c = [clean(x.get_text(" ", strip=True)) for x in tr.find_all(["td", "th"])]
            if len(c) >= 6 and re.fullmatch(r"\d{1,2}/\d{1,2}h?", c[0]):
                rows.append({
                    "dia_hora": c[0],
                    "lat": c[1],
                    "lon": c[2],
                    "viento": c[3],
                    "categoria": c[4],
                    "ubicacion": c[5],
                })
        if rows:
            return rows
    return []

def extract_map(soup, url):
    base_url = getattr(soup, "_polo_base_url", None) or url
    for img in soup.find_all("img", src=True):
        src = urljoin(base_url, img["src"])
        alt = clean(img.get("alt", ""))
        if "ImgTray" in src or re.search(r"trayectoria\s+pron[oó]stico", alt, re.I):
            return src
    return ""

def extract_date(soup, aviso):
    for tr in soup.find_all("tr"):
        c = [clean(x.get_text(" ", strip=True)) for x in tr.find_all(["td", "th"])]
        if c and c[0] == str(aviso):
            m = re.search(r"(20\d{2}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})", " ".join(c))
            if m:
                return m.group(1)
    return None

def classify(t):
    pats = [
        r"HURAC[AÁ]N\s+POLO(?:\s+AHORA\s+COMO)?\s+(?:DE\s+)?CATEGOR[IÍ]A\s+([1-5])",
        r"POLO.{0,120}?HURAC[AÁ]N(?:\s+DE)?\s+CATEGOR[IÍ]A\s+([1-5])",
        r"HURAC[AÁ]N(?:\s+DE)?\s+CATEGOR[IÍ]A\s+([1-5]).{0,120}?POLO",
    ]
    for p in pats:
        m = re.search(p, t, re.I | re.S)
        if m:
            return f"Huracán categoría {m.group(1)}"

    if re.search(
        r"POLO.{0,120}?TORMENTA\s+TROPICAL|TORMENTA\s+TROPICAL.{0,120}?POLO",
        t, re.I | re.S
    ):
        return "Tormenta tropical"

    if re.search(
        r"POLO.{0,120}?DEPRESI[ÓO]N\s+TROPICAL|DEPRESI[ÓO]N\s+TROPICAL.{0,120}?POLO",
        t, re.I | re.S
    ):
        return "Depresión tropical"

    raise RuntimeError("No se pudo interpretar la clasificación de Polo desde WebAviso.")

def parse_hours(hora_b):
    # Admite:
    # 21:00 horas (03:00 horas GMT)
    # 21:00 horas (03:00 horas GMT del día 25 de septiembre)
    m = re.search(
        r"(\d{1,2}:\d{2})\s+horas?\s*"
        r"\(\s*(\d{1,2}:\d{2})\s+horas?\s+GMT\b[^)]*\)",
        hora_b,
        re.I,
    )
    if m:
        return m.group(1), m.group(2)

    horas = re.findall(r"\b(\d{1,2}:\d{2})\b", hora_b)
    if len(horas) >= 2:
        return horas[0], horas[1]

    raise RuntimeError(f"No se pudo interpretar hora local/GMT. Bloque recibido: {hora_b!r}")

def main():
    print("=" * 72)
    print(" ACTUALIZADOR CICLÓN POLO V6.7")
    print(" FUENTE PRIMARIA:", PORTAL)
    print(" PORTAL OFICIAL SMN:", PORTAL)
    print(" PDF HISTÓRICO: NO UTILIZADO")
    print("=" * 72)

    # V6.7: abre la página oficial como navegador y selecciona el aviso activo de Polo.
    web = PORTAL
    soup, t = get_current_polo_page(web)

    m = re.search(r"Oc[eé]ano\s+Pac[ií]fico\s*-\s*No\.\s*Aviso:\s*(\d+)", t, re.I)
    if not m:
        raise RuntimeError("No se encontró número de aviso de Polo en WebAviso.")
    aviso = int(m.group(1))

    hora_b = field(
        t,
        r"Hora\s+local\s*\(hora\s+GMT\)\s*\|?",
        r"Ubicaci[oó]n\s+del\s+centro",
    )
    coord_b = field(
        t,
        r"Ubicaci[oó]n\s+del\s+centro\s*\|?",
        r"Distancia\s+al\s+lugar\s+m[aá]s\s+cercano",
    )
    referencia = field(
        t,
        r"Distancia\s+al\s+lugar\s+m[aá]s\s+cercano\s*\|?",
        r"Desplazamiento\s+actual",
    )
    movimiento = field(
        t,
        r"Desplazamiento\s+actual\s*\|?",
        r"Vientos\s+m[aá]ximos",
    )
    viento_b = field(
        t,
        r"Vientos\s+m[aá]ximos\s*\[km/h\]\s*\|?",
        r"Presi[oó]n\s+m[ií]nima\s+central",
    )
    presion_b = field(
        t,
        r"Presi[oó]n\s+m[ií]nima\s+central\s*\[hpa\]\s*\|?",
        r"Pron[oó]stico\s+de\s+lluvia",
    )

    vigilancia = field(
        t,
        r"Zona\s+de\s+vigilancia\s*\|?",
        r"Comentarios\s+adicionales",
    )

    if vigilancia:
        lluvia = field(
            t,
            r"Pron[oó]stico\s+de\s+lluvia\s*\|?",
            r"Zona\s+de\s+vigilancia",
        )
    else:
        lluvia = field(
            t,
            r"Pron[oó]stico\s+de\s+lluvia\s*\|?",
            r"Comentarios\s+adicionales",
        )
        vigilancia = "Sin zona de vigilancia indicada en el aviso vigente del SMN."

    comentarios = field(
        t,
        r"Comentarios\s+adicionales\s*\|?",
        r"Recomendaciones",
    )

    req = {
        "hora": hora_b,
        "coordenadas": coord_b,
        "referencia": referencia,
        "movimiento": movimiento,
        "viento": viento_b,
        "presion": presion_b,
        "lluvia": lluvia,
        "comentarios": comentarios,
    }
    faltan = [k for k, v in req.items() if not v]
    if faltan:
        raise RuntimeError(
            "WebAviso de Polo no contiene campos esenciales: "
            + ", ".join(faltan)
            + "; no se publica."
        )

    hora, gmt = parse_hours(hora_b)

    m = re.search(
        r"Latitud\s+Norte:\s*(\d+(?:\.\d+)?)\s*\|?\s*"
        r"Longitud\s+Oeste:\s*(\d+(?:\.\d+)?)",
        coord_b,
        re.I,
    )
    if not m:
        raise RuntimeError("No se pudieron interpretar coordenadas de Polo.")
    lat, lon = m.groups()

    m = re.search(
        r"Sostenidos:\s*(\d{2,3})\s*\|?\s*Rachas:\s*(\d{2,3})",
        viento_b,
        re.I,
    )
    if not m:
        raise RuntimeError("No se pudieron interpretar viento/rachas de Polo.")
    viento, racha = map(int, m.groups())

    m = re.search(r"(\d{3,4})", presion_b)
    if not m:
        raise RuntimeError("No se pudo interpretar presión de Polo.")
    presion = m.group(1) + " hPa"

    clasificacion = classify(t)

    fecha = extract_date(soup, aviso)
    if not fecha:
        raise RuntimeError("No se encontró fecha del aviso vigente de Polo.")

    pronostico = extract_forecast(soup)
    if not pronostico:
        raise RuntimeError("No se pudo extraer el pronóstico vigente de Polo.")

    mapa = extract_map(soup, web)
    if not mapa:
        raise RuntimeError("No se pudo extraer la trayectoria vigente de Polo.")

    oleaje_partes = re.findall(
        r"oleaje\s+de\s+\d+(?:\.\d+)?\s+a\s+\d+(?:\.\d+)?\s+metros?"
        r"(?:\s+de\s+altura)?\s+en\s+costas\s+de\s+[^.;]+",
        comentarios,
        re.I,
    )
    oleaje = "; ".join(clean(x) for x in oleaje_partes) or comentarios

    data = {
        "ciclon": "Polo",
        "fuente": "SMN / CONAGUA",
        "url_oficial": PORTAL,
        "url_datos": web,
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
        "viento_costero": comentarios,
        "oleaje": oleaje,
        "mapa": mapa,
        "pronostico": pronostico,
    }

    if racha < viento:
        raise RuntimeError("Validación fallida: racha menor que viento sostenido.")

    # Protección anti-retroceso: se conserva.
    if DATOS.exists():
        try:
            old = json.loads(DATOS.read_text(encoding="utf-8"))
            old_no = int(old.get("aviso", 0))
            if aviso < old_no:
                raise RuntimeError(
                    f"WebAviso de Polo devolvió aviso {aviso}; "
                    f"el tablero ya tiene {old_no}."
                )
        except json.JSONDecodeError:
            pass

    # Escritura atómica: sólo reemplaza el JSON después de pasar validaciones.
    tmp = Path("datos_polo.json.tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(DATOS)

    print()
    print("ACTUALIZACIÓN CORRECTA DESDE EL AVISO ACTIVO DE POLO (PLAYWRIGHT)")
    print("Aviso:", aviso)
    print("Fecha/Hora:", fecha, hora, "GMT:", gmt)
    print("Clasificación:", clasificacion)
    print("Posición:", lat, "N /", lon, "O")
    print("Referencia:", referencia)
    print("Movimiento:", movimiento)
    print("Viento/Rachas:", viento, "/", racha, "km/h")
    print("Presión:", presion)
    print("Vigilancia:", vigilancia)
    print("Pronóstico:", len(pronostico), "filas")
    print("Mapa:", mapa)
    print("datos_polo.json actualizado; index.html intacto.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERROR:", e, file=sys.stderr)
        print(
            "No se modificó el dashboard con datos parciales.",
            file=sys.stderr,
        )
        sys.exit(1)
