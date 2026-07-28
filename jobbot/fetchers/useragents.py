"""
Los dos User-Agent del bot, y por qué son dos.

`BOT_UA` se identifica como lo que es y apunta al repo, que es la forma correcta
de presentarse: si a alguien le molesta el tráfico, sabe quién es y dónde
reclamar. Se usa donde la fuente sirve el contenido sin pelear — un feed público
(Equifax), las APIs abiertas de Greenhouse/Lever/Ashby, o HTML plano.

`BROWSER_UA` es una cadena de Chrome. Se usa solo en las cuatro plataformas que
**rechazan o degradan** una petición que no parezca un navegador: Workday
responde 200 con una página HTML en vez del JSON, y Phenom, Radancy y Amazon
sirven la misma API que consume su propio front-end, que siempre manda esta
cabecera. En esos casos el User-Agent no evade ningún control de acceso: la API
es pública y no pide credenciales; solo evita un rechazo por heurística.

Ninguno de los dos toca robots.txt ni límites de tasa: eso lo maneja cada
fetcher con sus pausas entre páginas. LinkedIn e Indeed quedan fuera del bot a
propósito, porque ahí sí el scraping va contra sus términos.
"""

REPO = "https://github.com/Esteban-PG/Job-Scrapper"

BOT_UA = f"job-alert-bot/1.0 (uso personal; +{REPO})"

BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/149.0.0.0 Safari/537.36")
