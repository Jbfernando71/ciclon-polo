import json
import re
import sys
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

# ============================================================
# ACTUALIZADOR CICLÓN POLO V5.9
# Fuente exclusiva: SMN / CONAGUA
# El PDF oficial es la fuente de los datos meteorológicos.
# WebAviso se usa únicamente para localizar la imagen oficial.
# NO modifica index.html.
# ============================================================

BASE = "https://smn.conagua.gob.mx"
HISTORICO_ID = "10790"
URL_HISTORICO = f"{BASE}/tools/GUI/PortalLaravel/public/historicos/{HISTORICO_ID}"
URL_WEBAVISO = f"{BASE}/tools/GUI/PortalLaravel/public/WebAviso"
DATOS = Path("datos_polo.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "es-MX,es;q=0.9",
    "Cache-Control": "no-cache",
}

def limpiar(s):
    return re.sub(r"\s+", " ", s or "").strip()

def get(url, timeout=45):
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r

def ultimo_aviso():
    soup = BeautifulSoup(get(URL_HISTORICO).text, "html.parser")
    candidatos = []

    for tr in soup.find_all("tr"):
        c = [limpiar(x.get_text(" ", strip=True)) for x in tr.find_all(["td", "th"])]
        if len(c) < 3 or not re.search(r"\bPolo\b", " ".join(c), re.I):
            continue

        aviso = None
        fecha = None
        for x in c:
            if aviso is None and re.fullmatch(r"\d{1,3}", x):
                aviso = int(x)
            if fecha is None:
                m = re.search(r"(20\d{2}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})", x)
                if m:
                    fecha = (m.group(1), m.group(2))

        a = tr.find("a", href=re.compile(r"/historicos/pdf/\d+/\d+"))
        if aviso and a:
            candidatos.append({
                "aviso": aviso,
                "fecha_tabla": fecha,
                "pdf": urljoin(URL_HISTORICO, a["href"])
            })

    if not candidatos:
        raise RuntimeError("No se localizaron avisos oficiales de Polo.")

    return max(candidatos, key=lambda x: x["aviso"])

def texto_pdf(url):
    r = get(url)
    reader = PdfReader(BytesIO(r.content))
    paginas = [(p.extract_text() or "") for p in reader.pages]
    return paginas, limpiar("\n".join(paginas))

def extraer_pronostico(texto):
    bloque = re.search(
        r"PRON[ÓO]STICO\s+D[ií]a/Hora.*?Ubicaci[oó]n\s+(.+?)"
        r"(?=\s+TRAYECTORIA\s+PRON[ÓO]STICO)",
        texto, re.I | re.S
    )
    if not bloque:
        return []

    b = limpiar(bloque.group(1))
    patron = re.compile(
        r"(\d{1,2}/\d{1,2}h?)\s+"
        r"(\d{1,2}(?:\.\d+)?)\s+"
        r"(\d{2,3}(?:\.\d+)?)\s+"
        r"(\d{2,3}/\d{2,3})\s+"
        r"(Hurac[aá]n\s+categor[ií]a\s+[1-5]|Tormenta\s+tropical|Depresi[oó]n\s+tropical)\s+"
        r"(.+?)(?=\s+\d{1,2}/\d{1,2}h?\s+\d{1,2}(?:\.\d+)?\s+\d{2,3}(?:\.\d+)?\s+\d{2,3}/\d{2,3}|\s*$)",
        re.I | re.S
    )

    filas = []
    for m in patron.finditer(b):
        filas.append({
            "dia_hora": m.group(1),
            "lat": m.group(2),
            "lon": m.group(3),
            "viento": m.group(4),
            "categoria": limpiar(m.group(5)),
            "ubicacion": limpiar(m.group(6)),
        })
    return filas

def mapa_webaviso():
    try:
        soup = BeautifulSoup(get(URL_WEBAVISO).text, "html.parser")
        for img in soup.find_all("img", src=True):
            src = urljoin(URL_WEBAVISO, img["src"])
            alt = limpiar(img.get("alt", ""))
            if "ImgTray" in src or re.search(r"trayectoria\s+pron[oó]stico", alt, re.I):
                return src
    except Exception as e:
        print("ADVERTENCIA mapa:", e)
    return ""

