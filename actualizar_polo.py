import requests
import re
import sys
import json
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup

# ============================================================
# ACTUALIZADOR CICLÓN POLO V5.7
# Fuente exclusiva: SMN / CONAGUA
# Fuente primaria: WebAviso oficial del Pacífico
# ============================================================

BASE = "https://smn.conagua.gob.mx"
URL_AVISO = f"{BASE}/tools/GUI/PortalLaravel/public/WebAviso"
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

def buscar(patrones, texto, flags=re.I):
    if isinstance(patrones, str):
        patrones = [patrones]
    for patron in patrones:
        m = re.search(patron, texto, flags)
        if m:
            return limpiar(m.group(1))
    return None

def cargar_actual():
    if not DATOS.exists():
        return {}
    try:
        return json.loads(DATOS.read_text(encoding="utf-8"))
    except Exception:
        return {}

def obtener_webaviso():
    print("Consultando WebAviso oficial SMN:", URL_AVISO)
    r = get(URL_AVISO)
    soup = BeautifulSoup(r.text, "html.parser")
    texto = limpiar(soup.get_text(" ", strip=True))

    if not re.search(r"\bPolo\b", texto, re.I):
        raise RuntimeError(
            "WebAviso respondió, pero no pude confirmar que el aviso mostrado corresponda a Polo."
        )

    return soup, texto

def extraer_pronostico(soup):
    filas = []

    for tabla in soup.find_all("table"):
        encabezado = limpiar(tabla.get_text(" ", strip=True))
        if not (
            re.search(r"D[ií]a/Hora", encabezado, re.I)
            and re.search(r"Latitud", encabezado, re.I)
            and re.search(r"Vientos", encabezado, re.I)
            and re.search(r"Categor[ií]a", encabezado, re.I)
        ):
            continue

        for tr in tabla.find_all("tr"):
            celdas = [
                limpiar(c.get_text(" ", strip=True))
                for c in tr.find_all(["td", "th"])
            ]
            if len(celdas) < 6:
                continue
            if re.search(r"D[ií]a/Hora", celdas[0], re.I):
                continue
            if not re.match(r"\d{1,2}/\d{1,2}", celdas[0]):
                continue

            filas.append({
                "dia_hora": celdas[0],
                "lat": celdas[1],
                "lon": celdas[2],
                "viento": celdas[3],
                "categoria": celdas[4],
                "ubicacion": celdas[5],
            })

        if filas:
            break

    return filas

def extraer_mapa(soup):
    candidatos = []
    for img in soup.find_all("img", src=True):
        src = urljoin(URL_AVISO, img["src"])
        alt = limpiar(img.get("alt", ""))
        contexto = limpiar(img.parent.get_text(" ", strip=True)) if img.parent else ""
        puntaje = 0
        if "ImgTray" in src:
            puntaje += 10
        if re.search(r"trayectoria|pron[oó]stico", alt, re.I):
            puntaje += 5
        if re.search(r"trayectoria|pron[oó]stico", contexto, re.I):
            puntaje += 2
        if puntaje:
            candidatos.append((puntaje, src))

    if not candidatos:
        return "No confirmado"

    candidatos.sort(reverse=True)
    return candidatos[0][1]

