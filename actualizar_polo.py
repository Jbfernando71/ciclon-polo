import requests
import re
import sys
import html
from bs4 import BeautifulSoup
from pathlib import Path


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


def buscar(patron, texto, flags=re.IGNORECASE):
    coincidencia = re.search(patron, texto, flags)

    if not coincidencia:
        return None

    return limpiar(coincidencia.group(1))


def escapar(valor):
    return html.escape(str(valor or "No confirmado"))


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

    except requests.exceptions.ConnectionError as e:

        raise RuntimeError(
            "No fue posible establecer conexión con "
            f"SMN/CONAGUA: {e}"
        )

    except requests.exceptions.RequestException as e:

        raise RuntimeError(
            f"Error consultando SMN/CONAGUA: {e}"
        )

    print("Código HTTP:", respuesta.status_code)
    print(
        "Tamaño:",
        len(respuesta.content),
        "bytes"
    )

    soup = BeautifulSoup(
        respuesta.text,
        "html.parser"
    )

    # Eliminar contenido que no pertenece al texto
    # meteorológico visible.
    for elemento in soup(
        ["script", "style", "noscript"]
    ):
        elemento.decompose()

    texto = soup.get_text(
        " ",
        strip=True
    )

    texto = limpiar(texto)

    if not texto:

        raise RuntimeError(
            "SMN respondió sin contenido textual utilizable."
        )

    # --------------------------------------------------------
    # Confirmar POLO.
    # --------------------------------------------------------

    if not re.search(
        r"\bPolo\b",
        texto,
        re.IGNORECASE
    ):

        raise RuntimeError(
            "No pude confirmar un aviso de Polo "
            "en la publicación oficial del SMN."
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
            "No fue posible localizar Polo."
        )

    # Utilizamos una ventana amplia alrededor de la última
    # referencia a Polo encontrada en la publicación.
    posicion = coincidencias[-1].start()

    inicio = max(
        0,
        posicion - 5000
    )

    fin = min(
        len(texto),
        posicion + 15000
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
# EXTRAER REGISTRO MÁS RECIENTE
# ============================================================

def extraer_registro_actual(texto):

    # --------------------------------------------------------
    # Formato observado directamente en el portal SMN:
    #
    # 25 2026-09-23 12:00 horas (18:00 horas GMT)
    # 15.6 102.1
    # A 240 km ...
    # 230/280
    #
    # --------------------------------------------------------

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
        re.IGNORECASE |
        re.VERBOSE
    )

    registros = []

    for coincidencia in patron.finditer(texto):

        registro = {
            "aviso": int(
                coincidencia.group("aviso")
            ),
            "fecha": coincidencia.group("fecha"),
            "hora": coincidencia.group("hora"),
            "gmt": coincidencia.group("gmt"),
            "lat": coincidencia.group("lat"),
            "lon": coincidencia.group("lon"),
            "referencia": limpiar(
                coincidencia.group("referencia")
            ),
            "viento": int(
                coincidencia.group("viento")
            ),
            "racha": int(
                coincidencia.group("racha")
            ),
        }

        # ----------------------------------------------------
        # Validaciones básicas.
        # ----------------------------------------------------

        lat = float(registro["lat"])
        lon = float(registro["lon"])

        if not (0 <= lat <= 35):
            continue

        if not (80 <= lon <= 130):
            continue

        if not (20 <= registro["viento"] <= 400):
            continue

        if not (20 <= registro["racha"] <= 450):
            continue

        if not (0 <= registro["aviso"] <= 200):
            continue

        registros.append(registro)

    if not registros:

        raise RuntimeError(
            "Polo aparece en SMN, pero no pude validar "
            "la estructura del último aviso."
        )

    # --------------------------------------------------------
    # Utilizamos el número de aviso más alto.
    # --------------------------------------------------------

    registro = max(
        registros,
        key=lambda r: r["aviso"]
    )

    return registro


# ============================================================
# CLASIFICACIÓN
# ============================================================

