"""Command line interface: ``python -m cdmx_status`` / ``cdmx-status``."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from typing import Any

from .client import StatusClient


def render(snap: dict[str, Any]) -> str:
    """Human-readable table. Incidents are prefixed with ``!!``."""
    out: list[str] = []
    for line in snap["lineas"]:
        flag = "  " if line["normal"] else "!!"
        out.append(
            f"{flag} {line['sistema']:<24} {line['linea']!s:<12} "
            f"{line['estado']:<24} {line['estaciones_afectadas']:<44} "
            f"{line['informacion_adicional']}".rstrip()
        )
    out.append(
        f"\n{len(snap['lineas'])} líneas — {len(snap['incidencias'])} con incidencia "
        f"— hash {snap['hash']}"
    )
    return "\n".join(out)


def _emit(snap: dict[str, Any], as_json: bool, compact: bool = False) -> None:
    if as_json:
        print(json.dumps(snap, ensure_ascii=False, indent=None if compact else 2), flush=True)
    else:
        print(render(snap), flush=True)


async def _once(as_json: bool) -> int:
    async with StatusClient() as client:
        _emit(await client.snapshot(), as_json)
    return 0


async def _watch(interval: int, as_json: bool) -> int:
    # One client for the whole run: it holds a single JSF session rather than
    # making the server allocate a new one on every poll.
    async with StatusClient() as client:
        last_hash: str | None = None
        while True:
            try:
                snap = await client.snapshot()
                if snap["hash"] != last_hash:
                    print(
                        f"=== {snap['fetched_at']} ({len(snap['incidencias'])} incidencias)",
                        flush=True,
                    )
                    _emit(snap, as_json, compact=True)
                    last_hash = snap["hash"]
            except Exception as exc:  # a transient failure must not kill the loop
                print(
                    f"!! {datetime.now(timezone.utc).isoformat()} {exc}",
                    file=sys.stderr,
                    flush=True,
                )
            await asyncio.sleep(interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cdmx-status",
        description="Live service status for CDMX public transport.",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    parser.add_argument(
        "--watch",
        type=int,
        metavar="SECONDS",
        help="poll forever, emitting only when the status actually changes",
    )
    args = parser.parse_args(argv)

    coro = _watch(args.watch, args.json) if args.watch else _once(args.json)
    try:
        return asyncio.run(coro)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
