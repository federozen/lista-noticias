"""monitor_core.py — Cerebro compartido del Monitor Deportivo.
Scraping, clustering, tendencias y agenda. Sin Streamlit: lo importan
app.py (interfaz) y vigia.py (corridas automáticas en GitHub Actions)."""
import re
import json
import random
import unicodedata
import requests
import anthropic
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from datetime import datetime

MAX_ITEMS = 50
SIMILITUD_UMBRAL = 0.22

# ─── FUENTES ──────────────────────────────────────────────────────────────────
FUENTES_NAC = [
    {"id": "ole",           "nombre": "Olé",           "url": "https://www.ole.com.ar/",                             "color": "#00a846", "es_ole": True},
    {"id": "espn",          "nombre": "ESPN AR",        "url": "https://www.espn.com.ar/",                            "color": "#cc0000", "es_espn": True},
    {"id": "tyc",           "nombre": "TyC Sports",     "url": "https://www.tycsports.com/",                          "color": "#1565c0"},
    {"id": "infobae",       "nombre": "Infobae",        "url": "https://www.infobae.com/deportes/",                   "color": "#b00020"},
    {"id": "lanacion",      "nombre": "La Nación",      "url": "https://www.lanacion.com.ar/deportes/",               "color": "#1565c0"},
    {"id": "tn",            "nombre": "TN Deportes",    "url": "https://tn.com.ar/deportes/",                         "color": "#cc2200"},
    {"id": "clarin",        "nombre": "Clarín Dep.",    "url": "https://www.clarin.com/deportes/",                    "color": "#c00000"},
    {"id": "elgrafico",     "nombre": "El Gráfico",     "url": "https://www.elgrafico.com.ar/",                       "color": "#b07800"},
    {"id": "dobleamarilla", "nombre": "Doble Amarilla", "url": "https://www.dobleamarilla.com.ar/",                   "color": "#a07800", "es_wp": True},
    {"id": "bolavip",       "nombre": "Bolavip",        "url": "https://bolavip.com/ar",                              "color": "#c04a00"},
    {"id": "lavoz",         "nombre": "La Voz",         "url": "https://www.lavoz.com.ar/deportes/",                  "color": "#8b0000"},
    {"id": "capital",       "nombre": "La Capital",     "url": "https://www.lacapital.com.ar/secciones/ovacion.html", "color": "#6a0d8a"},
    {"id": "na",            "nombre": "Noticias Arg.",  "url": "https://noticiasargentinas.com/search?category=65552a2ae38b1d41233b1aac", "color": "#c00060"},

    # ── Nuevas nacionales (vía Google News) ──
    {"id": "cuatro42",   "nombre": "442",              "url": "https://news.google.com/rss/search?q=site:442.perfil.com&hl=es-419&gl=AR&ceid=AR:es-419",                       "color": "#7b2d8b", "es_rss": True},
    {"id": "cielosports","nombre": "Cielosports",      "url": "https://news.google.com/rss/search?q=site:cielosports.com&hl=es-419&gl=AR&ceid=AR:es-419",                      "color": "#0090d0", "es_rss": True},
    {"id": "popular",    "nombre": "Diario Popular",   "url": "https://news.google.com/rss/search?q=site:diariopopular.com.ar%20futbol&hl=es-419&gl=AR&ceid=AR:es-419",        "color": "#d32f2f", "es_rss": True},
    {"id": "ambito",     "nombre": "Ámbito Deportes",  "url": "https://news.google.com/rss/search?q=site:ambito.com%20futbol&hl=es-419&gl=AR&ceid=AR:es-419",                  "color": "#00594e", "es_rss": True},
    {"id": "afa",        "nombre": "AFA (oficial)",    "url": "https://news.google.com/rss/search?q=site:afa.com.ar&hl=es-419&gl=AR&ceid=AR:es-419",                           "color": "#6cace4", "es_rss": True},
    {"id": "radar_ar",   "nombre": "Radar AR",         "url": "https://news.google.com/rss/search?q=%22f%C3%BAtbol%20argentino%22&hl=es-419&gl=AR&ceid=AR:es-419",             "color": "#444444", "es_rss": True},
]

FUENTES_INT = [
    {"id": "as",        "nombre": "AS",              "url": "https://as.com/futbol/",                          "color": "#b00020", "es_as": True},
    {"id": "marca",     "nombre": "Marca",            "url": "https://www.marca.com/",                          "color": "#267326"},
    {"id": "mundodep",  "nombre": "Mundo Deportivo",  "url": "https://www.mundodeportivo.com/",                 "color": "#1565c0"},
    {"id": "sport",     "nombre": "Sport",            "url": "https://www.sport.es/es/",                        "color": "#cc0020"},
    {"id": "globo",     "nombre": "Globoesporte",     "url": "https://ge.globo.com/",                           "color": "#007a2f"},
    {"id": "gazzetta",  "nombre": "Gazzetta Sport",   "url": "https://www.gazzetta.it/Calcio/",                 "color": "#e8000a"},
    {"id": "corriere",  "nombre": "Corriere Sport",   "url": "https://www.corrieredellosport.it/calcio",        "color": "#e06000"},
    {"id": "record",    "nombre": "Record PT",        "url": "https://www.record.pt/futebol/",                  "color": "#c8000a"},

    {"id": "bbc",       "nombre": "BBC Sport",        "url": "https://feeds.bbci.co.uk/sport/football/rss.xml",      "color": "#bb1919", "es_rss": True},
    {"id": "goal",      "nombre": "Goal",             "url": "https://www.goal.com/es",                         "color": "#00a878"},
    {"id": "espnint",   "nombre": "ESPN INT",         "url": "https://www.espn.com/soccer/",                    "color": "#d00000"},
    {"id": "cbssport",  "nombre": "CBS Sports",       "url": "https://www.cbssports.com/rss/headlines/soccer/", "color": "#004b87", "es_rss": True},
    {"id": "sportnews", "nombre": "Sporting News",    "url": "https://www.sportingnews.com/us/soccer",          "color": "#cc3300"},
    {"id": "lequipe",   "nombre": "L'Equipe",         "url": "https://www.lequipe.fr/Football/",                "color": "#f5c400"},
    {"id": "fifa",      "nombre": "FIFA (RSS)",       "url": "https://www.fifa.com/rss-feeds/index.html",       "color": "#326295"},

    # ── Nuevos: inglés + especialistas de mercado (todos por RSS) ──
    {"id": "guardian",   "nombre": "Guardian Fútbol",  "url": "https://www.theguardian.com/football/rss",        "color": "#052962", "es_rss": True},
    {"id": "skysports",  "nombre": "Sky Sports",       "url": "https://www.skysports.com/rss/12040",             "color": "#0072c9", "es_rss": True},
    {"id": "dimarzio",   "nombre": "Di Marzio",        "url": "https://www.gianlucadimarzio.com/it/rss",         "color": "#0a3d62", "es_rss": True},
    {"id": "calciomer",  "nombre": "Calciomercato",    "url": "https://www.calciomercato.com/rss",               "color": "#c8102e", "es_rss": True},

    # ── Vía Google News directo (para medios sin RSS propio confiable) ──
    {"id": "tntsports",  "nombre": "TNT Sports AR",    "url": "https://news.google.com/rss/search?q=site:tntsports.com.ar&hl=es-419&gl=AR&ceid=AR:es-419",  "color": "#e4002b", "es_rss": True},
    {"id": "relevo",     "nombre": "Relevo",           "url": "https://news.google.com/rss/search?q=site:relevo.com&hl=es-419&gl=AR&ceid=AR:es-419",         "color": "#ff3c00", "es_rss": True},
    {"id": "footmercato","nombre": "Foot Mercato",     "url": "https://news.google.com/rss/search?q=site:footmercato.net&hl=es-419&gl=AR&ceid=AR:es-419",    "color": "#0a5c36", "es_rss": True},
    {"id": "fabrizio",   "nombre": "Fabrizio Romano",  "url": "https://news.google.com/rss/search?q=%22Fabrizio%20Romano%22%20fichaje%20OR%20transfer&hl=es-419&gl=AR&ceid=AR:es-419", "color": "#1a1a2e", "es_rss": True},

    # ── Nuevas internacionales: medios + instituciones ──
    {"id": "kicker",     "nombre": "Kicker (DE)",      "url": "https://news.google.com/rss/search?q=site:kicker.de&hl=de&gl=DE&ceid=DE:de",                                    "color": "#c00d0d", "es_rss": True},
    {"id": "athletic",   "nombre": "The Athletic",     "url": "https://news.google.com/rss/search?q=site:nytimes.com/athletic%20football&hl=en-US&gl=US&ceid=US:en",           "color": "#00292f", "es_rss": True},
    {"id": "ovacion",    "nombre": "Ovación (UY)",     "url": "https://news.google.com/rss/search?q=site:elpais.com.uy%20futbol&hl=es-419&gl=AR&ceid=AR:es-419",               "color": "#75aadb", "es_rss": True},
    {"id": "conmebol",   "nombre": "CONMEBOL",         "url": "https://news.google.com/rss/search?q=site:conmebol.com&hl=es-419&gl=AR&ceid=AR:es-419",                         "color": "#002b5c", "es_rss": True},
    {"id": "uefa",       "nombre": "UEFA",             "url": "https://news.google.com/rss/search?q=site:uefa.com&hl=es-419&gl=AR&ceid=AR:es-419",                             "color": "#00004b", "es_rss": True},
]

TODAS_FUENTES = FUENTES_NAC + FUENTES_INT
FUENTES_NAC_IDS = {f["id"] for f in FUENTES_NAC}

# ─── STOPWORDS ────────────────────────────────────────────────────────────────
STOPWORDS = set([
    "de","la","el","en","y","a","los","del","se","las","por","un","para","con","una","su","al","lo",
    "como","más","pero","sus","le","ya","o","fue","este","ha","si","porque","esta","son","entre",
    "cuando","muy","sin","sobre","también","me","hasta","hay","donde","quien","desde","todo","nos",
    "durante","e","esto","mi","antes","yo","otro","otras","otra","él","bien","así","cada","ser",
    "tiene","había","era","no","es","que","the","a","an","and","or","but","in","on","at","to","for",
    "of","with","by","from","is","was","are","were","be","been","have","has","had","will","would",
    "could","should","may","might","can","da","do","em","para","com","por","que","um","uma",
    "os","as","ao","na","no","nas","nos","se","seu","sua","seus","suas","não","após","tras",
    "vs","vs.","after","over","into","than","then","their","they","this","that",
])

