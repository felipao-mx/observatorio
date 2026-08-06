"""Async client and HTML parsing for the CDMX service-status feed.

metro.cdmx.gob.mx, metrobus.cdmx.gob.mx and ste.cdmx.gob.mx do not each have
their own status system -- all three just <iframe> a single PrimeFaces 12 page,
keyed by idMedioTransporte:

    https://incidentesmovilidad.cdmx.gob.mx/public/bandejaEstadoServicio.xhtml?idMedioTransporte=<sys>

See docs/FINDINGS.md for how this was determined and why the code looks the way
it does. The non-obvious parts are called out inline below.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup

BASE = "https://incidentesmovilidad.cdmx.gob.mx/public/bandejaEstadoServicio.xhtml"

SYSTEMS: dict[str, str] = {
    "stc": "Metro",
    "mb": "Metrobús",
    "ste": "Trolebús / Tren Ligero",
    "cb": "Cablebús",
}

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

TBL = "frmEstadoServicio:tblEstadoServicio"
PAGE_SIZE = 10  # server-side page size; not negotiable (see FINDINGS §3)
TIMEOUT = 30.0

# The BeautifulSoup backend is pinned deliberately. The pagination AJAX response
# returns bare <tr> fragments with no enclosing <table>; html.parser preserves
# them, whereas lxml/html5lib apply table-context fixup and silently drop them.
PARSER = "html.parser"

# These stay as regexes on purpose -- neither target is HTML structure.
# rowCount lives inside a JavaScript literal in a <script> block:
#     PrimeFaces.cw("DataTable",...,{paginator:{rows:10,rowCount:12,page:0,...}})
ROWCOUNT = re.compile(r"paginator:\{[^}]*rowCount:(\d+)")
# ...and the line identity exists only inside an icon *filename*:
#     /jakarta.faces.resource/img/iconos/lineas/stca.svg.xhtml
# Note the letter lines (A/B) -- this must not assume digits.
ICON = re.compile(r"/lineas/([a-z]+)([a-z0-9]+)\.(?:svg|png)", re.I)
# Rows with no line icon fall back to the system icon. For `ste` those are the
# unnumbered services; the feed gives no way to tell them apart.
SYS_ICON = re.compile(r"/transportes/([a-z]+)\.(?:svg|png)", re.I)
UNNUMBERED = {"ste": "Tren Ligero"}

REGULAR = "servicio regular"


class IncompleteDataError(RuntimeError):
    """Fewer rows came back than the server said exist.

    Raised rather than returning a short list, because silent truncation is the
    exact failure this library exists to prevent: an unpaginated read drops
    Metro's Líneas A and B without any visible error.
    """


def _cell_text(cells: list[Any], idx: int) -> str:
    """Text of the idx-th cell, or "" when the row is short.

    get_text(strip=True) only trims the ends of each string; upstream cells
    carry newlines and runs of spaces, so collapse those too.
    """
    if len(cells) <= idx:
        return ""
    return " ".join(cells[idx].get_text(" ", strip=True).split())


def _attr(tag: Any, name: str) -> str:
    """Read an attribute as a plain string.

    BeautifulSoup returns a list for attributes it treats as multi-valued
    (``class`` and friends). ``src`` and ``value`` are not among them in
    practice, but the type genuinely is ``str | list[str]``, so narrow it here
    rather than assuming.
    """
    if tag is None:
        return ""
    value = tag.get(name)
    if isinstance(value, list):
        return value[0] if value else ""
    return value or ""


def _parse_rows(markup: str, system: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(markup, PARSER)
    rows: list[dict[str, Any]] = []

    for tr in soup.select("tr[data-ri]"):
        cells = tr.find_all("td")
        if len(cells) < 3:
            continue

        src = _attr(cells[0].find("img"), "src")
        line_match, sys_match = ICON.search(src), SYS_ICON.search(src)
        if line_match:
            linea: str | None = line_match.group(2).upper()  # "1", "12", "A", "B"
        elif sys_match:
            linea = UNNUMBERED.get(system, "sistema")
        else:
            linea = None

        estado = _cell_text(cells, 1)
        rows.append(
            {
                "sistema": SYSTEMS[system],
                "sistema_id": system,
                "linea": linea,
                # The server's own row index. Needed because `linea` is not
                # always unique: STE ends with two rows that both carry the
                # plain system logo and no number, and the published page is
                # equally ambiguous -- a reader cannot tell them apart either.
                # `fila` is the only stable handle on those rows.
                "fila": int(_attr(tr, "data-ri") or -1),
                "icono": src.rsplit("/", 1)[-1].split(".xhtml")[0] if src else None,
                "estado": estado,
                "estaciones_afectadas": _cell_text(cells, 2),
                "informacion_adicional": _cell_text(cells, 3),
                "normal": estado.lower().startswith(REGULAR),
            }
        )
    return rows


def _ajax_fragment(xml: str) -> str | None:
    """Pull the table fragment out of a JSF partial-response envelope."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    for update in root.iter("update"):
        if update.get("id") == TBL:
            return update.text
    return None


