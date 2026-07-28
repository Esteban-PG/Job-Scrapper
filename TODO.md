# TODO — Bot de alertas de empleo

Estado al 24 de julio de 2026. Lo que falta para que el bot quede corriendo solo
y cubriendo las 15 bolsas.

## Dónde quedó

Funcionando y verificado en vivo:

- El paquete `jobbot/` corre: orquestador + 5 fetchers verificados (Equifax,
  Phenom, Workday, Radancy, Amazon), con el proyecto ya organizado en carpetas.
- El fetcher de Phenom quedó **parametrizado** (ver 3.2, ya hecho): P&G, Cisco y
  HPE son presets de la misma función.
- Fuentes y filtros externalizados en `config/sources.yaml`.
- Dedupe en SQLite, logging por fuente, `--dry-run`, `--source`, `--config`,
  `--no-seed`.
- **Aviso por Telegram si una fuente se cae** (y si se recupera), para que el
  silencio del bot no sea ambiguo. Ver 3.6.
- Telegram **probado end-to-end**: el bot **@FlippyJobBot** entregó un mensaje real.
- Workflow de GitHub Actions escrito (`*/30`), con persistencia de la base.

Hoy el bot revisa **6 fuentes** (Equifax + P&G + Cisco + HPE + Moody's +
Amazon) y encuentra 67 vacantes, 34 de las cuales pasan el filtro.

Base local **ya sembrada** con esas 67 y las 34 ya llegaron a Telegram (ver 1.1).

Falta: subirlo, activarlo, y cargarle las otras 9 bolsas.

---

## 1. Dejarlo corriendo (camino crítico, en este orden)

### 1.1 Sembrar la base — hecho

- [x] **Base sembrada el 25 de julio de 2026** con las 67 vacantes de las 6
      fuentes. Se corrió `python run.py --no-seed`, así que las **34 que pasan el
      filtro se enviaron a Telegram** en esa misma corrida (7 Equifax, 4 Cisco,
      7 HPE, 10 Moody's, 6 Amazon) en vez de perderse en el sembrado silencioso.
- [x] Dedupe verificado local: una segunda corrida seguida devolvió `0 nuevas`
      en las 6 fuentes y no mandó nada.
- El flag `--no-seed` quedó en el CLI para el mismo caso a futuro: con la base
  vacía notifica en vez de sembrar en silencio. Con la base ya poblada no hace
  nada, así que es inofensivo dejarlo puesto.

### 1.2 Repo git — hecho

- [x] Repo **público** en https://github.com/Esteban-PG/Job-Scrapper (en repos
      públicos los minutos de Actions son gratis e ilimitados; en privados el
      plan Free da 2000/mes y a `*/30` son ~1440, que entra pero justo).
- [x] Auditado que no se filtró ningún secreto: `.env` **nunca** se commiteó,
      `.env.example` está con los campos vacíos, y no aparece ningún patrón de
      token de Telegram en toda la historia del repo.
- [x] Licencia MIT (`LICENSE`). Sin licencia, un repo público es legalmente
      "todos los derechos reservados" y nadie puede usar el código.

Si algún día hace falta reauditar los secretos:

```bash
git check-ignore -v .env       # tiene que decir que .gitignore lo ignora
git log --all --oneline -- .env    # vacío = nunca se commiteó
```

### 1.3 Activar GitHub Actions

- [ ] Cargar los dos Secrets en *Settings → Secrets and variables → Actions*:
      `TELEGRAM_TOKEN` y `TELEGRAM_CHAT_ID` (los valores están en tu `.env` local).
- [ ] Correr el workflow a mano una vez: pestaña *Actions* → "Alertas de empleo"
      → *Run workflow*. Esa corrida siembra la base y no debería notificar nada.
      **Ojo**: `data/seen_jobs.db` está en `.gitignore`, así que la base sembrada
      local **no viaja al runner** — Actions arranca con la caché vacía y siembra
      de nuevo, en silencio. No vas a recibir las 34 repetidas; lo único que se
      pierde es lo que se publique entre hoy y esa primera corrida.