# ─── SIMILITUD SEMÁNTICA ──────────────────────────────────────────────────────
@lru_cache(maxsize=8192)
def normalizar_titulo(titulo: str) -> set:
    t = titulo.lower()
    t = unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return {w for w in t.split() if len(w) >= 3 and w not in STOPWORDS}

def similitud_jaccard(set_a: set, set_b: set) -> float:
    if not set_a or not set_b:
        return 0.0
    interseccion = len(set_a & set_b)
    union = len(set_a | set_b)
    return interseccion / union if union > 0 else 0.0

def es_exclusivo(titulo: str, propio_id: str, resultados: dict) -> bool:
    keys = normalizar_titulo(titulo)
    if len(keys) < 2:
        return False
    for f in TODAS_FUENTES:
        if f["id"] == propio_id:
            continue
        for n in resultados.get(f["id"], []):
            if similitud_jaccard(keys, normalizar_titulo(n["titulo"])) >= SIMILITUD_UMBRAL:
                return False
    return True

def analizar_ole_vs_competencia(resultados: dict) -> dict:
    # Pre-calcular keysets
    keysets = {}
    for f in TODAS_FUENTES:
        keysets[f["id"]] = [
            {"noticia": n, "keys": normalizar_titulo(n["titulo"])}
            for n in resultados.get(f["id"], [])
        ]

    ole_items = keysets.get("ole", [])
    competencia = [f for f in TODAS_FUENTES if not f.get("es_ole")]

    # 1. Exclusivos Olé
    exclusivos_ole = []
    for item in ole_items:
        encontrado = any(
            similitud_jaccard(item["keys"], ci["keys"]) >= SIMILITUD_UMBRAL
            for fid, citems in keysets.items()
            if fid != "ole"
            for ci in citems
        )
        if not encontrado:
            exclusivos_ole.append(item["noticia"])

    # 2. Faltantes en Olé
    faltantes_en_ole = []
    ya_agregados_keys = []
    for fuente in competencia:
        for item in keysets.get(fuente["id"], []):
            # ¿Lo tiene Olé?
            tiene_ole = any(
                similitud_jaccard(item["keys"], oi["keys"]) >= SIMILITUD_UMBRAL
                for oi in ole_items
            )
            if not tiene_ole:
                # Deduplicar entre faltantes
                es_dup = any(
                    similitud_jaccard(item["keys"], k) >= SIMILITUD_UMBRAL
                    for k in ya_agregados_keys
                )
                if not es_dup:
                    ya_agregados_keys.append(item["keys"])
                    faltantes_en_ole.append({
                        "titulo": item["noticia"]["titulo"],
                        "url": item["noticia"].get("url"),
                        "fuente_id": fuente["id"],
                        "fuente_nombre": fuente["nombre"],
                        "fuente_color": fuente["color"],
                    })

    # 3. Cubiertos por ambos
    cubiertos_por_ambos = []
    for item in ole_items:
        competidores = []
        for fid, citems in keysets.items():
            if fid == "ole":
                continue
            for ci in citems:
                sim = similitud_jaccard(item["keys"], ci["keys"])
                if sim >= SIMILITUD_UMBRAL:
                    competidores.append({"fuente_id": fid, "noticia": ci["noticia"], "sim": sim})
                    break
        if competidores:
            cubiertos_por_ambos.append({
                "noticia_ole": item["noticia"],
                "competencia": competidores[:4],
            })

    return {
        "exclusivos_ole": exclusivos_ole,
        "faltantes_en_ole": faltantes_en_ole,
        "cubiertos_por_ambos": cubiertos_por_ambos,
    }

def calcular_tendencias(resultados: dict) -> list:
    todas = []
    for f in TODAS_FUENTES:
        for n in resultados.get(f["id"], []):
            todas.append({"noticia": n, "fuente": f, "keys": normalizar_titulo(n["titulo"])})

    UMBRAL_CLUSTER = 0.20
    clusters = []
    asignado = [False] * len(todas)

    for i in range(len(todas)):
        if asignado[i]:
            continue
        cluster = {
            "titulo": todas[i]["noticia"]["titulo"],
            "url": todas[i]["noticia"].get("url"),
            "fuente_ids": {todas[i]["fuente"]["id"]},
            "noticias": [{"noticia": todas[i]["noticia"], "fuente": todas[i]["fuente"]}],
            "keys": todas[i]["keys"],
        }
        asignado[i] = True
        for j in range(i + 1, len(todas)):
            if asignado[j]:
                continue
            if similitud_jaccard(cluster["keys"], todas[j]["keys"]) >= UMBRAL_CLUSTER:
                cluster["fuente_ids"].add(todas[j]["fuente"]["id"])
                cluster["noticias"].append({"noticia": todas[j]["noticia"], "fuente": todas[j]["fuente"]})
                asignado[j] = True
        if len(cluster["fuente_ids"]) >= 2:
            clusters.append(cluster)

    clusters.sort(key=lambda c: (-len(c["fuente_ids"]), -len(c["noticias"])))
    return [
        {
            "titulo": c["titulo"],
            "url": c["url"],
            "cant_medios": len(c["fuente_ids"]),
            "fuente_ids": list(c["fuente_ids"]),
            "noticias": c["noticias"],
            "tiene_ole": "ole" in c["fuente_ids"],
            "nac": sum(1 for n in c["noticias"] if n["fuente"]["id"] in FUENTES_NAC_IDS),
            "intl": sum(1 for n in c["noticias"] if n["fuente"]["id"] not in FUENTES_NAC_IDS),
        }
        for c in clusters
    ]


# ─── FRAMEWORK EDITORIAL: LOS 10 ÁNGULOS ─────────────────────────────────────
# Condensado del framework del editor: competir por el significado, no por la
# información. Se inyecta en el parte matutino y en los briefs.
FRAMEWORK_ANGULOS = """Antes de proponer nada, identificá: qué pasó, qué cambió, a quién afecta, qué emoción genera, qué patrón revela y qué consecuencia deja. No digas qué pasó: decí por qué importa para el hincha. Competí por el significado antes que por la información.

Los 10 ángulos que más rinden (elegí los 2-3 que mejor apliquen a cada tema):
1. CAMBIO DE ESTATUS — ¿alguien dejó de ser lo que era? ("ya no es revelación: es campeón")
2. PATRÓN — ¿esto ya pasó antes? ("la historia que Boca vuelve a repetir")
3. CONSECUENCIA — ¿qué cambia desde mañana? ("lo que cambia para River después de la final")
4. HÉROE INESPERADO — ¿quién apareció donde nadie lo esperaba?
5. CONFLICTO — ¿quién piensa distinto? ("la grieta que dejó la final")
6. PARADOJA — ¿qué contradicción hay? ("jugó mejor y perdió")
7. IDENTIDAD — ¿qué dice esto sobre el club y su gente?
8. TENDENCIA — ¿qué se está viendo venir?
9. QUÉ SIGNIFICA — ¿qué representa realmente? ("mucho más que un campeonato")
10. EL DÍA DESPUÉS — ¿qué queda cuando termina el ruido? ("la pregunta que River debe responder ahora")"""

# Criterios personales del editor (se cargan desde la celda criterios_editor
# de la pestaña Config; vacío si no está configurado)
CRITERIOS_EDITOR = ""


def bloque_criterios() -> str:
    if CRITERIOS_EDITOR.strip():
        return f"\n\nCRITERIOS DEL EDITOR (respetalos siempre):\n{CRITERIOS_EDITOR.strip()}"
    return ""


PASES_KEYWORDS = [
    "fichaje", "fichajes", "ficha a", "pase de", "el pase", "refuerzo", "refuerzos",
    "transfer", "mercado de pases", "oferta por", "oferta de", "ofertas",
    "prestamo", "préstamo", "cedido", "cesion", "cesión", "clausula", "cláusula",
    "acuerdo por", "acuerdo con", "cerro la llegada", "cerró la llegada",
    "llegada de", "arribo de", "incorpora", "incorporacion", "incorporación",
    "negocia por", "negociacion por", "negociación por", "here we go",
    "se va de", "deja el club", "rescision", "rescisión", "renovacion", "renovación",
    "renueva", "firma con", "firmó con", "firmo con", "nuevo club", "vendido a",
    "venta de", "traspaso", "quiere contratar", "suena en", "en la mira de",
    "pretendido por", "interesa a", "va por", "ofrecieron",
]


def es_tema_de_pases(titulo: str) -> bool:
    t = titulo.lower()
    return any(k in t for k in PASES_KEYWORDS)