def main():
    print("=" * 68)
    print(" ACTUALIZADOR CICLÓN POLO V5.9")
    print(" FUENTE EXCLUSIVA: SMN / CONAGUA")
    print("=" * 68)

    meta = ultimo_aviso()
    aviso = meta["aviso"]
    print("Aviso localizado:", aviso)
    print("PDF:", meta["pdf"])

    paginas, t = texto_pdf(meta["pdf"])

    # Datos que el diagnóstico confirmó en el PDF oficial.
    m = re.search(r"Emisi[oó]n:\s*(20\d{2}-\d{2}-\d{2})\s+(\d{1,2}:\d{2}):\d{2}", t, re.I)
    if not m:
        raise RuntimeError("No se encontró fecha/hora de emisión.")
    fecha, hora_emision = m.group(1), m.group(2)

    m = re.search(r"Hora\s+local\s*\(GMT\)\s*(\d{1,2}:\d{2})\s+horas?\s*\((\d{1,2}:\d{2})\s+horas?\s+GMT\)", t, re.I)
    if not m:
        raise RuntimeError("No se encontró hora local/GMT.")
    hora, gmt = m.group(1), m.group(2)

    m = re.search(r"Ubicaci[oó]n\s+del\s+centro\s+Latitud\s+Norte:\s*(\d+(?:\.\d+)?)\s+Longitud\s+Oeste:\s*(\d+(?:\.\d+)?)", t, re.I)
    if not m:
        raise RuntimeError("No se encontraron coordenadas.")
    lat, lon = m.group(1), m.group(2)

    m = re.search(r"Distancia\s+(.+?)(?=\s+CONDICIONES\s+ACTUALES\s+Desplazamiento)", t, re.I | re.S)
    referencia = limpiar(m.group(1)) if m else "No confirmado"

    m = re.search(r"Desplazamiento\s+(.+?)(?=\s+Vientos\s+m[aá]x)", t, re.I | re.S)
    movimiento = limpiar(m.group(1)) if m else "No confirmado"

    m = re.search(r"Vientos\s+m[aá]x\s*\[km/h\]\s*Sostenidos:\s*(\d{2,3})\s+Rachas:\s*(\d{2,3})", t, re.I)
    if not m:
        raise RuntimeError("No se encontraron viento/rachas.")
    viento, racha = int(m.group(1)), int(m.group(2))

    m = re.search(r"Presi[oó]n\s+m[ií]nima\s*\[hPa\]\s*(\d{3,4})", t, re.I)
    presion = f"{m.group(1)} hPa" if m else "No confirmado"

    m = re.search(r"HURAC[AÁ]N\s+POLO\s+DE\s+CATEGOR[IÍ]A\s+([1-5])", t, re.I)
    if m:
        clasificacion = f"Huracán categoría {m.group(1)}"
    elif re.search(r"TORMENTA\s+TROPICAL\s+POLO", t, re.I):
        clasificacion = "Tormenta tropical"
    else:
        clasificacion = "No confirmado"

    # El PDF diagnóstico no contiene apartados titulados "Pronóstico de lluvia",
    # "Zona de vigilancia" o "Comentarios adicionales". Se usa únicamente lo
    # que sí publica el aviso, sin inventar ni reutilizar datos viejos.
    m = re.search(r"SITUACI[ÓO]N\s+ACTUAL\s+(.+?)(?=\s+CONDICIONES\s+ACTUALES)", t, re.I | re.S)
    situacion = limpiar(m.group(1)) if m else "No confirmado"

    lluvia = situacion if re.search(r"lluvias?", situacion, re.I) else "No confirmado"

    # No aparecen zonas específicas de prevención/vigilancia en el PDF
    # diagnosticado; por seguridad queda explícito como no confirmado.
    vigilancia = "No confirmado"

    # El aviso sí indica de forma general vientos fuertes y oleaje elevado,
    # pero no cuantifica rangos costeros en el texto extraído.
    viento_costero = "Vientos fuertes en costas (sin rango cuantificado en el aviso)" if re.search(r"vientos?\s+fuertes", situacion, re.I) else "No confirmado"
    oleaje = "Oleaje elevado en costas (sin altura cuantificada en el aviso)" if re.search(r"oleaje\s+elevado", situacion, re.I) else "No confirmado"

    pronostico = extraer_pronostico(t)
    if not pronostico:
        raise RuntimeError("No se pudo extraer la tabla de pronóstico del PDF vigente.")

    mapa = mapa_webaviso()

    d = {
        "ciclon": "Polo",
        "fuente": "SMN / CONAGUA",
        "url_oficial": meta["pdf"],
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
        # Nunca reutilizar mapa o pronóstico de un aviso anterior.
        "mapa": mapa,
        "pronostico": pronostico,
    }

    esenciales = ["fecha","hora","gmt","lat","lon","referencia","movimiento",
                  "viento","racha","presion","clasificacion"]
    faltan = [k for k in esenciales if d[k] in ("", "No confirmado", None)]
    if faltan:
        raise RuntimeError("Campos esenciales no extraídos: " + ", ".join(faltan))

    if racha < viento:
        raise RuntimeError("Validación fallida: racha menor que viento sostenido.")

    tmp = Path("datos_polo.json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(DATOS)

    print()
    print("ACTUALIZACIÓN CORRECTA")
    print("Aviso:", aviso)
    print("Fecha/Hora:", fecha, hora, "GMT:", gmt)
    print("Clasificación:", clasificacion)
    print("Posición:", lat, "N /", lon, "O")
    print("Referencia:", referencia)
    print("Movimiento:", movimiento)
    print("Viento/Rachas:", viento, "/", racha, "km/h")
    print("Presión:", presion)
    print("Pronóstico:", len(pronostico), "filas")
    print("Mapa:", mapa if mapa else "No confirmado")
    print("datos_polo.json actualizado.")
    print("index.html permanece intacto.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERROR:", e, file=sys.stderr)
        print("Por seguridad no se publica una actualización parcial.", file=sys.stderr)
        sys.exit(1)
