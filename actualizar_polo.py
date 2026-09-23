import requests
import re
import sys
import html
from pathlib import Path
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urljoin, urlparse


# ============================================================
# CONFIGURACIÓN
# ============================================================

URL_BASE = "https://smn.conagua.gob.mx/tools/GUI/PortalLaravel/public/WebAviso"
POLO_ID = "10822"
URL = f"{URL_BASE}?searchText={POLO_ID}"
DOMINIO_SMM = "smn.conagua.gob.mx"
INDEX = Path("index.html")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}


# ============================================================
# UTILIDADES
# ============================================================

def limpiar(texto):
    return re.sub(r"\s+", " ", texto or "").strip()


def escapar(valor):
    return html.escape(str(valor or "No confirmado"))


def buscar(patron, texto, flags=re.IGNORECASE):
    m = re.search(patron, texto, flags)

    if not m:
        return None

    return limpiar(m.group(1))


# ============================================================
# CONSULTAR SMN / CONAGUA
# ============================================================

def obtener_smn():

    print()
    print("Consultando exclusivamente SMN/CONAGUA...")
    print("URL:", URL)

    try:
        respuesta = requests.get(
            URL,
            headers=HEADERS,
            timeout=30
        )

        respuesta.raise_for_status()

    except requests.exceptions.RequestException as e:
        raise RuntimeError(
            f"No fue posible consultar SMN/CONAGUA: {e}"
        )

    print("Código HTTP:", respuesta.status_code)
    print("Tamaño:", len(respuesta.content), "bytes")

    soup = BeautifulSoup(
        respuesta.text,
        "html.parser"
    )

    # Conservamos el soup ORIGINAL para localizar
    # imágenes y tablas.
    soup_datos = BeautifulSoup(
        respuesta.text,
        "html.parser"
    )

    for elemento in soup(
        ["script", "style", "noscript"]
    ):
        elemento.decompose()

    texto = limpiar(
        soup.get_text(" ", strip=True)
    )

    if not texto:
        raise RuntimeError(
            "SMN respondió sin contenido textual utilizable."
        )

    if not re.search(
        r"\bPolo\b",
        texto,
        re.IGNORECASE
    ):
        raise RuntimeError(
            f"La respuesta de searchText={POLO_ID} no pudo validarse como Polo. "
            "Por seguridad index.html no será modificado."
        )

    print("Ciclón validado: Polo")
    print("Identificador SMN seleccionado:", POLO_ID)

    return texto, soup_datos


# ============================================================
# AISLAR CONTEXTO DE POLO
# ============================================================

def aislar_polo(texto):

    coincidencias = list(
        re.finditer(
            r"\bPolo\b",
            texto,
            re.IGNORECASE
        )
    )

    if not coincidencias:
        raise RuntimeError(
            "No se encontró Polo."
        )

    pos = coincidencias[-1].start()

    inicio = max(
        0,
        pos - 7000
    )

    fin = min(
        len(texto),
        pos + 18000
    )

    return texto[inicio:fin]


# ============================================================
# EXTRAER ÚLTIMO AVISO
# ============================================================