def solapamiento(a: set, b: set) -> float:
    """Coeficiente de solapamiento: intersección / el más chico de los dos.
    Mejor que Jaccard cuando un título es corto y creativo y el otro largo
    y descriptivo (el caso típico de Olé vs el resto)."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


# Palabras del léxico futbolero que no distinguen un tema de otro: dos títulos
# que solo comparten estas NO son el mismo tema.
GENERICOS_FUTBOL = {
    "acuerdo", "acordo", "pase", "pases", "fichaje", "fichajes", "refuerzo",
    "refuerzos", "vuelve", "vuelta", "regreso", "regresa", "llegada", "llega",
    "club", "equipo", "partido", "partidos", "gol", "goles", "final", "torneo",
    "futbol", "mercado", "oficial", "confirmado", "confirmada", "negociacion",
    "negociaciones", "jugador", "jugadores", "tecnico", "entrenador", "bombazo",
    "ultimo", "ultima", "primera", "primer", "hora", "horas", "video", "fotos",
}


def coincide_cobertura(a: set, b: set) -> bool:
    """¿Dos títulos hablan del mismo tema ya cubierto? Exige que compartan
    al menos 2 palabras DISTINTIVAS (nombres propios, no léxico genérico)."""
    if similitud_jaccard(a, b) >= 0.35:
        return True
    sa, sb = a - GENERICOS_FUTBOL, b - GENERICOS_FUTBOL
    return len(sa & sb) >= 2 and solapamiento(sa, sb) >= 0.5


def fetch_ultimas_ole() -> list:
    """Scrapea https://www.ole.com.ar/ultimas-noticias — el listado completo de
    lo publicado, incluidas las notas que nunca pisan la portada. Devuelve
    [{titulo, url}, ...]. Basado en el patrón data-noteid del sitio (estable),
    con la clase del listado como respaldo (parcial, sin el hash)."""
    try:
        resp = requests.get("https://www.ole.com.ar/ultimas-noticias",
                            headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        contenedores = soup.select("div[data-noteid]")
        if not contenedores:
            contenedores = soup.select("li[class*='listado']")
        out, vistos = [], set()
        for cont in contenedores:
            a = cont.find("a", href=True)
            if not a:
                continue
            href = a["href"]
            if href.startswith("/"):
                href = "https://www.ole.com.ar" + href
            if not href.startswith("http") or href in vistos:
                continue
            t_el = cont.find(["h1", "h2", "h3", "h4"])
            titulo = " ".join((t_el.get_text(strip=True) if t_el
                               else a.get_text(strip=True)).split())
            if len(titulo) < 16:
                # último recurso: armar el título desde el slug de la URL
                slug = href.rstrip("/").split("/")[-1].replace(".html", "")
                titulo = slug.replace("-", " ").capitalize()
                if len(titulo) < 16:
                    continue
            vistos.add(href)
            out.append({"titulo": titulo[:250], "url": href, "imagen": ""})
        return out[:MAX_ITEMS]
    except Exception:
        return []


def fetch_cobertura_ole_gnews() -> list:
    """Trae por Google News lo último publicado por Olé (más allá de su
    portada). Devuelve [{titulo, url}, ...]."""
    try:
        resp = requests.get(_gnews_url("ole.com.ar", "ole"), headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return [{"titulo": _limpiar_titulo_gnews(n["titulo"]), "url": n.get("url") or ""}
                for n in extraer_rss(resp.text)]
    except Exception:
        return []

# ─── AGENDA ACCIONABLE + MOMENTUM ─────────────────────────────────────────────
def calcular_momentum(tendencias: list, prev_tendencias: list) -> dict:
    """Compara cada cluster actual con el más parecido del snapshot anterior.
    Devuelve {indice_actual: {'delta': int, 'nuevo': bool}}.
    'delta' = variación en cantidad de medios; 'nuevo' si no matchea ninguno previo."""
    prev = prev_tendencias or []
    prev_keys = [normalizar_titulo(c["titulo"]) for c in prev]
    out = {}
    for i, c in enumerate(tendencias):
        k = normalizar_titulo(c["titulo"])
        best_j, best_sim = -1, 0.0
        for j, pk in enumerate(prev_keys):
            s = similitud_jaccard(k, pk)
            if s > best_sim:
                best_sim, best_j = s, j
        if best_j >= 0 and best_sim >= 0.30:
            out[i] = {"delta": c["cant_medios"] - prev[best_j]["cant_medios"], "nuevo": False}
        else:
            out[i] = {"delta": c["cant_medios"], "nuevo": True}
    return out

def construir_agenda(tendencias: list, ole_analisis: dict, prev_tendencias: list,
                     max_items: int = 14, cubiertos: list = None) -> list:
    """Convierte tendencias + análisis Olé en una lista priorizada de ACCIONES.
    Cada ítem trae un verbo (SUBIR YA / REDACTAR / SEGUIR / EMPUJAR), el motivo,
    el momentum y las noticias del cluster."""
    momentum = calcular_momentum(tendencias, prev_tendencias)
    items = []
    for i, c in enumerate(tendencias):
        mom = momentum.get(i, {"delta": 0, "nuevo": False})
        delta, nuevo = mom["delta"], mom["nuevo"]
        base = c["cant_medios"]
        tiene_ole = c.get("tiene_ole")
        score = base + max(delta, 0) * 2.5 + (3 if nuevo else 0) + (4 if not tiene_ole else 0)

        # ¿Es un hueco de verdad, o ya lo dimos en días anteriores?
        ya_dado = None
        if not tiene_ole and cubiertos:
            k_actual = normalizar_titulo(c["titulo"])
            for cub in cubiertos:
                if coincide_cobertura(k_actual, normalizar_titulo(cub["titulo"])):
                    ya_dado = cub
                    break
        if ya_dado is not None:
            cuando = ya_dado.get("fecha") or "estos días"
            accion = "RETOMAR"
            motivo = f"lo diste el {cuando} y hoy {base} medios lo mueven — ¿actualización o segunda vuelta?"
            score += 1
        elif not tiene_ole and base >= 3:
            accion, motivo = "SUBIR YA", f"{base} medios lo tienen y Olé no"
        elif not tiene_ole:
            accion, motivo = "REDACTAR", f"{base} medio(s) lo cubren y Olé no"
        elif nuevo or delta >= 2:
            accion = "SEGUIR"
            motivo = ("tema nuevo creciendo" if nuevo else f"creciendo (+{delta} medios)") + " — reforzá tu ángulo"
            score += 1
        else:
            continue  # ya cubierto por Olé y estable: no es una acción

        items.append({
            "accion": accion, "motivo": motivo, "titulo": c["titulo"], "url": c.get("url"),
            "cant_medios": base, "delta": delta, "nuevo": nuevo,
            "nac": c.get("nac", 0), "intl": c.get("intl", 0),
            "noticias": c.get("noticias", []), "score": score,
        })

    for n in (ole_analisis or {}).get("exclusivos_ole", [])[:5]:
        items.append({
            "accion": "EMPUJAR", "motivo": "exclusivo de Olé — promocionalo o hacé segunda vuelta",
            "titulo": n["titulo"], "url": n.get("url"),
            "cant_medios": 1, "delta": 0, "nuevo": False, "nac": 1, "intl": 0,
            "noticias": [], "score": 2.0,
        })

    items.sort(key=lambda x: -x["score"])
    return items[:max_items]

def prompt_parte_editorial(agenda: list) -> str:
    lineas = "\n".join(
        f"  {i+1}. [{it['accion']}] {it['titulo']} ({it['cant_medios']} medios; {it['motivo']})"
        for i, it in enumerate(agenda[:10])
    )
    return f"""Sos editor jefe de Olé. Esta es la agenda priorizada de forma automática.
Por cada ítem, en UNA sola línea, decime por qué le importa a un lector argentino y un ángulo concreto para la nota. Telegráfico, español rioplatense, sin relleno.

{lineas}"""

def prompt_brief_item(item: dict) -> str:
    fuentes_ctx = ""
    if item.get("noticias"):
        fuentes_ctx = "\nCómo lo titularon otros medios:\n" + "\n".join(
            f'  • [{n["fuente"]["nombre"]}] {n["noticia"]["titulo"]}'
            for n in item["noticias"][:6]
        )
    return f"""Sos editor jefe de Olé.

{FRAMEWORK_ANGULOS}{bloque_criterios()}

Para este tema, dame un mini-brief telegráfico en español rioplatense:
VALOR: por qué importa para el hincha (qué está en juego, no cuántos medios lo tienen).
ÁNGULOS: los 2 mejores ángulos del framework aplicados a ESTE tema — que ningún otro medio haya usado (mirá cómo titularon ellos).
TÍTULO: un título filoso para el mejor ángulo.

