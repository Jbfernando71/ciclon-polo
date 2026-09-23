import requests
import re
import sys
import html
from pathlib import Path
from bs4 import BeautifulSoup
from datetime import datetime


# ============================================================
# CONFIGURACIÓN
# ============================================================

URL = "https://smn.conagua.gob.mx/tools/GUI/PortalLaravel/public/WebAviso"
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
# CONSULTAR EXCLUSIVAMENTE SMN / CONAGUA
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

    except requests.exceptions.Timeout:

        raise RuntimeError(
            "El portal del SMN excedió el tiempo máximo "
            "de respuesta."
        )

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
            "No pude confirmar la presencia de Polo "
            "en la publicación oficial."
        )

    return texto


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

    # La última aparición suele corresponder al bloque
    # operativo/actual del sistema.
    pos = coincidencias[-1].start()

    inicio = max(
        0,
        pos - 7000
    )

    fin = min(
        len(texto),
        pos + 18000
    )

    bloque = texto[inicio:fin]

    if not re.search(
        r"\bPolo\b",
        bloque,
        re.IGNORECASE
    ):

        raise RuntimeError(
            "No fue posible aislar el contexto de Polo."
        )

    return bloque


# ============================================================
# EXTRAER HISTORIAL / ÚLTIMO AVISO
# ============================================================

def extraer_registro_actual(texto):

    patron = re.compile(
        r"""
        (?P<aviso>\d{1,3})
        \s+
        (?P<fecha>20\d{2}-\d{2}-\d{2})
        \s+
        (?P<hora>\d{2}:\d{2})
        \s+horas
        \s*
        \(
        (?P<gmt>\d{2}:\d{2})
        \s+horas\s+GMT
        \)
        \s+
        (?P<lat>\d{1,2}(?:\.\d+)?)
        \s+
        (?P<lon>\d{2,3}(?:\.\d+)?)
        \s+
        (?P<referencia>A\s+.*?)
        \s+
        (?P<viento>\d{2,3})
        /
        (?P<racha>\d{2,3})
        """,
        re.IGNORECASE | re.VERBOSE
    )

    registros = []

    for m in patron.finditer(texto):

        registro = {
            "aviso": int(m.group("aviso")),
            "fecha": m.group("fecha"),
            "hora": m.group("hora"),
            "gmt": m.group("gmt"),
            "lat": m.group("lat"),
            "lon": m.group("lon"),
            "referencia": limpiar(
                m.group("referencia")
            ),
            "viento": int(m.group("viento")),
            "racha": int(m.group("racha")),
        }

        lat = float(registro["lat"])
        lon = float(registro["lon"])

        if not (0 <= registro["aviso"] <= 200):
            continue

        if not (0 <= lat <= 35):
            continue

        if not (80 <= lon <= 130):
            continue

        if not (20 <= registro["viento"] <= 400):
            continue

        if not (20 <= registro["racha"] <= 450):
            continue

        registros.append(registro)

    if not registros:

        raise RuntimeError(
            "Polo aparece en el portal, pero no pude "
            "validar el registro del último aviso."
        )

    # Más seguro que ordenar únicamente por número:
    # fecha + hora + número de aviso.
    def clave(r):

        fecha_hora = datetime.strptime(
            f"{r['fecha']} {r['hora']}",
            "%Y-%m-%d %H:%M"
        )

        return (
            fecha_hora,
            r["aviso"]
        )

    return max(
        registros,
        key=clave
    )


# ============================================================
# LOCALIZAR BLOQUE DE CONDICIONES ACTUALES
# ============================================================

