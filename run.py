"""
Punto de entrada del bot de alertas de empleo.

    python run.py                    # revisa todo y notifica lo nuevo
    python run.py --dry-run          # muestra qué notificaría, sin mandar nada
    python run.py --source equifax   # corre una sola fuente
    python run.py --no-seed          # con la base vacía, notifica en vez de sembrar
    python run.py -v                 # logging DEBUG

Las fuentes y los filtros están en `config/sources.yaml`.
Las credenciales de Telegram, en `.env` (local) o como variables de entorno.
"""

from jobbot.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