def extraer_registro_actual(texto):

    """
    Extrae las CONDICIONES ACTUALES del aviso activo de Polo.

    IMPORTANTE:
    - El número de aviso se toma del encabezado oficial:
      "Océano Pacífico - No. Aviso: N".
    - Hora, posición, referencia, movimiento, viento y presión
      se toman únicamente del bloque "Condiciones Actuales".
    - NO se usa la tabla de Pronóstico ni el Historial de Seguimiento
      para determinar el estado actual.
    """

    # --------------------------------------------------------
    # 1. NÚMERO DE AVISO: encabezado oficial del Pacífico
    # --------------------------------------------------------
    # Preferimos una referencia explícita Polo + número de aviso.
    m_aviso = re.search(
        r"(?:Hurac[aá]n|Tormenta\s+tropical|Depresi[oó]n\s+tropical)?"
        r"\s*Polo\s+(\d{1,3})\b",
        texto,
        re.IGNORECASE
    )

    # Fallback: en la respuesta específica searchText=10822, el encabezado
    # oficial puede contener "Océano Pacífico - No. Aviso: N".
    if not m_aviso:
        m_aviso = re.search(
            r"Oc[eé]ano\s+Pac[ií]fico\s*-\s*No\.\s*Aviso:\s*(\d{1,3})",
            texto,
            re.IGNORECASE
        )

    if not m_aviso:
        raise RuntimeError(
            "No pude confirmar el número de aviso de Polo en la respuesta "
            f"específica searchText={POLO_ID}."
        )

    aviso = int(m_aviso.group(1))
    print("Aviso de Polo identificado:", aviso)

    # --------------------------------------------------------
    # 2. AISLAR ESTRICTAMENTE "CONDICIONES ACTUALES"
    #    Termina antes de "Pronóstico" (tabla futura).
    # --------------------------------------------------------
    m_bloque = re.search(
        r"Condiciones\s+Actuales\s+(.+?)"
        r"(?=\s+Pron[oó]stico\s+D[ií]a/Hora\b)",
        texto,
        re.IGNORECASE | re.DOTALL
    )

    if not m_bloque:
        # Variante defensiva: cortar antes del encabezado
        # de la tabla de pronóstico.
        m_bloque = re.search(
            r"Condiciones\s+Actuales\s+(.+?)"
            r"(?=\s+D[ií]a/Hora\s+Latitud\b)",
            texto,
            re.IGNORECASE | re.DOTALL
        )

    if not m_bloque:
        raise RuntimeError(
            "No pude aislar inequívocamente el bloque "
            "'Condiciones Actuales'. index.html no será modificado."
        )

    bloque = limpiar(m_bloque.group(1))

    # --------------------------------------------------------
    # 3. HORA LOCAL / GMT
    # --------------------------------------------------------
    m_hora = re.search(
        r"Hora\s+local\s*\(hora\s+GMT\)\s*"
        r"(\d{1,2}:\d{2})\s+horas\s*"
        r"\((\d{1,2}:\d{2})\s+horas\s+GMT",
        bloque,
        re.IGNORECASE
    )

    if not m_hora:
        raise RuntimeError(
            "No pude confirmar la hora local/GMT en "
            "'Condiciones Actuales'."
        )

    hora = m_hora.group(1).zfill(5)
    gmt = m_hora.group(2).zfill(5)

    # --------------------------------------------------------
    # 4. POSICIÓN
    # --------------------------------------------------------
    m_pos = re.search(
        r"Latitud\s+Norte:\s*(\d{1,2}(?:\.\d+)?)\s+"
        r"Longitud\s+Oeste:\s*(\d{2,3}(?:\.\d+)?)",
        bloque,
        re.IGNORECASE
    )

    if not m_pos:
        raise RuntimeError(
            "No pude confirmar latitud/longitud en "
            "'Condiciones Actuales'."
        )

    lat = m_pos.group(1)
    lon = m_pos.group(2)

    # --------------------------------------------------------
    # 5. REFERENCIA
    # --------------------------------------------------------
    referencia = buscar(
        r"Distancia\s+al\s+lugar\s+m[aá]s\s+cercano\s+"
        r"(.+?)"
        r"(?=\s+Desplazamiento\s+actual)",
        bloque,
        re.IGNORECASE | re.DOTALL
    )

    if not referencia:
        raise RuntimeError(
            "No pude confirmar la referencia geográfica "
            "en 'Condiciones Actuales'."
        )

    # --------------------------------------------------------
    # 6. MOVIMIENTO
    # --------------------------------------------------------
    movimiento = buscar(
        r"Desplazamiento\s+actual\s+"
        r"(.+?)"
        r"(?=\s+Vientos\s+m[aá]ximos)",
        bloque,
        re.IGNORECASE | re.DOTALL
    )

    if not movimiento:
        raise RuntimeError(
            "No pude confirmar el desplazamiento actual."
        )

    # --------------------------------------------------------
    # 7. VIENTOS ACTUALES
    # --------------------------------------------------------
    m_viento = re.search(
        r"Vientos\s+m[aá]ximos\s*"
        r"(?:\[\s*km/h\s*\])?\s*"
        r"Sostenidos:\s*(\d{2,3})\s+"
        r"Rachas:\s*(\d{2,3})",
        bloque,
        re.IGNORECASE
    )

    if not m_viento:
        raise RuntimeError(
            "No pude confirmar viento sostenido y rachas "
            "en 'Condiciones Actuales'."
        )

    viento = int(m_viento.group(1))
    racha = int(m_viento.group(2))

    # --------------------------------------------------------
    # 8. PRESIÓN ACTUAL
    # --------------------------------------------------------
    presion = buscar(
        r"Presi[oó]n\s+m[ií]nima\s+central\s*"
        r"(?:\[\s*hpa\s*\])?\s*"
        r"[:\-]?\s*(\d{3,4})",
        bloque,
        re.IGNORECASE
    )

    # --------------------------------------------------------
    # 9. FECHA
    #
    # El bloque actual del portal no muestra la fecha junto
    # a la hora. La confirmamos usando EXCLUSIVAMENTE la fila
    # del Historial cuyo No. de Aviso coincide con el encabezado
    # y cuyos lat/lon/vientos coinciden con Condiciones Actuales.
    # Esto evita confundir pronósticos futuros con datos actuales.
    # --------------------------------------------------------
    historial_patron = re.compile(
        rf"\b{aviso}\s+"
        r"(?P<fecha>20\d{{2}}-\d{{2}}-\d{{2}})\s+"
        rf"{re.escape(hora)}\s+horas\s*"
        r"\([^)]*GMT[^)]*\)\s+"
        rf"{re.escape(lat)}\s+"
        rf"{re.escape(lon)}\s+"
        r"(?P<referencia>A\s+.*?)\s+"
        rf"{viento}/{racha}\b",
        re.IGNORECASE | re.DOTALL
    )

    m_hist = historial_patron.search(texto)

    if not m_hist:
        raise RuntimeError(
            "El aviso activo y las Condiciones Actuales no pudieron "
            "validarse contra la fila correspondiente del Historial "
            "de Seguimiento. Por seguridad no se actualizará index.html."
        )

    fecha = m_hist.group("fecha")

    datos = {
        "aviso": aviso,
        "fecha": fecha,
        "hora": hora,
        "gmt": gmt,
        "lat": lat,
        "lon": lon,
        "referencia": referencia,
        "viento": viento,
        "racha": racha,
        "movimiento": movimiento,
        "presion": f"{presion} hPa" if presion else "No confirmado",
        "_bloque_actual": bloque,
    }

    return datos


