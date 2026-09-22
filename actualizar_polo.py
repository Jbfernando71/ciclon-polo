import requests
import re
import sys
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
# CONSULTAR SMN
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

    except requests.exceptions.Timeout:

        raise RuntimeError(
            "El portal del SMN excedió el tiempo máximo de respuesta."
        )

    except requests.exceptions.ConnectionError as e:

        raise RuntimeError(
            f"No fue posible establecer conexión con SMN/CONAGUA: {e}"
        )

    except requests.exceptions.RequestException as e:

        raise RuntimeError(
            f"Error durante la consulta al SMN/CONAGUA: {e}"
        )

    print("Código HTTP:", respuesta.status_code)
    print(
        "Tamaño de respuesta:",
        len(respuesta.content),
        "bytes"
    )

    respuesta.raise_for_status()

    # --------------------------------------------------------
    # Convertir HTML a texto
    # --------------------------------------------------------

    soup = BeautifulSoup(
        respuesta.text,
        "html.parser"
    )

    # Eliminar elementos que no contienen información
    # meteorológica visible.
    for elemento in soup(
        ["script", "style", "noscript"]
    ):
        elemento.decompose()

    texto = soup.get_text(
        " ",
        strip=True
    )

    texto = re.sub(
        r"\s+",
        " ",
        texto
    ).strip()

    if not texto:

        raise RuntimeError(
            "SMN respondió, pero no se obtuvo texto "
            "de la publicación."
        )

    # --------------------------------------------------------
    # Confirmar que Polo aparece realmente en la respuesta.
    # No exigimos 'Huracán Polo' porque su clasificación
    # meteorológica puede cambiar.
    # --------------------------------------------------------

    if not re.search(
        r"\bPolo\b",
        texto,
        re.IGNORECASE
    ):

        print()
        print(
            "===== TEXTO RECIBIDO SIN POLO ====="
        )
        print(texto[:5000])
        print(
            "===== FIN TEXTO RECIBIDO ====="
        )

        raise RuntimeError(
            "SMN respondió, pero no pude confirmar "
            "un aviso de Polo en el contenido recibido."
        )

    return texto


# ============================================================
# MOSTRAR CONTEXTO DE POLO
# ============================================================

def mostrar_contexto_polo(texto):

    coincidencias = list(
        re.finditer(
            r"\bPolo\b",
            texto,
            re.IGNORECASE
        )
    )

    print()
    print(
        "Número de apariciones de 'Polo':",
        len(coincidencias)
    )

    print()

    for numero, coincidencia in enumerate(
        coincidencias[:10],
        start=1
    ):

        inicio = max(
            0,
            coincidencia.start() - 1000
        )

        fin = min(
            len(texto),
            coincidencia.end() + 4000
        )

        fragmento = texto[
            inicio:fin
        ]

        print(
            f"===== CONTEXTO POLO {numero} ====="
        )

        print(fragmento)

        print(
            f"===== FIN CONTEXTO POLO {numero} ====="
        )

        print()


# ============================================================
# PROGRAMA PRINCIPAL
# ============================================================

def main():

    print()
    print(
        "============================================"
    )
    print(
        " DIAGNÓSTICO DEL ACTUALIZADOR CICLÓN POLO"
    )
    print(
        " Fuente exclusiva: SMN / CONAGUA"
    )
    print(
        "============================================"
    )
    print()

    if not INDEX.exists():

        raise RuntimeError(
            "No existe index.html en la raíz "
            "del repositorio."
        )

    texto = obtener_smn()

    print()
    print(
        "Polo fue localizado en el contenido "
        "recibido del SMN."
    )

    # --------------------------------------------------------
    # Mostrar fragmentos alrededor de la palabra Polo.
    # Esto facilitará construir posteriormente los patrones
    # de extracción correctos.
    # --------------------------------------------------------

    mostrar_contexto_polo(texto)

    # --------------------------------------------------------
    # Mostrar una porción amplia del documento.
    # --------------------------------------------------------

    print()
    print(
        "============================================"
    )
    print(
        " INICIO TEXTO RECIBIDO DEL SMN"
    )
    print(
        "============================================"
    )
    print()

    print(texto[:15000])

    print()
    print(
        "============================================"
    )
    print(
        " FIN TEXTO RECIBIDO DEL SMN"
    )
    print(
        "============================================"
    )

    # --------------------------------------------------------
    # Terminamos intencionalmente con error.
    #
    # De esta forma:
    # 1. GitHub conserva el log.
    # 2. No se ejecuta el paso de guardar cambios.
    # 3. index.html NO se modifica.
    # --------------------------------------------------------

    raise RuntimeError(
        "DIAGNÓSTICO TERMINADO. "
        "index.html no fue modificado."
    )


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
