"""
Monitor Deportivo Pro — Streamlit Edition v1.0
Adaptación del UserScript para correr como app web local con Streamlit.

Instalar dependencias:
    pip install streamlit anthropic requests beautifulsoup4 lxml

Correr:
    streamlit run app.py
"""

import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
import unicodedata
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from datetime import datetime
import anthropic
import random
import math

# ─── CONFIG ──────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Monitor Deportivo Pro",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── CSS GLOBAL ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── Fuente base más grande ── */
html, body, [class*="css"] {
    font-size: 16px !important;
}

/* ── Tabs principales: envolver en lugar de scrollear ── */
.stTabs [data-baseweb="tab-list"] {
    flex-wrap: wrap !important;
    gap: 4px !important;
    overflow-x: visible !important;
    white-space: normal !important;
}
.stTabs [data-baseweb="tab"] {
    font-size: 15px !important;
    font-weight: 600 !important;
    padding: 8px 16px !important;
    white-space: nowrap !important;
    border-radius: 6px 6px 0 0 !important;
}

/* ── Títulos de noticias en cards ── */
.stMarkdown a, .stMarkdown p, .stMarkdown span {
    font-size: 15px;
    line-height: 1.55;
}

/* ── Sidebar más legible ── */
[data-testid="stSidebar"] {
    font-size: 15px !important;
}
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stSelectbox,
[data-testid="stSidebar"] .stButton button {
    font-size: 15px !important;
}

/* ── Selectbox y radios más grandes ── */
.stSelectbox > div, .stRadio label {
    font-size: 15px !important;
}