def obtener_bloque_actual(texto, datos):

    # Construimos marcadores con datos que ya fueron
    # confirmados en el historial del SMN.
    hora = re.escape(datos["hora"])
    gmt = re.escape(datos["gmt"])
    lat = re.escape(datos["lat"])
    lon = re.escape(datos["lon"])

    patrones_inicio = [
        (
            r"Condiciones\s+Actuales"
            r".{0,250}?"
            + hora +
            r"\s+horas"
            r".{0,150}?"
            + gmt +
            r"\s+horas\s+GMT"
        ),
        (
            r"Condiciones\s+Actuales"
            r".{0,500}?"
            r"Latitud\s+Norte:\s*"
            + lat +
            r".{0,150}?"
            r"Longitud\s+Oeste:\s*"
            + lon
        ),
    ]

    inicio = None

    for patron in patrones_inicio:

        m = re.search(
            patron,
            texto,
            re.IGNORECASE | re.DOTALL
        )

        if m:
            inicio = m.start()
            break

    if inicio is None:

        # Último recurso: buscamos Condiciones Actuales
        # cerca de las coordenadas confirmadas.
        candidatos = list(
            re.finditer(
                r"Condiciones\s+Actuales",
                texto,
                re.IGNORECASE
            )
        )

        for candidato in reversed(candidatos):

            fragmento = texto[
                candidato.start():
                candidato.start() + 6000
            ]

            if (
                re.search(
                    rf"Latitud\s+Norte:\s*{lat}",
                    fragmento,
                    re.IGNORECASE
                )
                and
                re.search(
                    rf"Longitud\s+Oeste:\s*{lon}",
                    fragmento,
                    re.IGNORECASE
                )
            ):

                inicio = candidato.start()
                break

    if inicio is None:

        raise RuntimeError(
            "No pude identificar inequívocamente "
            "el bloque de Condiciones Actuales de Polo."
        )

    # Ventana limitada. Esto evita capturar otros avisos.
    bloque = texto[
        inicio:
        min(len(texto), inicio + 9000)
    ]

    return bloque


# ============================================================
# EXTRAER CLASIFICACIÓN
# ============================================================