TEMA: {item["titulo"]}{fuentes_ctx}"""

AGENDA_COLORES = {
    "SUBIR YA": "#c0392b", "REDACTAR": "#d68910", "RETOMAR": "#7d3c98", "EXPLOTA": "#e67e22",
    "SEGUIR": "#2471a3", "EMPUJAR": "#1e8449",
}

def analizar_ole_vs_compecencia_safe(resultados: dict) -> dict:
    """Wrapper seguro para el análisis semántico."""
    try:
        return analizar_ole_vs_competencia(resultados)
    except Exception as e:
        return {"exclusivos_ole": [], "faltantes_en_ole": [], "cubiertos_por_ambos": []}

# ─── EXTRACCIÓN HTML ──────────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Referer": "https://www.google.com/",
}

# Patrones para detectar imágenes genéricas/logos (definidos aquí para uso en extraer_generico)
_GENERIC_IMAGE_PATTERNS_EARLY = [
    "logo", "brand", "favicon", "default", "placeholder",
    "og-default", "og_default", "share-default",
    "ole-logo", "ole_logo", "icon",
]

def _es_imagen_generica(img_url: str) -> bool:
    """Retorna True si la URL parece ser un logo o imagen genérica del sitio."""
    if not img_url:
        return True
    lower = img_url.lower()
    return any(pat in lower for pat in _GENERIC_IMAGE_PATTERNS_EARLY)

def _extraer_imagen_rss_item(item_raw: str) -> str:
    """Extrae la imagen de un item RSS crudo (string XML). Más robusto que BS4 con namespaces."""
    # 1. media:content url="..."
    m = re.search(r'<media:content[^>]+url=["\']([^"\']+)["\']', item_raw)
    if m:
        src = m.group(1)
        if src.startswith("http") and not src.endswith(".gif") and not _es_imagen_generica(src):
            return src

    # 2. media:thumbnail url="..."
    m = re.search(r'<media:thumbnail[^>]+url=["\']([^"\']+)["\']', item_raw)
    if m:
        src = m.group(1)
        if src.startswith("http") and not src.endswith(".gif") and not _es_imagen_generica(src):
            return src

    # 3. enclosure type="image/..." url="..."
    m = re.search(r'<enclosure[^>]+type=["\']image/[^"\']*["\'][^>]+url=["\']([^"\']+)["\']', item_raw)
    if not m:
        m = re.search(r'<enclosure[^>]+url=["\']([^"\']+)["\'][^>]+type=["\']image/[^"\']*["\']', item_raw)
    if m:
        src = m.group(1)
        if src.startswith("http") and not _es_imagen_generica(src):
            return src

    # 4. content:encoded o description — buscar primer <img src="...">
    for tag in ["content:encoded", "description"]:
        m = re.search(rf'<{tag}[^>]*>(.*?)</{tag}>', item_raw, re.DOTALL)
        if m:
            content = m.group(1)
            # Decodificar CDATA si aplica
            cdata = re.search(r'<!\[CDATA\[(.*?)\]\]>', content, re.DOTALL)
            if cdata:
                content = cdata.group(1)
            # Buscar src= en img tags
            img_m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', content)
            if img_m:
                src = img_m.group(1)
                if src.startswith("http") and not src.endswith(".gif") and not _es_imagen_generica(src):
                    return src
            # También wp:featuredmedia o similares con URL
            wp_m = re.search(r'https?://[^\s"\'<>]+(?:jpg|jpeg|png|webp)', content, re.IGNORECASE)
            if wp_m:
                src = wp_m.group(0)
                if not _es_imagen_generica(src):
                    return src

    return ""

MAX_ANTIGUEDAD_HORAS = 48  # notas de RSS/Google News más viejas que esto se descartan


def _fecha_item_rss(item) -> "datetime | None":
    """Lee la fecha de publicación de un item RSS (pubDate) o Atom (published/updated)."""
    for tag in ("pubDate", "published", "updated", "dc:date"):
        t = item.find(tag)
        if t and t.get_text(strip=True):
            texto = t.get_text(strip=True)
            try:
                from email.utils import parsedate_to_datetime
                return parsedate_to_datetime(texto)          # RFC-822 (RSS)
            except Exception:
                pass
            try:
                return datetime.fromisoformat(texto.replace("Z", "+00:00"))  # ISO (Atom)
            except Exception:
                pass
    return None


def extraer_rss(xml_text: str) -> list:
    noticias, vistos = [], set()
    try:
        soup = BeautifulSoup(xml_text, "xml")
        # Dividir el XML en items crudos para extraer imágenes con regex
        items_raw = re.findall(r'<item[^>]*>(.*?)</item>', xml_text, re.DOTALL | re.IGNORECASE)
        if not items_raw:
            items_raw = re.findall(r'<entry[^>]*>(.*?)</entry>', xml_text, re.DOTALL | re.IGNORECASE)

        for i, item in enumerate(soup.find_all(["item", "entry"])[:MAX_ITEMS]):
            titulo_tag = item.find("title")
            if not titulo_tag:
                continue
            # descartar notas viejas (los feeds de Google News traen de días atrás)
            fecha_pub = _fecha_item_rss(item)
            if fecha_pub is not None:
                try:
                    from datetime import timezone as _tz
                    ahora = datetime.now(_tz.utc)
                    fp = fecha_pub if fecha_pub.tzinfo else fecha_pub.replace(tzinfo=_tz.utc)
                    if (ahora - fp).total_seconds() > MAX_ANTIGUEDAD_HORAS * 3600:
                        continue
                except Exception:
                    pass
            titulo = titulo_tag.get_text(strip=True)
            titulo = re.sub(r"<[^>]+>", "", titulo)
            titulo = titulo.replace("&amp;","&").replace("&lt;","<").replace("&gt;",">").replace("&quot;",'"').replace("&#39;","'")
            if not titulo or len(titulo) < 15 or len(titulo) > 300 or titulo in vistos:
                continue
            vistos.add(titulo)
            url = None
            link_tag = item.find("link")
            if link_tag:
                url = link_tag.get_text(strip=True) or link_tag.get("href")
            if not url or not url.startswith("http"):
                guid = item.find("guid", isPermaLink="true")
                url = guid.get_text(strip=True) if guid else None
            # Extraer imagen del item crudo correspondiente
            imagen = ""
            if i < len(items_raw):
                imagen = _extraer_imagen_rss_item(items_raw[i])
            noticias.append({"titulo": titulo, "url": url, "imagen": imagen})
    except Exception:
        pass
    return noticias[:MAX_ITEMS]

def _extraer_ole(html: str, fuente: dict) -> list:
    """
    Scraper específico para Olé.
    - Prioriza links que terminan en .html (formato estándar de notas de Olé)
    - Escala el DOM hacia los padres para encontrar el link envolvente
    - Filtra autores/tags tanto en URLs como en imágenes (evita fotos de firma)
    """
    soup = BeautifulSoup(html, "html.parser")
    BASE = "https://www.ole.com.ar"
    noticias, vistos = [], set()

    _OLE_URL_SKIP = [
        "/autor/", "/autores/", "/firma/", "/columnistas/", "/tag/", "/tags/",
        "/categoria/", "/seccion/", "/author/", "tag=", "/tema/",
        "mailto:", "javascript:", "#",
    ]
    _FIRMA_CLASES = [
        "author", "autor", "firma", "byline", "avatar", "perfil", "profile",
        "journalist", "periodista", "columnist", "writer", "reporter",
        "signature", "bio", "headshot",
    ]

    def resolve_ole(href):
        if not href:
            return None
        if any(s in href for s in _OLE_URL_SKIP):
            return None
        if href.startswith("//"):
            return "https:" + href
        if href.startswith("/"):
            return BASE + href
        if href.startswith("http"):
            return href
        return None

    def _es_img_firma(tag):
        for parent in tag.parents:
            cls = " ".join(parent.get("class", [])).lower()
            pid = (parent.get("id") or "").lower()
            if any(p in cls or p in pid for p in _FIRMA_CLASES):
                return True
            if parent.name in ("article", "section", "main"):
                break
        return False

    def get_best_link(titulo_el, card):
        """Prioriza .html, escala DOM hasta 4 niveles hacia arriba."""
        candidatos = []

        # 1. Padre directo <a>
        p = titulo_el.find_parent("a")
        if p:
            u = resolve_ole(p.get("href", ""))
            if u:
                candidatos.append(u)

        # 2. <a> hijo del título
        ic = titulo_el.find("a")
        if ic:
            u = resolve_ole(ic.get("href", ""))
            if u and u not in candidatos:
                candidatos.append(u)

        # 3. Todos los <a> del card
        for a in card.find_all("a", href=True):
            u = resolve_ole(a.get("href", ""))
            if u and u not in candidatos:
                candidatos.append(u)

        # 4. Escalar DOM del card hacia arriba (4 niveles)
        parent = card.parent
        for _ in range(4):
            if not parent or parent.name in ("body", "html", "[document]"):
                break
            if parent.name == "a":
                u = resolve_ole(parent.get("href", ""))
                if u and u not in candidatos:
                    candidatos.append(u)
            for a in (parent.find_all("a", href=True, recursive=False) or []):
                u = resolve_ole(a.get("href", ""))
                if u and u not in candidatos:
                    candidatos.append(u)
            parent = parent.parent

        if not candidatos:
            return None
        # Priorizar .html
        html_links = [u for u in candidatos if u.endswith(".html")]
        return html_links[0] if html_links else candidatos[0]

    def get_mejor_imagen(card):
        """Imagen principal del card, ignorando fotos de firma/autor."""
        IMG_ATTRS = ["src", "data-src", "data-lazy-src", "data-original", "data-url"]
        candidatos = []

        for tag in card.find_all("img"):
            if _es_img_firma(tag):
                continue
            best_src = ""
            srcset = tag.get("srcset", "") or tag.get("data-srcset", "")
            if srcset:
                parts = [s.strip().split(" ") for s in srcset.split(",") if s.strip()]
                sized = []
                for p in parts:
                    url_s = p[0]
                    try:
                        w = int(p[1].rstrip("w")) if len(p) > 1 and p[1].endswith("w") else 0
                    except ValueError:
                        w = 0
                    sized.append((w, url_s))
                sized.sort(key=lambda x: x[0], reverse=True)
                for _, url_s in sized:
                    if url_s.startswith("http") and not _es_imagen_generica(url_s) and "1x1" not in url_s:
                        best_src = url_s
                        break
            if not best_src:
                for attr in IMG_ATTRS:
                    src = tag.get(attr, "")
                    if (src and src.startswith("http")
                            and not src.endswith(".gif")
                            and not _es_imagen_generica(src)
                            and "1x1" not in src
                            and "pixel" not in src.lower()):
                        best_src = src
                        break
            if best_src:
                score = 0
                cls = " ".join(tag.get("class", [])).lower()
                for good in ["featured", "hero", "portada", "principal", "cover",
                             "thumb", "thumbnail", "wp-post-image", "article-image"]:
                    if good in cls:
                        score += 300
                m = re.search(r'[-/](\d{3,4})x(\d{3,4})[-/.]', best_src)
                if m:
                    score += int(m.group(1)) + int(m.group(2))
                if tag.get("srcset") or tag.get("data-srcset"):
                    score += 100
                candidatos.append((score, best_src))

        if not candidatos:
            return ""
        candidatos.sort(key=lambda x: x[0], reverse=True)
        return candidatos[0][1]

    CARD_SELS_OLE = [
        "article", "[class*=card]", "[class*=nota]", "[class*=story]",
        "[class*=article]", "[class*=item]",
    ]
    TITLE_SELS_OLE = ["h1", "h2", "h3", "h4", "[class*=title]", "[class*=titular]", "[class*=headline]"]

    for sel in CARD_SELS_OLE:
        for card in soup.select(sel)[:MAX_ITEMS * 2]:
            if len(noticias) >= MAX_ITEMS:
                break
            titulo_el = None
            for tsel in TITLE_SELS_OLE:
                titulo_el = card.select_one(tsel)
                if titulo_el:
                    break
            if not titulo_el:
                continue
            titulo = titulo_el.get_text(strip=True)
            if len(titulo) < 20 or len(titulo) > 300 or titulo in vistos:
                continue
            vistos.add(titulo)
            url = get_best_link(titulo_el, card)
            img = get_mejor_imagen(card)
            noticias.append({"titulo": titulo, "url": url, "imagen": img})

    # Fallback: h2/h3 con links directos
    if len(noticias) < 8:
        for el in soup.select("h2 a[href], h3 a[href]"):
            if len(noticias) >= MAX_ITEMS:
                break
            titulo = el.get_text(strip=True)
            if len(titulo) < 20 or len(titulo) > 300 or titulo in vistos:
                continue
            url = resolve_ole(el.get("href", ""))
            if url:
                vistos.add(titulo)
                noticias.append({"titulo": titulo, "url": url, "imagen": ""})

    return noticias[:MAX_ITEMS]

def _extraer_as(html: str, fuente: dict) -> list:
    """Scraper específico para AS (as.com/futbol/). Filtra links de autores/tags."""
    soup = BeautifulSoup(html, "html.parser")
    BASE = "https://as.com"
    noticias, vistos = [], set()

    _AS_URL_SKIP = ["/autor/", "/autores/", "/tag/", "/tags/", "/tema/",
                    "/categoria/", "mailto:", "javascript", "/redaccion/"]

    def resolve_as(href):
        if not href:
            return None
        if any(s in href for s in _AS_URL_SKIP):
            return None
        if href.startswith("javascript") or href == "#":
            return None
        if href.startswith("//"):
            return "https:" + href
        if href.startswith("/"):
            return BASE + href
        if href.startswith("http"):
            return href
        return None

    def get_nota_url_as(titulo_el, card):
        parent_a = titulo_el.find_parent("a")
        if parent_a:
            u = resolve_as(parent_a.get("href", ""))
            if u:
                return u
        inner_a = titulo_el.find("a")
        if inner_a:
            u = resolve_as(inner_a.get("href", ""))
            if u:
                return u
        for a in card.find_all("a", href=True):
            u = resolve_as(a.get("href", ""))
            if u:
                return u
        return None

    CARD_SELS_AS = [
        "article", "[class*=card]", "[class*=article]",
        "[class*=noticia]", "[class*=story]", "[class*=item]",
        "li[class*=list]",
    ]
    TITLE_SELS_AS = ["h1", "h2", "h3", "[class*=title]", "[class*=headline]", "[class*=titular]"]

    for sel in CARD_SELS_AS:
        for card in soup.select(sel)[:MAX_ITEMS * 2]:
            if len(noticias) >= MAX_ITEMS:
                break
            titulo_el = None
            for tsel in TITLE_SELS_AS:
                titulo_el = card.select_one(tsel)
                if titulo_el:
                    break
            if not titulo_el:
                continue
            titulo = titulo_el.get_text(strip=True)
            if len(titulo) < 20 or len(titulo) > 300 or titulo in vistos:
                continue
            vistos.add(titulo)
            url = get_nota_url_as(titulo_el, card)
            img = ""
            for tag in card.find_all("img"):
                src = (tag.get("src") or tag.get("data-src") or
                       tag.get("data-lazy-src") or tag.get("data-original") or "")
                if src and src.startswith("http") and not _es_imagen_generica(src):
                    img = src
                    break
            noticias.append({"titulo": titulo, "url": url, "imagen": img})

    if len(noticias) < 8:
        for el in soup.select("h2 a[href], h3 a[href]"):
            if len(noticias) >= MAX_ITEMS:
                break
            titulo = el.get_text(strip=True)
            if len(titulo) < 20 or len(titulo) > 300 or titulo in vistos:
                continue
            vistos.add(titulo)
            url = resolve_as(el.get("href", ""))
            if url:
                noticias.append({"titulo": titulo, "url": url, "imagen": ""})

    return noticias[:MAX_ITEMS]


def _extraer_espn(html: str, fuente: dict) -> list:
    """Scraper dedicado para ESPN AR (SPA React). El HTML estático trae JSON-LD
    con las URLs reales; las notas siguen el patrón /_/id/NNNNNN/."""
    noticias, seen = [], set()
    soup = BeautifulSoup(html, "html.parser")
    BASE = "https://www.espn.com.ar"
    ESPN_SKIP = ["/autor/", "/author/", "/tag/", "/tags/", "/equipo/", "/liga/",
                 "/atletismo/", "javascript:", "mailto:", "#", "/video/"]

    def resolve_espn(href):
        if not href:
            return None
        if any(s in href for s in ESPN_SKIP):
            return None
        if href.startswith("//"):
            return "https:" + href
        if href.startswith("/"):
            return BASE + href
        if href.startswith("http"):
            return href
        return None

    def es_url_nota(url):
        if not url:
            return False
        return "/_/id/" in url or "/nota/" in url or "/historia/" in url or "/story/" in url

    urls_json = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")

            def _walk(obj):
                if isinstance(obj, dict):
                    if obj.get("@type") in ("NewsArticle", "Article", "WebPage"):
                        u = obj.get("url") or obj.get("mainEntityOfPage", {}).get("@id", "")
                        if u and es_url_nota(u) and u not in urls_json:
                            urls_json.append(u)
                    if obj.get("@type") == "ItemList":
                        for item in obj.get("itemListElement", []):
                            u = item.get("url") or item.get("item", {}).get("url", "")
                            if u and es_url_nota(u) and u not in urls_json:
                                urls_json.append(u)
                    for v in obj.values():
                        _walk(v)
                elif isinstance(obj, list):
                    for v in obj:
                        _walk(v)
            _walk(data)
        except Exception:
            pass

    urls_html = []
    for a in soup.find_all("a", href=True):
        url = resolve_espn(a.get("href", ""))
        if url and es_url_nota(url) and url not in urls_html:
            urls_html.append(url)

    todas_urls = list(dict.fromkeys(urls_json + urls_html))

    url_to_titulo = {}
    TITLE_SELS_ESPN = ["h1", "h2", "h3", "h4",
                       "[class*=title]", "[class*=Title]",
                       "[class*=headline]", "[class*=Headline]",
                       "[class*=contentItem__title]"]
    for a in soup.find_all("a", href=True):
        url = resolve_espn(a.get("href", ""))
        if not url or not es_url_nota(url):
            continue
        titulo = None
        for sel in TITLE_SELS_ESPN:
            t_el = a.select_one(sel)
            if t_el:
                titulo = t_el.get_text(strip=True)
                break
        if not titulo:
            titulo = a.get_text(strip=True)
        titulo = " ".join(titulo.split())
        if 20 <= len(titulo) <= 300 and url not in url_to_titulo:
            url_to_titulo[url] = titulo

    for url in todas_urls:
        if len(noticias) >= MAX_ITEMS:
            break
        titulo = url_to_titulo.get(url)
        if not titulo:
            slug = url.rstrip("/").split("/")[-1]
            slug = re.sub(r"^\d+-", "", slug)
            titulo = slug.replace("-", " ").title()
            if len(titulo) < 15:
                continue
        if titulo in seen:
            continue
        seen.add(titulo)
        noticias.append({"titulo": titulo, "url": url, "imagen": ""})

    return noticias[:MAX_ITEMS]


def extraer_generico(html: str, fuente: dict) -> list:
    # Scrapers específicos
    if fuente.get("es_ole"):
        return _extraer_ole(html, fuente)
    if fuente.get("es_as"):
        return _extraer_as(html, fuente)
    if fuente.get("es_espn"):
        return _extraer_espn(html, fuente)

    if fuente.get("es_rss"):
        return extraer_rss(html)

    # Doble Amarilla es WordPress — usar su feed RSS que incluye imágenes
    if fuente.get("es_wp"):
        feed_url = fuente["url"].rstrip("/") + "/feed/"
        try:
            resp = requests.get(feed_url, headers=_FETCH_HEADERS, timeout=15)
            if resp.status_code == 200 and "<rss" in resp.text[:500]:
                return extraer_rss(resp.text)
        except Exception:
            pass  # Fallback al scraping normal si el feed falla

    soup = BeautifulSoup(html, "html.parser")
    base_url = re.match(r"https?://[^/]+", fuente["url"])
    base = base_url.group(0) if base_url else ""
    noticias, vistos = [], set()

    CARD_SELS = ["article", "[class*=card]", "[class*=story]", "[class*=nota]", "[class*=item]", "[class*=news]"]
    TITLE_SELS = ["h1","h2","h3","h4","[class*=title]","[class*=headline]","[class*=titular]"]

    def resolve_url(href):
        if not href or href.startswith("javascript") or href == "#":
            return None
        if href.startswith("//"):
            return "https:" + href
        if href.startswith("/"):
            return base + href
        if href.startswith("http"):
            return href
        return None

    def get_titulo(el):
        for sel in TITLE_SELS:
            t = el.select_one(sel)
            if t:
                return t.get_text(strip=True)
        return None

    def get_url(el, titulo_el):
        link = titulo_el.find_parent("a") or titulo_el.find("a") or el.find("a")
        if link:
            return resolve_url(link.get("href", ""))
        return None

    # Patrones de clases/padres que indican imagen de firma/autor (NO foto de nota)
    AUTOR_PATTERNS = [
        "author", "autor", "firma", "byline", "avatar", "perfil", "profile",
        "journalist", "periodista", "columnist", "writer", "reporter",
        "signature", "bio", "headshot",
    ]

    def _es_img_autor(tag):
        """Retorna True si la imagen está dentro de un contenedor de firma/autor."""
        for parent in tag.parents:
            cls = " ".join(parent.get("class", [])).lower()
            pid = (parent.get("id") or "").lower()
            combined = cls + " " + pid
            if any(p in combined for p in AUTOR_PATTERNS):
                return True
            # No escalar más allá del card
            if parent == tag.parent.parent.parent:
                break
        return False

    def _img_score(tag, src):
        """Puntúa una imagen: más grande y más prominente = mayor score."""
        score = 0
        # Dimensiones explícitas
        try:
            w = int(tag.get("width") or tag.get("data-width") or 0)
            h = int(tag.get("height") or tag.get("data-height") or 0)
            score += w + h
        except (ValueError, TypeError):
            pass
        # Clases que sugieren imagen principal (incluyendo WordPress)
        cls = " ".join(tag.get("class", [])).lower()
        for good in [
            "featured", "hero", "portada", "principal", "cover",
            "thumb", "thumbnail", "featured-image", "post-image",
            "article-image", "nota-img", "card-img",
            # WordPress específico
            "wp-post-image", "attachment-", "size-large", "size-full",
            "size-medium_large", "wp-block-image", "entry-thumb",
        ]:
            if good in cls:
                score += 500
        # Clases de autor = penalizar mucho
        for bad in AUTOR_PATTERNS:
            if bad in cls:
                score -= 9999
        # Si es autor por contexto = penalizar
        if _es_img_autor(tag):
            score -= 9999
        # srcset presente = suele ser imagen de contenido
        if tag.get("srcset") or tag.get("data-srcset"):
            score += 200
        # Dimensiones implícitas de URL (Olé usa /fit-in/NxN/, WP usa -NNNxNNN.)
        m = re.search(r'[-/](\d{3,4})x(\d{3,4})[-/.]', src)
        if m:
            score += int(m.group(1)) + int(m.group(2))
        # alt descriptivo (no vacío, no "logo") también suma
        alt = (tag.get("alt") or "").lower()
        if alt and len(alt) > 5 and "logo" not in alt:
            score += 50
        return score

    def get_imagen(el):
        """Extrae la imagen principal de una card, ignorando fotos de autores."""
        IMG_ATTRS = ["src", "data-src", "data-lazy-src", "data-original", "data-url", "data-image"]
        candidatos = []  # (score, src)

        for tag in el.find_all("img"):
            best_src = ""
            # srcset primero — generalmente tiene la versión más grande
            srcset = tag.get("srcset", "") or tag.get("data-srcset", "")
            if srcset:
                parts = [s.strip().split(" ") for s in srcset.split(",") if s.strip()]
                # Ordenar por ancho declarado (ej "800w") descendente
                sized = []
                for p in parts:
                    url = p[0]
                    try:
                        w = int(p[1].rstrip("w")) if len(p) > 1 and p[1].endswith("w") else 0
                    except ValueError:
                        w = 0
                    sized.append((w, url))
                sized.sort(key=lambda x: x[0], reverse=True)
                for _, url in sized:
                    if url.startswith("http") and not _es_imagen_generica(url) and "1x1" not in url:
                        best_src = url
                        break

            if not best_src:
                for attr in IMG_ATTRS:
                    src = tag.get(attr, "")
                    if (src and src.startswith("http")
                            and not src.endswith(".gif")
                            and not _es_imagen_generica(src)
                            and "1x1" not in src
                            and "pixel" not in src.lower()):
                        best_src = src
                        break

            if best_src:
                score = _img_score(tag, best_src)
                candidatos.append((score, best_src))

        # background-image en estilos
        for tag in el.find_all(style=True):
            m = re.search(r'background(?:-image)?:\s*url\(["\']?(https?://[^"\')\s]+)["\']?\)', tag["style"])
            if m:
                src = m.group(1)
                if not _es_imagen_generica(src) and "1x1" not in src:
                    cls = " ".join(tag.get("class", [])).lower()
                    score = 100
                    for bad in AUTOR_PATTERNS:
                        if bad in cls:
                            score = -9999
                    candidatos.append((score, src))

        if not candidatos:
            return ""
        # Tomar la de mayor score, descartar si score muy negativo (= autor)
        candidatos.sort(key=lambda x: x[0], reverse=True)
        best_score, best_src = candidatos[0]
        return best_src if best_score > -100 else ""

    # Intentar cards
    for sel in CARD_SELS:
        for card in soup.select(sel)[:MAX_ITEMS * 2]:
            if len(noticias) >= MAX_ITEMS:
                break
            titulo_el = None
            for tsel in TITLE_SELS:
                titulo_el = card.select_one(tsel)
                if titulo_el:
                    break
            if not titulo_el:
                continue
            titulo = titulo_el.get_text(strip=True)
            if len(titulo) < 20 or len(titulo) > 300 or titulo in vistos:
                continue
            vistos.add(titulo)
            url = get_url(card, titulo_el)
            imagen = get_imagen(card)
            noticias.append({"titulo": titulo, "url": url, "imagen": imagen})

    # Fallback: sólo headings
    if len(noticias) < 8:
        for sel in ["h2","h3"]:
            for el in soup.select(sel)[:MAX_ITEMS * 2]:
                if len(noticias) >= MAX_ITEMS:
                    break
                titulo = el.get_text(strip=True)
                if len(titulo) < 20 or len(titulo) > 300 or titulo in vistos:
                    continue
                vistos.add(titulo)
                link = el.find_parent("a") or el.find("a")
                url = resolve_url(link.get("href", "")) if link else None
                noticias.append({"titulo": titulo, "url": url})

    return noticias[:MAX_ITEMS]

# ─── FALLBACK UNIVERSAL: GOOGLE NEWS RSS ─────────────────────────────────────
# Si el scraping directo de una fuente falla o trae 0 notas, se le pide a
# Google News el feed de ese dominio (site:medio.com). Google ya indexa todos
# los medios, así que esto autocura fuentes rotas (SPAs, bloqueos, rediseños).

# Edición de Google News según el idioma de cada medio: pedirle un sitio
# italiano a la edición argentina puede devolver 0 resultados.
GNEWS_LOC = {
    # italiano
    "dimarzio": ("it", "IT", "IT:it"), "calciomer": ("it", "IT", "IT:it"),
    "gazzetta": ("it", "IT", "IT:it"), "corriere": ("it", "IT", "IT:it"),
    # inglés
    "guardian": ("en-US", "US", "US:en"), "skysports": ("en-US", "US", "US:en"),
    "bbc": ("en-US", "US", "US:en"), "cbssport": ("en-US", "US", "US:en"),
    "goal": ("en-US", "US", "US:en"), "espnint": ("en-US", "US", "US:en"),
    "sportnews": ("en-US", "US", "US:en"), "fifa": ("en-US", "US", "US:en"),
    # francés
    "lequipe": ("fr", "FR", "FR:fr"), "footmercato": ("fr", "FR", "FR:fr"),
    # portugués
    "globo": ("pt-BR", "BR", "BR:pt-419"),
    "record": ("pt-PT", "PT", "PT:pt-150"),
    # español de España
    "marca": ("es", "ES", "ES:es"), "as": ("es", "ES", "ES:es"),
    "sport": ("es", "ES", "ES:es"), "mundodep": ("es", "ES", "ES:es"),
    "relevo": ("es", "ES", "ES:es"),
}


def _gnews_url(dominio: str, fuente_id: str = "") -> str:
    hl, gl, ceid = GNEWS_LOC.get(fuente_id, ("es-419", "AR", "AR:es-419"))
    return (f"https://news.google.com/rss/search?q=site:{dominio}"
            f"&hl={hl}&gl={gl}&ceid={ceid}")


def _limpiar_titulo_gnews(titulo: str) -> str:
    """Google News agrega ' - Nombre del Medio' al final de cada título."""
    if " - " in titulo:
        base = titulo.rsplit(" - ", 1)[0].strip()
        if len(base) >= 15:
            return base
    return titulo


def _dominio_de(fuente: dict) -> str:
    if fuente.get("gnews"):
        return fuente["gnews"]
    url = fuente.get("url", "")
    m = re.search(r"https?://(?:www\.)?([^/]+)", url)
    return m.group(1) if m else ""


def _fallback_gnews(fuente: dict, motivo_original: str) -> dict:
    dominio = _dominio_de(fuente)
    if not dominio or "news.google.com" in fuente.get("url", ""):
        return {"id": fuente["id"], "noticias": [], "error": motivo_original}
    try:
        resp = requests.get(_gnews_url(dominio, fuente.get("id", "")), headers=HEADERS, timeout=15)
        resp.raise_for_status()
        noticias = extraer_rss(resp.text)
        for n in noticias:
            n["titulo"] = _limpiar_titulo_gnews(n["titulo"])
        if noticias:
            return {"id": fuente["id"], "noticias": noticias[:MAX_ITEMS],
                    "error": None, "via": "gnews"}
    except Exception:
        pass
    return {"id": fuente["id"], "noticias": [], "error": motivo_original}


def fetch_fuente(fuente: dict) -> dict:
    try:
        resp = requests.get(fuente["url"], headers=HEADERS, timeout=15)
        resp.raise_for_status()
        # Detectar encoding real desde el header o el HTML antes de usar resp.text
        # requests a veces asume ISO-8859-1 para text/html sin charset declarado
        content_type = resp.headers.get("content-type", "").lower()
        if "charset=" in content_type:
            # Respetar el charset del servidor
            encoding = content_type.split("charset=")[-1].split(";")[0].strip()
        else:
            # Intentar detectar desde el meta charset del HTML
            raw = resp.content
            sniff = raw[:4096].decode("ascii", errors="ignore").lower()
            if 'charset="utf-8"' in sniff or "charset=utf-8" in sniff:
                encoding = "utf-8"
            elif 'charset="iso-8859-1"' in sniff or 'charset=iso-8859-1' in sniff:
                encoding = "iso-8859-1"
            elif 'charset="windows-1252"' in sniff or 'charset=windows-1252' in sniff:
                encoding = "windows-1252"
            else:
                # Si apparent_encoding detecta latin, usarlo; si no, utf-8
                detected = (resp.apparent_encoding or "utf-8").lower()
                # Confiar en la detección (incluye windows-1252/latin para páginas
                # ES/PT/IT/FR sin charset declarado); sólo caer a utf-8 si es ascii/vacío.
                encoding = "utf-8" if detected in ("ascii", "") else detected
        resp.encoding = encoding
        noticias = extraer_generico(resp.text, fuente)
        if noticias:
            return {"id": fuente["id"], "noticias": noticias, "error": None}
        return _fallback_gnews(fuente, "scraping directo: 0 notas")
    except Exception as e:
        return _fallback_gnews(fuente, str(e))

# ─── IA — CLAUDE ──────────────────────────────────────────────────────────────
def call_claude(prompt: str, api_key: str, max_tokens: int = 2000) -> str:
    if not api_key:
        raise RuntimeError("Falta la API key de Anthropic.")
    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        raise RuntimeError(f"Error al llamar a Claude: {e}") from e
    # Concatenar todos los bloques de texto (no asumir que content[0] es texto)
    partes = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
    return "\n".join(partes).strip()

PERLITA_KEYWORDS = [
    "insolito", "insólito", "viral", "furor", "locura", "increible", "increíble",
    "inedito", "inédito", "record", "récord", "historico", "histórico", "blooper",
    "papelon", "papelón", "escandalo", "escándalo", "polemica", "polémica",
    "sorpresa", "sorprend", "curios", "emotivo", "conmovedor", "gesto de",
    "no lo vio nadie", "nunca visto", "por primera vez", "el más", "la más",
    "wtf", "video:", "el video", "la foto", "se volvio", "se volvió",
    "estallo", "estalló", "explotaron", "memes", "reaccion", "reacción",
]


def candidatas_perlitas(resultados: dict, max_items: int = 30) -> list:
    """Barre todos los titulares buscando señales de perlita (viral, insólito,
    récord, blooper...). Devuelve [(nombre_fuente, titulo), ...] dedupeado."""
    out, vistos = [], set()
    for f in TODAS_FUENTES:
        for n in resultados.get(f["id"], []):
            t = n.get("titulo", "")
            tl = t.lower()
            if not any(k in tl for k in PERLITA_KEYWORDS):
                continue
            k = frozenset(normalizar_titulo(t))
            if not k or k in vistos:
                continue
            vistos.add(k)
            out.append((f["nombre"], t[:150]))
            if len(out) >= max_items:
                return out
    return out


def prompt_analisis_general(resultados: dict) -> str:
    tendencias = calcular_tendencias(resultados)[:30]
    perlitas = candidatas_perlitas(resultados)
    bloque_perlitas = "\n".join(f"  • [{f}] {t}" for f, t in perlitas) or "  (ninguna detectada en esta pasada)"
    lineas = "\n".join(
        f"{i+1}. {c['titulo'][:130]} — {c['cant_medios']} medios "
        f"({c.get('nac', 0)} nac / {c.get('intl', 0)} int) · Olé: {'sí' if c.get('tiene_ole') else 'NO'}"
        for i, c in enumerate(tendencias)
    )
    return f"""Sos editor jefe de un portal deportivo argentino. Abajo están los 30 temas
