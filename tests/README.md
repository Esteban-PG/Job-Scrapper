# Tests

```bash
pip install -r requirements-dev.txt
pytest
```

**Ninguno toca la red ni Telegram.** Se pueden correr sin credenciales, sin
conexión y sin miedo a mandarte un mensaje: se prueban las funciones puras y la
base SQLite (siempre contra un archivo temporal, nunca contra
`data/seen_jobs.db`).

Eso deja los fetchers fuera de los tests a propósito: lo que hacen es hablar con
seis sitios que cambian cuando quieren, y un test que dependa de eso falla por
razones que no son culpa del código. Para saber si una fuente sigue viva está el
smoke test manual de cada módulo:

```bash
python -m jobbot.fetchers.moodys      # o equifax, phenom, workday, amazon
```

y, en producción, el aviso de fuente caída (`source_health`), que es justamente
el que cubre ese hueco sin necesidad de un test frágil.

Lo que sí se prueba de los fetchers son sus **funciones puras**: el parseo de
fechas, el armado de ubicaciones, la traducción de países y el decodificado del
JWT de Phenom. Ahí es donde están los bugs sutiles, y no necesitan red.