def extraer_clasificacion(texto, datos):

    bloque = obtener_bloque_actual(
        texto,
        datos
    )

    # Buscamos primero dentro del bloque actual.
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

            valor = limpiar(
                m.group(1)
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

    # Si el bloque actual no lo contiene, buscamos cerca
    # del nombre Polo, pero NO inferimos por velocidad.
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

    return "No confirmado"


# ============================================================
# EXTRAER DATOS DEL BLOQUE ACTUAL
# ============================================================

def extraer_datos_actuales(texto, datos):

    bloque = obtener_bloque_actual(
        texto,
        datos
    )

    adicionales = {}

    # --------------------------------------------------------
    # PRESIÓN
    #
    # Formato real observado:
    # Presión mínima central [hpa] 931
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # MOVIMIENTO
    #
    # Se detiene justo antes de Vientos máximos.
    # --------------------------------------------------------

    movimiento = buscar(
        r"Desplazamiento\s+actual\s+"
        r"(.+?)"
        r"(?=\s+Vientos\s+m[aá]ximos)",
        bloque,
        re.IGNORECASE | re.DOTALL
    )

    adicionales["movimiento"] = (
        movimiento
        if movimiento
        else "No confirmado"
    )

    # --------------------------------------------------------
    # LLUVIA
    #
    # Inicio: Pronóstico de lluvia
    # Fin: siguiente encabezado meteorológico conocido.
    # --------------------------------------------------------

    lluvia = buscar(
        r"Pron[oó]stico\s+de\s+lluvia\s+"
        r"(.+?)"
        r"(?="
        r"\s+(?:"
        r"Pron[oó]stico\s+de\s+viento|"
        r"Pron[oó]stico\s+de\s+oleaje|"
        r"Viento\s+y\s+oleaje|"
        r"Vientos?\s+en\s+costas?|"
        r"Oleaje|"
        r"Zona\s+de\s+prevenci[oó]n|"
        r"Zona\s+de\s+vigilancia|"
        r"Se\s+mantiene\s+zona|"
        r"Se\s+establece\s+zona|"
        r"Recomendaciones|"
        r"EL\s+SIGUIENTE\s+AVISO"
        r")"
        r")",
        bloque,
        re.IGNORECASE | re.DOTALL
    )

    adicionales["lluvia"] = (
        lluvia
        if lluvia
        else "No confirmado"
    )

    # --------------------------------------------------------
    # VIENTO COSTERO
    # --------------------------------------------------------

    viento_costero = buscar(
        r"(?:"
        r"Pron[oó]stico\s+de\s+viento|"
        r"Vientos?\s+en\s+costas?"
        r")"
        r"\s+"
        r"(.+?)"
        r"(?="
        r"\s+(?:"
        r"Pron[oó]stico\s+de\s+oleaje|"
        r"Oleaje|"
        r"Zona\s+de\s+prevenci[oó]n|"
        r"Zona\s+de\s+vigilancia|"
        r"Se\s+mantiene\s+zona|"
        r"Se\s+establece\s+zona|"
        r"Recomendaciones|"
        r"EL\s+SIGUIENTE\s+AVISO"
        r")"
        r")",
        bloque,
        re.IGNORECASE | re.DOTALL
    )

    adicionales["viento_costero"] = (
        viento_costero
        if viento_costero
        else "No confirmado"
    )

    # --------------------------------------------------------
    # OLEAJE
    # --------------------------------------------------------

    oleaje = buscar(
        r"(?:Pron[oó]stico\s+de\s+oleaje|Oleaje)"
        r"\s*[:\-]?\s*"
        r"(.+?)"
        r"(?="
        r"\s+(?:"
        r"Zona\s+de\s+prevenci[oó]n|"
        r"Zona\s+de\s+vigilancia|"
        r"Se\s+mantiene\s+zona|"
        r"Se\s+establece\s+zona|"
        r"Recomendaciones|"
        r"EL\s+SIGUIENTE\s+AVISO"
        r")"
        r")",
        bloque,
        re.IGNORECASE | re.DOTALL
    )

    adicionales["oleaje"] = (
        oleaje
        if oleaje
        else "No confirmado"
    )

    # --------------------------------------------------------
    # ZONAS DE PREVENCIÓN / VIGILANCIA
    # --------------------------------------------------------

    vigilancia = buscar(
        r"("
        r"(?:Se\s+mantiene|Se\s+establece)"
        r"\s+zona\s+de\s+"
        r"(?:prevenci[oó]n|vigilancia)"
        r".+?"
        r")"
        r"(?="
        r"\s+(?:"
        r"Pron[oó]stico|"
        r"Recomendaciones|"
        r"EL\s+SIGUIENTE\s+AVISO|"
        r"El\s+Servicio\s+Meteorol[oó]gico"
        r")"
        r")",
        bloque,
        re.IGNORECASE | re.DOTALL
    )

    if not vigilancia:

        vigilancia = buscar(
            r"("
            r"Zona\s+de\s+"
            r"(?:prevenci[oó]n|vigilancia)"
            r".+?"
            r")"
            r"(?="
            r"\s+(?:"
            r"Pron[oó]stico|"
            r"Recomendaciones|"
            r"EL\s+SIGUIENTE\s+AVISO"
            r")"
            r")",
            bloque,
            re.IGNORECASE | re.DOTALL
        )

    adicionales["vigilancia"] = (
        vigilancia
        if vigilancia
        else "No confirmado"
    )

    return adicionales


# ============================================================
# EXTRAER TODOS LOS DATOS
# ============================================================

def extraer_datos(texto):

    datos = extraer_registro_actual(
        texto
    )

    datos["clasificacion"] = (
        extraer_clasificacion(
            texto,
            datos
        )
    )

    adicionales = extraer_datos_actuales(
        texto,
        datos
    )

    datos.update(
        adicionales
    )

    return datos


# ============================================================
# VALIDACIÓN FINAL
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
            "Faltan campos esenciales del aviso: "
            + ", ".join(faltantes)
        )

    # Validaciones de coherencia.
    if datos["racha"] < datos["viento"]:

        raise RuntimeError(
            "Validación rechazada: la racha es inferior "
            "al viento sostenido."
        )

    if not re.search(
        r"(?:km|kil[oó]metros?)",
        datos["referencia"],
        re.IGNORECASE
    ):

        raise RuntimeError(
            "La referencia geográfica no parece válida."
        )


# ============================================================
# GENERAR DASHBOARD
# ============================================================

def generar_html(d):

    aviso = escapar(d["aviso"])
    fecha = escapar(d["fecha"])
    hora = escapar(d["hora"])
    gmt = escapar(d["gmt"])

    lat = escapar(d["lat"])
    lon = escapar(d["lon"])

    referencia = escapar(
        d["referencia"]
    )

    clasificacion = escapar(
        d["clasificacion"]
    )

    presion = escapar(
        d["presion"]
    )

    movimiento = escapar(
        d["movimiento"]
    )

    lluvia = escapar(
        d["lluvia"]
    )

    viento_costero = escapar(
        d["viento_costero"]
    )

    oleaje = escapar(
        d["oleaje"]
    )

    vigilancia = escapar(
        d["vigilancia"]
    )

    viento = d["viento"]
    racha = d["racha"]

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

<title>Dashboard SMN | Ciclón Tropical Polo</title>

<style>

