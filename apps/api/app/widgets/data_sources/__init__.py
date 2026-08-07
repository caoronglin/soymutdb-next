"""Widget data sources package.

Widget rows store stable identifiers that are resolved through
``data_sources.registry``. Registry handlers are async callables receiving
``(params: dict, db: AsyncSession)`` and returning a dict merged into the
Jinja2 template context.
"""