def obtener_clasificacion(texto, datos):

    bloque = aislar_polo(texto)

    # --------------------------------------------------------
    # Primero intentamos obtener la clasificación publicada
    # explícitamente por SMN.
    # --------------------------------------------------------

    patrones = [
        r"(Hurac[aá]n\s+categor[ií]a\s+[1-5])",
        r"(Tormenta\s+tropical)",
        r"(Depresi[oó]n\s+tropical)",
    ]

    for patron in patrones:

        coincidencias = list(
            re.finditer(
                patron,
                bloque,
                re.IGNORECASE
            )
        )

        if coincidencias:

            valor = limpiar(
                coincidencias[-1].group(1)
            )

            # Normalización visual.
            if re.match(
                r"hurac[aá]n",
                valor,
                re.IGNORECASE
            ):
                numero = buscar(
                    r"categor[ií]a\s+([1-5])",
                    valor
                )

                if numero:
                    return f"Huracán categoría {numero}"

            if re.match(
                r"tormenta",
                valor,
                re.IGNORECASE
            ):
                return "Tormenta tropical"

            if re.match(
                r"depresi[oó]n",
                valor,
                re.IGNORECASE
            ):
                return "Depresión tropical"

    # --------------------------------------------------------
    # Si el texto del portal no permite confirmar
    # inequívocamente la clasificación, NO inventamos.
    # --------------------------------------------------------

    return "No confirmado"


# ============================================================
# DATOS ADICIONALES
# ============================================================

def extraer_datos_adicionales(texto):

    bloque = aislar_polo(texto)

    datos = {}

    # --------------------------------------------------------
    # PRESIÓN
    #
    # Formato observado:
    # Presión mínima central [hpa] 931
    # --------------------------------------------------------

    presion = buscar(
        r"Presi[oó]n\s+m[ií]nima\s+central"
        r"\s*(?:\[\s*hpa\s*\])?"
        r"\s*(?:de|es|:)?\s*"
        r"(\d{3,4})",
        bloque
    )

    if presion:
        datos["presion"] = f"{presion} hPa"
    else:
        datos["presion"] = "No confirmado"

    # --------------------------------------------------------
    # MOVIMIENTO
    # --------------------------------------------------------

    movimiento = buscar(
        r"Desplazamiento\s+actual\s+"
        r"(.{1,100}?\d+\s*km/h)",
        bloque
    )

    datos["movimiento"] = (
        movimiento
        if movimiento
        else "No confirmado"
    )

    # --------------------------------------------------------
    # LLUVIA
    # --------------------------------------------------------

    lluvia = buscar(
        r"Pron[oó]stico\s+de\s+lluvia\s+"
        r"(.+?)"
        r"(?="
        r"\s+(?:"
        r"Pron[oó]stico\s+de\s+viento|"
        r"Viento|"
        r"Pron[oó]stico\s+de\s+oleaje|"
        r"Oleaje|"
        r"Zona\s+de|"
        r"Recomendaciones|"
        r"EL\s+SIGUIENTE\s+AVISO"
        r")"
        r")",
        bloque,
        re.IGNORECASE |
        re.DOTALL
    )

    datos["lluvia"] = (
        lluvia
        if lluvia
        else "No confirmado"
    )

    # --------------------------------------------------------
    # VIENTO COSTERO
    # --------------------------------------------------------

    viento_costero = buscar(
        r"(?:Pron[oó]stico\s+de\s+viento|"
        r"Viento(?:\s+en\s+costas?)?)"
        r"\s+"
        r"(.+?)"
        r"(?="
        r"\s+(?:"
        r"Pron[oó]stico\s+de\s+oleaje|"
        r"Oleaje|"
        r"Zona\s+de|"
        r"Recomendaciones|"
        r"EL\s+SIGUIENTE\s+AVISO"
        r")"
        r")",
        bloque,
        re.IGNORECASE |
        re.DOTALL
    )

    datos["viento_costero"] = (
        viento_costero
        if viento_costero
        else "No confirmado"
    )

    # --------------------------------------------------------
    # OLEAJE
    # --------------------------------------------------------

    oleaje = buscar(
        r"(?:Pron[oó]stico\s+de\s+oleaje|Oleaje)"
        r"\s+"
        r"(.+?)"
        r"(?="
        r"\s+(?:"
        r"Zona\s+de|"
        r"Recomendaciones|"
        r"EL\s+SIGUIENTE\s+AVISO"
        r")"
        r")",
        bloque,
        re.IGNORECASE |
        re.DOTALL
    )

    datos["oleaje"] = (
        oleaje
        if oleaje
        else "No confirmado"
    )

    # --------------------------------------------------------
    # PREVENCIÓN / VIGILANCIA
    # --------------------------------------------------------

    vigilancia = buscar(
        r"((?:Se\s+mantiene|Se\s+establece)"
        r".+?"
        r"(?:prevenci[oó]n|vigilancia)"
        r".+?)"
        r"(?="
        r"\s+(?:"
        r"Pron[oó]stico|"
        r"Recomendaciones|"
        r"EL\s+SIGUIENTE\s+AVISO"
        r")"
        r")",
        bloque,
        re.IGNORECASE |
        re.DOTALL
    )

    if not vigilancia:

        vigilancia = buscar(
            r"((?:Zona\s+de\s+prevenci[oó]n|"
            r"Zona\s+de\s+vigilancia)"
            r".+?)"
            r"(?="
            r"\s+(?:"
            r"Pron[oó]stico|"
            r"Recomendaciones|"
            r"EL\s+SIGUIENTE\s+AVISO"
            r")"
            r")",
            bloque,
            re.IGNORECASE |
            re.DOTALL
        )

    datos["vigilancia"] = (
        vigilancia
        if vigilancia
        else "No confirmado"
    )

    return datos


