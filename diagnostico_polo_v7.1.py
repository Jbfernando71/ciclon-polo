import asyncio
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright


PORTAL = (
    "https://smn.conagua.gob.mx/es/pronosticos/avisos/"
    "aviso-de-ciclon-tropical-en-el-oceano-pacifico"
)

WEBAVISO = (
    "https://smn.conagua.gob.mx/tools/GUI/"
    "PortalLaravel/public/WebAviso"
)

DATOS = Path("datos_polo.json")


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def between(text, start, end):
    m = re.search(
        start + r"\s*(.+?)(?=\s*" + end + r")",
        text,
        re.I | re.S,
    )
    return clean(m.group(1)) if m else None


def classify(text):
    if re.search(
        r"\bPolo\b.{0,220}\bbaja\s+presi[oó]n\s+remanente\b|"
        r"\bbaja\s+presi[oó]n\s+remanente\b.{0,220}\bPolo\b",
        text,
        re.I | re.S,
    ):
        return "Baja presión remanente"

    m = re.search(
        r"hurac[aá]n\s+Polo.{0,80}?categor[ií]a\s+([1-5])",
        text,
        re.I | re.S,
    )

    if m:
        return f"Huracán categoría {m.group(1)}"

    if re.search(
        r"\btormenta\s+tropical\s+Polo\b|"
        r"\bPolo\b.{0,120}\btormenta\s+tropical\b",
        text,
        re.I | re.S,
    ):
        return "Tormenta tropical"

    if re.search(
        r"\bdepresi[oó]n\s+tropical\s+Polo\b|"
        r"\bPolo\b.{0,120}\bdepresi[oó]n\s+tropical\b",
        text,
        re.I | re.S,
    ):
        return "Depresión tropical"

    return "Polo"


def first(pattern, text, group=1):
    m = re.search(pattern, text, re.I | re.S)
    return clean(m.group(group)) if m else None


def parse_forecast(soup):
    out = []

    for table in soup.find_all("table"):
        txt = clean(table.get_text(" ", strip=True))

        if not (
            re.search(r"D[ií]a/Hora", txt, re.I)
            and re.search(r"Categor[ií]a", txt, re.I)
        ):
            continue

        for tr in table.find_all("tr"):
            c = [
                clean(x.get_text(" ", strip=True))
                for x in tr.find_all(["td", "th"])
            ]

            if len(c) >= 6 and re.fullmatch(
                r"\d{1,2}/\d{1,2}h?", c[0]
            ):
                out.append(
                    {
                        "dia_hora": c[0],
                        "lat": c[1],
                        "lon": c[2],
                        "viento": c[3],
                        "categoria": c[4],
                        "ubicacion": c[5],
                    }
                )

        if out:
            break

    return out


def parse_notice(html, data_url, expected_no):
    soup = BeautifulSoup(html, "html.parser")
    text = clean(soup.get_text(" ", strip=True))

    if not re.search(r"\bPolo\b", text, re.I):
        raise RuntimeError(
            "El aviso seleccionado no contiene Polo."
        )

    no = first(
        r"Oc[eé]ano\s+Pac[ií]fico\s*-\s*"
        r"No\.\s*Aviso:\s*(\d+)",
        text,
    )

    if not no:
        raise RuntimeError(
            "No se encontró el número del aviso de Polo."
        )

    no = int(no)

    if no != expected_no:
        raise RuntimeError(
            f"El botón indicó Polo {expected_no}, "
            f"pero el contenido abierto es aviso {no}."
        )

    fecha = first(
        r"Emisi[oó]n:\s*(20\d{2}-\d{2}-\d{2})",
        text,
    )

    hora = first(
        r"Emisi[oó]n:\s*20\d{2}-\d{2}-\d{2}\s+"
        r"(\d{1,2}:\d{2})",
        text,
    )

    gmt = first(
        r"Emisi[oó]n:.*?"
        r"\((\d{1,2}:\d{2})\s+horas?\s+GMT",
        text,
    )

    lat = first(
        r"Latitud\s+Norte:\s*(\d+(?:\.\d+)?)",
        text,
    )

    lon = first(
        r"Longitud\s+Oeste:\s*(\d+(?:\.\d+)?)",
        text,
    )

    viento = first(
        r"Sostenidos:\s*(\d{1,3})",
        text,
    )

    racha = first(
        r"Rachas:\s*(\d{1,3})",
        text,
    )

    presion = first(
        r"Presi[oó]n\s+m[ií]nima\s+central"
        r"\s*\[hpa\]\s*\|?\s*(\d{3,4})",
        text,
    )

    referencia = between(
        text,
        r"Distancia\s+al\s+lugar\s+m[aá]s\s+cercano\s*\|?",
        r"Desplazamiento\s+actual",
    )

    movimiento = between(
        text,
        r"Desplazamiento\s+actual\s*\|?",
        r"Vientos\s+m[aá]ximos",
    )

    lluvia = between(
        text,
        r"Pron[oó]stico\s+de\s+lluvia\s*\|?",
        r"Zona\s+de\s+vigilancia|"
        r"Comentarios\s+adicionales",
    )

    vigilancia = between(
        text,
        r"Zona\s+de\s+vigilancia\s*\|?",
        r"Comentarios\s+adicionales",
    )

    comentarios = between(
        text,
        r"Comentarios\s+adicionales\s*\|?",
        r"Recomendaciones",
    )

    sintesis = first(
        r"S[ií]ntesis\s*(.+?)"
        r"(?=\s*Imagen\s+|"
        r"\s*Situaci[oó]n\s+|"
        r"\s*Pron[oó]stico\s+|"
        r"\s*Historial\s+)",
        text,
    )

    clas = classify(text)

    mapa = ""

    for img in soup.find_all("img", src=True):
        src = urljoin(data_url, img["src"])
        alt = clean(img.get("alt", ""))

        if (
            "ImgTray" in src
            or re.search(r"trayectoria|Polo", alt, re.I)
        ):
            mapa = src
            break

    pron = parse_forecast(soup)

    # No inventar datos ausentes en el aviso final.
    def num(v):
        return int(v) if v is not None else None

    return {
        "ciclon": "Polo",
        "fuente": "SMN / CONAGUA",
        "url_oficial": PORTAL,
        "url_datos": data_url,
        "aviso": no,
        "fecha": fecha,
        "hora": hora,
        "gmt": gmt,
        "clasificacion": clas,
        "lat": lat,
        "lon": lon,
        "referencia": referencia or sintesis,
        "movimiento": movimiento,
        "viento": num(viento),
        "racha": num(racha),
        "presion": (
            presion + " hPa"
            if presion
            else None
        ),
        "vigilancia": vigilancia,
        "lluvia": lluvia,
        "viento_costero": comentarios,
        "oleaje": comentarios,
        "mapa": mapa,
        "pronostico": pron,
    }


