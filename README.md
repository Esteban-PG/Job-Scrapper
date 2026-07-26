# Bot de alertas de empleo

Monitorea varias bolsas de trabajo y avisa por Telegram **apenas aparece una
vacante nueva** que encaje con el perfil buscado (roles junior de ingeniería de
software, análisis de datos o QA, en Costa Rica o remoto).

La idea es reemplazar 15 alertas por correo ruidosas — cada una con su formato,
su frecuencia y su propio ruido — por **un solo feed filtrado**.

```
23:15:48  INFO  equifax             11 vacantes ·   3 nuevas ·   2 notificadas
23:15:51  INFO  pg                   2 vacantes ·   0 nuevas ·   0 notificadas
23:15:53  INFO  cisco                4 vacantes ·   1 nueva  ·   1 notificada
23:15:56  INFO  hpe                 20 vacantes ·   2 nuevas ·   1 notificada
23:15:58  INFO  moodys              22 vacantes ·   3 nuevas ·   2 notificadas
23:16:00  INFO  amazon               8 vacantes ·   1 nueva  ·   1 notificada
23:16:00  INFO  total: 67 vacantes · 9 nuevas · 6 notificadas · 6/6 fuentes ok
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
| Phenom | endpoint `/widgets` | POST + token CSRF | ✅ verificada en vivo (P&G, Cisco, HPE) |
| Equifax | feed XML propio | 1 GET al feed | ✅ verificada en vivo |
| Radancy / TalentBrew | assets en `tbcdn.talentbrew.com` | GET con HTML adentro del JSON | ✅ verificada en vivo (Moody's) |
| Amazon | `amazon.jobs/api/jobs/search` | 1 POST, sin token | ✅ verificada en vivo |
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
python jobbot/fetchers/phenom.py    # P&G, Cisco y HPE
python jobbot/fetchers/workday.py
python jobbot/fetchers/radancy.py   # Moody's
python jobbot/fetchers/amazon.py
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

  - type: cisco                    # preset Phenom, igual que `pg` y `hpe`
    countries: ["Costa Rica"]

  - type: moodys                   # preset Radancy
    countries: ["Costa Rica"]

  - type: amazon                   # amazon.jobs; acepta nombre o ISO-2 ("CR")
    countries: ["Costa Rica"]
    categories:                    # opcional; omitir = las técnicas por defecto
      - "Software Development"     # `categories: []` = todas
      - "Operations, IT, & Support Engineering"
```

Las bolsas Phenom que ya tienen preset (`pg`, `cisco`, `hpe`) son una línea. Para una
Phenom nueva va `type: phenom` con los valores que se ven en el POST a
`/widgets` (`site`, `page_id`, `ref_num`, `id_prefix`); el ejemplo completo está
comentado en `config/sources.yaml`.

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
- **Amazon es la excepción, y filtra por categoría en el origen.** Publica tanto
  fuera de ingeniería que traer todo son 73 vacantes de Costa Rica para quedarse
  con 8. La diferencia con filtrar por palabra clave es que la **categoría es un
  campo estructurado del propio ATS**, no una búsqueda de texto: no se come
  títulos por cómo estén redactados. Aun así conviene ser generoso con la lista
  — "Software Development" sola trae 1 vacante, porque Amazon clasifica casi
  toda la ingeniería bajo "Operations, IT, & Support Engineering".
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
  el primer sospechoso. En Cisco el mismo token aparece **también plano en el
  HTML**; el fetcher prueba el JWT primero y cae al HTML si no está.
- **Phenom es la misma API para todos**: P&G, Cisco y HPE comparten endpoint,
  flujo de token y forma de respuesta; lo que cambia son cuatro campos del
  payload (`pageId`, `pageName`, `pageType`, `refNum`), el idioma/mercado del
  sitio (HPE corre en `en_us`/`us`, los otros en `en_global`/`global` — no
  limita las vacantes a EE.UU., el país lo sigue filtrando `selected_fields`) y
  alguna rareza suelta (P&G manda un bloque `locationData` de slider que los
  otros no tienen). Por eso el fetcher está parametrizado y cada empresa es un
  preset de la misma función.
- **Radancy / Moody's: el filtro de ubicación es todo-o-nada.** Solo se aplica
  si van los **cinco** parámetros juntos (`Location`, `LocationPath`,
  `Latitude`, `Longitude`, `LocationType=2`). Con cualquier combinación parcial
  la API **no falla**: devuelve el catálogo global — 251 vacantes en vez de 22.
  Probé las cinco combinaciones para confirmarlo. Como `location_hints` incluye
  "remote", ese fallo silencioso habría metido vacantes remotas de cualquier
  país, así que el fetcher **revalida localmente** que cada vacante mencione el
  país y avisa por log si tuvo que descartar algo. Verificado rompiendo el
  filtro a propósito: devuelve las 22 correctas y loguea el aviso.
