import requests
import re
import sys
from bs4 import BeautifulSoup
from pathlib import Path
from datetime import datetime

URL = "https://smn.conagua.gob.mx/tools/GUI/PortalLaravel/public/WebAviso"
INDEX = Path("index.html")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PoloSMNMonitor/1.0)"
}


def obtener_smn():
    r = requests.get(URL, headers=HEADERS, timeout=30)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")

    # Convertimos la página oficial en texto normalizado.
    texto = soup.get_text(" ", strip=True)
    texto = re.sub(r"\s+", " ", texto)

    # Protección fundamental:
    # solo continuar si el aviso activo realmente corresponde a Polo.
    if not re.search(r"Hurac[aá]n\s+Polo", texto, re.I):
        raise RuntimeError(
            "SMN respondió, pero no pude confirmar un aviso activo del Huracán Polo."
        )

    return texto


def buscar(patron, texto, nombre):
    m = re.search(patron, texto, re.I)

    if not m:
        raise RuntimeError(
            f"No pude confirmar el campo '{nombre}' en la publicación oficial."
        )

    return m.group(1).strip()


def extraer_datos(texto):

    aviso = buscar(
        r"Polo\s+(\d+)\s+",
        texto,
        "número de aviso"
    )

    categoria = buscar(
        r"POLO\s+CATEGOR[IÍ]A\s+(\d)",
        texto,
        "categoría"
    )

    hora = buscar(
        r"Hora local\s+\(hora GMT\)\s+"
        r"([0-9]{1,2}:[0-9]{2}\s+horas\s+\([^)]+GMT[^)]*\))",
        texto,
        "hora"
    )

    lat = buscar(
        r"Latitud Norte:\s*([0-9.]+)",
        texto,
        "latitud"
    )

    lon = buscar(
        r"Longitud Oeste:\s*([0-9.]+)",
        texto,
        "longitud"
    )

    distancia = buscar(
        r"Distancia al lugar más cercano\s+(.+?)\s+"
        r"Desplazamiento actual",
        texto,
        "distancia"
    )

    desplazamiento = buscar(
        r"Desplazamiento actual\s+(.+?)\s+"
        r"Vientos máximos",
        texto,
        "desplazamiento"
    )

    sostenidos = buscar(
        r"Sostenidos:\s*(\d+)",
        texto,
        "viento sostenido"
    )

    rachas = buscar(
        r"Rachas:\s*(\d+)",
        texto,
        "rachas"
    )

    presion = buscar(
        r"Presión mínima central\s*\[hpa\]\s*(\d+)",
        texto,
        "presión"
    )

    lluvia = buscar(
        r"Pronóstico de lluvia\s+(.+?)\s+Zona de vigilancia",
        texto,
        "pronóstico de lluvia"
    )

    vigilancia = buscar(
        r"Zona de vigilancia\s+(.+?)\s+Comentarios adicionales",
        texto,
        "zona de vigilancia"
    )

    comentarios = buscar(
        r"Comentarios adicionales\s+(.+?)\s+Recomendaciones",
        texto,
        "viento y oleaje"
    )

    return {
        "aviso": aviso,
        "categoria": categoria,
        "hora": hora,
        "lat": lat,
        "lon": lon,
        "distancia": distancia,
        "desplazamiento": desplazamiento,
        "sostenidos": sostenidos,
        "rachas": rachas,
        "presion": presion,
        "lluvia": lluvia,
        "vigilancia": vigilancia,
        "comentarios": comentarios,
    }


def escapar(s):
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
    )


def generar_html(d):

    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">

<meta http-equiv="refresh" content="900">

<title>Dashboard SMN | Huracán Polo</title>

<style>

:root {{
 --bg:#07131f;
 --panel:#102235;
 --line:#27445f;
 --text:#eef6ff;
 --muted:#a9bed2;
 --danger:#ff6868;
 --warn:#ffbd4a;
}}

* {{ box-sizing:border-box; }}