- [ ] **Verificar que la caché de la base funciona** — es el punto que más fácil
      se rompe y el más silencioso: si falla, la base llega vacía en cada
      corrida, el bot la toma por primera corrida y **siembra en silencio para
      siempre**. No te llega nada nunca más, y parece que simplemente no hay
      vacantes nuevas. Correr el workflow **una segunda vez** a mano y confirmar
      en el log que dice `0 nuevas`. Si dice `sembrando (sin notificar)`, la
      caché no está restaurando y hay que revisar el paso *Restaurar base de
      vistos*.
- [ ] Confirmar que la corrida programada arranca sola en el próximo :00 o :30
      (los cron de GitHub se atrasan; puede tardar unos minutos de más).

---

## 2. Cargar las 9 bolsas que faltan

El bot corre con 6 de las ~15 fuentes ya identificadas. Esta es la tarea de mayor
recompensa que queda.

- [ ] Juntar las URLs de las 9 bolsas restantes.
- [ ] Clasificar cada una mirando la URL, y agregarla a `config/sources.yaml`:

| Si la URL tiene… | `type:` | Params |
|---|---|---|
| `boards.greenhouse.io/<empresa>` | `greenhouse` | `company` |
| `jobs.lever.co/<empresa>` | `lever` | `company` |
| `jobs.ashbyhq.com/<empresa>` | `ashby` | `company` |
| `<tenant>.<dc>.myworkdayjobs.com/<site>` | `workday` | `tenant`, `dc`, `site`, `countries` |
| endpoint `/widgets` (Phenom) | `phenom` | `site`, `page_id`, `ref_num`, `id_prefix`, `countries` |
| …y si es P&G, Cisco o HPE | `pg` / `cisco` / `hpe` | `countries` (preset, todo lo demás ya está) |
| assets de `tbcdn.talentbrew.com` (Radancy) | `radancy` | `site`, `org_id`, `countries` |
| …y si es Moody's | `moodys` | `countries` (preset) |
| `amazon.jobs` | `amazon` | `countries` (nombre o ISO-2), `categories` |
| ninguna de las anteriores | `html` | `url`, `item_selector`, `base_url` |

- [ ] Probar cada fuente nueva sola antes de dejarla fija:
      `python run.py --source <nombre> --dry-run`
- [ ] **Greenhouse, Lever y Ashby siguen sin probarse en vivo** — el código está
      escrito pero nunca corrió contra una empresa real. La primera que agregues
      de esas tres, revisala con `--dry-run` antes de confiar en ella.

### LinkedIn e Indeed (fuera del bot, a propósito)

Bloquean el scraping y va contra sus términos. Quedan resueltos aparte:

- [ ] Crear las alertas nativas por correo en LinkedIn e Indeed.
- [ ] Regla en Gmail que las etiquete/archive en un solo lugar.

---

## 3. Pendientes menores

- [ ] **3.1 — Afinar los filtros** después de unos días de uso real. Están en
      `config/sources.yaml`, no hace falta tocar Python. Mirá sobre todo los falsos
      negativos: si aparece una vacante que te servía y el bot no avisó, casi
      siempre es que el título no matcheaba ningún `include`.
- [x] **3.2 — Generalizar el fetcher de Phenom.** Hecho al agregar Cisco:
      `jobbot/fetchers/phenom.py` expone `fetch_phenom(site, page_id, …)`
      parametrizado igual que `workday.py`, y `fetch_pg`/`fetch_cisco` son
      presets con los valores ya puestos. Una bolsa Phenom nueva se agrega con
      `type: phenom` desde `config/sources.yaml`, sin tocar Python; si se repite
      mucho, conviene darle su preset.
- [ ] **3.3 — Playwright**, solo si alguna bolsa resulta ser JS-pesada-sin-API.
      No hay ningún caso todavía; no adelantarse.
- [x] **3.7 — Tests.** 73 tests en `tests/`, sin red ni Telegram: filtros,
      SQLite (dedupe, umbral de avisos, migración de `source_health`), formato
      de mensajes y funciones puras de los fetchers. Se corren con `pytest`.
      Verificados con mutación: romper la precedencia de `exclude`, el umbral
      de avisos, el escapado de HTML o la migración hace fallar 1, 5, 2 y 13
      tests respectivamente.
