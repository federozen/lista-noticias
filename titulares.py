"""
titulares.py — Vista rápida de TODOS los titulares, sin Streamlit, CON fotos.

Pensado para chequear de un vistazo qué hay dando vueltas, sin levantar
la app completa. Dos salidas, ambas al mismo tiempo:

  1) Terminal: lista de texto plano, agrupada por medio.
  2) titulares.html: un archivo liviano que se abre solo en el navegador
     (doble clic), sin servidor — pensado para escanear rápido en el
     celu o la compu. Trae dos formas de navegar la misma lista:
       • Por medio    → agrupado por fuente (como antes).
       • Por horario  → agrupado por antigüedad de la publicación,
                        de lo más reciente a lo más viejo.

Sobre las fotos: cada noticia ya trae su propia imagen si el scraper de
esa fuente la pudo extraer (monitor_core.py). Para las que no, se hace un
fetch de la og:image de la nota (igual que hace el Streamlit), en
paralelo y con caché, antes de armar el HTML.

Sobre los horarios: solo los feeds RSS (la mayoría de los medios
internacionales y varios nacionales vía Google News) traen fecha de
publicación confiable. Los sitios que se scrapean directo (Olé, ESPN, AS,
genérico) no siempre la exponen, así que esas notas caen en el bloque
"Sin horario" dentro de la vista por horario, pero se siguen viendo bien
en la vista por medio.

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
    python titulares.py --sin-fotos      # no buscar fotos adicionales (más rápido)
    python titulares.py --telegram       # además, manda la lista por Telegram
    python titulares.py --no-html        # no generar el archivo HTML
"""
import argparse
import html as _html
import sys
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from monitor_core import (
    TODAS_FUENTES, FUENTES_NAC, FUENTES_INT, fetch_fuente, fetch_ultimas_ole,
    fetch_og_images_batch, _IMAGE_CACHE,
)

# Sección especial: el listado completo de /ultimas-noticias de Olé (todo lo
# publicado, incluso lo que nunca pisa la portada). Va primero en la lista;
# la portada de Olé (que ya scrapea `fetch_fuente`) queda como segunda sección,
# porque "ole" es la primera fuente de FUENTES_NAC.
OLE_ULTIMAS_FUENTE = {"id": "ole_ultimas", "nombre": "Olé — Últimas noticias", "color": "#00a846"}


def scrapear_todo(fuentes: list) -> dict:
    """Trae los titulares de cada fuente en paralelo."""
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


def completar_fotos(fuentes: list, resultados: dict, max_fotos: int = 150) -> None:
    """Busca la og:image de las notas que no trajeron imagen del scraping.
    Corre en paralelo y usa el mismo _IMAGE_CACHE que el Streamlit.

    Tiene un tope (`max_fotos`) para que el tiempo de ejecución quede acotado
    sin importar cuánto crezca el corpus total: prioriza las primeras fuentes
    en el orden de `fuentes` (Olé y nacionales primero), y si sobran notas sin
    imagen quedan directamente con el ⚽ de placeholder en esta corrida."""
    sin_imagen = [
        n for f in fuentes
        for n in resultados.get(f["id"], [])
        if not n.get("imagen") and n.get("url")
    ]
    if not sin_imagen:
        return
    if len(sin_imagen) > max_fotos:
        print(f"({len(sin_imagen)} notas sin imagen, se buscan las primeras {max_fotos} "
              f"para no alargar la corrida — usá --max-fotos para cambiar el tope)")
        sin_imagen = sin_imagen[:max_fotos]
    print(f"Buscando fotos para {len(sin_imagen)} notas sin imagen propia...")
    fetch_og_images_batch(sin_imagen)


def _imagen_de(n: dict) -> str:
    """Imagen propia del scraping, o la que se haya podido cachear después."""
    return n.get("imagen") or _IMAGE_CACHE.get(n.get("url", ""), "") or ""


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


