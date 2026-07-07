# Piloto automático del Monitor — puesta en marcha (sin consola)

## Qué es cada archivo

| Archivo | Qué hace |
|---|---|
| `app.py` | La interfaz Streamlit de siempre (ahora importa el núcleo) |
| `monitor_core.py` | El cerebro compartido: scraping, clustering, agenda |
| `sheets_memoria.py` | La memoria en Google Sheets (tablero + feedback) |
| `vigia.py` | El piloto automático que corre solo cada hora |
| `.github/workflows/vigia.yml` | Le dice a GitHub cuándo correr el vigía |
| `requirements.txt` | Dependencias de la app |
| `requirements-vigia.txt` | Dependencias del vigía (más liviano, sin Streamlit) |

## Estructura del repo en GitHub

```
tu-repo/
├── app.py
├── monitor_core.py
├── sheets_memoria.py
├── vigia.py
├── requirements.txt
├── requirements-vigia.txt
└── .github/
    └── workflows/
        └── vigia.yml      ← OJO: tiene que estar exactamente en esta carpeta
```

En GitHub web: **Add file → Create new file**, y en el nombre escribí
`.github/workflows/vigia.yml` (GitHub crea las carpetas solo).

## Paso 1 — Crear la planilla y la service account (una sola vez, ~10 min)

1. Creá un Google Sheet nuevo y vacío. De su URL copiá el **ID** (lo que está
   entre `/d/` y `/edit`).
2. Andá a https://console.cloud.google.com → creá un proyecto (nombre libre).
3. En "APIs y servicios → Biblioteca", buscá **Google Sheets API** y **Google
   Drive API**, habilitá las dos.
4. En "APIs y servicios → Credenciales" → **Crear credenciales → Cuenta de
   servicio**. Nombre libre, sin permisos extra, Listo.
5. Entrá a la cuenta de servicio creada → pestaña **Claves** → Agregar clave →
   Crear clave nueva → **JSON**. Se descarga un archivo `.json`: ese contenido
   completo es tu credencial.
6. En la cuenta de servicio vas a ver un email tipo
   `algo@proyecto.iam.gserviceaccount.com`. **Compartí tu Google Sheet con ese
   email** (botón Compartir, permiso Editor). Sin este paso no funciona nada.

## Paso 2 — Cargar los secrets

**En GitHub** (repo → Settings → Secrets and variables → Actions → New secret):
- `GOOGLE_SERVICE_ACCOUNT_JSON` → pegá el contenido completo del archivo .json
- `SHEET_ID` → el ID de la planilla
- `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` → opcionales (paso 4)

**En Streamlit Cloud** (app → Settings → Secrets):
```toml
ANTHROPIC_API_KEY = "sk-ant-..."
SHEET_ID = "el-id-de-tu-planilla"
GOOGLE_SERVICE_ACCOUNT_JSON = '''
{ ...pegá acá el JSON completo... }
'''
```

## Paso 3 — Probar el vigía a mano

Repo → pestaña **Actions** → "Vigía del monitor" → botón **Run workflow**.
En 2-3 minutos mirá el log: tiene que decir cuántas fuentes respondieron y
cuántas filas escribió. Abrí tu planilla: van a aparecer las pestañas
**Agenda**, **Snapshot** y **Config** llenándose solas.

## Paso 4 (opcional) — Avisos urgentes por Telegram

1. Instalá Telegram y buscá **@BotFather** → mandale `/newbot` → te da un
   **token**. Ese es `TELEGRAM_BOT_TOKEN`.
2. Mandale cualquier mensaje a tu bot nuevo (buscalo por el nombre que le
   pusiste).
3. Abrí en el navegador:
   `https://api.telegram.org/bot<TU_TOKEN>/getUpdates`
   y buscá `"chat":{"id":123456789` — ese número es `TELEGRAM_CHAT_ID`.
4. Cargá los dos como secrets en GitHub. Activale las notificaciones al chat.

## Cómo se usa en el día a día

- **La planilla es el tablero.** El vigía la llena solo, cada hora. Cada fila
  es una acción: SUBIR YA / REDACTAR / SEGUIR / EMPUJAR, con el tema, cuántos
  medios lo tienen y el momentum.
- **Vos respondés en la columna Estado**: escribí `hecho` o `descartado` y el
  vigía deja de insistir con ese tema. Si la dejás en `pendiente`, no te lo
  repite por 48 horas (configurable).
- **La pestaña Config es tu panel**: cambiá el umbral de medios o la watchlist
  (ej: `river, boca, seleccion argentina, scaloni`) directamente en la celda.
  No hace falta tocar código.
- **Telegram solo te habla si hay un SUBIR YA.** El silencio significa que no
  hay nada urgente.
- **La app de Streamlit sigue igual**, pero ahora su momentum es real (compara
  contra la última corrida del vigía, no contra tu último refresh) y en la
  barra lateral tenés el link directo a la planilla.

## Si algo falla

- El log de cada corrida queda en la pestaña Actions del repo.
- Si el vigía aborta con "muy pocas fuentes respondieron", es protección:
  prefiere no escribir nada antes que ensuciar la memoria con una corrida mala.
- El horario está en el yml (`cron`, en hora UTC = Argentina + 3). Hoy corre
  de 7 a 23 hora argentina, una vez por hora.