- [x] **3.8 — CI que corre los tests** en cada push, PR y a mano
      (`.github/workflows/tests.yml`), sobre Python 3.12 (la de producción) y
      3.14 (la de desarrollo). Sin secrets: ningún test sale a la red. Los tres
      badges del README salen de acá.
- [ ] **3.4 — Limpiar la base cada tanto** (opcional). `data/seen_jobs.db` solo crece.
      Con 15 fuentes tarda años en ser un problema, pero un `DELETE FROM seen
      WHERE ts < ...` de vez en cuando no sobra. **Ojo, hoy no es seguro**: `ts`
      es la primera vez que se vio la vacante y `mark_seen` nunca lo actualiza
      (`INSERT OR IGNORE`), así que borrar lo viejo saca IDs de vacantes que
      **siguen publicadas** y te llegan todas de nuevo. Va junto con el 3.5.
- [ ] **3.5 — `ts` como "última vez vista"** (habilita el 3.4). Que `mark_seen`
      refresque el `ts` de lo que sigue apareciendo y que `already_seen` ignore
      lo más viejo que N días. Con eso la limpieza se vuelve segura y, de paso,
      una vacante que se despublica y **se vuelve a publicar con el mismo ID**
      pasado ese plazo te vuelve a llegar (hoy no: el veto del ID es para
      siempre). Son ~10 líneas en `storage.py` más una constante en `config.py`.
- [x] **3.6 — Avisar cuando una fuente se cae.** Hecho: `source_health` en la
      base, `record_failure`/`record_success` en `storage.py` y el mensaje en
      `notify.py`. Avisa a la segunda corrida fallada seguida
      (`FAIL_ALERT_AFTER`), una sola vez por caída, y avisa también cuando la
      fuente vuelve. Si se caen varias juntas va un solo mensaje. Probado con
      una fuente falsa: silencio en la 1ª falla, aviso en la 2ª, silencio en la
      3ª, aviso de recuperación al volver.

---

## Decisiones abiertas

1. ~~¿Ver las vacantes actuales antes de sembrar?~~ **Resuelto**: se enviaron las
   34 a Telegram y la base quedó sembrada en la misma corrida (ver 1.1).
2. **¿Repo público o privado?** (ver 1.2 — afecta el costo de Actions)
3. **P&G: Phenom o Workday.** Hoy está activo `type: pg` (Phenom) y la entrada de
   Workday quedó comentada en `config/sources.yaml`. Son **la misma bolsa**: el botón
   "Aplicar" de Phenom redirige a `pg.wd5.myworkdayjobs.com`. Devuelven las mismas
   2 vacantes con IDs distintos (`pg-R000151170` vs `wd-pg-R000151170`), así que
   si activás las dos vas a recibir todo duplicado — el dedupe no las puede
   cruzar. Dejar una sola. **Cisco y HPE son el mismo caso** (`cisco.wd5/Cisco_Careers`
   y `hpe.wd5/Jobsathpe`): hoy están activos como Phenom y no hay entrada de
   Workday; si algún día se agrega, sacar una de las dos.

---

## Cosas que ya se investigaron (no volver a pelear con esto)

- **Equifax**: la página `/es/trabajos/` **ignora** `?location=`, `?country=` y
  `?page=` — filtra y pagina por JavaScript, y el servidor devuelve siempre las
  mismas 20 vacantes. El fetcher usa el **feed XML** (`/es/trabajos/xml/`), que
  trae el catálogo completo en un GET. No "arreglar" esto volviendo a scrapear el
  HTML: se pasó de 3 vacantes de Costa Rica a 12.
- **Workday**: `limit` topa en **20** (pedir 100 devuelve HTTP 400); se pagina por
  `offset`. Los IDs de facet de país son GUIDs opacos, pero el fetcher los
  resuelve solo desde el nombre — en `config/sources.yaml` va `countries: ["Costa Rica"]`
  y nada más. Verificado en 3 tenants (`pg`, `intel`, `3m`).
- **Phenom**: el `x-csrf-token` va **adentro** del cookie `PLAY_SESSION`, que es
  un JWT (campo `data.csrfToken`). Si el POST devuelve vacío o 403, ese es el
  primer sospechoso. En Cisco además aparece plano en el HTML, y el endpoint
  responde 200 aunque no se mande — pero se manda igual.
