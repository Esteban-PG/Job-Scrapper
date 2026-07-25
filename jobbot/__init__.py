"""
Bot de alertas de empleo.

Monitorea varias bolsas de trabajo y avisa por Telegram apenas aparece una
vacante nueva que pase los filtros.

Cuatro piezas desacopladas:
    fetchers/  una por plataforma; devuelven vacantes ya normalizadas
    storage    dedupe en SQLite (qué se vio ya)
    filters    include / exclude / ubicación
    notify     Telegram
    cli        el orquestador que las junta
"""

__version__ = "1.0.0"