:root{{
--bg:#07131f;
--panel:#102235;
--text:#eef6ff;
--muted:#a9bed2;
--line:#27445f;
--accent:#49a7ff;
--warn:#ffbd4a;
--danger:#ff6868;
--ok:#67d391
}}

*{{box-sizing:border-box}}

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
font-size:16px;
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
color:#fff;
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
.grid{{grid-template-columns:repeat(3,1fr)}}
.two{{grid-template-columns:1fr}}
}}

@media(max-width:520px){{
.grid{{grid-template-columns:1fr}}
.wrap{{padding:12px}}
}}

</style>

</head>

<body>

<main class="wrap">

<div class="top">

<div>
<h1>Seguimiento del Ciclón Tropical Polo</h1>

<div class="sub">
Servicio Meteorológico Nacional · CONAGUA · Pacífico mexicano
</div>
</div>

<div class="badge">
● SEGUIMIENTO ACTIVO · AVISO {aviso}
</div>

</div>


<section class="grid">

<div class="card">
<small>Clasificación</small>
<div class="big">{clasificacion}</div>
</div>

<div class="card">
<small>Posición</small>
<div class="big">{lat}° N · {lon}° O</div>
</div>

<div class="card">
<small>Viento sostenido</small>
<div class="big">{viento} km/h</div>
</div>

<div class="card">
<small>Rachas</small>
<div class="big">{racha} km/h</div>
</div>

<div class="card">
<small>Movimiento</small>
<div class="big">{movimiento}</div>
</div>

<div class="card">
<small>Presión mínima</small>
<div class="big">{presion}</div>
</div>

</section>


<div class="two">

<section class="panel">

<h2>Situación actual</h2>

<div class="effect">
<b>Referencia</b>
<span>{referencia}</span>
</div>

<div class="effect">
<b>Coordenadas</b>
<span>{lat}° N · {lon}° O</span>
</div>

<div class="alert">
<b>Zona de prevención / vigilancia</b><br>
{vigilancia}
</div>

</section>


<section class="panel">

<h2>Efectos confirmados por SMN/CONAGUA</h2>

<div class="effect">
<b>Lluvias</b>
<span>{lluvia}</span>
</div>

<div class="effect">
<b>Viento en costas</b>
<span>{viento_costero}</span>
</div>

<div class="effect">
<b>Oleaje</b>
<span>{oleaje}</span>
</div>

<div class="effect">
<b>Viento máximo del ciclón</b>
<span>
{viento} km/h sostenidos · rachas de {racha} km/h
</span>
</div>

</section>

</div>


<section class="panel" style="margin-top:14px">

<h2>Datos del aviso oficial</h2>

<div class="effect">
<b>Aviso SMN/CONAGUA</b>
<span>No. {aviso}</span>
</div>

<div class="effect">
<b>Fecha y hora</b>
<span>
{fecha} · {hora} horas ({gmt} horas GMT)
</span>
</div>

<div class="source">
Los campos que el actualizador no puede identificar
inequívocamente en la publicación oficial se muestran como
<strong>No confirmado</strong>. No se completan datos con NHC
ni con fuentes secundarias.
</div>

</section>


<div class="footer">

<div>

<b>Corte mostrado:</b>
{fecha} · {hora} horas.

<br>

Fuente exclusiva:
Servicio Meteorológico Nacional / CONAGUA.

<br>

Actualización automática mediante GitHub Actions.

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

    # El HTML generado contiene:
    # Corte mostrado: YYYY-MM-DD · HH:MM horas.
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

    texto = obtener_smn()

    datos = extraer_datos(
        texto
    )

    validar_datos(
        datos
    )

    print()
    print("========================================")
    print(" DATOS VALIDADOS")
    print("========================================")

    for clave, valor in datos.items():
        print(f"{clave}: {valor}")

    # --------------------------------------------------------
    # IMPEDIR RETROCESO DEL DASHBOARD
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
            "El aviso recuperado es anterior al que ya "
            "está publicado. index.html no será modificado."
        )

    nuevo_html = generar_html(
        datos
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
                "El aviso no contiene cambios respecto "
                "al dashboard publicado."
            )

            return

    # --------------------------------------------------------
    # ESCRITURA SEGURA / ATÓMICA
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
        f"index.html actualizado con Aviso No. "
        f"{datos['aviso']}."
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("========================================")
    print(" ACTUALIZADOR AUTOMÁTICO CICLÓN POLO V3")
    print(" Fuente exclusiva: SMN / CONAGUA")
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