# ============================================================
# BLOQUE DE CONDICIONES ACTUALES
# ============================================================

def obtener_bloque_actual(texto, datos):

    bloque = datos.get("_bloque_actual")

    if bloque:
        return bloque

    # Fallback defensivo si se llama sin el bloque preaislado.
    m = re.search(
        r"Condiciones\s+Actuales\s+(.+?)"
        r"(?=\s+Pron[oó]stico\s+D[ií]a/Hora\b)",
        texto,
        re.IGNORECASE | re.DOTALL
    )

    if not m:
        raise RuntimeError(
            "No pude identificar inequívocamente el bloque "
            "actual de Polo."
        )

    return limpiar(m.group(1))


# ============================================================
# CLASIFICACIÓN
# ============================================================

def extraer_clasificacion(texto, datos):

    bloque = obtener_bloque_actual(
        texto,
        datos
    )

    patrones = [
        r"(Hurac[aá]n\s+categor[ií]a\s+[1-5])",
        r"(Tormenta\s+tropical)",
        r"(Depresi[oó]n\s+tropical)",
    ]

    for patron in patrones:

        m = re.search(
            patron,
            bloque,
            re.IGNORECASE
        )

        if m:

            valor = limpiar(m.group(1))

            categoria = re.search(
                r"categor[ií]a\s+([1-5])",
                valor,
                re.IGNORECASE
            )

            if categoria:
                return (
                    "Huracán categoría "
                    + categoria.group(1)
                )

            if re.search(
                r"Tormenta",
                valor,
                re.IGNORECASE
            ):
                return "Tormenta tropical"

            if re.search(
                r"Depresi[oó]n",
                valor,
                re.IGNORECASE
            ):
                return "Depresión tropical"

    contexto = aislar_polo(texto)

    for patron in patrones:

        coincidencias = list(
            re.finditer(
                patron,
                contexto,
                re.IGNORECASE
            )
        )

        if coincidencias:

            valor = limpiar(
                coincidencias[-1].group(1)
            )

            categoria = re.search(
                r"categor[ií]a\s+([1-5])",
                valor,
                re.IGNORECASE
            )

            if categoria:
                return (
                    "Huracán categoría "
                    + categoria.group(1)
                )

            if "tormenta" in valor.lower():
                return "Tormenta tropical"

            if "depres" in valor.lower():
                return "Depresión tropical"

    return "No confirmado"