- **Radancy filtra por nodo geográfico**, no por nombre: Costa Rica es
  `LocationPath=3624060` (GeoNames) más sus coordenadas. Un ID inválido también
  cae en el catálogo global en silencio, así que los de `COUNTRY_GEO` están
  verificados uno por uno contra Moody's.
- **Amazon** no usa un ATS de terceros, tiene el suyo (`sourceSystem:
  JobCreator`), pero la API es la más simple de todas: un POST sin token ni
  cookies y `size: 100` trae las 73 de Costa Rica de una. Dos trampas: en
  `searchHits[].fields` **cada valor viene envuelto en una lista de un
  elemento** (`"title": ["Designer, …"]`), y el campo `urlNextStep` **no sirve
  de enlace** — apunta a `account.amazon.jobs/…/apply`, que redirige a la
  pantalla de login. La página pública es `www.amazon.jobs/en/jobs/<icimsJobId>`.
- **Las categorías de Amazon engañan.** "Software Development" tiene **1**
  vacante en Costa Rica; los *Incident Management Engineer* y el *AV Deployment
  Engineer* viven en "Operations, IT, & Support Engineering", y los de datos en
  "Business Intelligence". Un nombre mal escrito no da error: devuelve cero en
  silencio. Para ver los nombres exactos con su conteo:
  `python -m jobbot.fetchers.amazon --categorias`.
- **Amazon filtra por código ISO-2** (`CR`), no por nombre. El fetcher traduce
  `countries: ["Costa Rica"]` para no romper el contrato del resto de las
  fuentes, y si el país no está en su tabla lo dice con un error claro en vez de
  traer el mundo entero. Además `normalizedLocation` termina en el ISO-3
  (`"Heredia, Heredia, CRI"`), así que la ubicación se rearma con el nombre del
  país para que `location_hints` tenga contra qué matchear.
- **Vacantes multi-ubicación (HPE)**: 8 de las 20 de Costa Rica tienen la sede
  principal en Texas, India o México y Heredia como sede adicional. El filtro de
  país de la API **sí** las devuelve bien, pero `cityStateCountry` muestra solo
  la principal, así que el `location_hints` del bot las descartaría. Peor: el
  array `multi_location` lista las ciudades **sin el país**
  (`"Heredia, Heredia, 400803"`), o sea que no hay de dónde leer "Costa Rica".
  Como el filtro lo aplicó la API, el fetcher anota la ubicación como
  `Spring, Texas, … (+2 ubicaciones, incluye Costa Rica)`.
- **Cisco**: `pageName`/`pageType` describen desde qué página busca la UI y
  **no cambian los resultados** (verificado: buscar desde la categoría "Product
  and Engineering" o desde el buscador global devuelve lo mismo); el filtro real
  es `selected_fields`. `size` acepta 100 sin quejarse, al revés que Workday. El
  `x-csrf-token` resultó **opcional**: el endpoint responde 200 sin él, pero se
  manda igual para replicar al navegador.
- **P&G aparece en dos plataformas**: la bolsa es Phenom pero el botón "Aplicar"
  redirige a Workday (`pg.wd5.myworkdayjobs.com`). Ambos fetchers devuelven las
  mismas 2 vacantes de Costa Rica con IDs distintos (`pg-R000151170` vs
  `wd-pg-R000151170`), así que hay que activar **una sola**: el dedupe no puede
  cruzarlas. Cisco (`cisco.wd5/Cisco_Careers`) y HPE (`hpe.wd5/Jobsathpe`) son
  el mismo caso: si algún día se agregan como `type: workday`, hay que sacar el
  preset de Phenom correspondiente.

### Estado de verificación

| Fuente | Verificado en vivo |
|---|---|
| Equifax (feed XML) | ✅ 11 vacantes en Costa Rica |
| P&G (Phenom) | ✅ 2 vacantes en Costa Rica |
| Cisco (Phenom) | ✅ 4 vacantes en Costa Rica (de 1023 globales) |
| HPE (Phenom) | ✅ 20 vacantes en Costa Rica (de 1061 globales), 8 multi-sede |
| Moody's (Radancy) | ✅ 22 vacantes en Costa Rica (de 251 globales) |
| Amazon (ATS propio) | ✅ 8 vacantes técnicas en Costa Rica (73 sin filtrar por categoría) |
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
    amazon.py             amazon.jobs (POST sin token)
    equifax.py            feed XML
    phenom.py             Phenom (POST + CSRF en un JWT) + presets P&G/Cisco/HPE
    radancy.py            Radancy/TalentBrew (HTML adentro del JSON) + Moody's
    workday.py            Workday (POST CXS + facets)
    generic_html.py       último recurso: selector CSS
.github/workflows/job-alerts.yml
```

Las carpetas siguen las cuatro piezas de la arquitectura: cada archivo de
`jobbot/` es una de ellas, y `fetchers/` crece a medida que se suman
plataformas. Agregar una bolsa de una plataforma ya soportada **no toca ningún
archivo `.py`** — solo `config/sources.yaml`.