que más medios están cubriendo AHORA (de {len(TODAS_FUENTES)} medios monitoreados),
ya agrupados y ordenados por volumen.{bloque_criterios()}

Escribí un RESUMEN EJECUTIVO en español rioplatense, directo:

LECTURA GENERAL — 3 líneas: qué domina la conversación y qué tono tiene el día.

LOS 30 TEMAS, agrupados por eje (Selección / mercado de pases / torneo local /
fútbol internacional / otros). Por cada tema, UNA sola línea: qué pasó y por qué
importa para el hincha argentino. No repitas el título textual: interpretalo.
Marcá con ⚠️ los temas donde Olé no tiene cobertura.

DATO SALIENTE — 1 línea: la asimetría o el patrón más llamativo del panorama.

PERLITAS — 3 a 5 joyitas con potencial de tráfico: lo viral, lo insólito, la
sorpresa, el gesto, el récord raro. Elegilas de la canasta de candidatas (y del
top 30 si alguna califica). Por cada una: por qué puede rendir en una línea +
un título con gancho. Si una candidata es puro clickbait sin sustancia, salteala.

TEMAS:
{lineas}

CANDIDATAS A PERLITA (detectadas por señales de viralidad/rareza):
{bloque_perlitas}"""

def prompt_informe_ole(resultados: dict, analisis: dict, temas_editor: str = "") -> str:
    tendencias = calcular_tendencias(resultados)
    top = tendencias[:10]
    faltantes = analisis.get("faltantes_en_ole", [])[:15]
    bloque_top = "\n\n".join(
        f"TEMA {i+1}: {c['titulo'][:130]} ({c['cant_medios']} medios · Olé: {'sí' if c.get('tiene_ole') else 'NO'})\n"
        + "\n".join(f"   · [{n['fuente']['nombre']}] {n['noticia']['titulo'][:110]}"
                     for n in c.get("noticias", [])[:5])
        for i, c in enumerate(top)
    )
    bloque_falt = "\n".join(f"  • [{f['fuente_nombre']}] {f['titulo'][:120]}"
                             for f in faltantes) or "  (ninguno)"

    if temas_editor.strip():
        # contexto: cómo tituló la competencia los temas que pidió el editor
        pedidos = [t.strip() for t in re.split(r"[\n,;]+", temas_editor) if t.strip()]
        ctx = []
        for pedido in pedidos[:6]:
            kp = normalizar_titulo(pedido)
            relacionadas = []
            for c in tendencias:
                if solapamiento(kp, normalizar_titulo(c["titulo"])) >= 0.3 or \
                   any(w in c["titulo"].lower() for w in pedido.lower().split() if len(w) > 3):
                    for n in c.get("noticias", [])[:4]:
                        relacionadas.append(f"     · [{n['fuente']['nombre']}] {n['noticia']['titulo'][:110]}")
                    if len(relacionadas) >= 6:
                        break
            ctx.append(f"TEMA PEDIDO: {pedido}\n"
                       + ("\n".join(relacionadas[:6]) if relacionadas
                          else "     (sin cobertura detectada en el panorama actual)"))
        bloque_ctx = "\n\n".join(ctx)
        return f"""Sos editor de Olé. No generes noticias descriptivas: competí por el
