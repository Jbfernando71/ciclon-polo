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
    m = re.search(patron, texto, flags)
    return limpiar(m.group(1)) if m else None


def escapar(valor):
    return html.escape(str(valor or "No confirmado"))


# ============================================================
# CONSULTAR EXCLUSIVAMENTE SMN / CONAGUA
# ============================================================

def obtener_smn():

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
            "No pude confirmar un aviso de Polo "
            "en la publicación oficial."
        )

    return texto


# ============================================================
# AISLAR INFORMACIÓN DE POLO
# ============================================================

def aislar_polo(texto):

    posiciones = [
        m.start()
        for m in re.finditer(
            r"\bPolo\b",
            texto,
            re.IGNORECASE
        )
    ]

    if not posiciones:
        raise RuntimeError(
            "No se encontró Polo."
        )

    # Tomamos una ventana amplia alrededor de la
    # última referencia a Polo.
    pos = posiciones[-1]

    inicio = max(0, pos - 5000)
    fin = min(len(texto), pos + 15000)

    bloque = texto[inicio:fin]

    if not re.search(
        r"\bPolo\b",
        bloque,
        re.IGNORECASE
    ):
        raise RuntimeError(
            "No fue posible aislar información de Polo."
        )

    return bloque


# ============================================================
# EXTRAER ÚLTIMO AVISO
# ============================================================

def extraer_datos(texto):

    # --------------------------------------------------------
    # HISTORIAL
    #
    # El portal del SMN muestra registros del tipo:
    #
    # 25 2026-09-23 12:00 horas (18:00 horas GMT)
    # 15.6 102.1
    # A 240 km ...
    # 230/280
    #
    # Buscamos todos los registros compatibles y usamos
    # el de número de aviso más alto.
    # --------------------------------------------------------

    patron = re.compile(
        r"""
        (?P<aviso>\d{1,3})
        \s+
        (?P<fecha>20\d{2}-\d{2}-\d{2})
        \s+
        (?P<hora>\d{2}:\d{2})\s+horas
        \s*
        \(
        (?P<gmt>\d{2}:\d{2})\s+horas\s+GMT
        \)
        \s+
        (?P<lat>\d{1,2}(?:\.\d+)?)
        \s+
        (?P<lon>\d{2,3}(?:\.\d+)?)
        \s+
        (?P<referencia>
            A\s+.*?
        )
        \s+
        (?P<viento>\d{2,3})
        /
        (?P<racha>\d{2,3})
        """,
        re.IGNORECASE | re.VERBOSE
    )

    registros = []

    for m in patron.finditer(texto):

        referencia = limpiar(
            m.group("referencia")
        )

        # Cortar cualquier texto que pudiera haberse
        # extendido hasta el siguiente registro.
        referencia = re.split(
            r"\s+\d{1,3}\s+20\d{2}-\d{2}-\d{2}\s+",
            referencia
        )[0]

        registros.append({
            "aviso": int(m.group("aviso")),
            "fecha": m.group("fecha"),
            "hora": m.group("hora"),
            "gmt": m.group("gmt"),
            "lat": m.group("lat"),
            "lon": m.group("lon"),
            "referencia": referencia,
            "viento": int(m.group("viento")),
            "racha": int(m.group("racha")),
        })

    if not registros:
        raise RuntimeError(
            "Polo aparece en SMN, pero no pude validar "
            "la estructura del último aviso."
        )

    # --------------------------------------------------------
    # Evitar tomar números que no sean avisos.
    # --------------------------------------------------------

    registros = [
        r for r in registros
        if 0 <= r["aviso"] <= 200
        and 0 <= float(r["lat"]) <= 35
        and 80 <= float(r["lon"]) <= 130
        and 30 <= r["viento"] <= 400
        and 30 <= r["racha"] <= 450
    ]

    if not registros:
        raise RuntimeError(
            "Los posibles registros encontrados "
            "no superaron la validación meteorológica."
        )

    datos = max(
        registros,
        key=lambda r: r["aviso"]
    )

    # --------------------------------------------------------
    # CLASIFICACIÓN
    # Se determina exclusivamente a partir del viento
    # confirmado por el SMN.
    #
    # Escala Saffir-Simpson expresada en km/h.
    # --------------------------------------------------------

    v = datos["viento"]

    if v >= 252:
        clasificacion = "Huracán categoría 5"
    elif v >= 209:
        clasificacion = "Huracán categoría 4"
    elif v >= 178:
        clasificacion = "Huracán categoría 3"
    elif v >= 154:
        clasificacion = "Huracán categoría 2"
    elif v >= 119:
        clasificacion = "Huracán categoría 1"
    elif v >= 63:
        clasificacion = "Tormenta tropical"
    else:
        clasificacion = "Depresión tropical"

    datos["clasificacion"] = clasificacion

    # --------------------------------------------------------
    # DATOS ADICIONALES
    #
    # Si el texto no permite confirmarlos inequívocamente,
    # NO se inventan.
    # --------------------------------------------------------

    bloque = aislar_polo(texto)

    presion = buscar(
        r"presi[oó]n\s+m[ií]nima(?:\s+central)?"
        r"\s*(?:de|es|:)?\s*(\d{3,4}\s*hPa)",
        bloque
    )

    movimiento = buscar(
        r"(?:desplaza|desplazamiento)"
        r".{0,40}?"
        r"(?:hacia\s+)?"
        r"([^.;]{3,80}?\d+\s*km/h)",
        bloque
    )

    datos["presion"] = presion or "No confirmado"
    datos["movimiento"] = movimiento or "No confirmado"

    # --------------------------------------------------------
    # EFECTOS
    # No intentamos completar información ausente.
    # --------------------------------------------------------

    lluvia = buscar(
        r"((?:lluvias?|precipitaciones?).{0,800}?"
        r"(?:mm).{0,600}?)"
        r"(?=(?:viento|oleaje|zona|recomend|$))",
        bloque
    )

    oleaje = buscar(
        r"((?:oleaje|mar de fondo).{0,600}?"
        r"(?:m(?:etros?)?).{0,400}?)"
        r"(?=(?:lluvia|viento|zona|recomend|$))",
        bloque
    )

    vigilancia = buscar(
        r"((?:zona\s+de\s+(?:prevenci[oó]n|vigilancia)"
        r"|prevenci[oó]n|vigilancia).{0,700}?)"
        r"(?=(?:lluvia|viento|oleaje|recomend|$))",
        bloque
    )

    datos["lluvia"] = lluvia or "No confirmado"
    datos["oleaje"] = oleaje or "No confirmado"
    datos["vigilancia"] = vigilancia or "No confirmado"

    return datos