# ============================================================
# EXTRAER TODOS LOS DATOS
# ============================================================

def extraer_datos(texto):

    datos = extraer_registro_actual(texto)

    datos["clasificacion"] = obtener_clasificacion(
        texto,
        datos
    )

    adicionales = extraer_datos_adicionales(
        texto
    )

    datos.update(adicionales)

    return datos


# ============================================================
# GENERAR DASHBOARD HTML
# ============================================================

def generar_html(datos):

    aviso = escapar(datos["aviso"])
    fecha = escapar(datos["fecha"])
    hora = escapar(datos["hora"])
    gmt = escapar(datos["gmt"])

    lat = escapar(datos["lat"])
    lon = escapar(datos["lon"])

    referencia = escapar(
        datos["referencia"]
    )

    clasificacion = escapar(
        datos["clasificacion"]
    )

    presion = escapar(
        datos["presion"]
    )

    movimiento = escapar(
        datos["movimiento"]
    )

    lluvia = escapar(
        datos["lluvia"]
    )

    viento_costero = escapar(
        datos["viento_costero"]
    )

    oleaje = escapar(
        datos["oleaje"]
    )

    vigilancia = escapar(
        datos["vigilancia"]
    )

    viento = datos["viento"]
    racha = datos["racha"]

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
--panel2:#142b42;
--text:#eef6ff;
--muted:#a9bed2;
--line:#27445f;
--accent:#49a7ff;
--warn:#ffbd4a;
--danger:#ff6868;
--ok:#67d391
}}

*{{
box-sizing:border-box
}}

body{{
margin:0;
background:
linear-gradient(
180deg,
#07131f,
#0a1928
);
color:var(--text);
font-family:
Segoe UI,
Arial,
sans-serif
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
grid-template-columns:
repeat(6,1fr);
gap:12px;
margin:20px 0
}}

.card,
.panel{{
background:
rgba(16,34,53,.96);
border:
1px solid var(--line);
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
grid-template-columns:
1fr 1fr;
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
border:
1px solid #223d55;
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
border:
1px solid #6d5325;
color:#ffe2a3;
padding:12px;
border-radius:10px;
line-height:1.55
}}

