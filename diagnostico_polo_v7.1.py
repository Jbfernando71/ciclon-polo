import asyncio, json, re
from pathlib import Path
from playwright.async_api import async_playwright

PORTAL="https://smn.conagua.gob.mx/es/pronosticos/avisos/aviso-de-ciclon-tropical-en-el-oceano-pacifico"
OUT=Path("diagnostico_polo")
OUT.mkdir(exist_ok=True)

def safe(s,n=5000):
    return (s or "")[:n]

async def main():
    log=[]
    net=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        page=await browser.new_page(viewport={"width":1600,"height":1000})

        def req(r):
            if any(x in r.url.lower() for x in ["aviso","ciclon","portal","search","histor"]):
                net.append({"tipo":"request","method":r.method,"url":r.url,"post_data":safe(r.post_data,2000)})
        async def resp(r):
            if any(x in r.url.lower() for x in ["aviso","ciclon","portal","search","histor"]):
                item={"tipo":"response","status":r.status,"url":r.url,"content_type":r.headers.get("content-type","")}
                try:
                    if "json" in item["content_type"] or "text" in item["content_type"] or "html" in item["content_type"]:
                        item["body"]=safe(await r.text(),10000)
                except: pass
                net.append(item)
        page.on("request",req)
        page.on("response",resp)

        await page.goto(PORTAL,wait_until="domcontentloaded",timeout=90000)
        await page.wait_for_timeout(10000)

        log.append("URL PRINCIPAL: "+page.url)
        log.append("FRAMES INICIALES:")
        for i,f in enumerate(page.frames):
            log.append(f"  [{i}] {f.url}")
            try:
                txt=safe(await f.locator("body").inner_text(),12000)
                (OUT/f"frame_{i}_antes.txt").write_text(txt,encoding="utf-8")
            except Exception as e:
                log.append(f"    ERROR TEXTO: {e}")

        # Buscar cualquier elemento visible cuyo texto contenga Polo.
        candidates=[]
        for fi,f in enumerate(page.frames):
            try:
                loc=f.get_by_text(re.compile(r"\bPolo\b",re.I))
                count=await loc.count()
                for j in range(min(count,20)):
                    el=loc.nth(j)
                    try:
                        if await el.is_visible():
                            info=await el.evaluate("""e=>({
                              tag:e.tagName, text:e.innerText||e.textContent||'',
                              href:e.href||'', id:e.id||'', cls:e.className||'',
                              outer:e.outerHTML
                            })""")
                            candidates.append({"frame":fi,"index":j,**info})
                    except: pass
            except: pass

        (OUT/"candidatos_polo.json").write_text(json.dumps(candidates,ensure_ascii=False,indent=2),encoding="utf-8")
        log.append(f"CANDIDATOS VISIBLES POLO: {len(candidates)}")

        clicked=False
        for c in candidates:
            fi=c["frame"]; j=c["index"]
            f=page.frames[fi]
            try:
                el=f.get_by_text(re.compile(r"\bPolo\b",re.I)).nth(j)
                log.append("INTENTO CLICK: "+safe(c.get("outer",""),1500))
                await el.click(timeout=8000)
                clicked=True
                await page.wait_for_timeout(8000)
                break
            except Exception as e:
                log.append("CLICK FALLÓ: "+str(e))

        log.append("CLICK REALIZADO: "+str(clicked))
        log.append("FRAMES DESPUÉS:")
        for i,f in enumerate(page.frames):
            log.append(f"  [{i}] {f.url}")
            try:
                txt=safe(await f.locator("body").inner_text(),20000)
                (OUT/f"frame_{i}_despues.txt").write_text(txt,encoding="utf-8")
                html=safe(await f.content(),50000)
                (OUT/f"frame_{i}_despues.html").write_text(html,encoding="utf-8")
            except Exception as e:
                log.append(f"    ERROR: {e}")

        await page.screenshot(path=str(OUT/"despues_click.png"),full_page=True)
        await browser.close()

    (OUT/"red.json").write_text(json.dumps(net,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT/"resumen.txt").write_text("\n".join(log),encoding="utf-8")
    print("\n".join(log))
    print("\nDIAGNÓSTICO TERMINADO. No se modificó datos_polo.json ni index.html.")

asyncio.run(main())