# ============================================================
# DATOS ACTUALES
# ============================================================

def extraer_datos_actuales(texto, datos):

    bloque = obtener_bloque_actual(
        texto,
        datos
    )

    adicionales = {}

    # PRESIÓN
    presion = buscar(
        r"Presi[oó]n\s+m[ií]nima\s+central"
        r"\s*(?:\[\s*hpa\s*\])?"
        r"\s*[:\-]?\s*"
        r"(\d{3,4})",
        bloque
    )

    adicionales["presion"] = (
        f"{presion} hPa"
        if presion
        else "No confirmado"
    )

    # MOVIMIENTO
    movimiento = buscar(
        r"Desplazamiento\s+actual\s+"
        r"(.+?)"
        r"(?=\s+Vientos\s+m[aá]ximos)",
        bloque,
        re.IGNORECASE | re.DOTALL
    )

    adicionales["movimiento"] = (
        movimiento or "No confirmado"
    )

    # LLUVIA
    lluvia = buscar(
        r"Pron[oó]stico\s+de\s+lluvia\s+"
        r"(.+?)"
        r"(?=\s+Zona\s+de\s+vigilancia)",
        bloque,
        re.IGNORECASE | re.DOTALL
    )

    adicionales["lluvia"] = (
        lluvia or "No confirmado"
    )

    # ZONA
    vigilancia = buscar(
        r"Zona\s+de\s+vigilancia\s+"
        r"(.+?)"
        r"(?=\s+Comentarios\s+adicionales)",
        bloque,
        re.IGNORECASE | re.DOTALL
    )

    adicionales["vigilancia"] = (
        vigilancia or "No confirmado"
    )

    # COMENTARIOS ADICIONALES
    comentarios = buscar(
        r"Comentarios\s+adicionales\s+"
        r"(.+?)"
        r"(?=\s+Recomendaciones)",
        bloque,
        re.IGNORECASE | re.DOTALL
    )

    if comentarios:

        # VIENTO COSTERO
        viento_costero = buscar(
            r"("
            r"(?:Se\s+prev[eé]n\s+)?"
            r"rachas?\s+de\s+viento\s+"
            r"de\s+\d+(?:\.\d+)?\s+a\s+"
            r"\d+(?:\.\d+)?\s*km/h"
            r".*?"
            r")"
            r"(?="
            r"\s+y\s+oleaje|"
            r";|"
            r"\.|$"
            r")",
            comentarios,
            re.IGNORECASE | re.DOTALL
        )

        # OLEAJE
        oleaje = buscar(
            r"("
            r"oleaje\s+de\s+"
            r"\d+(?:\.\d+)?\s+a\s+"
            r"\d+(?:\.\d+)?\s+metros?"
            r".*"
            r")",
            comentarios,
            re.IGNORECASE | re.DOTALL
        )

    else:

        viento_costero = None
        oleaje = None

    adicionales["viento_costero"] = (
        viento_costero or "No confirmado"
    )

    adicionales["oleaje"] = (
        oleaje or "No confirmado"
    )

    return adicionales


# ============================================================
# MAPA OFICIAL SMN
# ============================================================