.footer{{
margin-top:14px;
display:flex;
justify-content:
space-between;
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

@media(max-width:1000px){{

.grid{{
grid-template-columns:
repeat(3,1fr)
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
AVISO {aviso}

</div>

</div>


<section class="grid">


<div class="card">

<small>
Clasificación
</small>

<div class="big">
{clasificacion}
</div>

</div>


<div class="card">

<small>
Posición
</small>

<div class="big">
{lat}° N · {lon}° O
</div>

</div>


<div class="card">

<small>
Viento sostenido
</small>

<div class="big">
{viento} km/h
</div>

</div>


<div class="card">

<small>
Rachas
</small>

<div class="big">
{racha} km/h
</div>

</div>


<div class="card">

<small>
Movimiento
</small>

<div class="big">
{movimiento}
</div>

</div>


<div class="card">

<small>
Presión mínima
</small>

<div class="big">
{presion}
</div>

</div>


</section>


<div class="two">


<section class="panel">

<h2>
Situación actual
</h2>


<div class="effect">

<b>
Referencia
</b>

<span>
{referencia}
</span>

</div>


<div class="effect">

<b>
Coordenadas
</b>

<span>
{lat}° N · {lon}° O
</span>

</div>


<div class="alert">

<b>
Zona de prevención / vigilancia
</b>

<br>

{vigilancia}

</div>


</section>


<section class="panel">

<h2>
Efectos confirmados por SMN/CONAGUA
</h2>


<div class="effect">

<b>
Lluvias
</b>

<span>
{lluvia}
</span>

</div>


<div class="effect">

<b>
Viento en costas
</b>

<span>
{viento_costero}
</span>

</div>


<div class="effect">

<b>
Oleaje
</b>

<span>
{oleaje}
</span>

</div>


<div class="effect">

<b>
Viento máximo del ciclón
</b>

<span>

{viento} km/h sostenidos ·
rachas de {racha} km/h

</span>

</div>


</section>


</div>


<section
class="panel"
style="margin-top:14px">

<h2>
Datos del aviso oficial
</h2>


<div class="effect">

<b>
Aviso SMN/CONAGUA
</b>

<span>
No. {aviso}
</span>

</div>


<div class="effect">

<b>
Fecha y hora
</b>

<span>

{fecha} ·
{hora} horas
({gmt} horas GMT)

</span>

</div>


<div class="effect">

<b>
Fuente
</b>

<span>

Servicio Meteorológico Nacional /
Comisión Nacional del Agua.

<br>

No se utilizan datos del NHC
ni de fuentes secundarias.

</span>

</div>


</section>


<div class="footer">


<div>

<b>
Corte mostrado:
</b>

{fecha} · {hora} horas.

<br>

Fuente exclusiva de datos:
SMN / CONAGUA.

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
# ACTUALIZACIÓN SEGURA
# ============================================================

def actualizar():

    texto = obtener_smn()

    datos = extraer_datos(
        texto
    )

    print()
    print(
        "========================================"
    )
    print(
        " DATOS VALIDADOS"
    )
    print(
        "========================================"
    )

    for clave, valor in datos.items():

        print(
            f"{clave}: {valor}"
        )

    nuevo_html = generar_html(
        datos
    )

    # --------------------------------------------------------
    # SI NO CAMBIÓ NADA
    # --------------------------------------------------------

    if INDEX.exists():

        actual = INDEX.read_text(
            encoding="utf-8"
        )

        if actual == nuevo_html:

            print()
            print(
                "No hay cambios respecto "
                "al dashboard publicado."
            )

            return

    # --------------------------------------------------------
    # ESCRITURA ATÓMICA
    #
    # index.html solo se sustituye después de haber generado
    # correctamente todo el nuevo documento.
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
        "index.html actualizado con "
        f"Aviso No. {datos['aviso']}."
    )


# ============================================================
# PROGRAMA PRINCIPAL
# ============================================================

def main():

    print()
    print(
        "========================================"
    )
    print(
        " ACTUALIZADOR AUTOMÁTICO CICLÓN POLO"
    )
    print(
        " Fuente exclusiva: SMN / CONAGUA"
    )
    print(
        "========================================"
    )

    actualizar()


# ============================================================
# EJECUCIÓN
# ============================================================

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
