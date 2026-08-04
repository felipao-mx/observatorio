"""Read live service status for Mexico City's public transport network.

Metro, Metrobús, Trolebús, Tren Ligero and Cablebús all publish their service
status through one shared (undocumented) government endpoint. This library
fetches it, works around its quirks, and hands back plain dictionaries.

    import asyncio
    from observatorio import StatusClient

    async def main():
        async with StatusClient() as client:
            snap = await client.snapshot()
            for line in snap["incidencias"]:
                print(line["sistema"], line["linea"], line["estado"])

    asyncio.run(main())

Reuse one client across polls -- it keeps a single upstream session and fetches
the four systems concurrently.

See ``docs/FINDINGS.md`` for how the endpoint behaves and why the quirks exist.
"""

from .client import (
    BASE,
    SYSTEMS,
    IncompleteDataError,
    StatusClient,
)

__all__ = [
    "BASE",
    "SYSTEMS",
    "IncompleteDataError",
    "StatusClient",
    "__version__",
]

__version__ = "0.1.0"
