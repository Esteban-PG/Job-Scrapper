# Bot de alertas de empleo

Monitorea varias bolsas de trabajo y avisa por Telegram **apenas aparece una
vacante nueva** que encaje con el perfil buscado (roles junior de ingeniería de
software, análisis de datos o QA, en Costa Rica o remoto).

La idea es reemplazar 15 alertas por correo ruidosas — cada una con su formato,
su frecuencia y su propio ruido — por **un solo feed filtrado**.

```
23:15:48  INFO  equifax             12 vacantes ·   3 nuevas ·   2 notificadas
23:15:51  INFO  pg                   2 vacantes ·   0 nuevas ·   0 notificadas
23:15:51  INFO  total: 14 vacantes · 3 nuevas · 2 notificadas · 2/2 fuentes ok
```

```
🟢 Nueva vacante
Billing Analyst - Junior
Heredia, Costa Rica · Accounting · Equifax
https://careers.equifax.com/es/trabajos/j00178026/billing-analyst-junior/
```

## La idea central

**15 bolsas no son 15 problemas.** Casi ninguna empresa construye su propia
bolsa de empleo: la subcontrata a un ATS conocido. Al clasificar las fuentes por
plataforma, las 15 colapsan a 4-5 plantillas reutilizables, y agregar la empresa
número 16 pasa a ser una entrada en un YAML.

| Plataforma | Cómo se reconoce | Cómo se resuelve | Estado |
|---|---|---|---|
| Greenhouse | `boards.greenhouse.io/<empresa>` | API JSON pública | plantilla lista |
| Lever | `jobs.lever.co/<empresa>` | API JSON pública | plantilla lista |
| Ashby | `jobs.ashbyhq.com/<empresa>` | API JSON pública | plantilla lista |
| Workday | `<tenant>.<dc>.myworkdayjobs.com` | POST JSON a `/wday/cxs/` | ✅ verificada en vivo |
| Phenom | endpoint `/widgets` | POST + token CSRF | ✅ verificada en vivo (P&G) |
| Equifax | feed XML propio | 1 GET al feed | ✅ verificada en vivo |
| JS pesado sin API | nada en la pestaña Network | Playwright | último recurso, sin casos aún |

**LinkedIn e Indeed quedan fuera a propósito.** Bloquean el scraping de forma
activa y va contra sus términos de servicio. Para esas dos la salida sana son
sus alertas nativas por correo + una regla en Gmail.

## Arquitectura

Cuatro piezas desacopladas, para que agregar una fuente no toque nada más:

```
config/sources.yaml ──> fetchers ──> dedupe (SQLite) ──> filtros ──> Telegram
                           │
                           └── uno por plataforma; devuelven el mismo schema
```

1. **Fetchers** (`jobbot/fetchers/`) — uno por plataforma. No saben nada de
   filtros ni de notificaciones: solo devuelven vacantes normalizadas.
2. **Dedupe** — SQLite con los IDs ya vistos. Sin esto el bot repite todo en
   cada corrida.
3. **Filtros** — incluir/excluir por título y pista de ubicación.
4. **Notificación** — Telegram por HTTP.

Todos los fetchers devuelven listas de dicts con esta forma. Es el contrato que
permite que el orquestador no sepa de dónde vino cada vacante:

```python
{
    "id":       "efx-J00178026",   # único y ESTABLE, con prefijo de fuente
    "title":    "Billing Analyst - Junior",
    "location": "Heredia, Costa Rica",
    "url":      "https://...",
    "source":   "Equifax",
    "category": "Accounting",      # opcional
    "posted":   "2026-07-20",      # opcional
}
```

El `id` es la clave de deduplicación: sale del código de vacante de la fuente,
nunca de la posición en la lista ni de un hash del título. Si el sitio reordena
sus resultados o corrige una palabra del título, el bot no vuelve a avisar.

## Correr local

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Ver qué encontraría, sin notificar ni tocar la base:
python run.py --dry-run

# En serio (necesita las credenciales de Telegram, ver abajo):
cp .env.example .env    # y completá los dos valores
python run.py
```

Sin `TELEGRAM_TOKEN`/`TELEGRAM_CHAT_ID` el bot no falla: imprime las vacantes por
consola. Práctico para ajustar filtros.

Flags útiles:

| Flag | Para qué |
|---|---|
| `--dry-run` | Imprime en vez de notificar y no escribe la base |
| `--source equifax` | Corre una sola fuente (por tipo o por nombre) |
| `--config otro.yaml` | Usa otro archivo de fuentes |
| `-v` | Logging en DEBUG |

Cada fetcher también corre solo, que es la forma rápida de ver si una fuente
sigue viva:

```bash
python jobbot/fetchers/equifax.py
python jobbot/fetchers/phenom.py
python jobbot/fetchers/workday.py
```

### Configurar Telegram

1. Hablale a [@BotFather](https://t.me/BotFather), mandá `/newbot`, elegí nombre
   y usuario (tiene que terminar en `bot`). Te devuelve el **token**.
2. Buscá tu bot nuevo por su usuario y **escribile cualquier cosa**. Sin ese
   primer mensaje tuyo, Telegram no le permite escribirte a vos.
3. Abrí `https://api.telegram.org/bot<TU_TOKEN>/getUpdates` en el navegador y
   copiá el número de `result[0].message.chat.id` — ese es el **chat id**.