def extraer_mapa_trayectoria(soup):

    candidatos = []

    for img in soup.find_all("img"):

        src = img.get("src")

        if not src:
            continue

        alt = limpiar(
            img.get("alt", "")
        )

        title = limpiar(
            img.get("title", "")
        )

        texto = (
            alt + " " +
            title + " " +
            src
        ).lower()

        puntuacion = 0

        if "trayectoria" in texto:
            puntuacion += 10

        if "pronost" in texto:
            puntuacion += 5

        if "imgtray" in src.lower():
            puntuacion += 10

        if puntuacion:
            candidatos.append(
                (puntuacion, src)
            )

    if not candidatos:

        print(
            "No se encontró una imagen de trayectoria "
            "identificable."
        )

        return None

    candidatos.sort(
        reverse=True
    )

    src = candidatos[0][1]

    url_imagen = urljoin(
        URL,
        src
    )

    parsed = urlparse(
        url_imagen
    )

    # --------------------------------------------------------
    # SEGURIDAD:
    # únicamente dominio oficial SMN/CONAGUA.
    # --------------------------------------------------------

    if parsed.hostname != DOMINIO_SMM:

        print(
            "La imagen localizada no pertenece "
            "al dominio oficial SMN."
        )

        return None

    print(
        "Mapa oficial de Polo:",
        url_imagen
    )

    return url_imagen


# ============================================================
# TABLA DE PRONÓSTICO
# ============================================================

def extraer_pronostico(soup):

    resultados = []

    for tabla in soup.find_all("table"):

        filas = tabla.find_all("tr")

        if not filas:
            continue

        encabezado = limpiar(
            filas[0].get_text(
                " ",
                strip=True
            )
        ).lower()

        # ----------------------------------------------------
        # Identificar inequívocamente tabla de pronóstico.
        # ----------------------------------------------------

        if not (
            "día/hora" in encabezado
            or "dia/hora" in encabezado
        ):
            continue

        if "latitud" not in encabezado:
            continue

        if "categor" not in encabezado:
            continue

        for fila in filas[1:]:

            celdas = [
                limpiar(
                    celda.get_text(
                        " ",
                        strip=True
                    )
                )
                for celda
                in fila.find_all(
                    ["td", "th"]
                )
            ]

            if len(celdas) < 6:
                continue

            # Validar formato Día/Hora.
            if not re.fullmatch(
                r"\d{1,2}/\d{2}h",
                celdas[0]
            ):
                continue

            resultados.append({
                "dia_hora": celdas[0],
                "lat": celdas[1],
                "lon": celdas[2],
                "viento": celdas[3],
                "categoria": celdas[4],
                "ubicacion": celdas[5],
            })

        if resultados:
            break

    print(
        "Posiciones de pronóstico encontradas:",
        len(resultados)
    )

    return resultados


# ============================================================
# DATOS COMPLETOS
# ============================================================

def extraer_datos(texto):

    datos = extraer_registro_actual(texto)

    datos["clasificacion"] = extraer_clasificacion(
        texto,
        datos
    )

    adicionales = extraer_datos_actuales(
        texto,
        datos
    )

    # Movimiento y presión ya fueron obtenidos estrictamente
    # desde Condiciones Actuales. Los demás campos se agregan aquí.
    adicionales["movimiento"] = datos["movimiento"]
    adicionales["presion"] = datos["presion"]

    datos.update(adicionales)

    # Campo interno: no debe formar parte de la salida pública/log.
    datos.pop("_bloque_actual", None)

    return datos


# ============================================================
# VALIDACIÓN
# ============================================================

def validar_datos(datos):

    obligatorios = [
        "aviso",
        "fecha",
        "hora",
        "gmt",
        "lat",
        "lon",
        "referencia",
        "viento",
        "racha",
    ]

    faltantes = [
        campo
        for campo in obligatorios
        if datos.get(campo) in (
            None,
            "",
            "No confirmado"
        )
    ]

    if faltantes:
        raise RuntimeError(
            "Faltan campos esenciales: "
            + ", ".join(faltantes)
        )

    if datos["racha"] < datos["viento"]:
        raise RuntimeError(
            "La racha es inferior al viento sostenido."
        )


# ============================================================
# HTML TABLA PRONÓSTICO
# ============================================================

