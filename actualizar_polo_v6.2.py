    lat, lon = m.groups()

    m = re.search(
        r"Sostenidos:\s*(\d{2,3})\s*\|?\s*Rachas:\s*(\d{2,3})",
        viento_b,
        re.I,
    )
    if not m:
        raise RuntimeError("No se pudieron interpretar viento/rachas.")
    viento, racha = map(int, m.groups())

    m = re.search(r"(\d{3,4})", presion_b)
    if not m:
        raise RuntimeError("No se pudo interpretar presión.")
    presion = m.group(1) + " hPa"

    clasificacion = classify(t)
    fecha = extract_date(soup, aviso)
    if not fecha:
        raise RuntimeError("No se encontró fecha del aviso vigente en WebAviso.")

    pronostico = extract_forecast(soup)
    if not pronostico:
        raise RuntimeError("No se pudo extraer el pronóstico vigente desde WebAviso.")

    mapa = extract_map(soup, web)
    if not mapa:
        raise RuntimeError("No se pudo extraer la trayectoria vigente desde WebAviso.")

    oleaje_partes = re.findall(
        r"oleaje\s+de\s+\d+(?:\.\d+)?\s+a\s+\d+(?:\.\d+)?\s+metros?"
        r"(?:\s+de\s+altura)?\s+en\s+costas\s+de\s+[^.;]+",
        comentarios,
        re.I,
    )
    oleaje = "; ".join(clean(x) for x in oleaje_partes) or comentarios

    data = {
        "ciclon": "Polo",
        "fuente": "SMN / CONAGUA",
        "url_oficial": PORTAL,
        "url_datos": web,
        "aviso": aviso,
        "fecha": fecha,
        "hora_publicacion": hora,
        "hora": hora,
        "gmt": gmt,
        "lat": lat,
        "lon": lon,
        "referencia": referencia,
        "movimiento": movimiento,
        "viento": viento,
        "racha": racha,
        "presion": presion,
        "clasificacion": clasificacion,
        "lluvia": lluvia,
        "vigilancia": vigilancia,
        "viento_costero": comentarios,
        "oleaje": oleaje,
        "mapa": mapa,
        "pronostico": pronostico,
    }

    if racha < viento:
        raise RuntimeError("Validación fallida: racha menor que viento sostenido.")

    if DATOS.exists():
        try:
            old = json.loads(DATOS.read_text(encoding="utf-8"))
            old_no = int(old.get("aviso", 0))
            if aviso < old_no:
                raise RuntimeError(
                    f"WebAviso devolvió aviso {aviso}; el tablero ya tiene {old_no}."
                )
        except json.JSONDecodeError:
            pass

    tmp = Path("datos_polo.json.tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(DATOS)

    print()
    print("ACTUALIZACIÓN CORRECTA DESDE WEBAVISO")
    print("Aviso:", aviso)
    print("Fecha/Hora:", fecha, hora, "GMT:", gmt)
    print("Clasificación:", clasificacion)
    print("Posición:", lat, "N /", lon, "O")
    print("Referencia:", referencia)
    print("Movimiento:", movimiento)
    print("Viento/Rachas:", viento, "/", racha, "km/h")
    print("Presión:", presion)
    print("Vigilancia:", vigilancia)
    print("Pronóstico:", len(pronostico), "filas")
    print("Mapa:", mapa)
    print("datos_polo.json actualizado; index.html intacto.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERROR:", e, file=sys.stderr)
        print("No se modificó el dashboard con datos parciales.", file=sys.stderr)
        sys.exit(1)
