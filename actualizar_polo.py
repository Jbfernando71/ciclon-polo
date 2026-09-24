import requests
import re
import sys
import json
from io import BytesIO
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from pypdf import PdfReader

# ============================================================
# CONFIGURACIÓN — POLO / SMN-CONAGUA
# ============================================================

HISTORICO_ID = "10790"
URL_HISTORICO = (
    "https://smn.conagua.gob.mx/tools/GUI/PortalLaravel/public/"
    f"historicos/{HISTORICO_ID}"
)
DOMINIO = "smn.conagua.gob.mx"
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

def cargar_actual():
    if not DATOS.exists():
        return {}
    try:
        return json.loads(DATOS.read_text(encoding="utf-8"))
    except Exception:
        return {}

def get(url, timeout=40):
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r

# ============================================================
# 1) LOCALIZAR EL ÚLTIMO BOLETÍN EN EL HISTÓRICO 10790
# ============================================================

def obtener_ultimo_boletin():
    print("Consultando histórico oficial SMN:", URL_HISTORICO)
    r = get(URL_HISTORICO)
    soup = BeautifulSoup(r.text, "html.parser")

    candidatos = []

    # El histórico oficial enlaza avisos PDF. Buscamos el número
    # tanto en href como en el texto de la fila/enlace.
    for a in soup.find_all("a", href=True):
        href = a["href"]
        absoluto = urljoin(URL_HISTORICO, href)

        if DOMINIO not in absoluto:
            continue

        if f"/historicos/pdf/{HISTORICO_ID}/" not in absoluto:
            continue

        m = re.search(
            rf"/historicos/pdf/{re.escape(HISTORICO_ID)}/(\d+)",
            absoluto,
            re.I
        )
        if m:
            candidatos.append((int(m.group(1)), absoluto))

    # Respaldo: localizar rutas aunque no estén en una etiqueta <a>.
    if not candidatos:
        for m in re.finditer(
            rf"(?:https?://{re.escape(DOMINIO)})?"
            rf"(/tools/GUI/PortalLaravel/public/historicos/pdf/"
            rf"{re.escape(HISTORICO_ID)}/(\d+))",
            r.text,
            re.I
        ):
            candidatos.append(
                (int(m.group(2)), urljoin(URL_HISTORICO, m.group(1)))
            )

    if not candidatos:
        raise RuntimeError(
            "El histórico 10790 respondió, pero no pude localizar enlaces "
            "a los boletines PDF de Polo."
        )

    # El número mayor es el último aviso publicado en ese histórico.
    aviso, url_pdf = max(candidatos, key=lambda x: x[0])

    print("Último aviso localizado:", aviso)
    print("PDF oficial:", url_pdf)
    return aviso, url_pdf

# ============================================================
# 2) EXTRAER TEXTO DEL PDF OFICIAL
# ============================================================

def texto_pdf(url_pdf):
    r = get(url_pdf)
    reader = PdfReader(BytesIO(r.content))
    paginas = []

    for p in reader.pages:
        paginas.append(p.extract_text() or "")

    texto = limpiar(" ".join(paginas))

    if not texto:
        raise RuntimeError("El PDF oficial no produjo texto utilizable.")

    if not re.search(r"\bPolo\b", texto, re.I):
        raise RuntimeError(
            "El último PDF del histórico 10790 no pudo validarse como Polo."
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
# 3) EXTRAER CAMPOS CONFIRMADOS DEL BOLETÍN
# ============================================================

def extraer_datos(aviso, texto, url_pdf):
    d = {
        "ciclon": "Polo",
        "fuente": "SMN / CONAGUA",
        "url_oficial": url_pdf,
        "aviso": aviso,
    }

    # Fecha: acepta 2026-09-23, 23/09/2026 y 23 de septiembre de 2026.
    fecha = buscar(r"\b(20\d{2}-\d{2}-\d{2})\b", texto)
    if not fecha:
        f = re.search(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b", texto)
        if f:
            fecha = f"{f.group(3)}-{int(f.group(2)):02d}-{int(f.group(1)):02d}"
    if not fecha:
        meses = {
            "enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,
            "julio":7,"agosto":8,"septiembre":9,"octubre":10,
            "noviembre":11,"diciembre":12
        }
        f = re.search(
            r"\b(\d{1,2})\s+de\s+"
            r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|"
            r"octubre|noviembre|diciembre)\s+de\s+(20\d{2})\b",
            texto, re.I
        )
        if f:
            fecha = f"{f.group(3)}-{meses[f.group(2).lower()]:02d}-{int(f.group(1)):02d}"
    d["fecha"] = fecha or "No confirmado"

    # Hora local y GMT.
    mh = re.search(
        r"Hora\s+local\s*\(hora\s+GMT\)\s*"
        r"(\d{1,2}:\d{2})\s*horas?\s*"
        r"\((\d{1,2}:\d{2})\s*horas?\s*GMT",
        texto, re.I
    )
    if mh:
        d["hora"] = mh.group(1).zfill(5)
        d["gmt"] = mh.group(2).zfill(5)
    else:
        d["hora"] = "No confirmado"
        d["gmt"] = "No confirmado"

    # Posición.
    mp = re.search(
        r"Latitud\s+Norte\s*:?\s*(\d{1,2}(?:\.\d+)?)\s*"
        r"Longitud\s+Oeste\s*:?\s*(\d{2,3}(?:\.\d+)?)",
        texto, re.I
    )
    if mp:
        d["lat"], d["lon"] = mp.group(1), mp.group(2)
    else:
        d["lat"] = d["lon"] = "No confirmado"

    # Referencia y movimiento.
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

    # Viento y rachas.
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
        r"Presi[oó]n\s+m[ií]nima\s+central.*?(\d{3,4})\s*(?:hPa)?",
        texto, re.I | re.S
    )
    d["presion"] = f"{presion} hPa" if presion else "No confirmado"

    # Clasificación: sólo expresiones unidas explícitamente al nombre Polo.
    patrones = [
        (r"hurac[aá]n\s+Polo.{0,50}?categor[ií]a\s+([1-5])", "huracan"),
        (r"Polo.{0,30}?hurac[aá]n.{0,30}?categor[ií]a\s+([1-5])", "huracan"),
    ]
    clas = None
    for patron, _ in patrones:
        m = re.search(patron, texto, re.I)
        if m:
            clas = f"Huracán categoría {m.group(1)}"
            break
    if not clas and re.search(r"tormenta\s+tropical\s+Polo|Polo.{0,30}?tormenta\s+tropical", texto, re.I):
        clas = "Tormenta tropical"
    if not clas and re.search(r"depresi[oó]n\s+tropical\s+Polo|Polo.{0,30}?depresi[oó]n\s+tropical", texto, re.I):
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
        r"(oleaje\s+de\s+\d+(?:\.\d+)?\s+a\s+\d+(?:\.\d+)?\s+metros?.+?)(?=\.|$)",
        comentarios, re.I | re.S
    ) or "No confirmado"

    return d

