import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ============================================================
# ACTUALIZADOR CICLÓN POLO V5.8
# Fuente exclusiva: SMN / CONAGUA
# Actualiza SOLO datos_polo.json. NO modifica index.html.
# ============================================================

BASE = "https://smn.conagua.gob.mx"
URL_AVISO = f"{BASE}/tools/GUI/PortalLaravel/public/WebAviso"
DATOS = Path("datos_polo.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/153.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-MX,es;q=0.9",
    "Cache-Control": "no-cache",
}

def limpio(s):
    return re.sub(r"\s+", " ", s or "").strip()

def descargar():
    r = requests.get(URL_AVISO, headers=HEADERS, timeout=45)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    texto = limpio(soup.get_text(" ", strip=True))
    if not re.search(r"\bPolo\b", texto, re.I):
        raise RuntimeError("No se pudo confirmar a Polo en WebAviso.")
    return soup, texto

def entre(texto, inicio, fin):
    p = rf"{inicio}\s*(.+?)(?=\s*{fin})"
    m = re.search(p, texto, re.I | re.S)
    return limpio(m.group(1)) if m else "No confirmado"

def mapa_actual(soup):
    # La imagen oficial de trayectoria del SMN usa WebImg/ImgTray...
    for img in soup.find_all("img", src=True):
        src = urljoin(URL_AVISO, img.get("src", ""))
        alt = limpio(img.get("alt", ""))
        if "ImgTray" in src or re.search(r"Trayectoria\s+pron[oó]stico", alt, re.I):
            return src
    return ""

def pronostico_actual(soup):
    # Primero intenta leer la tabla HTML de pronóstico.
    for tabla in soup.find_all("table"):
        txt = limpio(tabla.get_text(" ", strip=True))
        if not (re.search(r"D[ií]a/Hora", txt, re.I)
                and re.search(r"Vientos", txt, re.I)
                and re.search(r"Categor[ií]a", txt, re.I)):
            continue

        filas = []
        for tr in tabla.find_all("tr"):
            c = [limpio(x.get_text(" ", strip=True))
                 for x in tr.find_all(["th", "td"])]
            if len(c) < 6 or not re.fullmatch(r"\d{1,2}/\d{1,2}h?", c[0]):
                continue
            filas.append({
                "dia_hora": c[0],
                "lat": c[1],
                "lon": c[2],
                "viento": c[3],
                "categoria": c[4],
                "ubicacion": c[5],
            })
        if filas:
            return filas
    return []