4. Poné los dos valores en `.env` (local) y como Secrets en GitHub Actions.

El bot lee las credenciales de dos lugares, en este orden:

| Dónde | Para qué | Se sube al repo |
|---|---|---|
| Variables de entorno | Producción / GitHub Actions | no |
| Archivo `.env` | Comodidad local | no, está en `.gitignore` |

Las variables de entorno reales tienen prioridad sobre el `.env`, así que en
Actions los Secrets mandan aunque el archivo existiera.

## Agregar una fuente

Se edita `config/sources.yaml`, no el código. Mirá la URL de la bolsa y elegí el tipo:

```yaml
sources:
  - type: greenhouse
    company: nombre-en-la-url      # boards.greenhouse.io/nombre-en-la-url

  - type: workday
    tenant: pg                     # https://pg.wd5.myworkdayjobs.com/1000
    dc: wd5
    site: "1000"
    countries: ["Costa Rica"]
    name: "P&G"

  - type: equifax
    countries: ["Costa Rica"]
```

En Workday, `countries` va con el **nombre** del país tal como lo muestra el
filtro del sitio. Internamente Workday no filtra por nombre sino por un ID opaco
(Costa Rica = `99abe7e6bb3f4c108aebebf01a369ec5` en el tenant de P&G), así que
el fetcher lee el catálogo de facets que viene en la primera respuesta y traduce
el nombre solo. Eso evita tener que ir a buscar GUIDs a mano por cada tenant.

Si la bolsa no es de ninguna plataforma conocida, queda `type: html` con un
selector CSS — y si tampoco hay nada en el HTML, ahí sí toca Playwright.

Los filtros también viven en `config/sources.yaml`, así que se pueden afinar sin tocar
Python:

```yaml
filters:
  include: ['\bjunior\b', '\bdata\b', '\bqa\b', ...]
  exclude: ['\bsenior\b', '\bmanager\b', ...]
  location_hints: ['remote', 'costa rica', 'heredia', ...]
```

Un título que matchea `exclude` se descarta aunque matchee `include`. Para no
filtrar por ubicación, `location_hints: []`.

## Deploy

### GitHub Actions (incluido)

`.github/workflows/job-alerts.yml` corre cada 30 minutos en los servidores de
GitHub — no hace falta dejar la computadora prendida. Solo hay que cargar
`TELEGRAM_TOKEN` y `TELEGRAM_CHAT_ID` en *Settings → Secrets and variables →
Actions*.

**El detalle que importa:** el runner arranca limpio en cada corrida. Si no se
persiste `data/seen_jobs.db`, la base sale vacía, el bot cree que es su primera
corrida y re-notifica todo, cada 30 minutos, para siempre. El workflow lo
resuelve con `actions/cache`: como las caches de Actions son inmutables, la key
lleva el `run_id` (siempre distinta) y `restore-keys` recupera la más reciente
por prefijo.

Tres advertencias de GitHub Actions que conviene saber:

- **Los minutos se cobran en repos privados.** El plan Free da 2000 min/mes y
  GitHub redondea cada corrida hacia arriba al minuto. A `*/30` son ~1440
  corridas/mes: entra. A `*/15` serían ~2880 y se pasa. En **repos públicos los
  minutos son gratis e ilimitados**, así que si el repo es público (como
  portafolio, conviene) la frecuencia deja de ser un problema.
- Los cron **no son puntuales**: bajo carga se atrasan y a veces saltan una
  corrida. Para vacantes de empleo es irrelevante.
- Los workflows programados **se desactivan solos** tras 60 días sin actividad
  en el repo. Llega con un commit cada tanto, o usar la alternativa de abajo.

Para cambiar la frecuencia se edita una línea del workflow:

```yaml
- cron: "*/30 * * * *"    # cada 30 min · "0 * * * *" = cada hora
```

### VPS con cron

```cron
*/30 * * * * cd /ruta/al/bot && /ruta/al/.venv/bin/python run.py >> bot.log 2>&1
```

Acá `data/seen_jobs.db` persiste solo, que es la ventaja principal.

## Decisiones de diseño

- **La primera corrida no notifica.** Si la base está vacía, se llena con todo
  lo que hay pero no se avisa nada; si no, el bot arranca con una avalancha de
  vacantes viejas. Desde la segunda corrida solo avisa lo nuevo.