def generar_tabla_pronostico(pronostico):

    if not pronostico:

        return """
        <div class="effect">
        <b>Pronóstico</b>
        <span>No confirmado</span>
        </div>
        """

    filas = ""

    for p in pronostico:

        filas += f"""
        <tr>
        <td>{escapar(p["dia_hora"])}</td>
        <td>{escapar(p["lat"])}° N</td>
        <td>{escapar(p["lon"])}° O</td>
        <td>{escapar(p["viento"])} km/h</td>
        <td>{escapar(p["categoria"])}</td>
        <td>{escapar(p["ubicacion"])}</td>
        </tr>
        """

    return f"""
    <div class="table-wrap">
    <table>
    <thead>
    <tr>
    <th>Día/Hora</th>
    <th>Latitud</th>
    <th>Longitud</th>
    <th>Viento/Rachas</th>
    <th>Categoría</th>
    <th>Ubicación</th>
    </tr>
    </thead>

    <tbody>
    {filas}
    </tbody>
    </table>
    </div>
    """


# ============================================================
# GENERAR HTML
# ============================================================

def generar_html(
    d,
    mapa,
    pronostico
):

    mapa_html = ""

    if mapa:

        mapa_seguro = escapar(
            mapa
        )

        mapa_html = f"""
        <a
        href="{mapa_seguro}"
        target="_blank"
        rel="noopener">

        <img
        class="mapa"
        src="{mapa_seguro}"
        alt="Trayectoria pronóstico de Polo publicada por SMN/CONAGUA">

        </a>

        <div class="map-note">
        Trayectoria pronóstico publicada por
        el Servicio Meteorológico Nacional /
        CONAGUA.
        </div>
        """

    else:

        mapa_html = """
        <div class="effect">
        <b>Mapa de trayectoria</b>
        <span>
        No confirmado en la publicación oficial.
        </span>
        </div>
        """

    tabla_html = generar_tabla_pronostico(
        pronostico
    )

    return f"""<!doctype html>
<html lang="es">

<head>

<meta charset="utf-8">

<meta
name="viewport"
content="width=device-width,initial-scale=1">

<meta
http-equiv="refresh"
content="900">

<title>
Dashboard SMN | Ciclón Tropical Polo
</title>

<style>

:root{{
--bg:#07131f;
--panel:#102235;
--text:#eef6ff;
--muted:#a9bed2;
--line:#27445f;
--accent:#49a7ff;
--warn:#ffbd4a;
}}

*{{
box-sizing:border-box
}}

body{{
margin:0;
background:linear-gradient(180deg,#07131f,#0a1928);
color:var(--text);
font-family:Segoe UI,Arial,sans-serif
}}

.wrap{{
max-width:1450px;
margin:auto;
padding:22px
}}

.top{{
display:flex;
gap:18px;
align-items:center;
justify-content:space-between;
flex-wrap:wrap
}}

h1{{
font-size:26px;
margin:0
}}

.sub{{
color:var(--muted);
margin-top:5px
}}

.badge{{
background:#153653;
border:1px solid #2c618d;
padding:8px 12px;
border-radius:999px;
font-weight:700
}}

.grid{{
display:grid;
grid-template-columns:repeat(6,1fr);
gap:12px;
margin:20px 0
}}

.card,.panel{{
background:rgba(16,34,53,.96);
border:1px solid var(--line);
border-radius:14px;
padding:16px
}}

.card small{{
color:var(--muted);
text-transform:uppercase;
font-weight:700
}}

.big{{
font-size:22px;
font-weight:800;
margin-top:8px
}}

.two{{
display:grid;
grid-template-columns:1fr 1fr;
gap:14px
}}

.panel h2{{
font-size:17px;
margin:0 0 14px;
color:#d8eaff
}}

.effect{{
padding:14px;
background:#0d1d2c;
border-radius:10px;
border:1px solid #223d55;
margin-top:10px;
line-height:1.55
}}

.effect b{{
display:block;
margin-bottom:5px
}}

.effect span{{
color:var(--muted)
}}

.alert{{
margin-top:14px;
background:#3b2d16;
border:1px solid #6d5325;
color:#ffe2a3;
padding:12px;
border-radius:10px;
line-height:1.55
}}

.mapa{{
display:block;
width:100%;
max-height:720px;
object-fit:contain;
background:#fff;
border-radius:12px;
border:1px solid var(--line)
}}

.map-note{{
margin-top:8px;
font-size:12px;
color:var(--muted)
}}

.table-wrap{{
overflow-x:auto
}}

table{{
width:100%;
border-collapse:collapse;
font-size:13px
}}

th,td{{
padding:11px;
border-bottom:1px solid var(--line);
text-align:left;
vertical-align:top
}}

th{{
color:#bcd3e7;
background:#0d1d2c
}}

td{{
color:#dce9f5
}}

.footer{{
margin-top:14px;
display:flex;
justify-content:space-between;
gap:12px;
flex-wrap:wrap;
color:var(--muted);
font-size:12px
}}

.btn{{
display:inline-block;
background:#1c75bc;
color:white;
text-decoration:none;
padding:10px 14px;
border-radius:9px;
font-weight:700
}}

.source{{
margin-top:14px;
padding:10px 12px;
border-left:3px solid var(--accent);
background:#0d1d2c;
color:var(--muted);
font-size:12px;
line-height:1.5
}}

@media(max-width:1000px){{

.grid{{
grid-template-columns:repeat(3,1fr)
}}

.two{{
grid-template-columns:1fr
}}

}}

@media(max-width:520px){{

.grid{{
grid-template-columns:1fr
}}

.wrap{{
padding:12px
}}

}}

</style>

</head>


<body>

<main class="wrap">


<div class="top">

<div>

<h1>
Seguimiento del Ciclón Tropical Polo
</h1>

<div class="sub">
Servicio Meteorológico Nacional ·
CONAGUA · Pacífico mexicano
</div>

</div>

<div class="badge">
● SEGUIMIENTO ACTIVO ·
AVISO {escapar(d["aviso"])}
</div>

</div>


<section class="grid">

<div class="card">
<small>Clasificación</small>
<div class="big">
{escapar(d["clasificacion"])}
</div>
</div>

<div class="card">
<small>Posición</small>
<div class="big">
{escapar(d["lat"])}° N ·
{escapar(d["lon"])}° O
</div>
</div>

<div class="card">
<small>Viento sostenido</small>
<div class="big">
{d["viento"]} km/h
</div>
</div>

<div class="card">
<small>Rachas</small>
<div class="big">
{d["racha"]} km/h
</div>
</div>

<div class="card">
<small>Movimiento</small>
<div class="big">
{escapar(d["movimiento"])}
</div>
</div>

<div class="card">
<small>Presión mínima</small>
<div class="big">
{escapar(d["presion"])}
</div>
</div>

</section>


<div class="two">


<section class="panel">

<h2>Situación actual</h2>

<div class="effect">
<b>Referencia</b>
<span>
{escapar(d["referencia"])}
</span>
</div>

<div class="effect">
<b>Coordenadas</b>
<span>
{escapar(d["lat"])}° N ·
{escapar(d["lon"])}° O
</span>
</div>

<div class="alert">
<b>Zona de prevención / vigilancia</b>
<br>
{escapar(d["vigilancia"])}
</div>

</section>


<section class="panel">

<h2>
Efectos confirmados por SMN/CONAGUA
</h2>

<div class="effect">
<b>Lluvias</b>
<span>
{escapar(d["lluvia"])}
</span>
</div>

<div class="effect">
<b>Viento en costas</b>
<span>
{escapar(d["viento_costero"])}
</span>
</div>

<div class="effect">
<b>Oleaje</b>
<span>
{escapar(d["oleaje"])}
</span>
</div>

</section>

</div>


<section
class="panel"
style="margin-top:14px">

<h2>
Trayectoria pronóstico — SMN/CONAGUA
</h2>

{mapa_html}

</section>


<section
class="panel"
style="margin-top:14px">

<h2>
Pronóstico oficial de trayectoria
</h2>

{tabla_html}

</section>


<section
class="panel"
style="margin-top:14px">

<h2>
Datos del aviso oficial
</h2>

<div class="effect">
<b>Aviso SMN/CONAGUA</b>
<span>
No. {escapar(d["aviso"])}
</span>
</div>

<div class="effect">
<b>Fecha y hora</b>
<span>
{escapar(d["fecha"])} ·
{escapar(d["hora"])} horas
({escapar(d["gmt"])} horas GMT)
</span>
</div>

<div class="source">

Fuente exclusiva:
Servicio Meteorológico Nacional /
Comisión Nacional del Agua.

<br>

Los datos que no pueden confirmarse
inequívocamente se muestran como
<strong>No confirmado</strong>.

<br>

No se utilizan datos del NHC
ni de fuentes secundarias.

</div>

</section>


<div class="footer">

<div>

<b>Corte mostrado:</b>
{escapar(d["fecha"])} ·
{escapar(d["hora"])} horas.

<br>

Actualización automática
mediante GitHub Actions.

</div>

<a
class="btn"
href="{URL}"
target="_blank"
rel="noopener">

Abrir aviso oficial SMN ↗

</a>

</div>


</main>

</body>

</html>
"""


