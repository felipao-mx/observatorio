# cdmx-status

Live service status for Mexico City's public transport — Metro, Metrobús,
Trolebús, Tren Ligero and Cablebús — as plain Python dictionaries.

Async. All four systems fetched concurrently in ~0.2 s.

This is an unofficial library. It reads the public service-status page at
[incidentesmovilidad.cdmx.gob.mx](https://incidentesmovilidad.cdmx.gob.mx/public/bandejaEstadoServicio.xhtml?idMedioTransporte=stc),
which the Metro, Metrobús and STE websites embed. The page is server-rendered
HTML, and parsing it correctly is harder than it looks — see
[docs/FINDINGS.md](docs/FINDINGS.md) if you want to know why.

## Coverage

| `sistema_id` | System | Lines |
|---|---|---|
| `stc` | Metro | 1–9, 12, A, B |
| `mb` | Metrobús | 1–7 |
| `ste` | Trolebús + Tren Ligero | TE1–TE9, plus 2 unnumbered rows |
| `cb` | Cablebús | 1–3 |

33 rows per snapshot. **Not covered:** Tren Interurbano México–Toluca, Mexibús,
Mexicable, RTP, peseros, and Trolebús lines 10–14 (which STE publishes but the
feed omits).

## Install

```bash
pip install cdmx-status     # once published
```

Not on PyPI yet. For now:

```bash
git clone https://github.com/felipao/cdmx-status-scraper
cd cdmx-status-scraper
uv sync
```

Python 3.9+. Depends on `httpx` and `beautifulsoup4`.

## Usage

### `snapshot()` — all four systems

```python
async with StatusClient() as client:
    snap = await client.snapshot()
```

Returns a dict:

```python
{
    "fetched_at": "2026-08-04T20:09:18.732349+00:00",  # ours, not the server's
    "hash": "05c5a5c854aa",                            # for change detection
    "lineas": [...],                                   # 33 rows, every line
    "incidencias": [...],                              # subset where normal is False
}
```

### `fetch()` — one system

```python
async with StatusClient() as client:
    rows = await client.fetch("stc")
```

Returns a list of rows, healthy ones included:

```python
[
    {
        "sistema": "Metro",
        "sistema_id": "stc",
        "linea": "1",
        "fila": 0,
        "icono": "stc1.svg",
        "estado": "Servicio Regular",
        "estaciones_afectadas": "Ninguna",
        "informacion_adicional": "",
        "normal": True,
    },
    ...  # 12 rows for stc
]
```

The `sistema_id` is one of `"stc"`, `"mb"`, `"ste"` or `"cb"` (see
[Coverage](#coverage)); the full mapping is exported as `SYSTEMS`, and anything
else raises `ValueError`.

Both calls share the same row shape — see [Data shape](#data-shape) for what
each field means.

One client can be reused for repeated polls. Each cold request makes the server
allocate a new session, so a shared client keeps a handful of long-lived ones
rather than creating them every time.

`snapshot()` raises **`IncompleteDataError`** when the server declares more rows
than were parsed, rather than returning a short list — so a partial read
surfaces as an error instead of looking like fewer incidents.

The service showed no rate limiting across five days of five-minute polling. The
practical limit on freshness is how quickly agency staff enter an incident, not
the request rate.

## Data shape

Every row, from either call, has these fields:

| Field | Type | Meaning |
|---|---|---|
| `sistema` | str | Display name, e.g. `"Metrobús"` |
| `sistema_id` | str | `stc` · `mb` · `ste` · `cb` |
| `linea` | str \| None | `"1"`, `"12"`, `"A"`, `"B"`, `"Tren Ligero"`. Not unique — see below |
| `fila` | int | The server's own row index, dense and ordered per system |
| `icono` | str | Icon filename, e.g. `"MB1.png"`. The line number is derived from this |
| `estado` | str | Status text, e.g. `"Obstrucción de carril"`. Free text, open-ended |
| `estaciones_afectadas` | str | Affected segment, e.g. `"Félix Cuevas"`, or `"Ninguna"` |
| `informacion_adicional` | str | Free-text detail, often empty |
| `normal` | bool | `estado == "Servicio Regular"` |

`fetched_at` on a snapshot is generated locally. The page does print an
`Actualización: HH:MM`, but it is the render time of the request rather than a
last-modified, so it cannot be used to detect change — `hash` is provided for
that instead.

## How the data behaves

Observed over five days of continuous polling. Detail in
[docs/OBSERVATIONS.md](docs/OBSERVATIONS.md).

**`linea` is not unique.** One line can carry two simultaneous incidents with
different causes — seen 149 times, and visible on the official page as *"10 de
13"* rows for 12 lines. `fila` (the server's row index) and `estado` are what
distinguish them.

**`estado` is open-ended free text.** 17 distinct phrases appeared in five days,
two of them on the final day, and there is no published list. `normal` is
provided as a convenience: it is simply `estado == "Servicio Regular"`.

**Not everything abnormal is a fault.** `Avance lento por afluencia alta` means
the train is busy rather than broken, and it was the most common
weekday-morning state.

**The feed reports a healthy network while the Metro is closed.** Every line
read `Servicio Regular` overnight, including the 01:00–05:00 shutdown when no
trains run. The feed carries no notion of service hours.

**The table is never empty.** All 33 rows come back on every poll, healthy ones
included, so an absence of incidents is a positive statement rather than missing
data.

**`informacion_adicional` changes without the status changing.** Staff edit the
wording, including fixing and introducing typos (`congesionamiento` →
`congestionamiento`, `Sn Servicio`). Direction (`ambos sentidos`, `dirección
Tepalcates`) appears only in this field, never in `estado`, and its phrasing is
inconsistent.

**Incidents are sometimes cleared in bulk at end of service.** Around
23:00–00:30 several lines may clear in the same minute with *different*
durations, which looks like an administrative sweep rather than each one
recovering. Identical durations in a bulk clear indicate a genuine shared cause,
usually rain.

**Correlated events arrive in waves.** A storm opens lines a few minutes apart,
then clears them all in the same second. The largest observed was 8 Metro lines
opening within five minutes.

**Duration varies by cause; severity does not follow it.** Medians ranged from
10 minutes (object on the tracks) to 240 (road congestion). The most disruptive
event observed — a closed section of Línea 5 with replacement buses — lasted
less than a routine rain slowdown.

## CLI

```bash
cdmx-status                 # table of all 33 lines
cdmx-status --json          # machine-readable
cdmx-status --watch 300     # poll every 5 min, print only on change
```

```
   Metro                    A            Servicio Regular         Ninguna
!! Metrobús                 1            Obstrucción de carril    Félix Cuevas
!! Trolebús / Tren Ligero   1            Manifestación            Bellas Artes - Fray Servando

33 líneas — 4 con incidencia — hash 46acd01f5f08
```

## Development

```bash
make install   # uv sync
make test      # pytest, replaying VCR cassettes offline
make lint      # ruff + ty
make check     # lint + test
```

`make help` lists the rest. Network tests replay from `tests/cassettes`; parser
tests need no network at all.

Early — the public API may still move before `1.0`. Issues and PRs welcome, in
English or Spanish.

## Documentation

- [docs/FINDINGS.md](docs/FINDINGS.md) — how the endpoint behaves, and why the
  parsing looks the way it does
- [docs/OBSERVATIONS.md](docs/OBSERVATIONS.md) — behaviour seen only by
  watching the feed for days: vocabulary growth, duplicate rows, bulk clears

## Disclaimer

Unofficial. Not affiliated with STC Metro, Metrobús, STE or the Gobierno de la
Ciudad de México. It reads a public web page that can change or break without
notice; do not rely on it for safety-critical decisions.

## License

MIT — see [LICENSE](LICENSE).