significado antes que por la información.

{FRAMEWORK_ANGULOS}{bloque_criterios()}

El editor quiere trabajar ESTOS temas hoy. Para cada uno, dale munición:

POR CADA TEMA PEDIDO:
  • Los niveles de lectura que manda (qué cambió / a quién afecta / qué emoción /
    qué patrón / qué consecuencia).
  • CINCO ÁNGULOS del framework, cada uno con su título sugerido y el tipo de
    ángulo nombrado. Si la competencia ya cubrió el tema (tenés sus títulos),
    priorizá los ángulos que NADIE usó.
  • Tu recomendación: cuál es EL ángulo ganador y por qué.
  • Un dato o pregunta que le falta a la nota para ser imbatible.

Español rioplatense, directo, sin relleno.

TEMAS PEDIDOS (con cómo los tituló la competencia):
{bloque_ctx}"""

    return f"""Sos editor de Olé. No generes noticias descriptivas: para cada hecho
detectá patrones, conflictos, consecuencias, cambios de estatus, héroes
inesperados, paradojas e impacto emocional en el hincha. Competí por el
significado antes que por la información.

{FRAMEWORK_ANGULOS}{bloque_criterios()}

Abajo tenés los 10 temas más calientes (con cómo tituló cada medio) y los
huecos donde Olé no entró. Escribí en español rioplatense:

