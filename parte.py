"""parte.py — El parte de la mañana del copiloto editorial.

Corre solo (GitHub Actions, todos los días 7:30 hora argentina). Scrapea el
panorama del momento, lo cruza con la memoria (qué venía creciendo, qué ya
dimos) y le pide a Claude un parte con 5 focos sugeridos para el día — cada
uno con su ángulo del framework y un título tentativo.

Sale por Telegram (si está configurado) y queda en la pestaña "Parte".
Necesita los mismos secrets del vigía + ANTHROPIC_API_KEY.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import monitor_core
from monitor_core import (
    calcular_tendencias, analizar_ole_vs_compecencia_safe, construir_agenda,
    call_claude, fetch_cobertura_ole_gnews, FRAMEWORK_ANGULOS, bloque_criterios,
)
import sheets_memoria as mem
from vigia import scrapear_todo, enviar_telegram

_TZ_AR = timezone(timedelta(hours=-3))
_DIAS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def fecha_es(dt) -> str:
    return f"{_DIAS_ES[dt.weekday()]} {dt.strftime('%d/%m/%Y')}"


def para_telegram(texto: str) -> str:
    """Limpia restos de markdown que Telegram muestra crudos."""
    import re as _re
    t = texto.replace("**", "").replace("---", "").replace("###", "").replace("##", "")
    return _re.sub(r"^#+\s*", "", t, flags=_re.MULTILINE).strip()


def contexto_tema(it: dict) -> str:
    linea = f"[{it['accion']}] {it['titulo']} ({it['cant_medios']} medios"
    if it.get("nuevo"):
        linea += ", nuevo"
    elif it.get("delta", 0) > 0:
        linea += f", subió +{it['delta']}"
    linea += f") — {it['motivo']}"
    titulares = ""
    if it.get("noticias"):
        titulares = "\n" + "\n".join(
            f"    · [{n['fuente']['nombre']}] {n['noticia']['titulo'][:110]}"
            for n in it["noticias"][:5]
        )
    return linea + titulares


def prompt_parte(agenda: list, fecha: str) -> str:
    temas = "\n\n".join(contexto_tema(it) for it in agenda[:12])
    return f"""Sos editor jefe de Olé. Son las 7:30 del {fecha} y este es el panorama que
armó el sistema durante la noche: los temas accionables, con su momentum, si ya
los dimos, y cómo los tituló cada medio.

{FRAMEWORK_ANGULOS}{bloque_criterios()}

Escribí el PARTE DE LA MAÑANA. Reglas de forma, estrictas:
- Español rioplatense, directo, sin relleno. MÁXIMO 550 palabras en total.
- TEXTO PLANO: nada de #, ##, **, ni ---. Jerarquizá con MAYÚSCULAS y emojis
  (☕ 🔴 🟡 🔵 👀). Va a leerse en un teléfono.
- DISCIPLINA TEMPORAL: ancláte SOLO a lo que los títulos afirman. Si no consta
  que un partido ya se jugó, no digas "juega hoy" ni "(o acaba de jugar)":
  hablá de lo que los títulos dicen en pasado como pasado, y punto. Prohibido
  especular con horarios. Priorizá lo marcado "nuevo" o "subió"; lo "estable"
  de pocos medios probablemente sea arrastre viejo de portada: usalo solo si
  aporta.

Estructura:
PANORAMA — máximo 3 líneas: cómo amanece el día futbolero.
5 FOCOS PARA HOY — en orden de prioridad, MÁXIMO 55 palabras cada uno:
  🔴 tema y por qué hoy (1 línea) · ÁNGULO del framework que ningún medio usó,
  nombrado · TÍTULO tentativo filoso · si dice RETOMAR: actualización, segunda
  vuelta o dejarlo.
👀 OJO CON — 1 o 2 temas chicos que vienen creciendo, una línea cada uno.

PANORAMA:
{temas}"""


def main():
    if not mem.disponible():
        print("Sin planilla configurada. Abortando.")
        sys.exit(1)
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("Falta ANTHROPIC_API_KEY. Abortando.")
        sys.exit(1)

    cfg = mem.leer_config()
    monitor_core.CRITERIOS_EDITOR = cfg.get("criterios", "")

    print("1) Scrapeando el panorama de la mañana...")
    resultados = scrapear_todo()
    fuentes_ok = sum(1 for v in resultados.values() if v)
    if fuentes_ok < 5:
        print("   Muy pocas fuentes; sin panorama no hay parte.")
        sys.exit(1)

    tendencias = calcular_tendencias(resultados)
    if cfg.get("ignorar"):
        tendencias = [c for c in tendencias
                      if not any(w in c["titulo"].lower() for w in cfg["ignorar"])]
    ole = analizar_ole_vs_compecencia_safe(resultados)
    prev = mem.leer_snapshot_anterior()
    cubiertos = mem.cobertura_propia(dias=5)
    cubiertos += [{"titulo": t, "fecha": None} for t in fetch_cobertura_ole_gnews()]

    agenda = construir_agenda(tendencias, ole, prev, max_items=15, cubiertos=cubiertos)
    print(f"2) {len(tendencias)} clusters → {len(agenda)} temas para el parte "
          f"(memoria propia: {len(cubiertos)} temas)")
    if not agenda:
        print("   Mañana tranquila: no hay temas accionables para un parte.")
        return

    fecha = fecha_es(datetime.now(_TZ_AR))
    print("3) Escribiendo el parte con Claude...")
    parte = call_claude(prompt_parte(agenda, fecha), api_key, max_tokens=4000)
    print(f"   {len(parte)} caracteres")

    mem.guardar_informe(parte, f"parte matutino {fecha}")
    print(f"4) Guardado en la planilla → {mem.url_planilla()}")

    # Telegram: texto plano, cortado en párrafos enteros (límite 4096 por mensaje)
    cuerpo = f"☕ PARTE DE LA MAÑANA — {fecha}\n\n" + para_telegram(parte)
    tandas, actual = [], ""
    for parrafo in cuerpo.split("\n\n"):
        if actual and len(actual) + len(parrafo) + 2 > 3800:
            tandas.append(actual)
            actual = parrafo
        else:
            actual = f"{actual}\n\n{parrafo}" if actual else parrafo
    if actual:
        tandas.append(actual)
    tandas = tandas[:4]
    enviado = 0
    for nro, tanda in enumerate(tandas, 1):
        ok = enviar_telegram(tanda, html=False)
        enviado += 1 if ok else 0
        print(f"   telegram tanda {nro}/{len(tandas)}: {'ok' if ok else 'FALLÓ'}")
    print(f"5) Telegram: {enviado}/{len(tandas)} tandas enviadas")


if __name__ == "__main__":
    main()
