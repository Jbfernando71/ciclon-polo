import requests
import re
import sys
import json
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from pypdf import PdfReader

# ============================================================
# ACTUALIZADOR CICLÓN POLO V5.3
# Fuente exclusiva: SMN / CONAGUA
# Histórico oficial de Polo: 10790
# ============================================================

HISTORICO_ID = "10790"
BASE = "https://smn.conagua.gob.mx"
URL_HISTORICO = (
    f"{BASE}/tools/GUI/PortalLaravel/public/historicos/{HISTORICO_ID}"
)
DATOS = Path("datos_polo.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}

def limpiar(s):
    return re.sub(r"\s+", " ", s or "").strip()

def get(url, timeout=45):
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r

def cargar_actual():
    if not DATOS.exists():
        return {}
    try:
        return json.loads(DATOS.read_text(encoding="utf-8"))
    except Exception:
        return {}

# ============================================================
# LEER LA TABLA REAL DEL HISTÓRICO
# ============================================================

def obtener_ultimo_boletin():
    print("Consultando histórico oficial SMN:", URL_HISTORICO)
    r = get(URL_HISTORICO)
    soup = BeautifulSoup(r.text, "html.parser")

    candidatos = []

    for fila in soup.find_all("tr"):
        celdas = fila.find_all(["td", "th"])
        if len(celdas) < 3:
            continue

        valores = [limpiar(c.get_text(" ", strip=True)) for c in celdas]
        nombre = valores[0]

        if not re.search(r"\bPolo\b", nombre, re.I):
            continue

        # La segunda columna visible es el número real del aviso.
        m_aviso = re.fullmatch(r"\s*(\d+)\s*", valores[1])
        if not m_aviso:
            continue

        aviso = int(m_aviso.group(1))

        # El PDF se toma de LA MISMA FILA; no se deduce el aviso de la URL.
        enlace_pdf = None
        for a in fila.find_all("a", href=True):
            href = a["href"]
            texto_a = limpiar(a.get_text(" ", strip=True))
            if (
                "pdf" in href.lower()
                or "pdf" in texto_a.lower()
                or "/historicos/pdf/" in href.lower()
            ):
                enlace_pdf = urljoin(URL_HISTORICO, href)
                break

        if not enlace_pdf:
            continue

        fecha_tabla = valores[2] if len(valores) >= 3 else ""

        candidatos.append({
            "aviso": aviso,
            "fecha_tabla": fecha_tabla,
            "url_pdf": enlace_pdf,
        })

    if not candidatos:
        raise RuntimeError(
            "El histórico 10790 respondió, pero no pude leer las filas "
            "de Huracán Polo con su número de aviso y PDF."
        )

    ultimo = max(candidatos, key=lambda x: x["aviso"])

    print("Avisos de Polo encontrados:", len(candidatos))
    print("Último aviso localizado:", ultimo["aviso"])
    print("Fecha de tabla:", ultimo["fecha_tabla"])
    print("PDF de la misma fila:", ultimo["url_pdf"])

    return ultimo

# ============================================================
# LEER PDF OFICIAL
# ============================================================

def obtener_texto_pdf(url):
    r = get(url)

    content_type = r.headers.get("Content-Type", "").lower()
    if "pdf" not in content_type and not r.content.startswith(b"%PDF"):
        raise RuntimeError(
            "El enlace seleccionado no devolvió un PDF válido del SMN."
        )

    reader = PdfReader(BytesIO(r.content))
    texto = limpiar(
        " ".join((pagina.extract_text() or "") for pagina in reader.pages)
    )

    if not texto:
        raise RuntimeError("No fue posible extraer texto del PDF oficial.")

    if not re.search(r"\bPolo\b", texto, re.I):
        raise RuntimeError(
            "El PDF seleccionado no pudo validarse como un aviso de Polo."
        )

    return texto

def buscar(patrones, texto, flags=re.I):
    if isinstance(patrones, str):
        patrones = [patrones]
    for patron in patrones:
        m = re.search(patron, texto, flags)
        if m:
            return limpiar(m.group(1))
    return None

# ============================================================
# EXTRAER DATOS
# ============================================================

def extraer(aviso, fecha_tabla, url_pdf, texto):
    d = {
        "ciclon": "Polo",
        "fuente": "SMN / CONAGUA",
        "url_oficial": url_pdf,
        "aviso": aviso,
    }

    # La fecha/hora de la tabla del histórico es oficial.
    mt = re.search(
        r"(20\d{2}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})",
        fecha_tabla
    )
    if mt:
        d["fecha"] = mt.group(1)
        d["hora_publicacion"] = mt.group(2)
    else:
        d["fecha"] = "No confirmado"
        d["hora_publicacion"] = "No confirmado"

    # Hora local/GMT del propio boletín.
    mh = re.search(
        r"Hora\s+local\s*\(hora\s+GMT\)\s*:?\s*"
        r"(\d{1,2}:\d{2})\s*horas?\s*"
        r"\((\d{1,2}:\d{2})\s*horas?\s*GMT",
        texto, re.I
    )
    if mh:
        d["hora"] = mh.group(1)
        d["gmt"] = mh.group(2)
    else:
        d["hora"] = d["hora_publicacion"]
        d["gmt"] = "No confirmado"

    # Coordenadas.
    mp = re.search(
        r"Latitud\s+Norte\s*:?\s*(\d{1,2}(?:\.\d+)?)\s*"
        r"Longitud\s+Oeste\s*:?\s*(\d{2,3}(?:\.\d+)?)",
        texto, re.I
    )
    if mp:
        d["lat"], d["lon"] = mp.group(1), mp.group(2)
    else:
        d["lat"] = d["lon"] = "No confirmado"

    d["referencia"] = buscar(
        r"Distancia\s+al\s+lugar\s+m[aá]s\s+cercano\s*:?\s*(.+?)"
        r"(?=\s+Desplazamiento\s+actual)",
        texto, re.I | re.S
    ) or "No confirmado"

    d["movimiento"] = buscar(
        r"Desplazamiento\s+actual\s*:?\s*(.+?)"
        r"(?=\s+Vientos\s+m[aá]ximos)",
        texto, re.I | re.S
    ) or "No confirmado"

    mv = re.search(
        r"Vientos\s+m[aá]ximos.*?"
        r"Sostenidos\s*:?\s*(\d{2,3}).*?"
        r"Rachas\s*:?\s*(\d{2,3})",
        texto, re.I | re.S
    )
    if mv:
        d["viento"] = int(mv.group(1))
        d["racha"] = int(mv.group(2))
    else:
        d["viento"] = d["racha"] = "No confirmado"

    presion = buscar(
        r"Presi[oó]n\s+m[ií]nima\s+central.*?(\d{3,4})",
        texto, re.I | re.S
    )
    d["presion"] = f"{presion} hPa" if presion else "No confirmado"

    # Clasificación. Varias formas posibles del texto oficial.
    clas = None
    patrones_cat = [
        r"Hurac[aá]n\s+Polo.{0,80}?categor[ií]a\s+([1-5])",
        r"Polo.{0,80}?categor[ií]a\s+([1-5])",
        r"POLO\s+CATEGOR[IÍ]A\s+([1-5])",
        r"HURAC[AÁ]N\s+CATEGOR[IÍ]A\s+([1-5]).{0,80}?POLO",
    ]
    for patron in patrones_cat:
        m = re.search(patron, texto, re.I | re.S)
        if m:
            clas = f"Huracán categoría {m.group(1)}"
            break

    if not clas and re.search(
        r"tormenta\s+tropical\s+Polo|Polo.{0,50}?tormenta\s+tropical",
        texto, re.I | re.S
    ):
        clas = "Tormenta tropical"

    if not clas and re.search(
        r"depresi[oó]n\s+tropical\s+Polo|Polo.{0,50}?depresi[oó]n\s+tropical",
        texto, re.I | re.S
    ):
        clas = "Depresión tropical"

    d["clasificacion"] = clas or "No confirmado"

    d["lluvia"] = buscar(
        r"Pron[oó]stico\s+de\s+lluvia\s*:?\s*(.+?)"
        r"(?=\s+Zona\s+de\s+vigilancia)",
        texto, re.I | re.S
    ) or "No confirmado"

    d["vigilancia"] = buscar(
        r"Zona\s+de\s+vigilancia\s*:?\s*(.+?)"
        r"(?=\s+Comentarios\s+adicionales)",
        texto, re.I | re.S
    ) or "No confirmado"

    comentarios = buscar(
        r"Comentarios\s+adicionales\s*:?\s*(.+?)"
        r"(?=\s+Recomendaciones)",
        texto, re.I | re.S
    ) or ""

    d["viento_costero"] = buscar(
        r"((?:Se\s+prev[eé]n\s+)?rachas?\s+de\s+viento.+?km/h[^.;]*)",
        comentarios, re.I | re.S
    ) or "No confirmado"

    d["oleaje"] = buscar(
        r"(oleaje\s+de\s+\d+(?:\.\d+)?\s+a\s+\d+(?:\.\d+)?\s+metros?.+?)"
        r"(?=\.|$)",
        comentarios, re.I | re.S
    ) or "No confirmado"

    return d

# ============================================================
# VALIDACIÓN Y ESCRITURA SEGURA
# ============================================================

def validar(d):
    esenciales = ["aviso", "fecha", "lat", "lon", "viento", "racha"]

    faltan = [
        campo for campo in esenciales
        if d.get(campo) in (None, "", "No confirmado")
    ]

    if faltan:
        raise RuntimeError(
            "Se localizó el boletín, pero faltan campos esenciales: "
            + ", ".join(faltan)
        )

    if d["racha"] < d["viento"]:
        raise RuntimeError(
            "Validación fallida: la racha es menor al viento sostenido."
        )

def preparar_salida(nuevo):
    actual = cargar_actual()

    # Conservamos sólo elementos visuales/complementarios que el PDF
    # no proporciona de forma estructurada, para no romper el dashboard.
    nuevo["mapa"] = actual.get("mapa", "")
    nuevo["pronostico"] = actual.get("pronostico", [])

    return nuevo

def main():
    print("========================================")
    print(" ACTUALIZADOR CICLÓN POLO V5.3")
    print(" Fuente exclusiva: SMN / CONAGUA")
    print(" Histórico oficial:", HISTORICO_ID)
    print("========================================")

    ultimo = obtener_ultimo_boletin()

    actual = cargar_actual()
    aviso_actual = actual.get("aviso")

    try:
        aviso_actual_num = int(aviso_actual)
    except (TypeError, ValueError):
        aviso_actual_num = 0

    if ultimo["aviso"] < aviso_actual_num:
        raise RuntimeError(
            f"El histórico indica Aviso {ultimo['aviso']}, "
            f"anterior al publicado {aviso_actual_num}."
        )

    texto = obtener_texto_pdf(ultimo["url_pdf"])

    nuevo = extraer(
        ultimo["aviso"],
        ultimo["fecha_tabla"],
        ultimo["url_pdf"],
        texto
    )

    validar(nuevo)
    salida = preparar_salida(nuevo)

    contenido = json.dumps(
        salida,
        ensure_ascii=False,
        indent=2
    ) + "\n"

    actual_texto = (
        DATOS.read_text(encoding="utf-8")
        if DATOS.exists()
        else ""
    )

    if contenido == actual_texto:
        print("El dashboard ya contiene el último aviso.")
        return

    temporal = Path("datos_polo.json.tmp")
    temporal.write_text(contenido, encoding="utf-8")
    temporal.replace(DATOS)

    print("----------------------------------------")
    print("ACTUALIZACIÓN CORRECTA")
    print("Aviso:", salida["aviso"])
    print("Fecha:", salida["fecha"])
    print("Hora:", salida["hora"])
    print("Clasificación:", salida["clasificacion"])
    print("Posición:", salida["lat"], "N /", salida["lon"], "O")
    print("Viento:", salida["viento"], "km/h")
    print("Rachas:", salida["racha"], "km/h")
    print("----------------------------------------")
    print("datos_polo.json actualizado.")
    print("index.html permanece intacto.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERROR:", e, file=sys.stderr)
        print(
            "Por seguridad datos_polo.json permanece sin modificaciones.",
            file=sys.stderr
        )
        sys.exit(1)
