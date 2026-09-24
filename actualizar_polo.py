import requests
import re
import sys
import html
import json
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
DATOS = Path("datos_polo.json")

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
    # La fuente primaria del estado actual es el bloque
    # "Condiciones Actuales" de la respuesta específica de Polo.
    # El Historial se usa SOLO como apoyo para obtener la fecha;
    # una discrepancia del historial ya no invalida los datos actuales.
    # --------------------------------------------------------
    fecha = None

    # Intento 1: fila del historial con mismo aviso/hora/posición/vientos.
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
    if m_hist:
        fecha = m_hist.group("fecha")
        print("Fecha confirmada mediante Historial de Seguimiento:", fecha)
    else:
        print(
            "ADVERTENCIA: el Historial no coincide exactamente con las "
            "Condiciones Actuales; no se usará para invalidarlas."
        )

    # Intento 2: buscar una fecha asociada al mismo número de aviso.
    if not fecha:
        m_fecha_aviso = re.search(
            rf"\b{aviso}\s+(20\d{{2}}-\d{{2}}-\d{{2}})\b",
            texto,
            re.IGNORECASE
        )
        if m_fecha_aviso:
            fecha = m_fecha_aviso.group(1)
            print("Fecha obtenida de una referencia al Aviso", aviso, ":", fecha)

    # Si el portal no permite confirmar la fecha, NO la inventamos.
    if not fecha:
        fecha = "No confirmado"
        print("Fecha del aviso: No confirmado")

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
    """
    Obtiene la clasificación EXCLUSIVAMENTE de una mención que
    identifique a Polo por nombre. Esto evita confundir frases como
    "vientos de tormenta tropical" de las zonas de vigilancia con
    la clasificación actual del ciclón.
    """

    patrones_polo = [
        r"Hurac[aá]n\s+Polo\s+(?:de\s+)?categor[ií]a\s+([1-5])",
        r"Polo\s+(?:como\s+)?hurac[aá]n\s+(?:de\s+)?categor[ií]a\s+([1-5])",
        r"Tormenta\s+tropical\s+Polo\b",
        r"Polo\s+(?:como\s+)?tormenta\s+tropical\b",
        r"Depresi[oó]n\s+tropical\s+Polo\b",
        r"Polo\s+(?:como\s+)?depresi[oó]n\s+tropical\b",
    ]

    # Se busca en todo el aviso específico de Polo, pero SOLO en
    # expresiones donde el nombre Polo está unido a la clasificación.
    for i, patron in enumerate(patrones_polo):
        m = re.search(patron, texto, re.IGNORECASE)
        if not m:
            continue
        if i in (0, 1):
            return f"Huracán categoría {m.group(1)}"
        if i in (2, 3):
            return "Tormenta tropical"
        return "Depresión tropical"

    # Segundo respaldo: la síntesis oficial suele expresar
    # "huracán Polo de categoría N" dentro de una oración.
    m = re.search(
        r"hurac[aá]n\s+Polo.{0,40}?categor[ií]a\s+([1-5])",
        texto, re.IGNORECASE
    )
    if m:
        return f"Huracán categoría {m.group(1)}"

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
# JSON PÚBLICO PARA EL DASHBOARD
# ============================================================

def construir_salida(datos, mapa, pronostico):
    return {
        "ciclon": "Polo",
        "fuente": "SMN / CONAGUA",
        "url_oficial": URL,
        "aviso": datos.get("aviso"),
        "fecha": datos.get("fecha", "No confirmado"),
        "hora": datos.get("hora", "No confirmado"),
        "gmt": datos.get("gmt", "No confirmado"),
        "clasificacion": datos.get("clasificacion", "No confirmado"),
        "lat": datos.get("lat", "No confirmado"),
        "lon": datos.get("lon", "No confirmado"),
        "referencia": datos.get("referencia", "No confirmado"),
        "viento": datos.get("viento", "No confirmado"),
        "racha": datos.get("racha", "No confirmado"),
        "movimiento": datos.get("movimiento", "No confirmado"),
        "presion": datos.get("presion", "No confirmado"),
        "lluvia": datos.get("lluvia", "No confirmado"),
        "vigilancia": datos.get("vigilancia", "No confirmado"),
        "viento_costero": datos.get("viento_costero", "No confirmado"),
        "oleaje": datos.get("oleaje", "No confirmado"),
        "mapa": mapa or "No confirmado",
        "pronostico": pronostico,
    }


def obtener_corte_json_actual():
    if not DATOS.exists():
        return None
    try:
        actual = json.loads(DATOS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    fecha = actual.get("fecha")
    hora = actual.get("hora")
    if not fecha or fecha == "No confirmado" or not hora:
        return None
    try:
        return datetime.strptime(f"{fecha} {hora}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None


# ============================================================
# ACTUALIZAR SOLO DATOS (NO TOCA index.html)
# ============================================================

def actualizar():
    texto, soup = obtener_smn()
    datos = extraer_datos(texto)
    validar_datos(datos)
    mapa = extraer_mapa_trayectoria(soup)
    pronostico = extraer_pronostico(soup)

    print()
    print("========================================")
    print(" DATOS VALIDADOS")
    print("========================================")
    for clave, valor in datos.items():
        print(f"{clave}: {valor}")
    print("mapa:", mapa or "No confirmado")
    print("filas pronóstico:", len(pronostico))

    # Evitar retroceso solamente cuando la fecha nueva está confirmada.
    fecha_nueva = datos.get("fecha")
    nuevo_corte = None
    if fecha_nueva and fecha_nueva != "No confirmado":
        try:
            nuevo_corte = datetime.strptime(
                f"{fecha_nueva} {datos['hora']}", "%Y-%m-%d %H:%M"
            )
        except ValueError:
            nuevo_corte = None

    corte_actual = obtener_corte_json_actual()
    if nuevo_corte is not None and corte_actual is not None and nuevo_corte < corte_actual:
        raise RuntimeError("El aviso recuperado es anterior al publicado.")

    salida = construir_salida(datos, mapa, pronostico)
    nuevo_json = json.dumps(salida, ensure_ascii=False, indent=2) + "\n"

    if DATOS.exists() and DATOS.read_text(encoding="utf-8") == nuevo_json:
        print("No existen cambios respecto a datos_polo.json publicado.")
        return

    temporal = Path("datos_polo.json.tmp")
    temporal.write_text(nuevo_json, encoding="utf-8")
    temporal.replace(DATOS)
    print(f"datos_polo.json actualizado con Aviso No. {datos['aviso']}.")
    print("index.html permanece intacto: el diseño institucional no se sobrescribe.")


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("========================================")
    print(" ACTUALIZADOR CICLÓN POLO V5.1")
    print(" Fuente exclusiva: SMN / CONAGUA")
    print(f" URL específica de Polo: {URL}")
    print(" Datos JSON + mapa + trayectoria automática")
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
            "Por seguridad datos_polo.json permanece "
            "sin modificaciones.",
            file=sys.stderr
        )

        sys.exit(1)