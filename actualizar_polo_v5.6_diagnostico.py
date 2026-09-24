import requests
import re
import sys
from io import BytesIO
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from pypdf import PdfReader

# ============================================================
# DIAGNÓSTICO CICLÓN POLO V5.6
# Fuente exclusiva: SMN / CONAGUA
# NO modifica datos_polo.json ni index.html
# ============================================================

HISTORICO_ID = "10790"
BASE = "https://smn.conagua.gob.mx"
URL_HISTORICO = f"{BASE}/tools/GUI/PortalLaravel/public/historicos/{HISTORICO_ID}"

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
        if not re.search(r"\bPolo\b", valores[0], re.I):
            continue

        m = re.fullmatch(r"\s*(\d+)\s*", valores[1])
        if not m:
            continue

        enlace_pdf = None
        for a in fila.find_all("a", href=True):
            href = a["href"]
            if "/historicos/pdf/" in href.lower() or "pdf" in href.lower():
                enlace_pdf = urljoin(URL_HISTORICO, href)
                break

        if enlace_pdf:
            candidatos.append({
                "aviso": int(m.group(1)),
                "fecha_tabla": valores[2],
                "url_pdf": enlace_pdf,
            })

    if not candidatos:
        raise RuntimeError("No pude localizar avisos de Polo en el histórico oficial.")

    ultimo = max(candidatos, key=lambda x: x["aviso"])
    print("Avisos de Polo encontrados:", len(candidatos))
    print("Último aviso localizado:", ultimo["aviso"])
    print("Fecha de tabla:", ultimo["fecha_tabla"])
    print("PDF de la misma fila:", ultimo["url_pdf"])
    return ultimo

def extraer_paginas_pdf(url):
    r = get(url)
    ct = r.headers.get("Content-Type", "").lower()
    if "pdf" not in ct and not r.content.startswith(b"%PDF"):
        raise RuntimeError("El enlace no devolvió un PDF válido.")

    reader = PdfReader(BytesIO(r.content))
    paginas = []
    for i, pagina in enumerate(reader.pages, 1):
        texto = pagina.extract_text() or ""
        paginas.append((i, texto))
    return paginas

def mostrar_contextos(texto):
    claves = [
        "Hora local", "Latitud", "Longitud", "Distancia",
        "Desplazamiento", "Vientos", "Presión", "Presion",
        "lluvia", "vigilancia", "prevención", "prevencion",
        "Comentarios", "oleaje", "rachas", "Pronóstico",
        "Pronostico"
    ]

    print("\n" + "=" * 70)
    print(" CONTEXTOS DE CAMPOS IMPORTANTES")
    print("=" * 70)

    vistos = set()
    for clave in claves:
        for m in re.finditer(re.escape(clave), texto, re.I):
            ini = max(0, m.start() - 250)
            fin = min(len(texto), m.end() + 650)
            bloque = limpiar(texto[ini:fin])
            firma = bloque[:160]
            if firma in vistos:
                continue
            vistos.add(firma)
            print(f"\n--- CONTEXTO: {clave} ---")
            print(bloque)

def main():
    print("=" * 70)
    print(" DIAGNÓSTICO CICLÓN POLO V5.6")
    print(" Fuente exclusiva: SMN / CONAGUA")
    print(" NO MODIFICA datos_polo.json")
    print("=" * 70)

    ultimo = obtener_ultimo_boletin()
    paginas = extraer_paginas_pdf(ultimo["url_pdf"])

    print("\nNúmero de páginas del PDF:", len(paginas))

    texto_total = ""
    for numero, texto in paginas:
        texto_total += "\n" + texto
        print("\n" + "=" * 70)
        print(f" PÁGINA {numero}")
        print("=" * 70)
        print(texto)

    mostrar_contextos(texto_total)

    print("\n" + "=" * 70)
    print(" FIN DEL DIAGNÓSTICO V5.6")
    print(" No se modificó ningún archivo del dashboard.")
    print("=" * 70)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERROR:", e, file=sys.stderr)
        sys.exit(1)