async def main():
    print("=" * 72)
    print(" ACTUALIZADOR CICLÓN POLO V7.2")
    print(
        " SELECCIÓN DINÁMICA MEDIANTE "
        "data-aviso-id DEL PORTAL OFICIAL SMN"
    )
    print("=" * 72)

    old = {}

    if DATOS.exists():
        try:
            old = json.loads(
                DATOS.read_text(encoding="utf-8")
            )
        except Exception:
            pass

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True
        )

        page = await browser.new_page(
            viewport={
                "width": 1600,
                "height": 1000,
            }
        )

        await page.goto(
            PORTAL,
            wait_until="domcontentloaded",
            timeout=90000,
        )

        await page.wait_for_timeout(8000)

        polo = None

        for frame in page.frames:
            loc = frame.locator(
                "a.aviso-btn",
                has_text=re.compile(
                    r"\bPolo\b",
                    re.I,
                ),
            )

            if await loc.count():
                for i in range(
                    await loc.count()
                ):
                    el = loc.nth(i)

                    if await el.is_visible():
                        txt = clean(
                            await el.inner_text()
                        )

                        aviso_id = (
                            await el.get_attribute(
                                "data-aviso-id"
                            )
                        )

                        m = re.search(
                            r"\bPolo\s+(\d+)\b",
                            txt,
                            re.I,
                        )

                        if aviso_id and m:
                            polo = (
                                frame,
                                el,
                                int(m.group(1)),
                                aviso_id,
                            )
                            break

            if polo:
                break

        if not polo:
            await browser.close()

            old_no = int(
                old.get("aviso", 0) or 0
            )

            if (
                old.get("ciclon") == "Polo"
                and old_no > 0
            ):
                print(
                    "Polo ya no aparece entre "
                    "avisos activos. "
                    f"Se conserva el aviso {old_no}."
                )
                return

            raise RuntimeError(
                "No se encontró el botón activo "
                "de Polo y no existe un aviso "
                "previo válido."
            )

        frame, el, expected_no, aviso_id = polo

        print(
            f"Botón oficial encontrado: "
            f"Polo {expected_no}"
        )

        print(
            f"data-aviso-id: {aviso_id}"
        )

        await el.click(
            timeout=10000
        )

        await page.wait_for_timeout(
            6000
        )

        target = None

        for f in page.frames:
            if (
                "WebAviso" in f.url
                and f"searchText={aviso_id}"
                in f.url
            ):
                target = f
                break

        if not target:
            await browser.close()

            raise RuntimeError(
                "El SMN no abrió "
                f"WebAviso?searchText={aviso_id} "
                "después del clic."
            )

        print(
            "URL oficial seleccionada:",
            target.url,
        )

        html = await target.content()

        data = parse_notice(
            html,
            target.url,
            expected_no,
        )

        await browser.close()

    old_no = int(
        old.get("aviso", 0) or 0
    )

    if data["aviso"] < old_no:
        raise RuntimeError(
            "Retroceso bloqueado: "
            f"Polo {data['aviso']} "
            f"< tablero {old_no}."
        )

    if (
        data["viento"] is not None
        and data["racha"] is not None
        and data["racha"]
        < data["viento"]
    ):
        raise RuntimeError(
            "Validación fallida: "
            "racha menor que viento sostenido."
        )

    tmp = Path(
        "datos_polo.json.tmp"
    )

    tmp.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    tmp.replace(DATOS)

    print(
        "ACTUALIZACIÓN CORRECTA"
    )

    print(
        "Aviso:",
        data["aviso"],
    )

    print(
        "Clasificación:",
        data["clasificacion"],
    )

    print(
        "Fecha/Hora:",
        data["fecha"],
        data["hora"],
        "GMT:",
        data["gmt"],
    )

    print(
        "ID SMN:",
        aviso_id,
    )

    print(
        "index.html no fue modificado."
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())

    except Exception as e:
        print(
            "ERROR:",
            e,
            file=sys.stderr,
        )

        print(
            "No se modificó datos_polo.json "
            "con información parcial.",
            file=sys.stderr,
        )

        sys.exit(1)
