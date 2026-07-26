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
- Dedupe en SQLite, logging por fuente, `--dry-run`, `--source`, `--config`.
- Telegram **probado end-to-end**: el bot **@FlippyJobBot** entregó un mensaje real.
- Workflow de GitHub Actions escrito (`*/30`), con persistencia de la base.

Hoy el bot revisa **6 fuentes** (Equifax + P&G + Cisco + HPE + Moody's +
Amazon) y encuentra 67 vacantes, 34 de las cuales pasan el filtro.

Falta: subirlo, activarlo, y cargarle las otras 9 bolsas.

---

## 1. Dejarlo corriendo (camino crítico, en este orden)

### 1.1 Sembrar la base — decisión previa

`data/seen_jobs.db` todavía no existe. La primera corrida real siembra las 67 vacantes
actuales **en silencio** (por diseño, para no recibir una avalancha). Efecto
secundario: las **34 vacantes que hoy pasan el filtro nunca te van a llegar**
(7 de Equifax, 4 de Cisco, 7 de HPE, 10 de Moody's y 6 de Amazon).

- [ ] **Decidir**: ¿querés recibir esas 34 una vez antes de sembrar, o arrancar
      limpio y ver solo lo que aparezca de ahora en adelante?
  - Arrancar limpio → `python run.py` (siembra y calla).
  - Verlas primero → pedirlo antes de la primera corrida; después ya no se puede
    sin borrar la base.

### 1.2 Repo git

- [ ] Decidir **público o privado**. No es solo preferencia: en repos privados
      GitHub cobra los minutos de Actions (2000/mes gratis; a `*/30` son ~1440,
      entra justo). **En repos públicos los minutos son gratis e ilimitados**, y
      además este proyecto sirve de portafolio. Recomendado: **público**.
- [ ] Antes del primer commit, confirmar que **no se sube ningún secreto**:

```bash
git init
git add -A
git status --short          # revisar que NO aparezca .env
git check-ignore -v .env    # tiene que decir que .gitignore lo ignora
```

- [ ] Verificar que `.env.example` sigue con los campos **vacíos** (es plantilla y
      sí se sube; las credenciales van en `.env`, que no se sube).
- [ ] Primer commit y push:

```bash
git commit -m "Bot de alertas de empleo: orquestador, 3 fetchers y deploy"
gh repo create job-alert-bot --public --source=. --push
```

### 1.3 Activar GitHub Actions

- [ ] Cargar los dos Secrets en *Settings → Secrets and variables → Actions*:
      `TELEGRAM_TOKEN` y `TELEGRAM_CHAT_ID` (los valores están en tu `.env` local).
- [ ] Correr el workflow a mano una vez: pestaña *Actions* → "Alertas de empleo"
      → *Run workflow*. Esa corrida siembra la base y no debería notificar nada.
- [ ] **Verificar que la caché de la base funciona** — es el punto que más
      fácil se rompe y el más silencioso: si falla, el bot re-notifica todo cada
      30 minutos. Correr el workflow **una segunda vez** a mano y confirmar en
      el log que dice `0 nuevas`. Si dice que sembró de nuevo, la caché no está
      restaurando y hay que revisar el paso *Restaurar base de vistos*.
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
- [ ] **3.4 — Limpiar la base cada tanto** (opcional). `data/seen_jobs.db` solo crece.
      Con 15 fuentes tarda años en ser un problema, pero un `DELETE FROM seen
      WHERE ts < ...` de vez en cuando no sobra.

---

## Decisiones abiertas

1. **¿Ver las 18 vacantes actuales antes de sembrar?** (ver 1.1)
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
  `python -m jobbot.fetchers.amazon --categorias`, que los lista con su conteo.
- **Radancy (Moody's)**: el filtro de ubicación es **todo-o-nada**. Van juntos
  `Location` + `LocationPath` + `Latitude` + `Longitude` + `LocationType=2`, o
  la API devuelve el **catálogo global sin avisar** (251 vacantes en vez de 22).
  Lo mismo con un `LocationPath` inválido. El fetcher revalida el país
  localmente y loguea `[warn] … vacantes descartadas` si eso pasa: **si ves ese
  aviso, el filtro del servidor se rompió**, no es ruido. No "simplificar"
  mandando solo `Location`.
- **Telegram**: los mensajes van en **HTML, no Markdown**. Títulos reales como
  `FP&A Analyst` o `Support (French, English)` rompen el parser Markdown y el
  envío falla con HTTP 400.

## Referencia rápida

```bash
source .venv/bin/activate

python run.py --dry-run             # qué notificaría, sin mandar nada
python run.py --source equifax      # una sola fuente
python run.py -v                    # logging DEBUG
python jobbot/fetchers/equifax.py   # probar un fetcher aislado

# Empezar de cero (¡vuelve a sembrar y no notifica esa corrida!)
rm data/seen_jobs.db
```

Config: `config/sources.yaml` (fuentes + filtros) · Credenciales: `.env` (local) y
Secrets del repo (Actions) · Frecuencia: `.github/workflows/job-alerts.yml`.
