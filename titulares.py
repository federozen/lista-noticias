"""
titulares.py — Vista rápida de TODOS los titulares, sin Streamlit y sin fotos.

Pensado para chequear de un vistazo qué hay dando vueltas, sin levantar
la app completa. Dos salidas, ambas al mismo tiempo:

  1) Terminal: lista de texto plano, agrupada por medio.
  2) titulares.html: un archivo liviano que se abre solo en el navegador
     (doble clic), sin servidor, sin fotos — para escanear rápido en el
     celu o la compu.

Orden (modo "por medio", el default): primero "Olé — Últimas noticias"
(el listado completo de /ultimas-noticias, todo lo publicado), después
"Olé" a secas (lo que scrapea de la home), y luego el resto de medios.

Opcional: si están cargadas las variables de entorno TELEGRAM_BOT_TOKEN
y TELEGRAM_CHAT_ID (las mismas que usa vigia.py), también te manda la
lista completa por Telegram con --telegram.

Uso:
    python titulares.py                  # scrapea todo, imprime y genera el HTML
    python titulares.py --filtro boca    # solo titulares que contengan "boca"
    python titulares.py --ambito nac     # solo fuentes nacionales (o --ambito int)
    python titulares.py --az             # orden alfabético en vez de por medio
    python titulares.py --telegram       # además, manda la lista por Telegram
    python titulares.py --no-html        # no generar el archivo HTML
"""
import argparse
import html as _html
import sys
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from monitor_core import TODAS_FUENTES, FUENTES_NAC, FUENTES_INT, fetch_fuente, fetch_ultimas_ole

# Sección especial: el listado completo de /ultimas-noticias de Olé (todo lo
# publicado, incluso lo que nunca pisa la portada). Va primero en la lista;
# la portada de Olé (que ya scrapea `fetch_fuente`) queda como segunda sección,
# porque "ole" es la primera fuente de FUENTES_NAC.
OLE_ULTIMAS_FUENTE = {"id": "ole_ultimas", "nombre": "Olé — Últimas noticias", "color": "#00a846"}


def scrapear_todo(fuentes: list) -> dict:
    """Trae los titulares de cada fuente en paralelo. Sin imágenes: solo texto."""
    resultados = {}
    total = len(fuentes)
    print(f"Scrapeando {total} fuentes...")
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(fetch_fuente, f): f for f in fuentes}
        hechos = 0
        for fut in as_completed(futs):
            f = futs[fut]
            hechos += 1
            try:
                r = fut.result()
                noticias = r.get("noticias") or []
                error = r.get("error")
            except Exception as e:
                noticias, error = [], str(e)
            resultados[f["id"]] = noticias
            estado = f"{len(noticias):3d} notas" if not error else f"ERROR: {str(error)[:50]}"
            print(f"  [{hechos:2d}/{total}] {f['id']:<14} {estado}")
    return resultados


def imprimir_terminal(fuentes: list, resultados: dict, filtro: str, az: bool):
    print("\n" + "=" * 70)
    total = 0

    if az:
        planas = []
        for f in fuentes:
            for n in resultados.get(f["id"], []):
                if filtro and filtro not in n["titulo"].lower():
                    continue
                planas.append((n, f))
        planas.sort(key=lambda t: t[0]["titulo"].lower())
        for n, f in planas:
            print(f"  [{f['nombre']}] {n['titulo']}")
        total = len(planas)
    else:
        for f in fuentes:
            noticias = [
                n for n in resultados.get(f["id"], [])
                if not filtro or filtro in n["titulo"].lower()
            ]
            if not noticias:
                continue
            print(f"\n── {f['nombre']} ({len(noticias)}) " + "─" * max(0, 50 - len(f["nombre"])))
            for n in noticias:
                print(f"  • {n['titulo']}")
            total += len(noticias)

    print("\n" + "=" * 70)
    print(f"Total: {total} titulares" + (f' con "{filtro}"' if filtro else ""))