# ============================================================
# EVITAR RETROCESOS
# ============================================================

def obtener_corte_html_actual():

    if not INDEX.exists():
        return None

    contenido = INDEX.read_text(
        encoding="utf-8"
    )

    m = re.search(
        r"Corte\s+mostrado:</b>\s*"
        r"(20\d{2}-\d{2}-\d{2})"
        r"\s*·\s*"
        r"(\d{2}:\d{2})\s+horas",
        contenido,
        re.IGNORECASE
    )

    if not m:
        return None

    try:
        return datetime.strptime(
            f"{m.group(1)} {m.group(2)}",
            "%Y-%m-%d %H:%M"
        )

    except ValueError:
        return None


# ============================================================
# ACTUALIZAR
# ============================================================

def actualizar():

    texto, soup = obtener_smn()

    datos = extraer_datos(
        texto
    )

    validar_datos(
        datos
    )

    mapa = extraer_mapa_trayectoria(
        soup
    )

    pronostico = extraer_pronostico(
        soup
    )

    print()
    print("========================================")
    print(" DATOS VALIDADOS")
    print("========================================")

    for clave, valor in datos.items():
        print(f"{clave}: {valor}")

    print(
        "mapa:",
        mapa or "No confirmado"
    )

    print(
        "filas pronóstico:",
        len(pronostico)
    )

    # --------------------------------------------------------
    # EVITAR RETROCESO
    # --------------------------------------------------------

    nuevo_corte = datetime.strptime(
        f"{datos['fecha']} {datos['hora']}",
        "%Y-%m-%d %H:%M"
    )

    corte_actual = obtener_corte_html_actual()

    if (
        corte_actual is not None
        and nuevo_corte < corte_actual
    ):
        raise RuntimeError(
            "El aviso recuperado es anterior "
            "al publicado."
        )

    nuevo_html = generar_html(
        datos,
        mapa,
        pronostico
    )

    # --------------------------------------------------------
    # SIN CAMBIOS
    # --------------------------------------------------------

    if INDEX.exists():

        actual = INDEX.read_text(
            encoding="utf-8"
        )

        if actual == nuevo_html:

            print()
            print(
                "No existen cambios respecto "
                "al dashboard publicado."
            )

            return

    # --------------------------------------------------------
    # ESCRITURA ATÓMICA
    # --------------------------------------------------------

    temporal = Path(
        "index.html.tmp"
    )

    temporal.write_text(
        nuevo_html,
        encoding="utf-8"
    )

    temporal.replace(
        INDEX
    )

    print()
    print(
        f"index.html actualizado con "
        f"Aviso No. {datos['aviso']}."
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("========================================")
    print(" ACTUALIZADOR CICLÓN POLO V4.2.2")
    print(" Fuente exclusiva: SMN / CONAGUA")
    print(f" URL específica de Polo: {URL}")
    print(" Mapa + tabla de trayectoria automática")
    print("========================================")

    actualizar()


if __name__ == "__main__":

    try:

        main()

    except Exception as e:

        print()

        print(
            "ERROR:",
            e,
            file=sys.stderr
        )

        print(
            "Por seguridad index.html permanece "
            "sin modificaciones.",
            file=sys.stderr
        )

        sys.exit(1)