# ─── Bucketing por horario ───────────────────────────────────────────────────
BUCKETS = [
    ("ultima_hora", "🔴 Última hora", 1),
    ("1_3h", "🟠 Hace 1–3 horas", 3),
    ("3_6h", "🟡 Hace 3–6 horas", 6),
    ("6_12h", "🟢 Hace 6–12 horas", 12),
    ("mas_12h", "🔵 Hace más de 12 horas", None),
]


def _parsear_hora(hora_iso: str):
    if not hora_iso:
        return None
    try:
        dt = datetime.fromisoformat(hora_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def armar_items_planos(fuentes: list, resultados: dict, filtro: str) -> list:
    """Lista plana de (noticia, fuente) respetando el orden de `fuentes`."""
    items = []
    for f in fuentes:
        for n in resultados.get(f["id"], []):
            if filtro and filtro not in n["titulo"].lower():
                continue
            items.append((n, f))
    return items


def agrupar_por_horario(items: list) -> list:
    """Devuelve [(etiqueta_bucket, [(noticia, fuente, dt_o_None), ...]), ...]
    ordenado de más reciente a más viejo; el bucket sin hora va al final."""
    ahora = datetime.now(timezone.utc)
    con_hora, sin_hora = [], []
    for n, f in items:
        dt = _parsear_hora(n.get("hora", ""))
        if dt is None:
            sin_hora.append((n, f, None))
        else:
            con_hora.append((n, f, dt))
    con_hora.sort(key=lambda t: t[2], reverse=True)

    grupos = {clave: [] for clave, _, _ in BUCKETS}
    for n, f, dt in con_hora:
        horas = (ahora - dt).total_seconds() / 3600
        asignado = False
        for clave, _, limite in BUCKETS:
            if limite is None or horas <= limite:
                grupos[clave].append((n, f, dt))
                asignado = True
                break
        if not asignado:
            grupos["mas_12h"].append((n, f, dt))

    salida = [(etq, grupos[clave]) for clave, etq, _ in BUCKETS if grupos[clave]]
    if sin_hora:
        salida.append(("⚪ Sin horario disponible", sin_hora))
    return salida


# ─── Render de un ítem (con miniatura) ───────────────────────────────────────
def _fila_html(n: dict, f: dict, mostrar_medio: bool, hora_dt=None) -> str:
    titulo = _html.escape(n["titulo"])
    img = _imagen_de(n)
    img_html = (
        f'<img src="{_html.escape(img)}" loading="lazy" '
        f'onerror="this.style.display=\'none\';this.parentElement.classList.add(\'noimg\')">'
    ) if img else ""
    thumb_cls = "thumb" if img else "thumb noimg"

    medio_html = ""
    if mostrar_medio:
        medio_html = f'<span class="src" style="color:{f["color"]}">{_html.escape(f["nombre"])}</span> · '

    hora_html = ""
    if hora_dt is not None:
        hora_html = f'<span class="hora">{hora_dt.astimezone().strftime("%d/%m %H:%M")}</span>'

    if n.get("url"):
        link = (f'<a href="{_html.escape(n["url"])}" target="_blank" '
                f'rel="noopener">{titulo}</a>')
    else:
        link = titulo

    return (
        f'<div class="item">'
        f'<div class="{thumb_cls}">{img_html}</div>'
        f'<div class="txt">{medio_html}{hora_html}<br>{link}</div>'
        f'</div>'
    )


def generar_html(fuentes: list, resultados: dict, filtro: str, az: bool, path: Path) -> int:
    items = armar_items_planos(fuentes, resultados, filtro)
    total = len(items)

    # ── Vista "por medio" ──
    sidebar_medios = []
    if az:
        planas = sorted(items, key=lambda t: t[0]["titulo"].lower())
        filas_medio = [_fila_html(n, f, mostrar_medio=True) for n, f in planas]
    else:
        filas_medio = []
        por_fuente = {}
        for n, f in items:
            por_fuente.setdefault(f["id"], []).append((n, f))
        for f in fuentes:
            grupo = por_fuente.get(f["id"], [])
            if not grupo:
                continue
            filas_medio.append(
                f'<div class="medio" id="medio-{f["id"]}" style="color:{f["color"]}">{_html.escape(f["nombre"])} '
                f'<span class="cant">({len(grupo)})</span></div>'
            )
            sidebar_medios.append((f["id"], f["nombre"], len(grupo), f["color"]))
            for n, _f in grupo:
                filas_medio.append(_fila_html(n, f, mostrar_medio=False))

    # ── Vista "por horario" ──
    grupos_horario = agrupar_por_horario(items)
    filas_horario = []
    sidebar_horario = []
    for i, (etiqueta, grupo) in enumerate(grupos_horario):
        anchor_id = f"horario-{i}"
        filas_horario.append(
            f'<div class="medio horario-tag" id="{anchor_id}">{etiqueta} <span class="cant">({len(grupo)})</span></div>'
        )
        sidebar_horario.append((anchor_id, etiqueta, len(grupo)))
        for n, f, dt in grupo:
            filas_horario.append(_fila_html(n, f, mostrar_medio=True, hora_dt=dt))

    # ── Menú lateral: links de salto para cada vista ──
    if sidebar_medios:
        nav_medio_html = "".join(
            f'<a href="#medio-{fid}" class="nav-link" onclick="cerrarMenu()">'
            f'<span style="color:{color}">{_html.escape(nombre)}</span>'
            f'<span class="nav-cant">{cant}</span></a>'
            for fid, nombre, cant, color in sidebar_medios
        )
    else:
        nav_medio_html = '<p class="nav-empty">No disponible con orden alfabético (--az).</p>'

    nav_horario_html = "".join(
        f'<a href="#{aid}" class="nav-link" onclick="cerrarMenu()">{_html.escape(etq)}'
        f'<span class="nav-cant">{cant}</span></a>'
        for aid, etq, cant in sidebar_horario
    )

    ahora = datetime.now().strftime("%d/%m %H:%M")
    doc = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Todos los titulares — {ahora}</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; max-width: 760px;
         margin: 0 auto; padding: 16px; color: #14171a; background:#fff; }}
  h1 {{ font-size: 18px; margin-bottom: 2px; }}
  .meta {{ color:#657786; font-size:13px; margin-bottom:14px; }}
  .tabs {{ display:flex; gap:8px; margin-bottom:10px; }}
  .tab-btn {{ flex:1; padding:8px; font-size:14px; font-weight:600; border:1px solid #ccc;
             background:#f5f6f7; border-radius:6px; cursor:pointer; color:#14171a; }}
  .tab-btn.active {{ background:#14171a; color:#fff; border-color:#14171a; }}
  .medio {{ font-weight:800; font-size:12px; letter-spacing:.5px; text-transform:uppercase;
           margin-top:18px; margin-bottom:8px; }}
  .horario-tag {{ font-size:13px; }}
  .cant {{ color:#657786; font-weight:400; }}
  .item {{ display:flex; align-items:stretch; background:#fff; border:1px solid #e6e8eb;
          border-radius:12px; overflow:hidden; margin-bottom:10px; }}
  .thumb {{ flex-shrink:0; width:110px; height:110px; background:#eef0f5;
           overflow:hidden; display:flex; align-items:center; justify-content:center; }}
  .thumb img {{ width:100%; height:100%; object-fit:cover; display:block; }}
  .thumb.noimg::after {{ content:"⚽"; font-size:28px; }}
  .txt {{ font-size:15px; line-height:1.35; padding:10px 12px; display:flex;
         flex-direction:column; justify-content:center; }}
  .txt a {{ color:#14171a; text-decoration:none; }}
  .txt a:hover {{ text-decoration:underline; }}
  .src {{ font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.4px; }}
  .hora {{ font-size:11px; color:#657786; }}
  @media (max-width: 420px) {{
    .thumb {{ width:84px; height:84px; }}
    .txt {{ font-size:14px; }}
  }}
  input {{ width:100%; padding:8px; font-size:15px; margin-bottom:10px;
          border:1px solid #ccc; border-radius:6px; box-sizing:border-box; }}
  .view {{ display:none; }}
  .view.active {{ display:block; }}
  .medio {{ scroll-margin-top:12px; }}

  .layout {{ display:flex; gap:20px; align-items:flex-start; }}
  .main {{ flex:1; min-width:0; }}
  .sidebar {{ width:170px; flex-shrink:0; position:sticky; top:16px;
             max-height:calc(100vh - 32px); overflow-y:auto; }}
  .nav-list {{ display:none; flex-direction:column; gap:1px; }}
  .nav-list.active {{ display:flex; }}
  .nav-link {{ display:flex; justify-content:space-between; align-items:center; gap:6px;
              font-size:13px; padding:6px 8px; border-radius:6px; text-decoration:none; }}
  .nav-link:hover {{ background:#f5f6f7; }}
  .nav-cant {{ color:#657786; font-size:11px; }}
  .nav-empty {{ font-size:12px; color:#657786; padding:6px 8px; }}
  .hamburger {{ display:none; }}
  .backdrop {{ display:none; }}
  .backdrop.show {{ display:block; position:fixed; inset:0; background:rgba(0,0,0,.35); z-index:19; }}

  @media (max-width: 680px) {{
    .layout {{ display:block; }}
    .hamburger {{ display:inline-block; margin-bottom:10px; padding:8px 12px; font-size:13px;
                 font-weight:600; border:1px solid #ccc; border-radius:6px; background:#f5f6f7;
                 cursor:pointer; }}
    .sidebar {{ position:fixed; top:0; left:0; height:100%; width:230px; background:#fff;
               box-shadow:2px 0 12px rgba(0,0,0,.15); transform:translateX(-100%);
               transition:transform .2s ease; z-index:20; padding:16px 12px; box-sizing:border-box; }}
    .sidebar.open {{ transform:translateX(0); }}
  }}
</style></head>
<body>
  <h1>📋 Todos los titulares</h1>
  <div class="meta">{total} titulares · generado {ahora}</div>
  <button class="hamburger" onclick="toggleMenu()">☰ Medios</button>
  <div class="backdrop" onclick="toggleMenu()"></div>
  <div class="layout">
    <nav class="sidebar" id="sidebar">
      <div class="nav-list active" id="nav-medio">{nav_medio_html}</div>
      <div class="nav-list" id="nav-horario">{nav_horario_html}</div>
    </nav>
    <div class="main">
      <div class="tabs">
        <button class="tab-btn active" id="tab-medio" onclick="mostrarVista('medio')">📌 Por medio</button>
        <button class="tab-btn" id="tab-horario" onclick="mostrarVista('horario')">🕒 Por horario</button>
      </div>
      <input id="q" placeholder="Filtrar en esta lista..." oninput="filtrar()">
      <div id="view-medio" class="view active">
        {''.join(filas_medio)}
      </div>
      <div id="view-horario" class="view">
        {''.join(filas_horario)}
      </div>
    </div>
  </div>
  <script>
    function mostrarVista(v) {{
      document.querySelectorAll('.view').forEach(el => el.classList.remove('active'));
      document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
      document.querySelectorAll('.nav-list').forEach(el => el.classList.remove('active'));
      document.getElementById('view-' + v).classList.add('active');
      document.getElementById('tab-' + v).classList.add('active');
      document.getElementById('nav-' + v).classList.add('active');
      filtrar();
    }}
    function toggleMenu() {{
      document.getElementById('sidebar').classList.toggle('open');
      document.querySelector('.backdrop').classList.toggle('show');
    }}
    function cerrarMenu() {{
      document.getElementById('sidebar').classList.remove('open');
      document.querySelector('.backdrop').classList.remove('show');
    }}
    function filtrar() {{
      const q = document.getElementById('q').value.toLowerCase();
      document.querySelectorAll('.view.active .item').forEach(el => {{
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
    ap.add_argument("--sin-fotos", action="store_true",
                     help="No buscar og:image adicional (más rápido, menos fotos)")
    ap.add_argument("--max-fotos", type=int, default=150,
                     help="Tope de notas sin imagen para las que se busca og:image por corrida (default 150)")
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

    if not args.sin_fotos and not args.no_html:
        completar_fotos(fuentes_render, resultados, max_fotos=args.max_fotos)

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