- **Phenom, campos del payload**: `pageId`/`pageName`/`pageType` describen desde
  qué página busca la UI y **no cambian los resultados**; el filtro real es
  `selected_fields`. Se pagina con `from`/`size` y Cisco y HPE aceptan
  `size: 100` (Workday, en cambio, topa en 20). El `lang`/`country` del payload
  es el mercado del **sitio**, no un filtro: HPE corre en `en_us`/`us` y aun así
  devuelve las vacantes de Costa Rica.
- **Phenom, vacantes multi-ubicación**: en HPE, 8 de las 20 de Costa Rica tienen
  la sede principal en otro país (Texas, India, México) y Heredia como sede
  adicional. Salen bien del filtro de país, pero `cityStateCountry` muestra solo
  la principal y `multi_location` lista las ciudades **sin país**, así que el
  fetcher les anota "(+N ubicaciones, incluye Costa Rica)". Si se saca esa
  anotación, el `location_hints` del bot las descarta en silencio.
- **Amazon**: POST a `amazon.jobs/api/jobs/search?is_als=true`, **sin token ni
  cookies** (el `x-api-key` del navegador es opcional). Filtra por **ISO-2**
  (`CR`), no por nombre — el fetcher traduce. En `searchHits[].fields` cada
  valor viene **envuelto en una lista de un elemento**. El `urlNextStep` que
  trae cada vacante **no sirve de enlace**: redirige al login; usar
  `www.amazon.jobs/en/jobs/<icimsJobId>`.
- **Amazon, categorías**: es la única fuente que filtra por categoría en el
  origen (73 vacantes en Costa Rica, 65 fuera de ingeniería). **"Software
  Development" sola trae 1** — casi toda la ingeniería está en "Operations, IT,
  & Support Engineering", y los roles de datos en "Business Intelligence". Un
  nombre mal escrito devuelve cero **sin dar error**; sacalos de
  `python -m jobbot.fetchers.amazon --categories`, que los lista con su conteo.
- **Radancy (Moody's)**: el filtro de ubicación es **todo-o-nada**. Van juntos
  `Location` + `LocationPath` + `Latitude` + `Longitude` + `LocationType=2`, o
  la API devuelve el **catálogo global sin avisar** (251 vacantes en vez de 22).
  Lo mismo con un `LocationPath` inválido. El fetcher revalida el país
  localmente y loguea `[warn] … vacantes descartadas` si eso pasa: **si ves ese
  aviso, el filtro del servidor se rompió**, no es ruido. No "simplificar"
  mandando solo `Location`.
- **Cron de GitHub Actions**: no es puntual y **descarta** corridas bajo carga
  (no las encola). Medido con `*/30` sobre 58 horas: corrió el **29%** de lo
  programado, mediana de 83 min, mínimo 59 min, pico de 3.9 h. Los peores huecos
  cayeron entre 01:00 y 15:00 UTC. Por eso el cron pasó a `7,37 * * * *`: `:00`
  y `:30` son los minutos más congestionados de la plataforma. No hay forma de
  arreglarlo del todo desde el workflow; si alguna vez hiciera falta puntualidad
  real, sería con un disparador externo al `workflow_dispatch`, que es más
  infraestructura de la que esto amerita.
- **Telegram**: los mensajes van en **HTML, no Markdown**. Títulos reales como
  `FP&A Analyst` o `Support (French, English)` rompen el parser Markdown y el
  envío falla con HTTP 400.

## Referencia rápida

```bash
source .venv/bin/activate

python run.py --dry-run             # qué notificaría, sin mandar nada
python run.py --source equifax      # una sola fuente
python run.py -v                    # logging DEBUG
python -m jobbot.fetchers.equifax   # probar un fetcher aislado

# Empezar de cero (¡vuelve a sembrar y no notifica esa corrida!)
rm data/seen_jobs.db
python run.py --no-seed             # …salvo que quieras recibir la tanda inicial
```

Config: `config/sources.yaml` (fuentes + filtros) · Credenciales: `.env` (local) y
Secrets del repo (Actions) · Frecuencia: `.github/workflows/job-alerts.yml`.