# ============================================================
# 4) PROTEGER EL DASHBOARD Y CONSERVAR CAMPOS NO CONFIRMADOS
# ============================================================

def validar_esenciales(d):
    esenciales = ["aviso", "hora", "lat", "lon", "viento", "racha"]
    faltan = [
        k for k in esenciales
        if d.get(k) in (None, "", "No confirmado")
    ]
    if faltan:
        raise RuntimeError(
            "El último boletín fue localizado, pero faltan campos esenciales: "
            + ", ".join(faltan)
        )
    if isinstance(d["viento"], int) and isinstance(d["racha"], int):
        if d["racha"] < d["viento"]:
            raise RuntimeError("La racha recuperada es inferior al viento sostenido.")

def combinar_con_actual(nuevo):
    actual = cargar_actual()

    # Nunca conservar número/fecha/hora/posición/viento de un aviso anterior.
    # Para campos complementarios no confirmados, se muestra "No confirmado".
    salida = {
        "ciclon": "Polo",
        "fuente": "SMN / CONAGUA",
        "url_oficial": nuevo["url_oficial"],
        "aviso": nuevo["aviso"],
        "fecha": nuevo.get("fecha", "No confirmado"),
        "hora": nuevo.get("hora", "No confirmado"),
        "gmt": nuevo.get("gmt", "No confirmado"),
        "clasificacion": nuevo.get("clasificacion", "No confirmado"),
        "lat": nuevo.get("lat", "No confirmado"),
        "lon": nuevo.get("lon", "No confirmado"),
        "referencia": nuevo.get("referencia", "No confirmado"),
        "viento": nuevo.get("viento", "No confirmado"),
        "racha": nuevo.get("racha", "No confirmado"),
        "movimiento": nuevo.get("movimiento", "No confirmado"),
        "presion": nuevo.get("presion", "No confirmado"),
        "lluvia": nuevo.get("lluvia", "No confirmado"),
        "vigilancia": nuevo.get("vigilancia", "No confirmado"),
        "viento_costero": nuevo.get("viento_costero", "No confirmado"),
        "oleaje": nuevo.get("oleaje", "No confirmado"),

        # El PDF histórico no garantiza una imagen de trayectoria ni una
        # tabla HTML de pronóstico. Se conservan sólo para no romper el diseño.
        # Quedan identificadas como contenido de la publicación anterior hasta
        # que el SMN vuelva a exponerlas en una fuente estructurada confirmable.
        "mapa": actual.get("mapa", "No confirmado"),
        "pronostico": actual.get("pronostico", []),
    }
    return salida

def main():
    print("========================================")
    print(" ACTUALIZADOR CICLÓN POLO V5.2")
    print(" Fuente exclusiva: SMN / CONAGUA")
    print(" Histórico oficial:", HISTORICO_ID)
    print("========================================")

    aviso, url_pdf = obtener_ultimo_boletin()

    actual = cargar_actual()
    aviso_actual = actual.get("aviso")
    if isinstance(aviso_actual, int) and aviso < aviso_actual:
        raise RuntimeError(
            f"El histórico devolvió Aviso {aviso}, anterior al publicado {aviso_actual}."
        )

    texto = texto_pdf(url_pdf)
    nuevo = extraer_datos(aviso, texto, url_pdf)
    validar_esenciales(nuevo)

    salida = combinar_con_actual(nuevo)
    nuevo_json = json.dumps(salida, ensure_ascii=False, indent=2) + "\n"

    if DATOS.exists() and DATOS.read_text(encoding="utf-8") == nuevo_json:
        print("datos_polo.json ya corresponde al último boletín.")
        return

    tmp = Path("datos_polo.json.tmp")
    tmp.write_text(nuevo_json, encoding="utf-8")
    tmp.replace(DATOS)

    print(f"datos_polo.json actualizado al Aviso No. {aviso}.")
    print("index.html NO fue modificado.")

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