/* ── Expanders ── */
.streamlit-expanderHeader {
    font-size: 14px !important;
}
</style>
""", unsafe_allow_html=True)


# ─── NÚCLEO COMPARTIDO (scraping, clustering, agenda) ────────────────────────
from monitor_core import *          # noqa: F401,F403
from monitor_core import _extraer_cuerpo_nota, _FETCH_HEADERS  # noqa: F401
import sheets_memoria

if "resultados" not in st.session_state:
    st.session_state.resultados = {}
if "ultima_act" not in st.session_state:
    st.session_state.ultima_act = None
if "analisis_general" not in st.session_state:
    st.session_state.analisis_general = ""
if "informe_ole" not in st.session_state:
    st.session_state.informe_ole = ""
if "ole_analisis" not in st.session_state:
    st.session_state.ole_analisis = None
if "tendencias" not in st.session_state:
    st.session_state.tendencias = []
if "prev_tendencias" not in st.session_state:
    st.session_state.prev_tendencias = []
if "agenda_parte" not in st.session_state:
    st.session_state.agenda_parte = ""
if "agenda_briefs" not in st.session_state:
    st.session_state.agenda_briefs = {}
if "nota_rapida" not in st.session_state:
    st.session_state.nota_rapida = ""
if "nota_rapida_titulares" not in st.session_state:
    st.session_state.nota_rapida_titulares = []
if "nota_rapida_modo" not in st.session_state:
    st.session_state.nota_rapida_modo = ""
if "sentimiento_resultado" not in st.session_state:
    st.session_state.sentimiento_resultado = None
if "sentimiento_query" not in st.session_state:
    st.session_state.sentimiento_query = ""
if "canasta" not in st.session_state:
    st.session_state.canasta = []  # lista de dicts {fuente, noticia}
if "canasta_borrador" not in st.session_state:
    st.session_state.canasta_borrador = ""

# Cache de imágenes a nivel de módulo (accesible desde threads)
# Se mantiene mientras el proceso de Streamlit esté vivo
_IMAGE_CACHE: dict = {}

# ─── IMÁGENES OG ─────────────────────────────────────────────────────────────
def _canasta_agregar(titulo: str, url: str, fuente: dict, scrape_cuerpo: bool = True):
    """
    Agrega una noticia a la canasta si no está ya.
    Si scrape_cuerpo=True y hay URL, intenta leer el cuerpo de la nota en el momento.
    """
    ya = any(item["noticia"]["titulo"] == titulo for item in st.session_state.canasta)
    if ya:
        return
    cuerpo = ""
    if scrape_cuerpo and url:
        try:
            cuerpo = _extraer_cuerpo_nota(url, max_chars=1800)
        except Exception:
            cuerpo = ""
    st.session_state.canasta.append({
        "fuente": fuente,
        "noticia": {"titulo": titulo, "url": url},
        "cuerpo": cuerpo,
    })

def render_news_cards(noticias: list, fuente: dict, resultados: dict, cols_per_row: int = 3):
    """
    Renderiza noticias como cards con imagen grande arriba del título.
    Descarga og:images en paralelo antes de renderizar.
    """
    if not noticias:
        st.warning("Sin datos para esta fuente.")
        return

    # Separar noticias sin imagen del scraping — esas necesitan fetch de og:image
    sin_imagen = [n for n in noticias if not n.get("imagen") and n.get("url")]
    if sin_imagen:
        with st.spinner("Cargando imágenes..."):
            fetch_og_images_batch(sin_imagen)

    # Render en grilla
    rows = [noticias[i:i+cols_per_row] for i in range(0, len(noticias), cols_per_row)]
    color = fuente["color"]

    for row in rows:
        cols = st.columns(cols_per_row)
        for col, n in zip(cols, row):
            with col:
                # Prioridad: imagen extraída del card > og:image cacheado
                img_url = n.get("imagen") or _IMAGE_CACHE.get(n.get("url", ""), "")
                excl = es_exclusivo(n["titulo"], fuente["id"], resultados)

                # Card HTML completa
                excl_badge = (
                    f'<div style="position:absolute;top:8px;left:8px;'
                    f'background:rgba(212,160,23,.92);color:#fff;'
                    f'font-size:10px;font-weight:700;padding:2px 8px;'
                    f'border-radius:3px;letter-spacing:.6px">★ EXCLUSIVO</div>'
                ) if excl else ""

                img_html = (
                    f'<div style="position:relative;width:100%;padding-bottom:52%;'
                    f'overflow:hidden;background:#eef0f5;border-radius:8px 8px 0 0">'
                    f'<img src="{img_url}" style="position:absolute;inset:0;width:100%;'
                    f'height:100%;object-fit:cover" onerror="this.style.display=\'none\'">'
                    f'{excl_badge}</div>'
                ) if img_url else (
                    f'<div style="width:100%;padding:28px 0;background:#eef0f5;'
                    f'border-radius:8px 8px 0 0;text-align:center;font-size:28px">⚽</div>'
                )

                border_color = "#d4a017" if excl else color
                bg_excl = "background:#fffdf4;" if excl else ""

                titulo_link = (
                    f'<a href="{n["url"]}" target="_blank" rel="noopener" '
                    f'style="color:#14171a;text-decoration:none;font-size:15px;'
                    f'font-weight:600;line-height:1.5;display:block">'
                    f'{n["titulo"]}</a>'
                ) if n.get("url") else (
                    f'<span style="color:#14171a;font-size:15px;font-weight:600;'
                    f'line-height:1.5">{n["titulo"]}</span>'
                )

                fuente_tag = (
                    f'<span style="font-size:10px;font-weight:700;color:{color};'
                    f'font-family:sans-serif;letter-spacing:.6px;text-transform:uppercase">'
                    f'{fuente["nombre"]}</span>'
                )

                card_html = f"""
                <div style="border:1px solid #dde1ea;border-left:3px solid {border_color};
                     border-radius:8px;overflow:hidden;margin-bottom:4px;{bg_excl}
                     box-shadow:0 1px 4px rgba(0,0,0,.07)">
                  {img_html}
                  <div style="padding:10px 12px 12px">
                    {fuente_tag}
                    <div style="margin-top:5px">{titulo_link}</div>
                  </div>
                </div>
                """
                st.markdown(card_html, unsafe_allow_html=True)
                # Botón agregar a canasta (debajo de cada card)
                en_canasta = any(
                    item["noticia"]["titulo"] == n["titulo"]
                    for item in st.session_state.canasta
                )
                btn_label = "✅ En canasta" if en_canasta else "🧺 Agregar a canasta"
                if st.button(
                    btn_label,
                    key=f"canasta_{fuente['id']}_{hash(n['titulo'])}",
                    use_container_width=True,
                    disabled=en_canasta,
                ):
                    _canasta_agregar(n["titulo"], n.get("url"), fuente)
                    st.rerun()

# ─── SIDEBAR ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📡 Monitor Deportivo Pro")
    st.markdown(f"**{len(TODAS_FUENTES)} medios** · {len(FUENTES_NAC)} nac + {len(FUENTES_INT)} int")
    st.divider()

    try:
        _default_key = st.secrets.get("ANTHROPIC_API_KEY", "")
        sheets_memoria.configure(
            st.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON", ""),
            st.secrets.get("SHEET_ID", ""),
        )
    except Exception:
        _default_key = ""
    if sheets_memoria.disponible():
        st.caption(f"🧠 Memoria: [planilla conectada]({sheets_memoria.url_planilla()})")
    else:
        st.caption("🧠 Memoria: no configurada (momentum solo por sesión)")
    api_key = st.text_input(
        "🔑 Anthropic API Key",
        type="password",
        value=_default_key,
        placeholder="sk-ant-api03-...",
        help="Se puede dejar en Secrets de Streamlit (ANTHROPIC_API_KEY). Los feeds cargan sin key.",
    )

    st.divider()

    col_a, col_b = st.columns(2)
    with col_a:
        solo_nac = st.checkbox("Solo nacionales", value=False)
    with col_b:
        solo_int = st.checkbox("Solo int.", value=False)

    if st.button("↺ Actualizar fuentes", type="primary", use_container_width=True):
        actualizacion_parcial = solo_nac or solo_int
        fuentes_a_cargar = TODAS_FUENTES
        if solo_nac:
            fuentes_a_cargar = FUENTES_NAC
        elif solo_int:
            # Olé es la vara de comparación de todo el sistema: se refresca SIEMPRE
            fuente_ole = next(f for f in FUENTES_NAC if f["id"] == "ole")
            fuentes_a_cargar = FUENTES_INT + [fuente_ole]

        progress = st.progress(0, text="Cargando medios...")
        resultados_nuevos = {}
        errores = []
        total = len(fuentes_a_cargar)

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(fetch_fuente, f): f for f in fuentes_a_cargar}
            done = 0
            for future in as_completed(futures):
                res = future.result()
                resultados_nuevos[res["id"]] = res["noticias"]
                if res["error"]:
                    errores.append(f"{res['id']}: {res['error']}")
                done += 1
                progress.progress(done / total, text=f"Cargando... {done}/{total}")

        if actualizacion_parcial:
            # conservar los datos previos de las fuentes no actualizadas
            fusion = dict(st.session_state.get("resultados", {}))
            fusion.update(resultados_nuevos)
            resultados_nuevos = fusion
            st.caption("Actualización parcial: las demás fuentes conservan sus datos previos (Olé siempre se refresca).")
        st.session_state.resultados = resultados_nuevos
        st.session_state.ultima_act = datetime.now()
        st.session_state.ole_analisis = analizar_ole_vs_compecencia_safe(resultados_nuevos)
        prev_mem = []
        if sheets_memoria.disponible():
            try:
                prev_mem = sheets_memoria.leer_snapshot_anterior()
            except Exception:
                prev_mem = []
        st.session_state.prev_tendencias = prev_mem or st.session_state.get("tendencias", []) or []
        st.session_state.tendencias = calcular_tendencias(resultados_nuevos)
        if sheets_memoria.disponible() and not actualizacion_parcial:
            try:
                sheets_memoria.guardar_snapshot(st.session_state.tendencias, origen="app")
            except Exception:
                pass
        progress.empty()

        total_noticias = sum(len(v) for v in resultados_nuevos.values())
        st.success(f"✔ {total_noticias} noticias de {total} medios")
        if errores:
            with st.expander(f"⚠ {len(errores)} errores"):
                st.text("\n".join(errores))
        st.rerun()

    if st.session_state.ultima_act:
        st.caption(f"Última actualización: {st.session_state.ultima_act.strftime('%H:%M:%S')}")
        total_noticias = sum(len(v) for v in st.session_state.resultados.values())
        st.metric("Total de noticias", total_noticias)

    st.divider()
    # ── CANASTA ──────────────────────────────────────────────────────────────
    cant_canasta = len(st.session_state.canasta)
    st.markdown(f"**🧺 Canasta** — {cant_canasta} nota(s)")
    if cant_canasta > 0:
        col_ca, col_cb = st.columns(2)
        with col_ca:
            if st.button("🗑 Vaciar", use_container_width=True, key="sidebar_vaciar_canasta"):
                st.session_state.canasta = []
                st.rerun()
        with col_cb:
            texto_canasta = "\n\n".join(
                f"[{item['fuente']['nombre']}] {item['noticia']['titulo']}\n{item['noticia'].get('url','')}"
                for item in st.session_state.canasta
            )
            st.download_button(
                "📥 Exportar",
                texto_canasta,
                file_name=f"canasta_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                mime="text/plain",
                use_container_width=True,
                key="sidebar_exportar_canasta",
            )

    st.divider()
    st.markdown("**IA con Claude**")

    if st.button("✦ Análisis General", use_container_width=True):
        if not api_key:
            st.error("Ingresá tu API key")
        elif not st.session_state.resultados:
            st.error("Actualizá las fuentes primero")
        else:
            with st.spinner("Analizando con Claude..."):
                try:
                    prompt = prompt_analisis_general(st.session_state.resultados)
                    st.session_state.analisis_general = call_claude(prompt, api_key, 5000)
                    st.success("✔ Análisis generado")
                except Exception as e:
                    st.error(f"Error: {e}")

    temas_editor = st.text_area(
        "Temas que querés tratar (uno por línea; vacío = el sistema sugiere)",
        key="temas_editor_ole", height=90,
        placeholder="Almada a River\nBoca y el nuevo DT\nSelección: la lista de Scaloni",
    )
    _label_ole = "🟢 Ángulos para mis temas" if temas_editor.strip() else "🟢 Informe Olé IA (sugerencias)"
    if st.button(_label_ole, use_container_width=True):
        if not api_key:
            st.error("Ingresá tu API key")
        elif not st.session_state.resultados:
            st.error("Actualizá las fuentes primero")
        else:
            analisis = st.session_state.ole_analisis or analizar_ole_vs_compecencia_safe(st.session_state.resultados)
            with st.spinner("Buscando ángulos con Claude..."):
                try:
                    prompt = prompt_informe_ole(st.session_state.resultados, analisis, temas_editor)
                    st.session_state.informe_ole = call_claude(prompt, api_key, 5000)
                    st.success("✔ Listo")
                except Exception as e:
                    st.error(f"Error: {e}")





# ─── MAIN ─────────────────────────────────────────────────────────────────────
st.title("📡 Monitor Deportivo Pro")

if not st.session_state.resultados:
    st.info("👈 Hacé clic en **↺ Actualizar fuentes** en el panel izquierdo para comenzar.")
    st.stop()

resultados = st.session_state.resultados
ole_analisis = st.session_state.ole_analisis
tendencias = st.session_state.tendencias

# ─── TABS PRINCIPALES ────────────────────────────────────────────────────────
tab_agenda, tab_buscar, tab_todos, tab_nac, tab_int, tab_ole, tab_tend, tab_ia, tab_nota, tab_sent, tab_canasta = st.tabs([
    "🎯 Agenda",
    "🔎 Buscar",
    f"📋 Todos ({sum(len(v) for v in resultados.values())})",
    f"🇦🇷 Nacionales ({sum(len(resultados.get(f['id'],[])) for f in FUENTES_NAC)})",
    f"🌍 Internacionales ({sum(len(resultados.get(f['id'],[])) for f in FUENTES_INT)})",
    "⭐ Olé vs Todos",
    f"📊 Tendencias ({len(tendencias)})",
    "🤖 Análisis IA",
    "✍️ Nota Rápida",
    "🌡️ Tono Editorial",
    f"🧺 Canasta ({len(st.session_state.canasta)})",
])

# ─── TAB AGENDA ──────────────────────────────────────────────────────────────
with tab_agenda:
    st.subheader("🎯 Qué se puede hacer ahora")
    agenda = construir_agenda(tendencias, ole_analisis, st.session_state.get("prev_tendencias"))

    hay_prev = bool(st.session_state.get("prev_tendencias"))
    if not hay_prev:
        st.caption("Momentum disponible desde el segundo refresco (compara contra el anterior).")

    if not agenda:
        st.info("No hay acciones destacadas todavía. Actualizá las fuentes un par de veces.")
    else:
        col_h1, col_h2 = st.columns([3, 1])
        with col_h1:
            st.caption(f"{len(agenda)} acciones priorizadas · rojo = urgente · verde = tu ventaja")
        with col_h2:
            if st.button("✦ Parte editorial (IA)", use_container_width=True):
                if not api_key:
                    st.error("Ingresá tu API key en el panel izquierdo")
                else:
                    with st.spinner("Redactando el parte con Claude..."):
                        try:
                            st.session_state.agenda_parte = call_claude(
                                prompt_parte_editorial(agenda), api_key, 1200
                            )
                        except Exception as e:
                            st.error(f"Error: {e}")

        if st.session_state.get("agenda_parte"):
            with st.expander("📝 Parte editorial (IA)", expanded=True):
                st.markdown(st.session_state.agenda_parte)

        for it in agenda:
            color = AGENDA_COLORES.get(it["accion"], "#555")
            if it["nuevo"]:
                mom = "🆕 nuevo"
            elif it["delta"] > 0:
                mom = f"▲ +{it['delta']} medios"
            elif it["delta"] < 0:
                mom = f"▼ {it['delta']} medios"
            else:
                mom = "= estable"
            titulo_html = (
                f'<a href="{it["url"]}" target="_blank" rel="noopener" '
                f'style="color:#14171a;text-decoration:none;font-weight:600">{it["titulo"]}</a>'
                if it.get("url") else
                f'<span style="color:#14171a;font-weight:600">{it["titulo"]}</span>'
            )
            st.markdown(f"""
            <div style="border:1px solid #dde1ea;border-left:5px solid {color};
                 border-radius:8px;padding:10px 14px;margin-bottom:6px;
                 box-shadow:0 1px 4px rgba(0,0,0,.06)">
              <span style="background:{color};color:#fff;font-size:11px;font-weight:800;
                    padding:2px 8px;border-radius:4px;letter-spacing:.5px">{it["accion"]}</span>
              <span style="font-size:12px;color:#657786;margin-left:8px">{it["motivo"]}</span>
              <div style="margin-top:6px;font-size:15px">{titulo_html}</div>
              <div style="margin-top:4px;font-size:12px;color:#657786">
                {it["cant_medios"]} medios · {it["nac"]} nac / {it["intl"]} int · {mom}
              </div>
            </div>
            """, unsafe_allow_html=True)

            brief_key = str(hash(it["titulo"]))
            col_b1, col_b2 = st.columns(2)
            with col_b1:
                if st.button("✦ Brief IA", key=f"agenda_brief_{it['accion']}_{brief_key}",
                             use_container_width=True):
                    if not api_key:
                        st.error("Ingresá tu API key")
                    else:
                        with st.spinner("Pensando el ángulo..."):
                            try:
                                st.session_state.agenda_briefs[brief_key] = call_claude(
                                    prompt_brief_item(it), api_key, 400
                                )
                            except Exception as e:
                                st.error(f"Error: {e}")
            with col_b2:
                en_canasta = any(
                    item["noticia"]["titulo"] == it["titulo"] for item in st.session_state.canasta
                )
                if st.button(
                    "✅ En canasta" if en_canasta else "🧺 A canasta",
                    key=f"agenda_canasta_{it['accion']}_{brief_key}",
                    use_container_width=True, disabled=en_canasta,
                ):
                    fuente_rep = (it["noticias"][0]["fuente"]
                                  if it.get("noticias") else
                                  {"id": "agenda", "nombre": "Agenda", "color": color})
                    _canasta_agregar(it["titulo"], it.get("url"), fuente_rep)
                    st.rerun()

            if st.session_state.agenda_briefs.get(brief_key):
                st.info(st.session_state.agenda_briefs[brief_key])

# ─── TAB BUSCADOR GLOBAL ─────────────────────────────────────────────────────
with tab_buscar:
    st.subheader("🔎 Buscar en todas las fuentes")
    total_notas = sum(len(v) for v in resultados.values())
    if not total_notas:
        st.info("Actualizá las fuentes primero.")
    else:
        c_q, c_a = st.columns([3, 1])
        with c_q:
            q_global = st.text_input(
                f"Buscar entre {total_notas} noticias de {len(TODAS_FUENTES)} fuentes",
                key="q_global", placeholder="ej: Mastantuono, penal, Scaloni...",
            )
        with c_a:
            ambito_b = st.selectbox("Ámbito", ["Todas", "Nacionales", "Internacionales"], key="ambito_b")

        if q_global and len(q_global.strip()) >= 3:
            q = q_global.strip().lower()
            fuentes_b = (FUENTES_NAC if ambito_b == "Nacionales"
                         else FUENTES_INT if ambito_b == "Internacionales"
                         else TODAS_FUENTES)
            hits_total = 0
            for f in fuentes_b:
                hits = [n for n in resultados.get(f["id"], []) if q in n["titulo"].lower()]
                if not hits:
                    continue
                hits_total += len(hits)
                st.markdown(
                    f'<div style="margin-top:10px"><span style="color:{f["color"]};'
                    f'font-weight:700">● {f["nombre"]}</span> '
                    f'<span style="color:#657786;font-size:12px">({len(hits)})</span></div>',
                    unsafe_allow_html=True,
                )
                for n in hits[:8]:
                    if n.get("url"):
                        st.markdown(f'&nbsp;&nbsp;• [{n["titulo"]}]({n["url"]})')
                    else:
                        st.markdown(f'&nbsp;&nbsp;• {n["titulo"]}')
                if len(hits) > 8:
                    st.caption(f"   …y {len(hits) - 8} más en {f['nombre']}")
            if hits_total == 0:
                st.warning(f'Nada con "{q_global}" en {ambito_b.lower()}. Probá con menos letras o sin acentos.')
            else:
                st.caption(f"{hits_total} resultados en total")
        elif q_global:
            st.caption("Escribí al menos 3 letras.")

# ─── TAB TODOS LOS TITULARES (vista rápida, sin fotos) ───────────────────────
with tab_todos:
    total_todos = sum(len(resultados.get(f["id"], [])) for f in TODAS_FUENTES)
    st.caption(f"{total_todos} titulares de {len(TODAS_FUENTES)} medios — sin fotos, para leer rápido")

    col_t1, col_t2, col_t3 = st.columns([2, 2, 1])
    with col_t1:
        ambito_todos = st.radio(
            "Ámbito", ["Todas", "Nacionales", "Internacionales"],
            horizontal=True, key="ambito_todos",
        )
    with col_t2:
        filtro_todos = st.text_input(
            "🔍 Filtrar (opcional)", key="filtro_todos", placeholder="ej: Boca, River, Messi...",
        )
    with col_t3:
        orden_todos = st.selectbox("Orden", ["Por medio", "A-Z"], key="orden_todos")

    fuentes_todos = (
        FUENTES_NAC if ambito_todos == "Nacionales"
        else FUENTES_INT if ambito_todos == "Internacionales"
        else TODAS_FUENTES
    )

    def _fila_html(n, color=None):
        titulo = n["titulo"]
        tag = (
            f'<span style="color:{color};font-weight:700;font-size:11px;'
            f'margin-right:6px">●</span>' if color else ""
        )
        if n.get("url"):
            return (
                f'<div style="padding:3px 0;border-bottom:1px solid #eee;font-size:14.5px">'
                f'{tag}<a href="{n["url"]}" target="_blank" rel="noopener" '
                f'style="color:#14171a;text-decoration:none">{titulo}</a></div>'
            )
        return (
            f'<div style="padding:3px 0;border-bottom:1px solid #eee;font-size:14.5px">'
            f'{tag}{titulo}</div>'
        )

    html_parts = ['<div style="line-height:1.4">']

    if orden_todos == "A-Z":
        planas = []
        for f in fuentes_todos:
            noticias_f = resultados.get(f["id"], [])
            if filtro_todos:
                noticias_f = [n for n in noticias_f if filtro_todos.lower() in n["titulo"].lower()]
            for n in noticias_f:
                planas.append((n, f))
        planas.sort(key=lambda t: t[0]["titulo"].lower())
        for n, f in planas:
            html_parts.append(_fila_html(n, f["color"]))
    else:
        for f in fuentes_todos:
            noticias_f = resultados.get(f["id"], [])
            if filtro_todos:
                noticias_f = [n for n in noticias_f if filtro_todos.lower() in n["titulo"].lower()]
            if not noticias_f:
                continue
            html_parts.append(
                f'<div style="margin-top:14px;font-weight:800;color:{f["color"]};'
                f'font-size:12px;letter-spacing:.5px;text-transform:uppercase">'
                f'{f["nombre"]} <span style="color:#657786;font-weight:400">'
                f'({len(noticias_f)})</span></div>'
            )
            for n in noticias_f:
                html_parts.append(_fila_html(n))

    html_parts.append("</div>")

    if len(html_parts) <= 2:
        st.info("Sin titulares para mostrar con ese filtro.")
    else:
        st.markdown("".join(html_parts), unsafe_allow_html=True)

# ─── TAB NACIONALES ──────────────────────────────────────────────────────────
with tab_nac:
    fuente_sel = st.selectbox(
        "Medio",
        [f["nombre"] for f in FUENTES_NAC],
        key="sel_nac",
    )
    fuente_obj = next(f for f in FUENTES_NAC if f["nombre"] == fuente_sel)
    noticias = resultados.get(fuente_obj["id"], [])

    col_h1, col_h2 = st.columns([3, 1])
    with col_h1:
        st.markdown(
            f'<span style="color:{fuente_obj["color"]};font-weight:700;font-size:18px">'
            f'{fuente_obj["nombre"]}</span> — {len(noticias)} noticias',
            unsafe_allow_html=True,
        )
    with col_h2:
        cols_per_row = st.selectbox("Columnas", [2, 3, 4], index=1, key="cols_nac")

    filtro = st.text_input("🔍 Filtrar por palabra", key="filtro_nac")
    lista = [n for n in noticias if filtro.lower() in n["titulo"].lower()] if filtro else noticias

    render_news_cards(lista, fuente_obj, resultados, cols_per_row=cols_per_row)

# ─── TAB INTERNACIONALES ─────────────────────────────────────────────────────
with tab_int:
    fuente_sel_i = st.selectbox(
        "Medio",
        [f["nombre"] for f in FUENTES_INT],
        key="sel_int",
    )
    fuente_obj_i = next(f for f in FUENTES_INT if f["nombre"] == fuente_sel_i)
    noticias_i = resultados.get(fuente_obj_i["id"], [])

    col_h1i, col_h2i = st.columns([3, 1])
    with col_h1i:
        st.markdown(
            f'<span style="color:{fuente_obj_i["color"]};font-weight:700;font-size:18px">'
            f'{fuente_obj_i["nombre"]}</span> — {len(noticias_i)} noticias',
            unsafe_allow_html=True,
        )
    with col_h2i:
        cols_per_row_i = st.selectbox("Columnas", [2, 3, 4], index=1, key="cols_int")

    filtro_i = st.text_input("🔍 Filtrar por palabra", key="filtro_int")
    lista_i = [n for n in noticias_i if filtro_i.lower() in n["titulo"].lower()] if filtro_i else noticias_i

    render_news_cards(lista_i, fuente_obj_i, resultados, cols_per_row=cols_per_row_i)

# ─── TAB OLÉ VS TODOS ────────────────────────────────────────────────────────
with tab_ole:
    if not ole_analisis:
        st.info("Actualizá las fuentes para ver el análisis semántico.")
    else:
        excl = ole_analisis["exclusivos_ole"]
        falt = ole_analisis["faltantes_en_ole"]
        comp = ole_analisis["cubiertos_por_ambos"]

        c1, c2, c3 = st.columns(3)
        c1.metric("⭐ Exclusivos Olé", len(excl), help="Temas que solo cubre Olé")
        c2.metric("❌ Ausentes en Olé", len(falt), help="Temas que tiene la competencia y Olé NO cubre")
        c3.metric("🔄 Temas compartidos", len(comp), help="Cubiertos por ambos, posible ángulo diferente")

        st.divider()

        sub1, sub2, sub3 = st.tabs([
            f"⭐ Exclusivos Olé ({len(excl)})",
            f"❌ Faltantes ({len(falt)})",
            f"🔄 Compartidos ({len(comp)})",
        ])

        with sub1:
            if not excl:
                st.info("No se detectaron exclusivos.")
            for n in excl:
                if n.get("url"):
                    st.markdown(f"⭐ [{n['titulo']}]({n['url']})")
                else:
                    st.markdown(f"⭐ {n['titulo']}")

        with sub2:
            if not falt:
                st.success("✔ Olé cubre todos los temas detectados.")
            else:
                for f_item in falt:
                    col_hex = f_item["fuente_color"]
                    badge_html = (
                        f'<span style="background:{col_hex}22;color:{col_hex};border:1px solid {col_hex}55;'
                        f'padding:1px 8px;border-radius:4px;font-size:11px;font-weight:700">'
                        f'{f_item["fuente_nombre"]}</span>'
                    )
                    if f_item.get("url"):
                        st.markdown(
                            f'{badge_html} [{f_item["titulo"]}]({f_item["url"]})',
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(
                            f'{badge_html} {f_item["titulo"]}',
                            unsafe_allow_html=True,
                        )

        with sub3:
            if not comp:
                st.info("Sin temas compartidos detectados.")
            for item in comp[:30]:
                nol = item["noticia_ole"]
                with st.expander(f"🔄 {nol['titulo'][:90]}..."):
                    if nol.get("url"):
                        st.markdown(f"**Olé:** [{nol['titulo']}]({nol['url']})")
                    else:
                        st.markdown(f"**Olé:** {nol['titulo']}")
                    for ci in item["competencia"]:
                        fobj = next((f for f in TODAS_FUENTES if f["id"] == ci["fuente_id"]), None)
                        nombre = fobj["nombre"] if fobj else ci["fuente_id"]
                        color = fobj["color"] if fobj else "#666"
                        badge = (
                            f'<span style="color:{color};font-weight:700;font-size:11px">{nombre}</span>'
                        )
                        if ci["noticia"].get("url"):
                            st.markdown(
                                f'{badge} [{ci["noticia"]["titulo"]}]({ci["noticia"]["url"]})',
                                unsafe_allow_html=True,
                            )
                        else:
                            st.markdown(f'{badge} {ci["noticia"]["titulo"]}', unsafe_allow_html=True)

# ─── TAB TENDENCIAS ──────────────────────────────────────────────────────────
with tab_tend:
    if not tendencias:
        st.info("Actualizá las fuentes para ver las tendencias.")
    else:
        total_fuentes = len(TODAS_FUENTES)
        sin_ole = [t for t in tendencias if not t["tiene_ole"]]
        con_ole = [t for t in tendencias if t["tiene_ole"]]
        hot     = [t for t in tendencias if t["cant_medios"] / total_fuentes >= 0.20]

        # ── Métricas ─────────────────────────────────────────────────────────
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Temas detectados", len(tendencias))
        m2.metric("❌ Sin Olé", len(sin_ole))
        m3.metric("✅ Con Olé", len(con_ole))
        m4.metric("🔥 Trending", len(hot))

        st.divider()

        # ── Helpers de frecuencia de palabras ────────────────────────────────
        EXTRA_STOP = {
            "partido","partidos","juego","juegos","dice","dijo","señalo",
            "aseguro","confirmo","revelo","anuncio","hablo","tiene","hoy",
            "ayer","manana","semana","anno","mes","vez","nuevo","nueva",
            "gran","primer","primera","sera","puede","equipo","sobre",
            "habla","luego","hace","dado","segun","after","over","into",
            "than","their","they","this","that","with","will","from",
        }

        def build_word_freq(fuente_ids: list) -> list:
            freq = {}
            for fid in fuente_ids:
                for n in (st.session_state.resultados or {}).get(fid, []):
                    for w in normalizar_titulo(n["titulo"]) - EXTRA_STOP:
                        if len(w) > 3:
                            freq[w] = freq.get(w, 0) + 1
            return sorted(freq.items(), key=lambda x: -x[1])

        def html_word_cloud(freq_list: list, color_hex: str) -> str:
            """Genera una nube de palabras como HTML puro con posicionamiento en espiral."""
            if not freq_list:
                return "<p style='color:#aaa;text-align:center;padding:40px'>Sin datos</p>"

            words = freq_list[:60]
            max_c = words[0][1]
            min_c = words[-1][1]
            rng   = max_c - min_c or 1

            # Parsear color hex → rgb
            h = color_hex.lstrip("#")
            cr, cg, cb = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)

            # Posicionamiento en espiral (coordenadas % dentro del contenedor)
            placed = []  # (cx, cy, half_w, half_h)
            items_html = []
            random.seed(42)

            for word, count in words:
                t = (count - min_c) / rng          # 0..1
                fsize = 11 + t * 26                # 11px..37px
                # Color: interpolar entre color_hex (t=1) y gris claro (t=0)
                r = int(cr + (220 - cr) * (1 - t))
                g = int(cg + (225 - cg) * (1 - t))
                b = int(cb + (230 - cb) * (1 - t))
                weight = "700" if t > 0.45 else "400"
                opacity = 0.5 + t * 0.5

                # Estimar tamaño en % (contenedor 480×260px)
                hw = len(word) * fsize * 0.30 / 4.8   # half-width %
                hh = fsize * 0.65 / 2.6               # half-height %

                ok = False
                for step in range(400):
                    angle  = step * 0.28
                    radius = step * 0.15
                    cx = 50 + radius * math.cos(angle)
                    cy = 50 + radius * math.sin(angle) * 0.55
                    if cx - hw < 1 or cx + hw > 99 or cy - hh < 2 or cy + hh > 98:
                        continue
                    pad = 1.2
                    if not any(
                        abs(cx - px) < hw + phw + pad and abs(cy - py) < hh + phh + pad
                        for px, py, phw, phh in placed
                    ):
                        placed.append((cx, cy, hw, hh))
                        items_html.append(
                            f'<span style="position:absolute;left:{cx:.1f}%;top:{cy:.1f}%;'
                            f'transform:translate(-50%,-50%);font-size:{fsize:.1f}px;'
                            f'font-weight:{weight};color:rgb({r},{g},{b});'
                            f'opacity:{opacity:.2f};white-space:nowrap;'
                            f'font-family:Barlow,sans-serif;line-height:1;'
                            f'cursor:default" title="{count} menciones">{word}</span>'
                        )
                        ok = True
                        break

            return (
                '<div style="position:relative;width:100%;height:260px;'
                'background:#f8fafc;border-radius:10px;overflow:hidden;'
                'border:1px solid #e2e8f0">'
                + "".join(items_html)
                + "</div>"
            )

        # ── Layout: ranking | nubes ───────────────────────────────────────────
        # ── NUBE DE PALABRAS (ancho completo, arriba) ─────────────────────────
        st.markdown("#### 🔤 Nube de palabras")
        nac_ids  = [f["id"] for f in FUENTES_NAC]
        intl_ids = [f["id"] for f in FUENTES_INT]
        ct1, ct2 = st.tabs(["🇦🇷 Nacionales", "🌍 Internacionales"])

        def _cloud_section(fuente_ids, color_hex):
            freq = build_word_freq(fuente_ids)
            cloud_html = html_word_cloud(freq, color_hex).replace("height:260px", "height:320px")
            st.markdown(cloud_html, unsafe_allow_html=True)
            if freq:
                top = " &nbsp;·&nbsp; ".join(
                    f'<b>{w}</b> <span style="color:#94a3b8;font-size:11px">×{c}</span>'
                    for w, c in freq[:14]
                )
                st.markdown(
                    f'<div style="margin-top:8px;font-size:12px;line-height:2;color:#374151">{top}</div>',
                    unsafe_allow_html=True,
                )

        with ct1:
            _cloud_section(nac_ids, "#00a846")
        with ct2:
            _cloud_section(intl_ids, "#1a7fc1")

        st.divider()

        # ── RANKING DE TEMAS (ancho completo, abajo) ─────────────────────────
        st.markdown("#### 📊 Ranking de temas")
        filtro = st.radio(
            "Filtrar por",
            ["Sin Olé ❌", "Con Olé ✅", "🔥 Hot", "Todos"],
            horizontal=True, key="filtro_tend",
        )
        lista = tendencias[:80]
        if filtro == "Sin Olé ❌":   lista = [t for t in lista if not t["tiene_ole"]]
        elif filtro == "Con Olé ✅": lista = [t for t in lista if t["tiene_ole"]]
        elif filtro == "🔥 Hot":     lista = [t for t in lista if t["cant_medios"] / total_fuentes >= 0.20]

        st.caption(f"{len(lista)} temas · similitud Jaccard ≥ {SIMILITUD_UMBRAL}")

        for t in lista[:50]:
            pct = t["cant_medios"] / total_fuentes
            bar_pct = int(pct * 100)
            if pct >= 0.5:    accent, emoji = "#dc2626", "🔥🔥"
            elif pct >= 0.30: accent, emoji = "#ea580c", "🔥"
            elif pct >= 0.15: accent, emoji = "#ca8a04", "▲"
            else:             accent, emoji = "#3b82f6", "·"

            ole_dot = "🟢" if t["tiene_ole"] else "🔴"

            chips = "".join(
                f'<span style="font-size:9px;font-weight:700;padding:1px 5px;'
                f'border-radius:3px;background:{item["fuente"]["color"]}18;'
                f'color:{item["fuente"]["color"]};border:1px solid {item["fuente"]["color"]}30">'
                f'{item["fuente"]["nombre"]}</span> '
                for item in t["noticias"]
            )

            st.markdown(
                f"""<div style="margin-bottom:7px;padding:9px 12px;border-radius:8px;
                    border-left:4px solid {accent};background:#fafafa;
                    border:1px solid #eee;border-left:4px solid {accent}">
                  <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
                    <span style="font-size:11px;font-weight:700;color:{accent}">{emoji} {t['cant_medios']} medios</span>
                    <span>{ole_dot}</span>
                    <span style="font-size:10px;color:#94a3b8">{t['nac']}🇦🇷 {t['intl']}🌍</span>
                    <div style="flex:1;height:5px;background:#e2e8f0;border-radius:3px;overflow:hidden">
                      <div style="width:{bar_pct}%;height:100%;background:{accent}"></div>
                    </div>
                    <span style="font-size:10px;color:#94a3b8">{bar_pct}%</span>
                  </div>
                  <div style="font-size:15px;font-weight:600;color:#0f172a;
                      line-height:1.4;margin-bottom:5px">{t['titulo'][:130]}</div>
                  <div style="display:flex;flex-wrap:wrap;gap:2px">{chips}</div>
                </div>""",
                unsafe_allow_html=True,
            )

            # ── Botones de acción por card ────────────────────────────────────
            t_idx = lista.index(t)
            btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 4])
            with btn_col1:
                ver_notas = st.button("▸ Ver notas", key=f"vernotas_{t_idx}", use_container_width=True)
            with btn_col2:
                analizar_tono = st.button("🌡️ Tono", key=f"tono_{t_idx}", use_container_width=True)

            if ver_notas:
                st.session_state[f"open_notas_{t_idx}"] = not st.session_state.get(f"open_notas_{t_idx}", False)
            if analizar_tono:
                st.session_state[f"open_tono_{t_idx}"] = not st.session_state.get(f"open_tono_{t_idx}", False)
                if st.session_state[f"open_tono_{t_idx}"]:
                    st.session_state[f"tono_resultado_{t_idx}"] = None  # reset para nueva búsqueda

            if st.session_state.get(f"open_notas_{t_idx}", False):
                with st.container():
                    for item in t["noticias"]:
                        n, f = item["noticia"], item["fuente"]
                        badge = (f'<span style="color:{f["color"]};font-size:10px;font-weight:700;'
                                 f'background:{f["color"]}18;padding:1px 6px;border-radius:3px">'
                                 f'{f["nombre"]}</span>')
                        if n.get("url"):
                            st.markdown(f'{badge} [{n["titulo"]}]({n["url"]})', unsafe_allow_html=True)
                        else:
                            st.markdown(f'{badge} {n["titulo"]}', unsafe_allow_html=True)

            if st.session_state.get(f"open_tono_{t_idx}", False):
                tono_key = f"tono_resultado_{t_idx}"
                if st.session_state.get(tono_key) is None:
                    if not api_key:
                        st.warning("Ingresá tu API key en el panel izquierdo para analizar el tono.")
                    else:
                        with st.spinner("Analizando tono editorial..."):
                            try:
                                prompt = prompt_tono_editorial(t["titulo"], t["noticias"][:40])
                                raw_json = call_claude(prompt, api_key, 1200)
                                clean = raw_json.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
                                st.session_state[tono_key] = json.loads(clean)
                            except Exception as e:
                                st.session_state[tono_key] = {"error": str(e)}

                res = st.session_state.get(tono_key)
                if res and "error" not in res:
                    TONO_CFG = {
                        "positivo":  ("🟢", "#16a34a", "#f0fdf4"),
                        "negativo":  ("🔴", "#dc2626", "#fef2f2"),
                        "neutro":    ("⚪", "#6b7280", "#f9fafb"),
                        "alarmista": ("🟡", "#d97706", "#fffbeb"),
                        "expectante":("🔵", "#2563eb", "#eff6ff"),
                    }
                    with st.container():
                        st.markdown(
                            f'<div style="padding:10px 14px;border-radius:8px;background:#f0f9ff;'
                            f'border-left:4px solid #0ea5e9;font-size:14px;margin:6px 0">'
                            f'📝 {res.get("resumen","")}</div>',
                            unsafe_allow_html=True,
                        )
                        dist = res.get("distribucion", {})
                        total_cl = sum(dist.values()) or 1
                        dcols = st.columns(5)
                        for i, (tono, count) in enumerate(dist.items()):
                            em, col, bg = TONO_CFG.get(tono, ("⚫","#374151","#f9fafb"))
                            pct = int(count / total_cl * 100)
                            with dcols[i]:
                                st.markdown(
                                    f'<div style="text-align:center;padding:8px 4px;border-radius:7px;'
                                    f'background:{bg};border:1px solid {col}30">'
                                    f'<div style="font-size:18px">{em}</div>'
                                    f'<div style="font-size:17px;font-weight:700;color:{col}">{count}</div>'
                                    f'<div style="font-size:10px;color:#6b7280;text-transform:capitalize">{tono}</div>'
                                    f'<div style="font-size:9px;color:#9ca3af">{pct}%</div>'
                                    f'</div>',
                                    unsafe_allow_html=True,
                                )
                        for item in res.get("por_medio", []):
                            tono = item.get("tono", "neutro")
                            em, col, bg = TONO_CFG.get(tono, ("⚫","#374151","#f9fafb"))
                            st.markdown(
                                f'<div style="display:flex;gap:8px;align-items:flex-start;'
                                f'padding:7px 10px;margin-top:4px;border-radius:6px;'
                                f'background:{bg};border:1px solid {col}20">'
                                f'<span style="font-size:16px;flex-shrink:0">{em}</span>'
                                f'<div><span style="font-size:10px;font-weight:700;color:{col};text-transform:uppercase">'
                                f'{item.get("medio","")} · {tono}</span><br>'
                                f'<span style="font-size:12px;color:#1e293b">{item.get("titular","")}</span><br>'
                                f'<span style="font-size:11px;color:#64748b;font-style:italic">{item.get("razon","")}</span>'
                                f'</div></div>',
                                unsafe_allow_html=True,
                            )
                elif res and "error" in res:
                    st.error(f"Error al analizar: {res['error']}")

# ─── TAB IA ──────────────────────────────────────────────────────────────────
with tab_ia:
    ia1, ia2, ia3 = st.tabs(["✦ Análisis General", "🟢 Informe Olé", "📋 Exclusivos (todos)"])

    with ia1:
        if st.session_state.analisis_general:
            st.text_area(
                "Análisis General",
                st.session_state.analisis_general,
                height=500,
                label_visibility="collapsed",
            )
            st.download_button(
                "📥 Descargar análisis",
                st.session_state.analisis_general,
                file_name="analisis_general.txt",
                mime="text/plain",
            )
        else:
            st.info("Hacé clic en **✦ Análisis General** en el panel izquierdo (requiere API key).")

    with ia2:
        if st.session_state.informe_ole:
            st.text_area(
                "Informe Olé",
                st.session_state.informe_ole,
                height=500,
                label_visibility="collapsed",
            )
            st.download_button(
                "📥 Descargar informe",
                st.session_state.informe_ole,
                file_name="informe_ole.txt",
                mime="text/plain",
            )
        else:
            st.info("Hacé clic en **🟢 Informe Olé IA** en el panel izquierdo (requiere API key).")

    with ia3:
        st.markdown(f"**Titulares únicos por tema** — similitud Jaccard < {SIMILITUD_UMBRAL}")
        exclusivos_todos = []
        for f in TODAS_FUENTES:
            for n in resultados.get(f["id"], []):
                if es_exclusivo(n["titulo"], f["id"], resultados):
                    exclusivos_todos.append({"fuente": f, "noticia": n})

        if not exclusivos_todos:
            st.info("No se detectaron exclusivos.")
        else:
            st.caption(f"{len(exclusivos_todos)} exclusivos detectados")
            for item in exclusivos_todos[:100]:
                f = item["fuente"]
                n = item["noticia"]
                badge = (
                    f'<span style="color:{f["color"]};font-weight:700;font-size:11px;'
                    f'background:{f["color"]}15;padding:1px 8px;border-radius:4px">'
                    f'{f["nombre"]}</span>'
                )
                if n.get("url"):
                    st.markdown(f'{badge} [{n["titulo"]}]({n["url"]})', unsafe_allow_html=True)
                else:
                    st.markdown(f'{badge} {n["titulo"]}', unsafe_allow_html=True)

# ─── TAB NOTA RÁPIDA ─────────────────────────────────────────────────────────
with tab_nota:
    st.markdown("### ✍️ Asistente de Nota Rápida")
    st.caption("Buscá un tema, elegí las notas que querés usar y generá el borrador con IA.")

    # ── PASO 1: Fuente del tema ───────────────────────────────────────────────
    st.markdown("#### 1️⃣ ¿De dónde tomamos las notas?")
    modo_tema = st.radio(
        "",
        ["📊 Desde el ranking de tendencias", "🔍 Buscar en los medios cargados", "✏️ Escribir tema libre"],
        horizontal=True,
        key="nota_modo_tema",
        label_visibility="collapsed",
    )

    titulares_seleccionados = []
    tema_elegido = ""

    # ── Modo 1: Desde el ranking de tendencias ──────────────────────────────
    if modo_tema == "📊 Desde el ranking de tendencias":
        if not tendencias:
            st.warning("Primero actualizá las fuentes para cargar tendencias.")
        else:
            opciones_temas = [
                f"[{t['cant_medios']} medios] {t['titulo'][:90]}"
                for t in tendencias[:40]
            ]
            tema_idx = st.selectbox(
                "Tema del ranking",
                range(len(opciones_temas)),
                format_func=lambda i: opciones_temas[i],
                key="nota_tema_idx",
            )
            tema_elegido = tendencias[tema_idx]["titulo"]
            titulares_pool = tendencias[tema_idx]["noticias"]

            st.caption(f"**{len(titulares_pool)}** notas en este tema — marcá las que querés usar:")
            sel_key_t = f"nota_sel_tend_{tema_idx}"
            if sel_key_t not in st.session_state:
                st.session_state[sel_key_t] = set(range(len(titulares_pool)))  # todas por defecto

            col_ta, col_tb = st.columns([1, 5])
            with col_ta:
                if st.button("☑ Todas", key="nota_tend_all", use_container_width=True):
                    st.session_state[sel_key_t] = set(range(len(titulares_pool)))
                    st.rerun()
            with col_tb:
                if st.button("☐ Ninguna", key="nota_tend_none", use_container_width=True):
                    st.session_state[sel_key_t] = set()
                    st.rerun()

            for idx, item in enumerate(titulares_pool):
                f = item["fuente"]
                n = item["noticia"]
                checked = idx in st.session_state[sel_key_t]
                badge_html = (
                    f'<span style="font-size:10px;font-weight:700;padding:1px 6px;'
                    f'border-radius:3px;background:{f["color"]}18;color:{f["color"]};'
                    f'border:1px solid {f["color"]}30">{f["nombre"]}</span>'
                )
                col_ck, col_txt = st.columns([1, 11])
                with col_ck:
                    nuevo = st.checkbox("", value=checked, key=f"nota_tend_ck_{tema_idx}_{idx}")
                    if nuevo and idx not in st.session_state[sel_key_t]:
                        st.session_state[sel_key_t].add(idx)
                    elif not nuevo and idx in st.session_state[sel_key_t]:
                        st.session_state[sel_key_t].discard(idx)
                with col_txt:
                    titulo_display = f"[{n['titulo']}]({n['url']})" if n.get("url") else n["titulo"]
                    st.markdown(f'{badge_html} {titulo_display}', unsafe_allow_html=True)

            titulares_seleccionados = [titulares_pool[i] for i in sorted(st.session_state.get(sel_key_t, set())) if i < len(titulares_pool)]
            if titulares_seleccionados:
                col_ok, col_basket = st.columns([3, 2])
                with col_ok:
                    st.success(f"✔ {len(titulares_seleccionados)} nota(s) seleccionada(s)")
                with col_basket:
                    if st.button("🧺 Agregar seleccionadas a canasta", key="nota_tend_a_canasta", use_container_width=True):
                        for item in titulares_seleccionados:
                            _canasta_agregar(item["noticia"]["titulo"], item["noticia"].get("url"), item["fuente"])
                        st.success(f"✔ {len(titulares_seleccionados)} nota(s) enviadas a la canasta")
                        st.rerun()

    # ── Modo 2: Búsqueda por palabra clave ───────────────────────────────────
    elif modo_tema == "🔍 Buscar en los medios cargados":
        col_bq1, col_bq2 = st.columns([3, 1])
        with col_bq1:
            busqueda = st.text_input(
                "Palabra o nombre a buscar",
                placeholder="Ej: Messi, Boca, lesión, Scaloni...",
                key="nota_busqueda",
            )
        with col_bq2:
            fuente_busq = st.selectbox(
                "Fuentes",
                ["Todas", "Solo nacionales", "Solo internacionales"],
                key="nota_busq_fuentes",
            )

        resultados_busq = []
        if busqueda.strip():
            q = busqueda.strip().lower()
            pool = TODAS_FUENTES
            if fuente_busq == "Solo nacionales":   pool = FUENTES_NAC
            elif fuente_busq == "Solo internacionales": pool = FUENTES_INT
            for f in pool:
                for n in resultados.get(f["id"], []):
                    if q in n["titulo"].lower():
                        resultados_busq.append({"fuente": f, "noticia": n})

        if resultados_busq:
            tema_elegido = busqueda.strip()
            st.caption(f"**{len(resultados_busq)}** notas encontradas — marcá las que querés usar:")

            # Inicializar selección en session state
            sel_key = f"nota_sel_{busqueda}"
            if sel_key not in st.session_state:
                st.session_state[sel_key] = set()

            col_sa, col_sb = st.columns([1, 5])
            with col_sa:
                if st.button("☑ Todas", key="nota_sel_all", use_container_width=True):
                    st.session_state[sel_key] = set(range(len(resultados_busq)))
                    st.rerun()
            with col_sb:
                if st.button("☐ Ninguna", key="nota_sel_none", use_container_width=True):
                    st.session_state[sel_key] = set()
                    st.rerun()

            for idx, item in enumerate(resultados_busq[:50]):
                f = item["fuente"]
                n = item["noticia"]
                checked = idx in st.session_state[sel_key]
                badge_html = (
                    f'<span style="font-size:10px;font-weight:700;padding:1px 6px;'
                    f'border-radius:3px;background:{f["color"]}18;color:{f["color"]};'
                    f'border:1px solid {f["color"]}30">{f["nombre"]}</span>'
                )
                col_ck, col_txt = st.columns([1, 11])
                with col_ck:
                    nuevo = st.checkbox("", value=checked, key=f"nota_ck_{busqueda}_{idx}")
                    if nuevo and idx not in st.session_state[sel_key]:
                        st.session_state[sel_key].add(idx)
                    elif not nuevo and idx in st.session_state[sel_key]:
                        st.session_state[sel_key].discard(idx)
                with col_txt:
                    titulo_display = f"[{n['titulo']}]({n['url']})" if n.get("url") else n["titulo"]
                    st.markdown(f'{badge_html} {titulo_display}', unsafe_allow_html=True)

            seleccionados_idx = st.session_state.get(sel_key, set())
            titulares_seleccionados = [resultados_busq[i] for i in sorted(seleccionados_idx) if i < len(resultados_busq)]
            if titulares_seleccionados:
                col_ok2, col_basket2 = st.columns([3, 2])
                with col_ok2:
                    st.success(f"✔ {len(titulares_seleccionados)} nota(s) seleccionada(s) para generar")
                with col_basket2:
                    if st.button("🧺 Agregar seleccionadas a canasta", key="nota_busq_a_canasta", use_container_width=True):
                        for item in titulares_seleccionados:
                            _canasta_agregar(item["noticia"]["titulo"], item["noticia"].get("url"), item["fuente"])
                        st.success(f"✔ {len(titulares_seleccionados)} nota(s) enviadas a la canasta")
                        st.rerun()
            else:
                st.info("Marcá al menos una nota para continuar.")

        elif busqueda.strip():
            st.warning(f'No se encontraron notas que mencionen "{busqueda}". Probá con otro término.')

    # ── Modo 3: Tema libre ────────────────────────────────────────────────────
    else:
        tema_elegido = st.text_input(
            "Escribí el tema de la nota",
            placeholder="Ej: Lesión de Lautaro Martínez antes de la Copa América",
            key="nota_tema_libre",
        )
        titulares_libres = st.text_area(
            "Pegá titulares de referencia (uno por línea, opcional)",
            placeholder="Lautaro Martínez se lesionó en el entrenamiento\nEl Toro en duda para el próximo partido...",
            height=100,
            key="nota_titulares_libres",
        )
        if titulares_libres.strip():
            fuente_generica = {"nombre": "Referencia", "color": "#666666", "id": "manual"}
            titulares_seleccionados = [
                {"fuente": fuente_generica, "noticia": {"titulo": t.strip(), "url": None}}
                for t in titulares_libres.strip().split("\n") if t.strip()
            ]

    st.divider()

    # ── PASO 2: Opciones + Contexto ───────────────────────────────────────────
    st.markdown("#### 2️⃣ Opciones de redacción")
    col_nota2a, col_nota2b = st.columns([1, 1])
    with col_nota2a:
        estilo_nota = st.selectbox(
            "Estilo",
            ["Informativa", "Analítica", "Urgente/Flash"],
            key="nota_estilo",
        )
        tipo_nota = st.selectbox(
            "Entregable",
            ["Nota completa", "Solo titulares alternativos", "Esqueleto + ángulos"],
            key="nota_tipo",
        )
    with col_nota2b:
        contexto_extra = st.text_area(
            "Contexto adicional (opcional)",
            placeholder=(
                "Agregá datos propios, información de fondo, declaraciones que tengas, "
                "el ángulo que querés tomar, o cualquier detalle extra que el redactor manejó y no está en las notas..."
            ),
            height=120,
            key="nota_contexto",
        )

    st.divider()

    # ── PASO 3: Generar ───────────────────────────────────────────────────────
    api_key_nota = api_key
    puede_generar = bool(titulares_seleccionados or (modo_tema == "✏️ Escribir tema libre" and tema_elegido.strip()))

    col_btn1, col_btn2, _ = st.columns([1, 1, 2])
    with col_btn1:
        generar = st.button(
            "✦ Generar con IA",
            type="primary",
            use_container_width=True,
            disabled=not puede_generar,
            key="btn_generar_nota",
        )
    with col_btn2:
        if st.button("🗑 Limpiar", use_container_width=True, key="btn_limpiar_nota"):
            st.session_state.nota_rapida = ""
            st.rerun()

    if generar:
        if not api_key_nota:
            st.error("Ingresá tu API key en el panel izquierdo para usar la IA.")
        elif not tema_elegido and not titulares_seleccionados:
            st.error("Seleccioná al menos una nota o escribí un tema.")
        else:
            if not tema_elegido and titulares_seleccionados:
                tema_elegido = titulares_seleccionados[0]["noticia"]["titulo"]

            urls_disponibles = [t for t in titulares_seleccionados if t["noticia"].get("url")]
            max_scrape = min(6, len(urls_disponibles))

            titulares_enriquecidos = titulares_seleccionados
            if urls_disponibles:
                with st.spinner(f"🔍 Leyendo el cuerpo de {max_scrape} nota(s) seleccionada(s)..."):
                    titulares_enriquecidos = scrape_cuerpos_notas(titulares_seleccionados, max_notas=max_scrape)
                ok_count = sum(1 for t in titulares_enriquecidos if t.get("ok"))
                if ok_count > 0:
                    st.success(f"✔ Cuerpo leído en {ok_count}/{max_scrape} notas")
                else:
                    st.warning("⚠️ No se pudo leer el cuerpo — modo esqueleto seguro")
            else:
                st.warning("⚠️ Las notas seleccionadas no tienen URL — modo esqueleto seguro")
                titulares_enriquecidos = [{**t, "cuerpo": "", "ok": False} for t in titulares_seleccionados]

            with st.spinner("✦ Redactando con Claude..."):
                try:
                    prompt = prompt_nota_rapida(tema_elegido, titulares_enriquecidos, estilo_nota, tipo_nota, contexto_extra.strip())
                    st.session_state.nota_rapida = call_claude(prompt, api_key_nota, 3500)
                    st.session_state.nota_rapida_titulares = titulares_enriquecidos
                    ok_final = sum(1 for t in titulares_enriquecidos if t.get("ok"))
                    st.session_state.nota_rapida_modo = "con cuerpo completo" if ok_final > 0 else "esqueleto seguro (sin cuerpo)"
                except Exception as e:
                    st.error(f"Error al llamar a Claude: {e}")

    # ── PASO 4: Resultado ─────────────────────────────────────────────────────
    if st.session_state.nota_rapida:
        modo_badge = st.session_state.get("nota_rapida_modo", "")
        raw = st.session_state.nota_rapida

        def _split_seccion(texto, encabezado):
            pattern = rf"════+\s*{re.escape(encabezado)}\s*════+\s*(.*?)(?=════|$)"
            m = re.search(pattern, texto, re.DOTALL | re.IGNORECASE)
            return m.group(1).strip() if m else ""

        seccion_nota        = _split_seccion(raw, "NOTA") or _split_seccion(raw, "ESQUELETO DE NOTA")
        seccion_verificacion = _split_seccion(raw, "TABLA DE VERIFICACIÓN") or _split_seccion(raw, "DATOS CONFIRMADOS.*")
        seccion_angulos     = _split_seccion(raw, "ÁNGULOS ALTERNATIVOS")
        sin_secciones = not (seccion_nota or seccion_verificacion)

        if "esqueleto" in modo_badge:
            st.warning("🦴 **Modo esqueleto seguro** — completá los espacios antes de publicar.")
        elif modo_badge:
            ok_n = sum(1 for t in st.session_state.nota_rapida_titulares if t.get("ok"))
            st.info(f"📰 Generado con el cuerpo real de **{ok_n}** nota(s). Revisá la Tabla de Verificación antes de publicar.")

        if sin_secciones:
            st.markdown("#### 📄 Resultado")
            nota_editada = st.text_area("", value=raw, height=560, label_visibility="collapsed", key="nota_textarea")
        else:
            tab_r1, tab_r2, tab_r3 = st.tabs(["📄 Nota / Esqueleto", "🔍 Tabla de Verificación", "💡 Ángulos Alternativos"])

            with tab_r1:
                st.caption("Editá el texto antes de copiar o descargar.")
                nota_editada = st.text_area("", value=seccion_nota, height=480, label_visibility="collapsed", key="nota_textarea")
                col_dl1, col_dl2 = st.columns(2)
                with col_dl1:
                    st.download_button("📥 .txt", nota_editada,
                        file_name=f"nota_{datetime.now().strftime('%Y%m%d_%H%M')}.txt", mime="text/plain", use_container_width=True)
                with col_dl2:
                    st.download_button("📥 .md", nota_editada,
                        file_name=f"nota_{datetime.now().strftime('%Y%m%d_%H%M')}.md", mime="text/markdown", use_container_width=True)

            with tab_r2:
                if seccion_verificacion:
                    for linea in seccion_verificacion.split("\n"):
                        linea = linea.strip()
                        if not linea: continue
                        if "✅" in linea:   color, bg, borde = "#166534", "#f0fdf4", "#86efac"
                        elif "⚠️" in linea: color, bg, borde = "#92400e", "#fffbeb", "#fcd34d"
                        elif "❌" in linea:  color, bg, borde = "#991b1b", "#fef2f2", "#fca5a5"
                        else:               color, bg, borde = "#374151", "#f9fafb", "#e5e7eb"
                        st.markdown(
                            f'<div style="padding:7px 12px;margin-bottom:5px;border-radius:6px;'
                            f'background:{bg};border-left:3px solid {borde};color:{color};font-size:14px">{linea}</div>',
                            unsafe_allow_html=True)
                    st.download_button("📥 Tabla .txt", seccion_verificacion,
                        file_name=f"verificacion_{datetime.now().strftime('%Y%m%d_%H%M')}.txt", mime="text/plain")
                else:
                    st.info("No se generó tabla de verificación.")

            with tab_r3:
                if seccion_angulos:
                    st.markdown(seccion_angulos)
                else:
                    st.info("No se detectaron ángulos alternativos.")

        st.divider()
        st.download_button("📥 Descargar respuesta completa", raw,
            file_name=f"nota_completa_{datetime.now().strftime('%Y%m%d_%H%M')}.txt", mime="text/plain")
    else:
        st.info("El borrador aparecerá acá una vez que lo generes.")


# ─── TAB TONO EDITORIAL ─────────────────────────────────────────────────────
with tab_sent:
    st.markdown("### 🌡️ Tono Editorial")
    st.caption("Analizá cómo distintos medios cubren un tema, jugador o club con IA.")

    col_s1, col_s2 = st.columns([3, 1])
    with col_s1:
        query_sent = st.text_input(
            "Buscá un tema, jugador, club o DT",
            placeholder='Ej: Messi, Boca, River, Milito, Selección...',
            key="sent_query_input",
        )
    with col_s2:
        fuente_sent = st.selectbox(
            "Fuentes",
            ["Todas", "Solo nacionales", "Solo internacionales"],
            key="sent_fuentes",
        )

    # Filtrar titulares que mencionan la query
    titulares_sent = []
    if query_sent.strip():
        q = query_sent.strip().lower()
        fuentes_pool = TODAS_FUENTES
        if fuente_sent == "Solo nacionales":
            fuentes_pool = FUENTES_NAC
        elif fuente_sent == "Solo internacionales":
            fuentes_pool = FUENTES_INT

        for f in fuentes_pool:
            for n in resultados.get(f["id"], []):
                if q in n["titulo"].lower():
                    titulares_sent.append({"fuente": f, "noticia": n})

        if titulares_sent:
            st.caption(f"Se encontraron **{len(titulares_sent)}** titulares que mencionan *{query_sent}*")
            with st.expander(f"Ver los {len(titulares_sent)} titulares encontrados", expanded=False):
                for item in titulares_sent:
                    f = item["fuente"]
                    n = item["noticia"]
                    badge = (f'<span style="font-size:10px;font-weight:700;padding:1px 6px;'
                             f'border-radius:3px;background:{f["color"]}18;color:{f["color"]};'
                             f'border:1px solid {f["color"]}30">{f["nombre"]}</span>')
                    st.markdown(f'{badge} {n["titulo"]}', unsafe_allow_html=True)
        elif query_sent.strip():
            st.warning(f'No se encontraron titulares que mencionen "{query_sent}". Probá con otro término.')

    st.divider()

    col_sb1, col_sb2 = st.columns([1, 3])
    with col_sb1:
        analizar_sent = st.button(
            "🌡️ Analizar tono",
            type="primary",
            use_container_width=True,
            disabled=not titulares_sent,
            key="btn_analizar_sent",
        )
    if analizar_sent:
        if not api_key:
            st.error("Ingresá tu API key en el panel izquierdo.")
        elif not titulares_sent:
            st.error("No hay titulares para analizar.")
        else:
            with st.spinner(f"Analizando tono de {len(titulares_sent)} titulares..."):
                try:
                    prompt = prompt_tono_editorial(query_sent, titulares_sent[:40])
                    raw_json = call_claude(prompt, api_key, 1200)
                    # Limpiar posibles backticks
                    clean = raw_json.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
                    resultado = json.loads(clean)
                    st.session_state.sentimiento_resultado = resultado
                    st.session_state.sentimiento_query = query_sent
                except json.JSONDecodeError:
                    st.error("Error al parsear la respuesta. Intentá de nuevo.")
                except Exception as e:
                    st.error(f"Error: {e}")

    # ── Mostrar resultado ────────────────────────────────────────────────────
    if st.session_state.sentimiento_resultado:
        res = st.session_state.sentimiento_resultado
        q_display = st.session_state.sentimiento_query

        st.markdown(f"#### Resultado para: *{q_display}*")

        # Resumen
        st.markdown(
            f'<div style="padding:12px 16px;border-radius:8px;background:#f0f9ff;'
            f'border-left:4px solid #0ea5e9;font-size:15px;margin-bottom:16px">'
            f'📝 {res.get("resumen","")}</div>',
            unsafe_allow_html=True,
        )

        # Distribución
        dist = res.get("distribucion", {})
        total_cl = sum(dist.values()) or 1
        TONO_CFG = {
            "positivo":  ("🟢", "#16a34a", "#f0fdf4"),
            "negativo":  ("🔴", "#dc2626", "#fef2f2"),
            "neutro":    ("⚪", "#6b7280", "#f9fafb"),
            "alarmista": ("🟡", "#d97706", "#fffbeb"),
            "expectante":("🔵", "#2563eb", "#eff6ff"),
        }
        st.markdown("##### Distribución de tono")
        cols_dist = st.columns(5)
        for i, (tono, count) in enumerate(dist.items()):
            emoji, color, bg = TONO_CFG.get(tono, ("⚫", "#374151", "#f9fafb"))
            pct = int(count / total_cl * 100)
            with cols_dist[i]:
                st.markdown(
                    f'<div style="text-align:center;padding:10px 6px;border-radius:8px;'
                    f'background:{bg};border:1px solid {color}30">'
                    f'<div style="font-size:22px">{emoji}</div>'
                    f'<div style="font-size:20px;font-weight:700;color:{color}">{count}</div>'
                    f'<div style="font-size:11px;color:#6b7280;text-transform:capitalize">{tono}</div>'
                    f'<div style="font-size:10px;color:#9ca3af">{pct}%</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        st.markdown("##### Tono por medio")
        por_medio = res.get("por_medio", [])
        for item in por_medio:
            tono = item.get("tono", "neutro")
            emoji, color, bg = TONO_CFG.get(tono, ("⚫", "#374151", "#f9fafb"))
            medio = item.get("medio", "")
            titular = item.get("titular", "")
            razon = item.get("razon", "")
            st.markdown(
                f'<div style="display:flex;gap:10px;align-items:flex-start;'
                f'padding:9px 12px;margin-bottom:5px;border-radius:7px;'
                f'background:{bg};border:1px solid {color}20">'
                f'<span style="font-size:18px;flex-shrink:0">{emoji}</span>'
                f'<div style="flex:1">'
                f'<span style="font-size:11px;font-weight:700;color:{color};text-transform:uppercase">'
                f'{medio} · {tono}</span><br>'
                f'<span style="font-size:13px;color:#1e293b">{titular}</span><br>'
                f'<span style="font-size:11px;color:#64748b;font-style:italic">{razon}</span>'
                f'</div></div>',
                unsafe_allow_html=True,
            )

        if res.get("patrones"):
            st.markdown("##### Patrones detectados")
            for p in res["patrones"]:
                st.markdown(f"- {p}")

        # Descarga
        st.divider()
        export = json.dumps(res, ensure_ascii=False, indent=2)
        st.download_button(
            "📥 Descargar análisis JSON",
            export,
            file_name=f"tono_{q_display}_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
            mime="application/json",
        )

# ─── TAB CANASTA ─────────────────────────────────────────────────────────────
with tab_canasta:
    st.markdown("### 🧺 Canasta de notas")
    st.caption(
        "Agregá notas desde cualquier tab usando el botón **🧺 Agregar a canasta** de cada card. "
        "Luego podés copiar todo el texto o enviarlo a la IA para generar una nota."
    )

    canasta = st.session_state.canasta

    if not canasta:
        st.info("La canasta está vacía. Navegá por las tabs y agregá notas con el botón 🧺.")
    else:
        st.success(f"**{len(canasta)} nota(s)** en la canasta")

        # ── Controles superiores ──────────────────────────────────────────────
        col_c1, col_c2, col_c3 = st.columns([1, 1, 2])
        with col_c1:
            if st.button("🗑 Vaciar canasta", use_container_width=True, key="canasta_vaciar"):
                st.session_state.canasta = []
                st.rerun()
        with col_c2:
            # Texto completo: título + URL + cuerpo scrapeado
            def _texto_item_canasta(item):
                fuente_n = item["fuente"]["nombre"]
                titulo_n = item["noticia"]["titulo"]
                url_n = item["noticia"].get("url") or "(sin URL)"
                cuerpo_n = item.get("cuerpo", "").strip()
                partes = [f"[{fuente_n}] {titulo_n}", f"URL: {url_n}"]
                if cuerpo_n:
                    partes.append(f"TEXTO:\n{cuerpo_n}")
                return "\n".join(partes)

            texto_export = "\n\n──────────────────────\n\n".join(
                _texto_item_canasta(item) for item in canasta
            )
            st.download_button(
                "📥 Exportar .txt",
                texto_export,
                file_name=f"canasta_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                mime="text/plain",
                use_container_width=True,
                key="canasta_exportar",
            )

        st.divider()

        # ── Lista de notas en canasta ─────────────────────────────────────────
        st.markdown("#### Notas acumuladas")
        for idx, item in enumerate(canasta):
            f = item["fuente"]
            n = item["noticia"]
            cuerpo_item = item.get("cuerpo", "").strip()
            badge_html = (
                f'<span style="font-size:10px;font-weight:700;padding:2px 8px;'
                f'border-radius:3px;background:{f["color"]}18;color:{f["color"]};'
                f'border:1px solid {f["color"]}30">{f["nombre"]}</span>'
            )
            col_rem, col_exp = st.columns([1, 11])
            with col_rem:
                if st.button("✕", key=f"canasta_rm_{idx}", help="Quitar de la canasta"):
                    st.session_state.canasta.pop(idx)
                    st.rerun()
            with col_exp:
                titulo_display = f"[{n['titulo']}]({n['url']})" if n.get("url") else n["titulo"]
                # Si hay cuerpo: mostrar en expander; si no, mostrar plano
                if cuerpo_item:
                    with st.expander(f"{badge_html} {titulo_display}", expanded=False):
                        st.markdown(
                            f'<div style="font-size:13px;color:#374151;line-height:1.6;'
                            f'padding:6px 0">{cuerpo_item[:600]}{"..." if len(cuerpo_item) > 600 else ""}</div>',
                            unsafe_allow_html=True,
                        )
                        if n.get("url"):
                            st.caption(f"🔗 [Ver nota completa]({n['url']})")
                        col_re_scr, _ = st.columns([2, 4])
                        with col_re_scr:
                            if st.button("🔄 Re-scrapear", key=f"canasta_rescrap_{idx}"):
                                nuevo_cuerpo = _extraer_cuerpo_nota(n["url"], max_chars=1800)
                                st.session_state.canasta[idx]["cuerpo"] = nuevo_cuerpo
                                st.rerun()
                else:
                    st.markdown(f'{badge_html} {titulo_display}', unsafe_allow_html=True)
                    if n.get("url"):
                        col_scr, _ = st.columns([2, 6])
                        with col_scr:
                            if st.button("📄 Leer cuerpo", key=f"canasta_leer_{idx}"):
                                with st.spinner("Leyendo nota..."):
                                    cuerpo_nuevo = _extraer_cuerpo_nota(n["url"], max_chars=1800)
                                st.session_state.canasta[idx]["cuerpo"] = cuerpo_nuevo
                                st.rerun()

        st.divider()

        # ── Texto acumulado para copiar ───────────────────────────────────────
        st.markdown("#### 📋 Texto acumulado (para copiar)")
        cant_con_cuerpo = sum(1 for item in canasta if item.get("cuerpo"))
        st.caption(f"{cant_con_cuerpo}/{len(canasta)} notas con cuerpo scrapeado")
        st.text_area(
            "Copiá este bloque",
            texto_export,
            height=300,
            key="canasta_textarea",
            label_visibility="collapsed",
        )

        st.divider()

        # ── Enviar canasta a la IA ─────────────────────────────────────────────
        st.markdown("#### ✦ Procesar con IA")
        st.caption("Usá las notas de la canasta como fuente para generar una nota con Claude.")

        col_ai1, col_ai2 = st.columns([3, 1])
        with col_ai1:
            tema_canasta = st.text_input(
                "Tema de la nota (podés dejarlo vacío para que lo infiera de las notas)",
                placeholder="Ej: Mercado de pases de Boca, lesión de Messi...",
                key="canasta_tema_ia",
            )
        with col_ai2:
            estilo_canasta = st.selectbox(
                "Estilo",
                ["Informativa", "Analítica", "Urgente/Flash"],
                key="canasta_estilo_ia",
            )

        tipo_canasta = st.selectbox(
            "Entregable",
            ["Nota completa", "Solo titulares alternativos", "Esqueleto + ángulos"],
            key="canasta_tipo_ia",
        )

        contexto_canasta = st.text_area(
            "Contexto adicional (opcional)",
            placeholder="Agregá datos propios, declaraciones o el ángulo que querés tomar...",
            height=80,
            key="canasta_contexto_ia",
        )

        col_gen_c1, col_gen_c2, _ = st.columns([1, 1, 2])
        with col_gen_c1:
            generar_canasta = st.button(
                "✦ Generar con IA",
                type="primary",
                use_container_width=True,
                key="canasta_btn_generar",
                disabled=not bool(canasta),
            )
        with col_gen_c2:
            if st.button("🗑 Limpiar borrador", use_container_width=True, key="canasta_btn_limpiar"):
                st.session_state["canasta_borrador"] = ""
                st.rerun()

        if generar_canasta:
            if not api_key:
                st.error("Ingresá tu API key en el panel izquierdo.")
            else:
                tema_final = tema_canasta.strip() or canasta[0]["noticia"]["titulo"]

                # Usar cuerpo ya scrapeado en la canasta; re-scrapear solo los que no tienen
                titulares_enr = []
                sin_cuerpo = []
                for item in canasta:
                    if item.get("cuerpo"):
                        # Ya tiene cuerpo scrapeado → formato compatible con prompt_nota_rapida
                        titulares_enr.append({
                            "fuente": item["fuente"],
                            "noticia": item["noticia"],
                            "cuerpo": item["cuerpo"],
                            "ok": True,
                        })
                    elif item["noticia"].get("url"):
                        sin_cuerpo.append(item)
                    else:
                        titulares_enr.append({
                            "fuente": item["fuente"],
                            "noticia": item["noticia"],
                            "cuerpo": "",
                            "ok": False,
                        })

                if sin_cuerpo:
                    max_extra = min(6, len(sin_cuerpo))
                    with st.spinner(f"🔍 Leyendo {max_extra} nota(s) sin cuerpo..."):
                        enriquecidos_extra = scrape_cuerpos_notas(sin_cuerpo, max_notas=max_extra)
                    # Actualizar canasta con los cuerpos recién scrapeados
                    for enr in enriquecidos_extra:
                        titulo_enr = enr["noticia"]["titulo"]
                        for i, ci in enumerate(st.session_state.canasta):
                            if ci["noticia"]["titulo"] == titulo_enr and enr.get("cuerpo"):
                                st.session_state.canasta[i]["cuerpo"] = enr["cuerpo"]
                                break
                        titulares_enr.append(enr)

                ok_cnt = sum(1 for t in titulares_enr if t.get("ok"))
                if ok_cnt > 0:
                    st.success(f"✔ {ok_cnt}/{len(titulares_enr)} notas con cuerpo para la IA")
                else:
                    st.warning("⚠️ No se pudo leer el cuerpo — modo esqueleto seguro")

                with st.spinner("✦ Generando nota con Claude..."):
                    try:
                        prompt = prompt_nota_rapida(
                            tema_final, titulares_enr,
                            estilo_canasta, tipo_canasta, contexto_canasta
                        )
                        raw = call_claude(prompt, api_key, 3000)
                        st.session_state["canasta_borrador"] = raw
                    except Exception as e:
                        st.error(f"Error: {e}")

        # ── Mostrar borrador de canasta ───────────────────────────────────────
        if st.session_state.get("canasta_borrador"):
            st.divider()
            st.markdown("#### Borrador generado")
            raw = st.session_state["canasta_borrador"]
            secciones = re.split(r"[═=]{10,}", raw)
            if len(secciones) > 1:
                for sec in secciones:
                    sec = sec.strip()
                    if not sec:
                        continue
                    if "\n" in sec and len(sec.split("\n")[0]) < 50:
                        titulo_sec = sec.split("\n")[0].strip()
                        cuerpo_sec = "\n".join(sec.split("\n")[1:]).strip()
                        st.markdown(f"##### {titulo_sec}")
                        if cuerpo_sec:
                            st.markdown(cuerpo_sec)
                    else:
                        st.markdown(sec)
            else:
                st.markdown(raw)

            st.divider()
            st.download_button(
                "📥 Descargar nota",
                raw,
                file_name=f"nota_canasta_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                mime="text/plain",
                key="canasta_download_nota",
            )



st.divider()
st.caption(
    f"Monitor Deportivo Pro v1.0 (Streamlit) · "
    f"Similitud semántica Jaccard (umbral: {SIMILITUD_UMBRAL}) · "
    f"{len(TODAS_FUENTES)} medios"
)