class StatusClient:
    """Async reader for the CDMX service-status feed.

        async with StatusClient() as client:
            snap = await client.snapshot()

    Hold on to one instance across polls. Every cold request makes the server
    allocate a JSESSIONID that it keeps in memory until session timeout, so a
    reused client means a handful of long-lived sessions rather than fresh ones
    on every poll.

    Each system gets its **own** session, which is what makes the concurrent
    fetch safe. JSF ViewState is scoped to a session's logical-view store, and
    four concurrent GETs on one shared session evict each other's views -- the
    pagination POST then comes back as an expired-view re-render instead of the
    table fragment. That failed roughly one snapshot in ten, intermittently.
    Per-system sessions remove the shared store, and therefore the race.
    """

    def __init__(self, timeout: float = TIMEOUT) -> None:
        self._timeout = timeout
        self._clients: dict[str, httpx.AsyncClient] = {}

    async def __aenter__(self) -> StatusClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    def _client_for(self, system: str) -> httpx.AsyncClient:
        if system not in self._clients:
            self._clients[system] = httpx.AsyncClient(
                timeout=self._timeout,
                headers={"User-Agent": UA},
                follow_redirects=True,
            )
        return self._clients[system]

    async def aclose(self) -> None:
        """Close every per-system HTTP client."""
        clients, self._clients = list(self._clients.values()), {}
        await asyncio.gather(*(c.aclose() for c in clients))

    async def _paginate(self, system: str, url: str, viewstate: str, first: int) -> str:
        """Fetch one extra page via the PrimeFaces paginate AJAX call.

        _rows must stay at PAGE_SIZE. Asking for a bigger page to get everything
        in one request does not work: JSF rejects an out-of-range page size and
        re-renders the whole ViewRoot instead of the table fragment.
        """
        response = await self._client_for(system).post(
            url,
            data={
                "jakarta.faces.partial.ajax": "true",
                "jakarta.faces.source": TBL,
                "jakarta.faces.partial.execute": TBL,
                "jakarta.faces.partial.render": TBL,
                TBL: TBL,
                f"{TBL}_pagination": "true",
                f"{TBL}_first": str(first),
                f"{TBL}_rows": str(PAGE_SIZE),
                f"{TBL}_encodeFeature": "true",
                "frmEstadoServicio": "frmEstadoServicio",
                "jakarta.faces.ViewState": viewstate,
            },
            headers={
                "Faces-Request": "partial/ajax",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        response.raise_for_status()
        return response.text

    async def fetch(self, system: str) -> list[dict[str, Any]]:
        """Every row for one system, following pagination.

        The table is paginated server-side at 10 rows/page, so a plain GET
        returns page 1 only -- which drops Metro's Líneas A and B (12 rows) and
        one STE row (11 rows). rowCount tells us how many pages to ask for.
        """
        if system not in SYSTEMS:
            raise ValueError(f"unknown system {system!r}; expected one of {sorted(SYSTEMS)}")

        url = f"{BASE}?idMedioTransporte={system}"
        response = await self._client_for(system).get(url)
        response.raise_for_status()
        page = response.text

        rows = _parse_rows(page, system)

        declared = ROWCOUNT.search(page)
        total = int(declared.group(1)) if declared else len(rows)

        soup = BeautifulSoup(page, PARSER)
        viewstate = _attr(soup.find("input", attrs={"name": "jakarta.faces.ViewState"}), "value")

        if viewstate and total > PAGE_SIZE:
            for first in range(PAGE_SIZE, total, PAGE_SIZE):
                fragment = _ajax_fragment(await self._paginate(system, url, viewstate, first))
                if fragment:
                    rows += _parse_rows(fragment, system)

        if len(rows) != total:
            raise IncompleteDataError(
                f"{system}: got {len(rows)} rows but the server declared {total}. "
                "Pagination may have changed -- refusing to return partial data."
            )
        return rows

    async def snapshot(self) -> dict[str, Any]:
        """All four systems, fetched concurrently."""
        results = await asyncio.gather(*(self.fetch(s) for s in SYSTEMS))
        rows = [row for group in results for row in group]
        return {
            # The page prints "Actualización: HH:MM" but it is render time, not
            # a last-modified, so we stamp our own and hash for change detection.
            "fetched_at": datetime.now(UTC).isoformat(),
            "hash": hashlib.sha256(
                json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()[:12],
            "lineas": rows,
            "incidencias": [r for r in rows if not r["normal"]],
        }