body {{
 margin:0;
 background:linear-gradient(180deg,#07131f,#0a1928);
 color:var(--text);
 font-family:Segoe UI,Arial,sans-serif;
}}

.wrap {{
 max-width:1450px;
 margin:auto;
 padding:22px;
}}

.top {{
 display:flex;
 justify-content:space-between;
 align-items:center;
 gap:16px;
 flex-wrap:wrap;
}}

h1 {{
 margin:0;
 font-size:28px;
}}

.sub {{
 color:var(--muted);
 margin-top:6px;
}}

.badge {{
 background:#5a1520;
 border:1px solid #a73b49;
 padding:9px 13px;
 border-radius:999px;
 font-weight:800;
}}

.grid {{
 display:grid;
 grid-template-columns:repeat(6,1fr);
 gap:12px;
 margin:20px 0;
}}

.card,.panel {{
 background:rgba(16,34,53,.97);
 border:1px solid var(--line);
 border-radius:14px;
 padding:16px;
}}

.card small {{
 color:var(--muted);
 text-transform:uppercase;
 font-weight:700;
}}

.big {{
 font-size:22px;
 font-weight:800;
 margin-top:8px;
}}

.two {{
 display:grid;
 grid-template-columns:1.2fr .8fr;
 gap:14px;
}}

.panel h2 {{
 font-size:17px;
 margin:0 0 14px;
}}

.video {{
 position:relative;
 width:100%;
 padding-bottom:56.25%;
 height:0;
 overflow:hidden;
 border-radius:12px;
 background:#000;
}}

.video iframe {{
 position:absolute;
 inset:0;
 width:100%;
 height:100%;
 border:0;
}}

.alert {{
 margin-top:12px;
 background:#3b2d16;
 border:1px solid #6d5325;
 color:#ffe2a3;
 padding:12px;
 border-radius:10px;
}}

.info {{
 margin-top:12px;
 padding:14px;
 background:#0d1d2c;
 border:1px solid #223d55;
 border-radius:10px;
 line-height:1.5;
}}

.footer {{
 margin-top:14px;
 display:flex;
 justify-content:space-between;
 gap:12px;
 flex-wrap:wrap;
 color:var(--muted);
 font-size:12px;
}}

.btn {{
 display:inline-block;
 background:#1c75bc;
 color:#fff;
 text-decoration:none;
 padding:10px 14px;
 border-radius:9px;
 font-weight:700;
}}

@media(max-width:1000px) {{
 .grid {{grid-template-columns:repeat(3,1fr)}}
 .two {{grid-template-columns:1fr}}
}}

@media(max-width:600px) {{
 .grid {{grid-template-columns:1fr 1fr}}
 .wrap {{padding:12px}}
}}

</style>
</head>

<body>

<main class="wrap">

<div class="top">

<div>
<h1>Seguimiento del Huracán Polo</h1>
<div class="sub">
Servicio Meteorológico Nacional · CONAGUA · Océano Pacífico
</div>
</div>

<div class="badge">
● HURACÁN CATEGORÍA {d["categoria"]}
</div>

</div>


<section class="grid">

<div class="card">
<small>Aviso SMN</small>
<div class="big">No. {d["aviso"]}</div>
</div>

<div class="card">
<small>Posición</small>
<div class="big">{d["lat"]}° N · {d["lon"]}° O</div>
</div>

<div class="card">
<small>Referencia</small>
<div class="big">{escapar(d["distancia"])}</div>
</div>

<div class="card">
<small>Viento sostenido</small>
<div class="big">{d["sostenidos"]} km/h</div>
</div>

<div class="card">
<small>Rachas</small>
<div class="big">{d["rachas"]} km/h</div>
</div>

<div class="card">
<small>Movimiento</small>
<div class="big">{escapar(d["desplazamiento"])}</div>
<div class="sub">Presión: {d["presion"]} hPa</div>
</div>

</section>


<div class="two">

<section class="panel">

<h2>Situación y trayectoria de referencia</h2>

<div class="video">

<iframe
 src="https://www.youtube.com/embed/nCwtd38bKDM"
 title="Seguimiento del ciclón tropical Polo"
 allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
 allowfullscreen>
</iframe>

</div>

<div class="sub">
Video complementario. Los datos meteorológicos mostrados
en este dashboard proceden exclusivamente del SMN/CONAGUA.
</div>

<div class="alert">
<b>Zona de alertamiento / vigilancia:</b><br>
{escapar(d["vigilancia"])}
</div>

</section>


<section class="panel">

<h2>Condiciones oficiales</h2>

<div class="info">

<b>Pronóstico de lluvia</b><br>
{escapar(d["lluvia"])}

</div>

<div class="info">

<b>Viento y oleaje</b><br>
{escapar(d["comentarios"])}

</div>

</section>

</div>


<section class="panel" style="margin-top:14px">

<h2>Fuente y control de actualización</h2>

<div class="info">

<b>Aviso SMN:</b> No. {d["aviso"]}<br><br>

<b>Hora oficial:</b>
{escapar(d["hora"])}<br><br>

<b>Posición:</b>
{d["lat"]}° N / {d["lon"]}° O<br><br>

<b>Fuente:</b>
Servicio Meteorológico Nacional (SMN) /
Comisión Nacional del Agua (CONAGUA).

</div>

</section>


<div class="footer">

<div>

<b>Último aviso incorporado:</b>
No. {d["aviso"]} · {escapar(d["hora"])}
<br>

<b>Actualización automática:</b>
GitHub Actions consulta exclusivamente el portal oficial del SMN.

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


def main():

    if not INDEX.exists():
        raise RuntimeError("No existe index.html en el repositorio.")

    print("Consultando SMN/CONAGUA...")

    texto = obtener_smn()
    datos = extraer_datos(texto)

    print("Polo confirmado.")
    print("Aviso:", datos["aviso"])
    print("Categoría:", datos["categoria"])
    print("Posición:", datos["lat"], datos["lon"])
    print("Viento:", datos["sostenidos"], "/", datos["rachas"])
    print("Movimiento:", datos["desplazamiento"])

    nuevo_html = generar_html(datos)

    html_actual = INDEX.read_text(encoding="utf-8")

    # Evita commits si ya está exactamente actualizado.
    if nuevo_html == html_actual:
        print("Dashboard ya actualizado. No hay cambios.")
        return

    INDEX.write_text(nuevo_html, encoding="utf-8")

    print("index.html actualizado correctamente.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:

        # MUY IMPORTANTE:
        # ante cualquier error NO modificamos el dashboard.
        print("ERROR:", e, file=sys.stderr)
        print(
            "Por seguridad index.html permanece sin modificaciones.",
            file=sys.stderr
        )

        sys.exit(1)