FOCOS SUGERIDOS — Elegí los 6 temas con más potencial. Por cada uno:
  • El tema en una línea y qué nivel de lectura manda (qué cambió / a quién
    afecta / qué emoción genera / qué patrón revela / qué consecuencia deja).
  • AL MENOS CINCO ÁNGULOS DISTINTOS del framework, cada uno con su título
    sugerido. Nombrá el tipo de ángulo. Evitá los que ya usó la competencia
    (sus títulos están a la vista).
  • Tu recomendación: cuál de los cinco es EL ángulo, y por qué.

HUECOS RÁPIDOS — De la lista de faltantes, marcá los 3 que valen la pena y el
ángulo de entrada en una línea; ignorá el resto.

TOP 10 TEMAS:
{bloque_top}

FALTANTES EN OLÉ:
{bloque_falt}"""

def _extraer_cuerpo_nota(url: str, max_chars: int = 900) -> str:
    """Intenta extraer los primeros párrafos del cuerpo de una nota. Retorna '' si falla.
    Limitado a 900 chars por nota para controlar el gasto de tokens de entrada."""
    if not url or not url.startswith("http"):
        return ""
    try:
        resp = requests.get(url, headers=_FETCH_HEADERS, timeout=12, allow_redirects=True)
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        # Eliminar scripts, estilos, menús, publicidades
        for tag in soup(["script", "style", "nav", "header", "footer",
                          "aside", "form", "figure", "noscript", "iframe"]):
            tag.decompose()
        # Selectores de cuerpo de nota, del más específico al más genérico
        BODY_SELS = [
            "article .article-body", "article .nota-cuerpo", "article .entry-content",
            "article .article-content", "article .post-content", "article .content-body",
            ".article__body", ".nota__cuerpo", ".article-text", ".news-body",
            "[class*=article-body]", "[class*=nota-cuerpo]", "[class*=entry-content]",
            "[class*=article-content]", "[class*=post-body]",
            "article", "[role=main]",
        ]
        texto = ""
        for sel in BODY_SELS:
            el = soup.select_one(sel)
            if el:
                parrafos = [p.get_text(" ", strip=True) for p in el.find_all("p") if len(p.get_text(strip=True)) > 40]
                texto = "\n".join(parrafos[:5])  # máx 5 párrafos por nota
                if len(texto) > 200:
                    break
        if not texto:
            # Último recurso: todos los <p> largos de la página
            parrafos = [p.get_text(" ", strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 60]
            texto = "\n".join(parrafos[:4])
        return texto[:max_chars].strip()
    except Exception:
        return ""

def scrape_cuerpos_notas(titulares: list, max_notas: int = 6) -> list:
    """
    Enriquece los titulares con el cuerpo scrapeado de cada URL.
    Retorna lista de dicts con keys: fuente, noticia, cuerpo, ok.
    Solo scrappea las primeras max_notas con URL válida.
    """
    enriquecidos = []
    con_url = [item for item in titulares if item["noticia"].get("url")][:max_notas]
    sin_url  = [item for item in titulares if not item["noticia"].get("url")]

    if con_url:
        with ThreadPoolExecutor(max_workers=5) as ex:
            futures = {ex.submit(_extraer_cuerpo_nota, item["noticia"]["url"]): item for item in con_url}
            for future in as_completed(futures):
                item = futures[future]
                try:
                    cuerpo = future.result()
                except Exception:
                    cuerpo = ""
                enriquecidos.append({**item, "cuerpo": cuerpo, "ok": bool(cuerpo)})

    for item in sin_url:
        enriquecidos.append({**item, "cuerpo": "", "ok": False})

    # Agregar el resto de titulares (más allá de max_notas) sin cuerpo
    ids_procesados = {id(item) for item in con_url + sin_url}
    for item in titulares:
        if id(item) not in ids_procesados:
            enriquecidos.append({**item, "cuerpo": "", "ok": False})

    return enriquecidos

def prompt_nota_rapida(tema: str, titulares_enriquecidos: list, estilo: str, tipo_nota: str, contexto_extra: str = "") -> str:
    con_cuerpo  = [t for t in titulares_enriquecidos if t.get("ok")]
    solo_titulo = [t for t in titulares_enriquecidos if not t.get("ok")]
    tiene_info_real = len(con_cuerpo) > 0

    # Bloque de fuentes con cuerpo completo
    bloque_completo = ""
    if con_cuerpo:
        partes = []
        for t in con_cuerpo:
            f, n = t["fuente"], t["noticia"]
            partes.append(
                f"── [{f['nombre']}] {n['titulo']}\n"
                f"URL: {n.get('url','')}\n"
                f"TEXTO:\n{t['cuerpo']}"
            )
        bloque_completo = "\n\n".join(partes)

    # Bloque de fuentes solo con titular
    bloque_titulares = ""
    if solo_titulo:
        bloque_titulares = "\n".join(
            f"  • [{t['fuente']['nombre']}] {t['noticia']['titulo']}"
            for t in solo_titulo
        )

    estilos = {
        "Informativa": (
            "Estilo agencia de noticias argentina (Télam/NA). "
            "Tono directo, neutro, sin opinión ni adjetivos innecesarios. "
            "Verbos en pasado o presente simple. Oraciones cortas. "
            "Los datos concretos van primero, el contexto después."
        ),
        "Analítica": (
            "Estilo agencia argentina con profundidad. "
            "Tono directo y neutro pero con contexto, antecedentes y proyección. "
            "Cada afirmación tiene respaldo en las fuentes. "
            "Párrafos más largos, estructura de causa-efecto."
        ),
        "Urgente/Flash": (
            "Estilo despacho urgente de agencia argentina. "
            "Máximo 3 párrafos muy cortos. Verbo en presente. "
            "Solo el dato central, sin contexto. "
            "Primera oración = toda la noticia en una línea."
        ),
    }
    tipos = {
        "Nota completa": (
            "Nota con subtítulos (SIN lead/cierre clásico de manual). Estructura:\n"
            "- Primer párrafo suelto: el hecho central en 2-3 oraciones directas, sin subtítulo.\n"
            "- Luego 3 o 4 secciones, cada una con subtítulo informativo en negrita (## Subtítulo), "
            "seguido de 2-3 párrafos de 60-80 palabras.\n"
            "- La nota entera: entre 400 y 550 palabras.\n"
            "- Los subtítulos deben ser concretos y periodísticos, no genéricos "
            "(ej: '## La lesión y los plazos de recuperación' en vez de '## Contexto')."
        ),
        "Solo titulares alternativos": (
            "Generá 8 titulares alternativos: 2 impactantes, 2 SEO, "
            "2 para redes sociales (con gancho), 2 estilo agencia neutro. "
            "Para cada uno agregá una línea corta explicando el enfoque."
        ),
        "Esqueleto + ángulos": (
            "Esqueleto con subtítulos numerados (## 1. ..., ## 2. ...) "
            "y una línea describiendo qué información va en cada sección. "
            "Al final, 3 ángulos posibles con título sugerido para cada uno."
        ),
    }

    instruccion_angulo = f"""ANTES DE ESCRIBIR — el método (obligatorio, no lo saltees):