def generar_html(fuentes: list, resultados: dict, filtro: str, az: bool, path: Path) -> int:
    filas = []
    total = 0

    def fila(n, color=None):
        titulo = _html.escape(n["titulo"])
        dot = f'<span style="color:{color};margin-right:6px">●</span>' if color else ""
        if n.get("url"):
            return (f'<div class="item">{dot}<a href="{_html.escape(n["url"])}" '
                     f'target="_blank" rel="noopener">{titulo}</a></div>')
        return f'<div class="item">{dot}{titulo}</div>'

    if az:
        planas = []
        for f in fuentes:
            for n in resultados.get(f["id"], []):
                if filtro and filtro not in n["titulo"].lower():
                    continue
                planas.append((n, f))
        planas.sort(key=lambda t: t[0]["titulo"].lower())
        for n, f in planas:
            filas.append(fila(n, f["color"]))
        total = len(planas)
    else:
        for f in fuentes:
            noticias = [
                n for n in resultados.get(f["id"], [])
                if not filtro or filtro in n["titulo"].lower()
            ]
            if not noticias:
                continue
            filas.append(
                f'<div class="medio" style="color:{f["color"]}">{_html.escape(f["nombre"])} '
                f'<span class="cant">({len(noticias)})</span></div>'
            )
            for n in noticias:
                filas.append(fila(n))
            total += len(noticias)

    ahora = datetime.now().strftime("%d/%m %H:%M")
    doc = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Todos los titulares — {ahora}</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; max-width: 720px;
         margin: 0 auto; padding: 16px; color: #14171a; background:#fff; }}
  h1 {{ font-size: 18px; margin-bottom: 2px; }}
  .meta {{ color:#657786; font-size:13px; margin-bottom:14px; }}
  .medio {{ font-weight:800; font-size:12px; letter-spacing:.5px; text-transform:uppercase;
           margin-top:16px; }}
  .cant {{ color:#657786; font-weight:400; }}
  .item {{ padding:3px 0; border-bottom:1px solid #eee; font-size:15px; line-height:1.4; }}
  .item a {{ color:#14171a; text-decoration:none; }}
  .item a:hover {{ text-decoration:underline; }}
  input {{ width:100%; padding:8px; font-size:15px; margin-bottom:10px;
          border:1px solid #ccc; border-radius:6px; box-sizing:border-box; }}
</style></head>
<body>
  <h1>📋 Todos los titulares</h1>
  <div class="meta">{total} titulares · generado {ahora}</div>
  <input id="q" placeholder="Filtrar en esta lista..." oninput="filtrar()">
  <div id="lista">
    {''.join(filas)}
  </div>
  <script>
    function filtrar() {{
      const q = document.getElementById('q').value.toLowerCase();
      document.querySelectorAll('#lista .item').forEach(el => {{
        el.style.display = el.textContent.toLowerCase().includes(q) ? '' : 'none';
      }});
    }}
  </script>
</body></html>"""
    path.write_text(doc, encoding="utf-8")
    return total


def enviar_telegram(fuentes: list, resultados: dict, filtro: str):
    import os
    import requests as rq

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        print("\n(Telegram no configurado: faltan TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")
        return

    lineas = []
    for f in fuentes:
        noticias = [
            n for n in resultados.get(f["id"], [])
            if not filtro or filtro in n["titulo"].lower()
        ]
        if not noticias:
            continue
        lineas.append(f"\n<b>{f['nombre']}</b> ({len(noticias)})")
        lineas.extend(f"• {n['titulo'][:140]}" for n in noticias)

    texto = "📋 Todos los titulares\n" + "\n".join(lineas)
    # Telegram corta mensajes largos; los partimos en bloques de ~3500 chars
    bloques = [texto[i:i + 3500] for i in range(0, len(texto), 3500)] or [texto]
    ok_total = True
    for bloque in bloques:
        r = rq.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": bloque, "disable_web_page_preview": True},
            timeout=15,
        )
        ok_total = ok_total and r.status_code == 200
    print(f"\nTelegram: {'enviado' if ok_total else 'falló, revisá el token/chat_id'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--filtro", default="", help="Filtrar titulares por palabra")
    ap.add_argument("--ambito", choices=["todas", "nac", "int"], default="todas")
    ap.add_argument("--az", action="store_true", help="Orden alfabético en vez de por medio")
    ap.add_argument("--telegram", action="store_true", help="Enviar la lista por Telegram")
    ap.add_argument("--no-html", action="store_true", help="No generar titulares.html")
    ap.add_argument("--out", default="titulares.html", help="Ruta del archivo HTML de salida")
    ap.add_argument("--abrir", action="store_true", help="Abrir el HTML en el navegador al terminar")
    args = ap.parse_args()

    fuentes = (FUENTES_NAC if args.ambito == "nac"
               else FUENTES_INT if args.ambito == "int"
               else TODAS_FUENTES)
    filtro = args.filtro.strip().lower()

    resultados = scrapear_todo(fuentes)

    incluir_ultimas = args.ambito in ("todas", "nac")
    if incluir_ultimas:
        print("Trayendo Olé — últimas noticias (listado completo, no solo portada)...")
        resultados["ole_ultimas"] = fetch_ultimas_ole()
        print(f"  [ole_ultimas  ] {len(resultados['ole_ultimas']):3d} notas")
        fuentes_render = [OLE_ULTIMAS_FUENTE] + fuentes
    else:
        fuentes_render = fuentes

    imprimir_terminal(fuentes_render, resultados, filtro, args.az)

    if not args.no_html:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        total = generar_html(fuentes_render, resultados, filtro, args.az, path)
        print(f"\nHTML generado: {path}  ({total} titulares)")
        if args.abrir:
            webbrowser.open(f"file://{path.resolve()}")

    if args.telegram:
        enviar_telegram(fuentes_render, resultados, filtro)


if __name__ == "__main__":
    sys.exit(main() or 0)
