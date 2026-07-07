"""informe.py — Informe editorial semanal generado por IA.

Corre solo (GitHub Actions, domingos) o a mano. Toma el Historial acumulado
de la semana en la planilla, lo condensa en temas únicos (para no mandarle
miles de filas repetidas a Claude), y le pide a Claude un análisis de fondo:
ejes temáticos, huecos de Olé, tendencias lentas y recomendaciones.
El resultado queda en la pestaña "Informes" y, si hay bot, un resumen
por Telegram.

Necesita: los mismos secrets del vigía + ANTHROPIC_API_KEY.
"""
import os
import sys

import monitor_core
from monitor_core import normalizar_titulo, similitud_jaccard, call_claude, bloque_criterios
import sheets_memoria as mem
from vigia import enviar_telegram

DIAS = 7
UMBRAL_AGRUPADO = 0.30


def condensar(historial: list) -> list:
    """Agrupa las filas del historial (el mismo tema aparece en muchas
    corridas) en temas únicos con su trayectoria."""
    temas = []
    for fila in historial:
        keys = normalizar_titulo(fila["titulo"])
        destino = None
        for t in temas:
            if similitud_jaccard(keys, t["keys"]) >= UMBRAL_AGRUPADO:
                destino = t
                break
        if destino is None:
            temas.append({
                "keys": keys, "titulo": fila["titulo"],
                "max_medios": fila["cant_medios"],
                "dias": {fila["fecha"]},
                "tiene_ole": fila["tiene_ole"],
                "primera": fila["fecha"], "ultima": fila["fecha"],
            })
        else:
            destino["keys"] = destino["keys"] | keys  # el tema aprende vocabulario al evolucionar
            destino["max_medios"] = max(destino["max_medios"], fila["cant_medios"])
            destino["dias"].add(fila["fecha"])
            destino["tiene_ole"] = destino["tiene_ole"] or fila["tiene_ole"]
            destino["ultima"] = max(destino["ultima"], fila["fecha"])
            if fila["cant_medios"] >= destino["max_medios"]:
                destino["titulo"] = fila["titulo"]
    temas.sort(key=lambda t: (-len(t["dias"]), -t["max_medios"]))
    return temas


def prompt_informe(temas: list) -> str:
    lineas = "\n".join(
        f"- {t['titulo'][:120]} | pico {t['max_medios']} medios | "
        f"{len(t['dias'])} día(s) en agenda ({t['primera']} a {t['ultima']}) | "
        f"Olé: {'sí' if t['tiene_ole'] else 'NO'}"
        for t in temas[:120]
    )
    return f"""Sos editor jefe de Olé. Este es el registro condensado de lo que publicaron
33 medios deportivos (nacionales e internacionales) en los últimos {DIAS} días.
Cada línea: tema, pico de medios que lo cubrieron, cuántos días estuvo en agenda,
y si Olé lo cubrió.

Escribí un INFORME EDITORIAL SEMANAL en español rioplatense, directo y sin
relleno, con estas secciones:

1. EJES DE LA SEMANA — los 3-5 grandes ejes temáticos que dominaron
   (ej: mercado de pases, Selección, torneo local, Mundial) y cuánto pesó cada uno.
2. HUECOS DE OLÉ — temas con buena cobertura ajena donde Olé no entró o entró
   tarde. Sé concreto: nombralos.
3. TENDENCIAS LENTAS — temas que vienen creciendo día a día y van a explotar
   la semana que viene. Es la sección más valiosa: lo que el día a día no deja ver.
4. AGENDA PROPIA — dónde Olé marcó agenda o tuvo exclusivas.
5. RECOMENDACIONES — 5 acciones concretas para la semana que arranca, en orden
   de prioridad, cada una con su ángulo.

{bloque_criterios()}

REGISTRO:
{lineas}"""


def main():
    if not mem.disponible():
        print("Sin planilla configurada; el informe necesita el Historial. Abortando.")
        sys.exit(1)
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("Falta el secret ANTHROPIC_API_KEY en GitHub. Abortando.")
        sys.exit(1)

    monitor_core.CRITERIOS_EDITOR = mem.leer_config().get("criterios", "")
    print(f"1) Leyendo Historial de los últimos {DIAS} días...")
    historial = mem.leer_historial(DIAS)
    print(f"   {len(historial)} registros")
    if len(historial) < 20:
        print("   Todavía hay poco historial acumulado; el informe saldría flojo.")
        print("   Probá de nuevo cuando el vigía lleve al menos un par de días corriendo.")
        return

    print("2) Condensando en temas únicos...")
    temas = condensar(historial)
    print(f"   {len(temas)} temas únicos")

    print("3) Pidiendo el análisis a Claude...")
    informe = call_claude(prompt_informe(temas), api_key, max_tokens=3000)
    print(f"   informe de {len(informe)} caracteres")

    periodo = f"últimos {DIAS} días ({len(temas)} temas)"
    ok = mem.guardar_informe(informe, periodo)
    print(f"4) Guardado en pestaña Informes: {'ok' if ok else 'FALLÓ'}")
    print(f"   → {mem.url_planilla()}")

    resumen = informe[:1500] + ("…" if len(informe) > 1500 else "")
    if enviar_telegram(f"<b>📊 Informe semanal listo</b>\n\n{resumen}\n\n📋 Completo en la planilla."):
        print("5) Resumen enviado por Telegram")


if __name__ == "__main__":
    main()