Identificá en silencio los 6 niveles de lectura del hecho: qué pasó, qué cambió,
a quién afecta, qué emoción genera, qué tendencia o patrón revela y qué
consecuencia deja. Después elegí UN ángulo del framework de Olé (cambio de
estatus, patrón, consecuencia, héroe inesperado, conflicto, paradoja, identidad,
tendencia, qué significa, el día después) y construí TODA la nota alrededor de
ese ángulo: el título compite por el significado, no por la información; el
primer párrafo instala el ángulo, no la crónica.{bloque_criterios()}

"""

    if tiene_info_real:
        instruccion_alucinacion = instruccion_angulo + """⚠️ REGLAS ANTI-ALUCINACIÓN (CRÍTICAS — leelas antes de escribir una sola palabra):
- Usá ÚNICAMENTE datos, cifras, citas y hechos que aparezcan textualmente en las FUENTES de abajo.
- Prohibido agregar contexto histórico, estadísticas o antecedentes que no estén en los textos.
- Las citas entre comillas SOLO pueden ser frases que aparezcan literalmente en los textos fuente.
- Si un dato no está en los textos, escribí [DATO A CONFIRMAR] en su lugar. Sin excepciones.
- Si dos fuentes se contradicen, mencioná la contradicción explícitamente."""

        instruccion_formato = """
FORMATO DE RESPUESTA OBLIGATORIO — respetá este orden exacto:

════════════════════════════════════
NOTA
════════════════════════════════════
[Aquí va la nota redactada según el estilo y entregable solicitado]


════════════════════════════════════
TABLA DE VERIFICACIÓN
════════════════════════════════════
Lista TODOS los datos concretos que usaste en la nota (cifras, nombres, citas, hechos).
Para cada uno indicá:
• DATO: el dato exacto como aparece en la nota
• FUENTE: nombre del medio de donde lo tomaste
• VERIFICADO: ✅ si está textualmente en el cuerpo scrapeado | ⚠️ si solo aparece en el titular | ❌ si no encontrás respaldo

Ejemplo de fila:
• DATO: "sufrió un desgarro en el isquiotibial derecho" | FUENTE: TyC Sports | VERIFICADO: ✅

════════════════════════════════════
ÁNGULOS ALTERNATIVOS
════════════════════════════════════
3 enfoques distintos del framework (nombrá el tipo de ángulo), con título sugerido para cada uno.
"""

        bloque_fuentes = f"""=== FUENTES CON TEXTO COMPLETO ({len(con_cuerpo)}) — de estas podés extraer datos ===
{bloque_completo}"""
        if bloque_titulares:
            bloque_fuentes += f"""

=== FUENTES SOLO CON TITULAR ({len(solo_titulo)}) — NO inferir datos, solo confirmar que el tema existe ===
{bloque_titulares}"""
    else:
        instruccion_alucinacion = instruccion_angulo + """⚠️ MODO ESQUELETO SEGURO — no se pudo leer el cuerpo de ninguna nota.
No redactes la nota. En cambio, seguí el formato de respuesta obligatorio de abajo."""

        instruccion_formato = """
FORMATO DE RESPUESTA OBLIGATORIO:

════════════════════════════════════
ESQUELETO DE NOTA
════════════════════════════════════
Estructura con secciones numeradas y vacías, listas para que el redactor complete.
Indicá qué tipo de información va en cada sección.

════════════════════════════════════
DATOS CONFIRMADOS (solo desde titulares)
════════════════════════════════════
Lista con bullet points. Solo lo que los titulares permiten afirmar con certeza.
Formato: • [dato] — confirmado por: [medio]

════════════════════════════════════
DATOS A CONFIRMAR ANTES DE PUBLICAR
════════════════════════════════════
Lista de preguntas concretas que el redactor debe responder antes de publicar.

════════════════════════════════════
ÁNGULOS ALTERNATIVOS
════════════════════════════════════
3 enfoques distintos según qué datos aparezcan, con título sugerido para cada uno.
"""
        bloque_fuentes = f"""=== SOLO TITULARES DISPONIBLES ({len(solo_titulo)}) ===
{bloque_titulares}"""

    return f"""Sos un redactor deportivo de un portal argentino. Tu tarea es trabajar sobre este tema:

TEMA: {tema}
ESTILO: {estilos.get(estilo, estilos["Informativa"])}
ENTREGABLE: {tipos.get(tipo_nota, tipos["Nota completa"])}

{instruccion_alucinacion}
{instruccion_formato}

{bloque_fuentes}

Escribí en español rioplatense con voseo. Tono de agencia de noticias argentina (estilo Télam, NA, DyN).
Reglas de estilo periodístico argentino:
- Los clubes se nombran como los nombra la prensa argentina: "River" (no "River Plate"), "Boca" (no "Boca Juniors"), "Racing" (no "Racing Club"), "San Lorenzo" (no "San Lorenzo de Almagro"), "Independiente", "Huracán", "Vélez", "Lanús", "Defensa", etc.
- Los seleccionados: "la Selección" o "el equipo nacional" (no "la Albiceleste" salvo que sea en un contexto festivo), "la Sub-20", "la Sub-23".
- Los jugadores se mencionan por apellido a partir de la segunda referencia: "Messi" (no "La Pulga"), "Di María" (no "el Fideo"). Sin apodos en texto de agencia.
- Cargos y funciones en minúscula: "el entrenador Scaloni", "el presidente Laporta", "el director técnico".
- Evitá frases como "en este contexto", "cabe destacar", "vale la pena mencionar", "a su vez", "en tanto".
- No uses adjetivos valorativos ("increíble", "impresionante", "histórico", "brillante") salvo que estén textualmente en la fuente.
- Nunca uses "lead", "bajada" ni ningún término de manual de redacción en el cuerpo de la nota.
{("\n=== CONTEXTO ADICIONAL DEL REDACTOR ===\n" + contexto_extra + "\n(Podés usar este contexto libremente en la nota — es información aportada por el redactor, no requiere verificación de fuente.)") if contexto_extra else ""}
"""


def prompt_tono_editorial(query: str, titulares_filtrados: list) -> str:
    bloque = "\n".join(
        f'[{item["fuente"]["nombre"]}] {item["noticia"]["titulo"]}'
        for item in titulares_filtrados
    )
    return f"""Analizá el tono editorial de estos titulares sobre "{query}".

TITULARES ({len(titulares_filtrados)} en total):
{bloque}

Respondé ÚNICAMENTE con un objeto JSON válido, sin texto antes ni después, sin backticks.
El JSON debe tener exactamente esta estructura:

{{
  "resumen": "una oración que describe el tono general de la cobertura",
  "distribucion": {{
    "positivo": 0,
    "negativo": 0,
    "neutro": 0,
    "alarmista": 0,
    "expectante": 0
  }},
  "por_medio": [
    {{
      "medio": "nombre del medio",
      "tono": "positivo|negativo|neutro|alarmista|expectante",
      "titular": "el titular analizado",
      "razon": "una línea explicando por qué ese tono"
    }}
  ],
  "patrones": [
    "patrón editorial detectado 1",
    "patrón editorial detectado 2"
  ]
}}

Tonos posibles:
- positivo: elogio, logro, buena noticia
- negativo: crítica, fracaso, escándalo, mala noticia
- neutro: informativo puro, sin carga valorativa
- alarmista: urgencia, crisis, peligro, dramatismo
- expectante: incertidumbre, espera, "podría", "se espera"
"""



_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Referer": "https://www.google.com/",
}

def fetch_og_image(url: str) -> str:
    """Busca la imagen principal de una nota. Retorna la URL de la imagen o ''."""
    if not url or not url.startswith("http") or "google.com/search" in url:
        return ""
    if url in _IMAGE_CACHE:
        return _IMAGE_CACHE[url]
    try:
        resp = requests.get(url, headers=_FETCH_HEADERS, timeout=10, allow_redirects=True)
        soup = BeautifulSoup(resp.text, "html.parser")

        # 1. Intentar og:image / twitter:image
        for meta in [
            soup.find("meta", property="og:image"),
            soup.find("meta", property="og:image:url"),
            soup.find("meta", attrs={"name": "twitter:image"}),
            soup.find("meta", attrs={"name": "twitter:image:src"}),
        ]:
            if not meta:
                continue
            candidate = meta.get("content", "") or meta.get("value", "") or ""
            if candidate and not _es_imagen_generica(candidate):
                _IMAGE_CACHE[url] = candidate
                return candidate

        # 2. Fallback: primera imagen grande dentro del artículo
        #    Selectores ordenados de más específico a más genérico
        img_selectors = [
            "article figure img",
            "article .image img",
            "article img[src]",
            ".nota-cuerpo img",
            ".article-body img",
            ".entry-content img",
            "figure img",
            "[class*=hero] img",
            "[class*=featured] img",
            "[class*=portada] img",
            "[class*=cover] img",
        ]
        for sel in img_selectors:
            for tag in soup.select(sel):
                src = (
                    tag.get("src") or tag.get("data-src") or
                    tag.get("data-lazy-src") or tag.get("data-original") or ""
                )
                if (src and src.startswith("http")
                        and not src.endswith(".gif")
                        and not _es_imagen_generica(src)
                        and "1x1" not in src and "pixel" not in src.lower()):
                    _IMAGE_CACHE[url] = src
                    return src

        _IMAGE_CACHE[url] = ""
        return ""
    except Exception:
        _IMAGE_CACHE[url] = ""
        return ""

_IMAGE_CACHE = {}  # cache de og:images por URL (vive lo que dure el proceso)


def fetch_og_images_batch(noticias: list) -> None:
    """Fetch og:images en paralelo para una lista de noticias. Guarda en _IMAGE_CACHE."""
    urls_sin_cache = [
        n["url"] for n in noticias
        if n.get("url") and n["url"] not in _IMAGE_CACHE
        and "news.google.com" not in n["url"]  # redirects de Google News: no tienen imagen
    ]
    if not urls_sin_cache:
        return
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(fetch_og_image, u) for u in urls_sin_cache]
        for f in as_completed(futures):
            try:
                f.result()
            except Exception:
                pass