def extraer(soup, texto):
    d = {
        "ciclon": "Polo",
        "fuente": "SMN / CONAGUA",
        "url_oficial": URL_AVISO,
    }

    aviso = buscar([
        r"Oc[eé]ano\s+Pac[ií]fico\s*-\s*No\.\s*Aviso\s*:?\s*(\d+)",
        r"No\.\s*Aviso\s*:?\s*(\d+)"
    ], texto)
    d["aviso"] = int(aviso) if aviso else "No confirmado"

    clas = None
    m = re.search(r"HURAC[AÁ]N\s+POLO\s+DE\s+CATEGOR[IÍ]A\s+([1-5])", texto, re.I)
    if not m:
        m = re.search(r"hurac[aá]n\s+Polo\s+de\s+categor[ií]a\s+([1-5])", texto, re.I)
    if m:
        clas = f"Huracán categoría {m.group(1)}"
    elif re.search(r"tormenta\s+tropical\s+Polo", texto, re.I):
        clas = "Tormenta tropical"
    elif re.search(r"depresi[oó]n\s+tropical\s+Polo", texto, re.I):
        clas = "Depresión tropical"
    d["clasificacion"] = clas or "No confirmado"

    mh = re.search(
        r"Hora\s+local\s*\(hora\s+(?:GMT|UTC)\)\s*"
        r"(\d{1,2}:\d{2})\s*horas?\s*"
        r"\((\d{1,2}:\d{2})\s*horas?\s*(?:GMT|UTC)",
        texto, re.I
    )
    if mh:
        d["hora"] = mh.group(1)
        d["gmt"] = mh.group(2)
    else:
        d["hora"] = d["gmt"] = "No confirmado"

    mp = re.search(
        r"Ubicaci[oó]n\s+del\s+centro\s+Latitud\s+Norte\s*:?\s*"
        r"(\d{1,2}(?:\.\d+)?)\s+Longitud\s+Oeste\s*:?\s*"
        r"(\d{2,3}(?:\.\d+)?)",
        texto, re.I
    )
    if mp:
        d["lat"], d["lon"] = mp.group(1), mp.group(2)
    else:
        d["lat"] = d["lon"] = "No confirmado"

    d["referencia"] = buscar(
        r"Distancia\s+al\s+lugar\s+m[aá]s\s+cercano\s+(.+?)"
        r"(?=\s+Desplazamiento\s+actual)",
        texto, re.I | re.S
    ) or "No confirmado"

    d["movimiento"] = buscar(
        r"Desplazamiento\s+actual\s+(.+?)"
        r"(?=\s+Vientos?\s+m[aá]ximos?)",
        texto, re.I | re.S
    ) or "No confirmado"

    mv = re.search(
        r"Vientos?\s+m[aá]ximos?\s*\[?km/h\]?\s*"
        r"Sostenidos\s*:?\s*(\d{2,3})\s+"
        r"Rachas\s*:?\s*(\d{2,3})",
        texto, re.I
    )
    if mv:
        d["viento"] = int(mv.group(1))
        d["racha"] = int(mv.group(2))
    else:
        d["viento"] = d["racha"] = "No confirmado"

    presion = buscar(
        r"Presi[oó]n\s+m[ií]nima\s+central\s*\[?hpa\]?\s*(\d{3,4})",
        texto
    )
    d["presion"] = f"{presion} hPa" if presion else "No confirmado"

    d["lluvia"] = buscar(
        r"Pron[oó]stico\s+de\s+lluvia\s+(.+?)"
        r"(?=\s+Zona\s+de\s+vigilancia)",
        texto, re.I | re.S
    ) or "No confirmado"

    d["vigilancia"] = buscar(
        r"Zona\s+de\s+vigilancia\s+(.+?)"
        r"(?=\s+Comentarios\s+adicionales)",
        texto, re.I | re.S
    ) or "No confirmado"

    comentarios = buscar(
        r"Comentarios\s+adicionales\s+(.+?)"
        r"(?=\s+Recomendaciones)",
        texto, re.I | re.S
    ) or ""

    # En el dashboard conviene conservar el texto costero completo porque
    # puede contener varios estados y varios rangos de viento.
    d["viento_costero"] = comentarios if comentarios else "No confirmado"

    oleajes = re.findall(
        r"oleaje\s+de\s+\d+(?:\.\d+)?\s+a\s+\d+(?:\.\d+)?\s+metros?"
        r"(?:\s+de\s+altura)?[^.;]*",
        comentarios, re.I
    )
    d["oleaje"] = "; ".join(limpiar(x) for x in oleajes) if oleajes else "No confirmado"

    # Fecha/hora: se toma de la fila del aviso actual en Historial de Seguimiento.
    if isinstance(d["aviso"], int):
        patron_hist = (
            rf"(?:^|\s){d['aviso']}\s+"
            rf"(20\d{{2}}-\d{{2}}-\d{{2}})\s+"
            rf"(\d{{1,2}}:\d{{2}})\s+horas?"
        )
        mhist = re.search(patron_hist, texto, re.I)
        if mhist:
            d["fecha"] = mhist.group(1)
            # La hora de condiciones actuales es preferente; si falta, usa historial.
            if d["hora"] == "No confirmado":
                d["hora"] = mhist.group(2)
        else:
            d["fecha"] = "No confirmado"
    else:
        d["fecha"] = "No confirmado"

    d["hora_publicacion"] = d["hora"]
    d["mapa"] = extraer_mapa(soup)
    d["pronostico"] = extraer_pronostico(soup)

    return d

def validar(d):
    esenciales = [
        "aviso", "fecha", "hora", "lat", "lon",
        "viento", "racha", "clasificacion"
    ]
    faltan = [
        c for c in esenciales
        if d.get(c) in (None, "", "No confirmado")
    ]
    if faltan:
        raise RuntimeError(
            "Faltan campos esenciales del aviso oficial: " + ", ".join(faltan)
        )

    if int(d["racha"]) < int(d["viento"]):
        raise RuntimeError("Validación fallida: racha menor que viento sostenido.")

    if not d["pronostico"]:
        raise RuntimeError(
            "No pude confirmar la tabla de pronóstico del aviso actual."
        )

    if d["mapa"] == "No confirmado":
        print("ADVERTENCIA: no se confirmó imagen de trayectoria; no se reutilizará una anterior.")

def main():
    print("=" * 64)
    print(" ACTUALIZADOR CICLÓN POLO V5.7")
    print(" Fuente exclusiva: SMN / CONAGUA")
    print(" Fuente primaria: WebAviso")
    print("=" * 64)

    soup, texto = obtener_webaviso()
    nuevo = extraer(soup, texto)
    validar(nuevo)

    actual = cargar_actual()
    try:
        aviso_anterior = int(actual.get("aviso", 0))
    except (TypeError, ValueError):
        aviso_anterior = 0

    if int(nuevo["aviso"]) < aviso_anterior:
        raise RuntimeError(
            f"WebAviso devolvió Aviso {nuevo['aviso']}, anterior al "
            f"Aviso {aviso_anterior} ya publicado."
        )

    contenido = json.dumps(nuevo, ensure_ascii=False, indent=2) + "\n"
    actual_texto = DATOS.read_text(encoding="utf-8") if DATOS.exists() else ""

    if contenido == actual_texto:
        print("El dashboard ya contiene exactamente el último aviso.")
        return

    temporal = Path("datos_polo.json.tmp")
    temporal.write_text(contenido, encoding="utf-8")
    temporal.replace(DATOS)

    print("-" * 64)
    print("ACTUALIZACIÓN CORRECTA")
    print("Aviso:", nuevo["aviso"])
    print("Fecha/Hora:", nuevo["fecha"], nuevo["hora"], "GMT:", nuevo["gmt"])
    print("Clasificación:", nuevo["clasificacion"])
    print("Posición:", nuevo["lat"], "N /", nuevo["lon"], "O")
    print("Referencia:", nuevo["referencia"])
    print("Movimiento:", nuevo["movimiento"])
    print("Viento/Rachas:", nuevo["viento"], "/", nuevo["racha"], "km/h")
    print("Presión:", nuevo["presion"])
    print("Pronóstico:", len(nuevo["pronostico"]), "filas")
    print("Mapa:", nuevo["mapa"])
    print("-" * 64)
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