- **Traer todo y filtrar local.** Los fetchers no filtran por palabra clave en
  el origen (`subsearch` vacío en Phenom, `searchText` vacío en Workday). Cada
  sitio indexa distinto y una búsqueda por "junior" se come vacantes que sí
  servían. Se trae todo lo de la ubicación y filtra el bot.
- **Una fuente caída no tumba la corrida.** Cada fuente va en su try/except; se
  loguea el error y sigue con las demás. El proceso solo sale con error si
  fallaron *todas*.
- **Si Telegram falla, la vacante no se marca como vista.** Así se reintenta en
  la próxima corrida en vez de perderse en silencio.
- **Mensajes en HTML, no Markdown.** Los títulos reales traen `&`, paréntesis y
  guiones (`FP&A Analyst`, `Support (French, English)`) que rompen el parser
  Markdown de Telegram y hacen fallar el envío con HTTP 400.
- **Scraping respetuoso.** Cron cada 30 minutos, `User-Agent` identificable y
  pausas entre páginas y entre fuentes. Nadie llena una vacante en menos de una
  hora; bajar la frecuencia solo aumenta el riesgo de bloqueo.
- **Secretos por variable de entorno.** Nunca en el repo.

## Notas de ingeniería inversa

Lo que apareció al verificar las fuentes contra los sitios reales:

- **Equifax**: la página pública `/es/trabajos/` acepta `?location=`, `?country=`
  y `?page=`… y los ignora a todos. El filtrado y la paginación son client-side:
  el servidor devuelve siempre las mismas 20 vacantes, sin importar los
  parámetros (verificado: página 1 y página 2 traen exactamente el mismo set).
  Un scraper sobre ese HTML devolvía 3 vacantes de Costa Rica y parecía correcto.
  El sitio publica además un feed XML (`/es/trabajos/xml/`) con el catálogo
  completo: **12 vacantes de Costa Rica en un solo GET**, con ubicación y
  categoría ya estructuradas, y el mismo código de vacante que usa la URL
  pública. El fetcher usa el feed.
- **Workday**: `limit` topa en 20 — pedir 100 devuelve HTTP 400. La paginación
  va por `offset`. El endpoint CXS respondió igual en tres tenants distintos
  (`pg`, `intel`, `3m`), que es lo que lo vuelve plantilla y no un caso puntual.
- **P&G / Phenom**: el `x-csrf-token` no viene en un `<meta>` ni en un header,
  sino **adentro** del cookie `PLAY_SESSION`, que es un JWT — hay que decodificar
  el payload y sacar `data.csrfToken`. Si el POST vuelve vacío o con 403, ese es
  el primer sospechoso.
- **P&G aparece en dos plataformas**: la bolsa es Phenom pero el botón "Aplicar"
  redirige a Workday (`pg.wd5.myworkdayjobs.com`). Ambos fetchers devuelven las
  mismas 2 vacantes de Costa Rica con IDs distintos (`pg-R000151170` vs
  `wd-pg-R000151170`), así que hay que activar **una sola**: el dedupe no puede
  cruzarlas.

### Estado de verificación

| Fuente | Verificado en vivo |
|---|---|
| Equifax (feed XML) | ✅ 12 vacantes en Costa Rica |
| P&G (Phenom) | ✅ 2 vacantes en Costa Rica |
| Workday (tenant `pg`) | ✅ 2 vacantes, mismas que Phenom |
| Greenhouse / Lever / Ashby | ⚠️ código listo, sin empresa real configurada todavía |

## Stack

Python 3, `requests` + `beautifulsoup4` + `PyYAML`. Sin frameworks. SQLite de la
librería estándar. Playwright queda reservado para si alguna fuente resulta ser
JS-pesada-sin-API.

## Estructura

```
run.py                    punto de entrada
config/
  sources.yaml            fuentes y filtros (lo único que se edita a diario)
data/
  seen_jobs.db            vacantes ya vistas (no se versiona)
jobbot/
  cli.py                  orquestador: junta las cuatro piezas
  config.py               .env, rutas y sources.yaml
  filters.py              include / exclude / ubicación
  storage.py              dedupe en SQLite
  notify.py               Telegram
  fetchers/
    __init__.py           registro: type -> función
    ats.py                Greenhouse, Lever y Ashby (API JSON pública)
    equifax.py            feed XML
    phenom.py             Phenom (POST + CSRF adentro de un JWT)
    workday.py            Workday (POST CXS + facets)
    generic_html.py       último recurso: selector CSS
.github/workflows/job-alerts.yml
```

Las carpetas siguen las cuatro piezas de la arquitectura: cada archivo de
`jobbot/` es una de ellas, y `fetchers/` crece a medida que se suman
plataformas. Agregar una bolsa de una plataforma ya soportada **no toca ningún
archivo `.py`** — solo `config/sources.yaml`.
