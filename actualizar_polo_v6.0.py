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
# ACTUALIZADOR CICLÓN POLO V6.0
# Fuente exclusiva: SMN / CONAGUA
# Fuente meteorológica: PDF oficial del aviso.
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

def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()

def get(url):
    r = requests.get(url, headers=HEADERS, timeout=45)
    r.raise_for_status()
    return r

def locate_latest():
    soup = BeautifulSoup(get(URL_HISTORICO).text, "html.parser")
    found = []
    for tr in soup.find_all("tr"):
        cells = [clean(x.get_text(" ", strip=True)) for x in tr.find_all(["td","th"])]
        row = " ".join(cells)
        if not re.search(r"\bPolo\b", row, re.I):
            continue
        link = tr.find("a", href=re.compile(r"/historicos/pdf/\d+/\d+"))
        if not link:
            continue
        nums = [int(x) for x in cells if re.fullmatch(r"\d{1,3}", x)]
        if not nums:
            continue
        aviso = nums[0]
        found.append((aviso, urljoin(URL_HISTORICO, link["href"])))
    if not found:
        raise RuntimeError("No se encontró el aviso oficial de Polo.")
    return max(found, key=lambda x: x[0])

def read_pdf(url):
    reader = PdfReader(BytesIO(get(url).content))
    raw = "\n".join((p.extract_text() or "") for p in reader.pages)
    return raw, clean(raw)

def forecast(text):
    # El diagnóstico confirmó que el bloque está entre PRONÓSTICO y TRAYECTORIA PRONÓSTICO.
    m = re.search(r"PRON[ÓO]STICO\s+(.+?)\s+TRAYECTORIA\s+PRON[ÓO]STICO", text, re.I | re.S)
    if not m:
        return []
    b = clean(m.group(1))

    # Quitar encabezado de columnas.
    b = re.sub(
        r"^D[ií]a/Hora\s+Latitud\s+norte\s+Long\.\s+Oeste\s+Vientos\s+\[Km/h\]\s+Categor[ií]a\s+Ubicaci[oó]n\s+",
        "", b, flags=re.I
    )

    starts = list(re.finditer(
        r"(?<!\d)(\d{1,2}/\d{1,2}h?)\s+(\d{1,2}(?:\.\d+)?)\s+"
        r"(\d{2,3}(?:\.\d+)?)\s+(\d{2,3}/\d{2,3})\s+",
        b, re.I
    ))
    rows = []
    for i, s in enumerate(starts):
        end = starts[i+1].start() if i+1 < len(starts) else len(b)
        tail = clean(b[s.end():end])
        cat = re.match(
            r"(Hurac[aá]n\s+categor[ií]a\s+[1-5]|Tormenta\s+tropical|Depresi[oó]n\s+tropical)\s+(.+)",
            tail, re.I | re.S
        )
        if not cat:
            continue
        rows.append({
            "dia_hora": s.group(1),
            "lat": s.group(2),
            "lon": s.group(3),
            "viento": s.group(4),
            "categoria": clean(cat.group(1)),
            "ubicacion": clean(cat.group(2)),
        })
    return rows

def current_map():
    try:
        soup = BeautifulSoup(get(URL_WEBAVISO).text, "html.parser")
        for img in soup.find_all("img", src=True):
            src = urljoin(URL_WEBAVISO, img["src"])
            alt = clean(img.get("alt", ""))
            if "ImgTray" in src or re.search(r"trayectoria.*pron[oó]stico", alt, re.I):
                return src
    except Exception as e:
        print("ADVERTENCIA: mapa no confirmado:", e)
    return ""

def must(pattern, text, name, flags=re.I):
    m = re.search(pattern, text, flags)
    if not m:
        raise RuntimeError(f"No se pudo extraer: {name}")
    return m

def main():
    print("="*68)
    print(" ACTUALIZADOR CICLÓN POLO V6.0")
    print(" FUENTE EXCLUSIVA: SMN / CONAGUA")
    print("="*68)

    aviso, pdf_url = locate_latest()
    print("Aviso:", aviso)
    print("PDF:", pdf_url)

    raw, t = read_pdf(pdf_url)

    m = must(r"Emisi[oó]n:\s*(20\d{2}-\d{2}-\d{2})\s+(\d{1,2}:\d{2}):\d{2}", t, "emisión")
    fecha = m.group(1)

    m = must(r"Hora\s+local\s*\(GMT\)\s*(\d{1,2}:\d{2})\s+horas?\s*\((\d{1,2}:\d{2})\s+horas?\s+GMT\)", t, "hora local/GMT")
    hora, gmt = m.group(1), m.group(2)

    m = must(r"Latitud\s+Norte:\s*(\d+(?:\.\d+)?)\s+Longitud\s+Oeste:\s*(\d+(?:\.\d+)?)", t, "coordenadas")
    lat, lon = m.group(1), m.group(2)

    m = must(r"Distancia\s+(.+?)\s+CONDICIONES\s+ACTUALES\s+Desplazamiento", t, "distancia", re.I|re.S)
    referencia = clean(m.group(1))

    m = must(r"Desplazamiento\s+(.+?)\s+Vientos\s+m[aá]x", t, "desplazamiento", re.I|re.S)
    movimiento = clean(m.group(1))

    m = must(r"Vientos\s+m[aá]x\s*\[km/h\]\s*Sostenidos:\s*(\d{2,3})\s+Rachas:\s*(\d{2,3})", t, "viento/rachas")
    viento, racha = int(m.group(1)), int(m.group(2))

    m = must(r"Presi[oó]n\s+m[ií]nima\s*\[hPa\]\s*(\d{3,4})", t, "presión")
    presion = f"{m.group(1)} hPa"

    m = must(r"HURAC[AÁ]N\s+POLO\s+DE\s+CATEGOR[IÍ]A\s+([1-5])", t, "clasificación")
    clasificacion = f"Huracán categoría {m.group(1)}"

    # Texto oficial de situación actual. El diagnóstico no mostró una tabla
    # cuantitativa separada de lluvia/viento/oleaje, así que no se inventa.
    m = re.search(r"SITUACI[ÓO]N\s+ACTUAL\s+(.+?)\s+CONDICIONES\s+ACTUALES", t, re.I|re.S)
    situacion = clean(m.group(1)) if m else "No confirmado"
    lluvia = situacion if "lluvia" in situacion.lower() else "No confirmado"
    vigilancia = "No confirmado"
    viento_costero = "Vientos fuertes en costas; el aviso no cuantifica el rango en el texto extraído." if re.search(r"vientos?\s+fuertes", situacion, re.I) else "No confirmado"
    oleaje = "Oleaje elevado en costas; el aviso no cuantifica la altura en el texto extraído." if re.search(r"oleaje\s+elevado", situacion, re.I) else "No confirmado"

    pronostico = forecast(t)
    if len(pronostico) < 4:
        raise RuntimeError(f"Pronóstico incompleto: solo {len(pronostico)} filas extraídas.")

    mapa = current_map()

    data = {
        "ciclon": "Polo",
        "fuente": "SMN / CONAGUA",
        "url_oficial": pdf_url,
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
        "pronostico": pronostico
    }

    tmp = Path("datos_polo.json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    print("datos_polo.json actualizado; index.html intacto.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERROR:", e, file=sys.stderr)
        sys.exit(1)