def main():
    print("=" * 66)
    print(" ACTUALIZADOR CICLÓN POLO V5.8")
    print(" FUENTE EXCLUSIVA: SMN / CONAGUA")
    print("=" * 66)

    soup, t = descargar()

    # Aviso
    m = re.search(r"Oc[eé]ano\s+Pac[ií]fico\s*-\s*No\.\s*Aviso:\s*(\d+)", t, re.I)
    if not m:
        raise RuntimeError("No se encontró el número de aviso.")
    aviso = int(m.group(1))

    # Clasificación
    m = re.search(r"HURAC[AÁ]N\s+POLO\s+DE\s+CATEGOR[IÍ]A\s+([1-5])", t, re.I)
    if m:
        clasificacion = f"Huracán categoría {m.group(1)}"
    elif re.search(r"TORMENTA\s+TROPICAL\s+POLO", t, re.I):
        clasificacion = "Tormenta tropical"
    elif re.search(r"DEPRESI[ÓO]N\s+TROPICAL\s+POLO", t, re.I):
        clasificacion = "Depresión tropical"
    else:
        clasificacion = "No confirmado"

    # Hora local / GMT
    m = re.search(
        r"Hora\s+local\s*\(hora\s+GMT\)\s*\|?\s*"
        r"(\d{1,2}:\d{2})\s*horas?\s*"
        r"\((\d{1,2}:\d{2})\s*horas?\s*GMT\)",
        t, re.I
    )
    hora = m.group(1) if m else "No confirmado"
    gmt = m.group(2) if m else "No confirmado"

    # Coordenadas
    m = re.search(
        r"Ubicaci[oó]n\s+del\s+centro\s*\|?\s*"
        r"Latitud\s+Norte:\s*(\d{1,2}(?:\.\d+)?)\s*\|?\s*"
        r"Longitud\s+Oeste:\s*(\d{2,3}(?:\.\d+)?)",
        t, re.I
    )
    lat = m.group(1) if m else "No confirmado"
    lon = m.group(2) if m else "No confirmado"

    referencia = entre(t,
        r"Distancia\s+al\s+lugar\s+m[aá]s\s+cercano\s*\|?",
        r"Desplazamiento\s+actual")

    movimiento = entre(t,
        r"Desplazamiento\s+actual\s*\|?",
        r"Vientos\s+m[aá]ximos")

    # Viento y rachas
    m = re.search(
        r"Vientos\s+m[aá]ximos\s*\[km/h\]\s*\|?\s*"
        r"Sostenidos:\s*(\d{2,3})\s*\|?\s*Rachas:\s*(\d{2,3})",
        t, re.I
    )
    viento = int(m.group(1)) if m else "No confirmado"
    racha = int(m.group(2)) if m else "No confirmado"

    # Presión
    m = re.search(
        r"Presi[oó]n\s+m[ií]nima\s+central\s*\[hpa\]\s*\|?\s*(\d{3,4})",
        t, re.I
    )
    presion = f"{m.group(1)} hPa" if m else "No confirmado"

    lluvia = entre(t,
        r"Pron[oó]stico\s+de\s+lluvia\s*\|?",
        r"Zona\s+de\s+vigilancia")

    vigilancia = entre(t,
        r"Zona\s+de\s+vigilancia\s*\|?",
        r"Comentarios\s+adicionales")

    comentarios = entre(t,
        r"Comentarios\s+adicionales\s*\|?",
        r"Recomendaciones")

    # Viento costero: conserva el comentario oficial completo para no perder estados/rangos.
    viento_costero = comentarios if comentarios != "No confirmado" else "No confirmado"

    # Extrae todas las frases de oleaje del comentario.
    oleajes = re.findall(
        r"oleaje\s+de\s+\d+(?:\.\d+)?\s+a\s+\d+(?:\.\d+)?\s+metros?"
        r"(?:\s+de\s+altura)?\s+en\s+costas\s+de\s+[^.;]+",
        comentarios, re.I
    )
    oleaje = "; ".join(limpio(x) for x in oleajes) if oleajes else "No confirmado"

    # Fecha: se obtiene de la fila del mismo aviso en el historial.
    fecha = "No confirmado"
    hora_hist = None
    gmt_hist = None
    patron = (
        rf"(?:^|\s){aviso}\s*\|?\s*"
        rf"(20\d{{2}}-\d{{2}}-\d{{2}})\s+"
        rf"(\d{{1,2}}:\d{{2}})\s*horas?\s*"
        rf"\((\d{{1,2}}:\d{{2}})\s*horas?\s*GMT"
    )
    mh = re.search(patron, t, re.I)
    if mh:
        fecha, hora_hist, gmt_hist = mh.group(1), mh.group(2), mh.group(3)
        if hora == "No confirmado":
            hora = hora_hist
        if gmt == "No confirmado":
            gmt = gmt_hist

    pronostico = pronostico_actual(soup)
    mapa = mapa_actual(soup)

    d = {
        "ciclon": "Polo",
        "fuente": "SMN / CONAGUA",
        "url_oficial": URL_AVISO,
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

    # Validaciones para impedir mezclar avisos o publicar información incompleta.
    esenciales = ["fecha", "hora", "gmt", "lat", "lon", "referencia",
                  "movimiento", "viento", "racha", "presion",
                  "clasificacion", "lluvia", "vigilancia"]
    faltan = [x for x in esenciales if d[x] in ("", "No confirmado", None)]
    if faltan:
        raise RuntimeError("Campos oficiales no extraídos: " + ", ".join(faltan))

    if not pronostico:
        raise RuntimeError("No se pudo extraer el pronóstico del aviso vigente.")
    if not mapa:
        raise RuntimeError("No se pudo confirmar el mapa del aviso vigente.")
    if int(racha) < int(viento):
        raise RuntimeError("Racha menor que viento sostenido; se cancela actualización.")

    # Evita retroceder de aviso.
    if DATOS.exists():
        try:
            viejo = json.loads(DATOS.read_text(encoding="utf-8"))
            viejo_aviso = int(viejo.get("aviso", 0))
            if aviso < viejo_aviso:
                raise RuntimeError(
                    f"SMN devolvió aviso {aviso}, pero el dashboard ya tiene {viejo_aviso}."
                )
        except json.JSONDecodeError:
            pass

    salida = json.dumps(d, ensure_ascii=False, indent=2) + "\n"
    tmp = Path("datos_polo.json.tmp")
    tmp.write_text(salida, encoding="utf-8")
    tmp.replace(DATOS)

    print()
    print("ACTUALIZACIÓN CORRECTA")
    print("Aviso:", aviso)
    print("Fecha:", fecha)
    print("Hora local/GMT:", hora, "/", gmt)
    print("Clasificación:", clasificacion)
    print("Coordenadas:", lat, "N /", lon, "O")
    print("Referencia:", referencia)
    print("Movimiento:", movimiento)
    print("Viento/Rachas:", viento, "/", racha, "km/h")
    print("Presión:", presion)
    print("Pronóstico:", len(pronostico), "filas")
    print("Mapa:", mapa)
    print("datos_polo.json actualizado.")
    print("index.html permanece intacto.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERROR:", e, file=sys.stderr)
        print("Por seguridad no se publica una actualización parcial.", file=sys.stderr)
        sys.exit(1)