# ============================================================
# GENERAR DASHBOARD
# ============================================================

def generar_html(d):

    clasificacion = escapar(d["clasificacion"])
    referencia = escapar(d["referencia"])
    movimiento = escapar(d["movimiento"])
    presion = escapar(d["presion"])
    lluvia = escapar(d["lluvia"])
    oleaje = escapar(d["oleaje"])
    vigilancia = escapar(d["vigilancia"])

    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="900">
<title>Dashboard SMN | Ciclón Tropical Polo</title>

<style>
:root{{--bg:#07131f;--panel:#102235;--panel2:#142b42;
--text:#eef6ff;--muted:#a9bed2;--line:#27445f;
--accent:#49a7ff;--warn:#ffbd4a;--danger:#ff6868;
--ok:#67d391}}

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

h1{{font-size:26px;margin:0}}

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
color:white;
text-decoration:none;
padding:10px 14px;
border-radius:9px;
font-weight:700
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
● SEGUIMIENTO ACTIVO · AVISO {d["aviso"]}
</div>

</div>


<section class="grid">

<div class="card">
<small>Clasificación</small>
<div class="big">{clasificacion}</div>
</div>

<div class="card">
<small>Posición</small>
<div class="big">
{escapar(d["lat"])}° N · {escapar(d["lon"])}° O
</div>
</div>

<div class="card">
<small>Viento sostenido</small>
<div class="big">{d["viento"]} km/h</div>
</div>

<div class="card">
<small>Rachas</small>
<div class="big">{d["racha"]} km/h</div>
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
<span>
{escapar(d["lat"])}° N ·
{escapar(d["lon"])}° O
</span>
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
<b>Oleaje</b>
<span>{oleaje}</span>
</div>

<div class="effect">
<b>Viento máximo del ciclón</b>
<span>
{d["viento"]} km/h sostenidos ·
rachas de {d["racha"]} km/h
</span>
</div>

</section>

</div>


<section class="panel" style="margin-top:14px">

<h2>Datos del aviso oficial</h2>

<div class="effect">
<b>Aviso SMN/CONAGUA</b>
<span>No. {d["aviso"]}</span>
</div>

<div class="effect">
<b>Fecha y hora</b>
<span>
{escapar(d["fecha"])} ·
{escapar(d["hora"])} horas
({escapar(d["gmt"])} horas GMT)
</span>
</div>

<div class="effect">
<b>Fuente</b>
<span>
Servicio Meteorológico Nacional /
Comisión Nacional del Agua.
No se utilizan datos del NHC ni de fuentes secundarias.
</span>
</div>

</section>


<div class="footer">

<div>

<b>Corte mostrado:</b>
{escapar(d["fecha"])} ·
{escapar(d["hora"])} horas.

<br>

Fuente exclusiva de datos:
SMN / CONAGUA.

<br>

Actualización automática mediante GitHub Actions.

</div>

<a class="btn"
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

    datos = extraer_datos(texto)

    print()
    print("========================================")
    print(" DATOS VALIDADOS")
    print("========================================")

    for clave, valor in datos.items():
        print(f"{clave}: {valor}")

    nuevo_html = generar_html(datos)

    # --------------------------------------------------------
    # Si no cambia nada, terminar correctamente.
    # --------------------------------------------------------

    if INDEX.exists():

        actual = INDEX.read_text(
            encoding="utf-8"
        )

        if actual == nuevo_html:

            print()
            print(
                "No hay cambios respecto al "
                "dashboard publicado."
            )

            return

    # --------------------------------------------------------
    # Escritura atómica.
    #
    # Primero escribimos un archivo temporal.
    # Solo después sustituimos index.html.
    # --------------------------------------------------------

    temporal = INDEX.with_suffix(".html.tmp")

    temporal.write_text(
        nuevo_html,
        encoding="utf-8"
    )

    temporal.replace(INDEX)

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
    print(" ACTUALIZADOR AUTOMÁTICO CICLÓN POLO")
    print(" Fuente exclusiva: SMN / CONAGUA")
    print("========================================")
    print()

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
