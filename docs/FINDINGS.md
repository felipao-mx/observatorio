# CDMX transit service status — investigation findings

Investigated 2026-07-28/29. Everything below was verified against the live
service, not inferred from docs.

This document covers **how the endpoint behaves** and why the parser is shaped
the way it is. For behaviour observed over time — vocabulary growth, duplicate
rows, bulk clears — see [OBSERVATIONS.md](OBSERVATIONS.md).

---

## 1. The three agency pages share one backend

The starting hypothesis was that these three pages look alike because they share
a service:

- `https://www.metro.cdmx.gob.mx/la-red/estado-del-servicio`
- `https://www.metrobus.cdmx.gob.mx/ServicioMB`
- `https://www.ste.cdmx.gob.mx/estado-de-servicio`

Confirmed, and more strongly than expected: the agency pages contain **zero**
`<table>` elements. Each one is just an `<iframe>` around a single shared app:

```
https://incidentesmovilidad.cdmx.gob.mx/public/bandejaEstadoServicio.xhtml?idMedioTransporte=<sys>
```

| Embedding site | `idMedioTransporte` | Covers | Rows |
|---|---|---|---|
| metro.cdmx.gob.mx | `stc` | Metro | 12 |
| metrobus.cdmx.gob.mx | `mb` | Metrobús | 7 |
| ste.cdmx.gob.mx | `ste` | Trolebús + Tren Ligero | 11 |
| ste.cdmx.gob.mx | `cb` | Cablebús | 3 |

The STE page embeds **two** iframes — Cablebús has its own `idMedioTransporte`,
it is not folded into `ste`.

The iframe lives at `main > .Panel-elements .Text > iframe#iFrameEstatus`. The
three agency sites also run the same CMS (identical `/themes/base/assets/js/dist/framework.js?v=2.8.0`),
which is why the surrounding chrome matches too.

### Access

No auth, no API key, no Referer check — `curl` works directly. Returns HTTP 200
with live data. `robots.txt` does not exist (the 404 page itself declares
`<meta name="robots" content="all">`), so no crawl restriction is published.

CSP is `frame-ancestors 'self' *.cdmx.gob.mx`, which only restricts embedding,
not fetching.

---

## 2. Stack

PrimeFaces 12 / Jakarta Faces on nginx, behind a JBoss-style backend
(`JSESSIONID=...incidentesmovilidad-prod`).

**There is a REST layer, but it is closed.** `/rest` returns `401`, while every
other path probed (`/api`, `/api/v1/estadoServicio`, `/public/*.json`,
`/swagger-ui.html`, …) returns `404`. The 401-vs-404 distinction says something
real is mounted at `/rest` behind auth. Scraping the HTML is the only public
path today — but this makes it worth emailing SEMOVI to ask for credentials or
a documented feed.

---

## 3. Trap: server-side pagination silently drops lines

**This is the one that will bite you.** The table is a PrimeFaces DataTable
paginated server-side at 10 rows/page. A plain `GET` returns only page 1.

The consequences are not cosmetic:

- **Metro**: 12 lines, but a naive GET returns 10. **Líneas A and B are on page 2**
  and vanish entirely.
- **STE**: 11 rows, so one row is lost the same way.

The true count is in the widget config embedded in the page:

```js
PrimeFaces.cw("DataTable","widget_frmEstadoServicio_tblEstadoServicio",{
  paginator:{ rows:10, rowCount:12, page:0, ... }
});
```

Parse `rowCount`, then request the remaining pages with the PrimeFaces paginate
AJAX call — a `POST` to the same URL carrying the `ViewState` from the GET:

```
jakarta.faces.partial.ajax=true
jakarta.faces.source=frmEstadoServicio:tblEstadoServicio
jakarta.faces.partial.render=frmEstadoServicio:tblEstadoServicio
frmEstadoServicio:tblEstadoServicio_pagination=true
frmEstadoServicio:tblEstadoServicio_first=10
frmEstadoServicio:tblEstadoServicio_rows=10
jakarta.faces.ViewState=<from the GET>
```

The response is `text/xml` with the new rows inside
`<update id="frmEstadoServicio:tblEstadoServicio"><![CDATA[ … ]]></update>`.

**`_rows=100` to grab everything in one request does not work.** JSF rejects a
page size outside the declared range and re-renders the whole `ViewRoot`
instead of the table fragment — you get a 11 KB payload with no rows in it.

---

## 4. Trap: the line number is not in the HTML text

No text cell contains the line identity. It exists **only** in the row's icon
filename:

```html
<td><img src="/jakarta.faces.resource/img/iconos/lineas/MB3.png.xhtml?v=eb689f0"></td>
<td>Retraso en el servicio</td>
<td>Línea Completa</td>
<td>Marcha lenta en el corredor…</td>
```

Naming per system: `stc1.svg … stc12.svg`, plus **`stca.svg` / `stcb.svg`** for
Líneas A and B; `MB1–MB7.png`; `TE1–TE9.png`; `CB1–CB3.png`.

Two things follow:

1. The regex must **not assume digits** — Metro's A and B are letters. A
   digits-only pattern drops them even after you fix pagination.
2. Rows with no line icon fall back to the system icon
   (`/transportes/ste.png`). STE has **two** such rows and the feed gives no
   way to tell them apart — presumably Tren Ligero and one other unnumbered
   service. Trolebús itself only appears as TE1–TE9 despite the STE site
   listing 14 lines. **Unresolved; needs a second source.**

   Checked against the rendered page (2026-07-30): rows 10 and 11 both display
   the plain blue STE logo, with no number and no distinguishing text. So the
   ambiguity is in the source, not in the parser — a person reading the
   official page cannot tell them apart either.

   Because of this, **`linea` is not a unique key.** Each row therefore carries
   `fila`, the server's own `data-ri` row index, which is the only stable
   handle on those two rows. It stays dense and ordered across the pagination
   boundary (the last STE row comes from page 2).

   **One of the two is probably a duplicate.** CDMX has exactly one Tren Ligero
   line — Línea 1, Tasqueña–Xochimilco, 18 stations; the three further lines in
   the press are still only studies. And the two rows are byte-for-byte
   identical in the HTML apart from `data-ri` and the odd/even stripe class:
   same icon, same status, same empty cells.

   Not proven, because one alternative fits equally well: STE's own site lists
   Trolebús **L1–L14** while the feed carries only TE1–TE9, so a line present in
   their database without an icon file would fall back to the same system logo
   and be indistinguishable.

   The distinguishing test — track `fila=9` and `fila=10` separately and see
   whether they ever differ — ran for five days and **they never diverged**.
   That is consistent with a duplicate, but weak: STE produced only one
   incident in the whole period, so the two rows had almost no opportunity to
   differ. Still unresolved.

---

## 5. Trap: "Actualización: HH:MM" is not a last-modified

The page prints a date and an update time:

```html
<label …>29 julio 2026</label>
<label …>Actualización: </label><label …>00:03</label>
```

It is **render time** — `now()` at request. Verified across fetches: it read
`23:54` when fetched at 23:54 and `00:04` when fetched at 00:04.

So it cannot tell you whether anything changed, and cannot be used to skip work
or measure feed freshness. Hash the parsed rows and diff instead — that is what
`snapshot()["hash"]` is for.

There is also no `p:poll` widget on the page, so it never auto-refreshes; the
polling cadence is entirely yours to choose.

---

## 6. Polling feasibility — measured

A full snapshot of all four systems:

| Metric | Value |
|---|---|
| Requests | 6 (4 GET + 2 paginate POST) |
| Payload | ~66 KB (no gzip; server ignores `Accept-Encoding`) |
| Wall time | ~0.5 s |

Extrapolated:

| Interval | Requests/day | Ingress/day |
|---|---|---|
| every 5 min | 1,728 | ~19 MB |
| every 10 min | 864 | ~9.5 MB |

**No rate limiting observed.** A burst of 12 rapid GETs returned 200 every time
at a steady ~60 ms, with no 429 and no throttling. Sustained 5-minute polling is
~0.02 req/sec — negligible load.

### Be polite about sessions

Every cold GET makes the server allocate a **new `JSESSIONID`**, which it holds
in memory until session timeout. Naive polling leaks four sessions per cycle.
Reusing the cookie jar fixes this — verified: `Set-Cookie` appears on the first
request and never again. `StatusClient` keeps one jar for its lifetime.

### The real limit is human, not technical

Poll interval is not the bottleneck — **how quickly SEMOVI staff enter an
incident is**. Going below ~5 min buys little against a hand-updated feed.
Suggested cadence: 5 min during rush (05:00–10:00, 17:00–21:00), 15 min
overnight. Halves the volume, loses nothing real.

**Why 5 minutes rather than 10.** The shortest incidents observed ran 10–15
minutes. Measured durations are quantised to the poll interval, so a 10-minute
poll would catch such an incident once or miss it entirely.

---

## 7. Coverage gaps

- **Tren Interurbano México–Toluca is absent** — federal/Edomex, not CDMX. Needs
  its own source.
- **Trolebús shows only TE1–TE9** though STE publishes 14 lines.
- **Two indistinguishable unnumbered STE rows** (see §4).
- **RTP has no `idMedioTransporte`.** It appears in the data only as a substitute
  operator mentioned in free text when a Metro section closes, never as a system
  of its own.
- **No notion of service hours.** Every line reads `Servicio Regular` overnight,
  including the 00:00–05:00 Metro shutdown. The feed does not blank out or
  freeze; it clears the last incidents and then describes a normal network with
  no trains running.
- **The `estado` vocabulary is open-ended** — 17 phrases over five days and
  still growing on the last one, with no published enumeration. See
  [OBSERVATIONS §1](OBSERVATIONS.md).

---

## 8. Parsing strategy

Deliberate split, since it comes up in review:

**BeautifulSoup** (`html.parser` backend) for anything that is HTML structure —
walking `tr[data-ri]` → `td`, reading text, pulling the `ViewState` input.

The backend is pinned to `html.parser` **on purpose**. The pagination AJAX
response returns bare `<tr>` fragments with no enclosing `<table>`;
`html.parser` preserves them, while `lxml` and `html5lib` apply HTML
table-context fixup and silently discard orphan rows. Verified.

**Regex** for the two targets that are *not* HTML:

- `rowCount` lives inside a JavaScript object literal in a `<script>` block, so
  a DOM parser only gets you as far as the script text.
- The line identity is a substring of an icon *filename* in a URL.

**`xml.etree`** for the JSF `partial-response` envelope, to pull the CDATA
payload out of `<update id="…">`.

---

## 9. Trap: ViewState does not survive concurrent requests on one session

Fetching the four systems concurrently is the obvious optimisation (0.5 s →
0.16 s). Doing it over a **shared** HTTP session is a trap.

JSF `ViewState` is scoped to the session's logical-view store. Four concurrent
`GET`s on one `JSESSIONID` create four views in that store and evict each
other's entries, so by the time a system issues its pagination `POST`, its
`ViewState` may already be gone. JSF answers an expired view by re-rendering
the whole `ViewRoot` — the same response signature as the `_rows=100` failure
in §3 — and the table fragment is simply absent.

Measured: **roughly 1 snapshot in 10 failed**, intermittently, always on
whichever system lost the race.

This is nasty precisely because it is silent and partial. The affected system
returns its 10 first-page rows and nothing else, which looks like perfectly
valid data unless you are checking against `rowCount`.

Two consequences baked into the client:

1. **One session per system.** Each `idMedioTransporte` gets its own
   `httpx.AsyncClient`, so there is no shared view store and no race. Still
   fully concurrent; still only four long-lived sessions when the client is
   reused across polls. 25/25 clean after the change.
2. **`IncompleteDataError` when parsed rows disagree with `rowCount`.** This is
   what surfaced the bug in the first place. Any scraper of this endpoint
   should compare against the declared count rather than trusting what it got.

Note the earlier verification that concurrency was "safe" was incomplete: it
confirmed the four concurrent `GET`s return correct per-system data, which they
do, but never exercised the `POST` that depends on the `ViewState` those GETs
hand out.

---

## 10. Metrobús publishes planned work the feed never shows

`metrobus.cdmx.gob.mx/ServicioMB` carries two static HTML tables alongside the
status iframe. Neither appears in `incidentesmovilidad`, and **neither Metro
nor STE publishes an equivalent** — both those pages contain zero tables.

**Estaciones en mantenimiento** — scheduled station closures, published months
ahead. Columns: `Periodo de Cierre | Línea | Estación | Dirección / Sentido |
Motivo`. As of 2026-08-01 it listed 14 entries running to 20 November, working
weekend by weekend down Línea 2 and then Línea 3 for tactile-guide maintenance.

This is forward-looking data, which nothing else here is. It also verifies
against the live feed: the schedule listed `1 y 2 de agosto · L2 · De la Salle`
and the feed opened `Intervención en la estación` at De la Salle at 09:31 on
1 August. A consumer reading the schedule could have warned users days earlier.

**Escaleras y elevadores** — escalator and lift outages, with direction and an
estimated repair date. This is accessibility information, and no other source
found in this investigation carries it.

Caveats:

- Dates are free-text Spanish and **carry no year**: `1 y 2 de agosto`,
  `8 y 9 agosto` (missing "de"), `7 al 20 de noviembre` (a range, not a pair),
  `Por definir` (open-ended). The missing year is ambiguous across a
  December/January boundary.
- The escalator table has **no header row** and was pasted from a spreadsheet
  (`data-sheets-root` in the markup), so its structure is fragile and likely to
  change whenever someone re-pastes it.
- Metrobús only. Planned Metro closures, which do happen, are not published in
  any machine-readable place found so far.

---

## 11. Testing

Cassette-based, via `vcrpy` + `pytest-vcr`, replayed offline.

Two configuration details are load-bearing:

- **Do not match on request body.** Both the `ViewState` and the session cookie
  rotate on every recording, so body matching invalidates every cassette the
  moment it is re-recorded. `method + scheme + host + port + path + query` is
  enough — the only `POST`s are the pagination calls, one per system, each
  carrying its own `idMedioTransporte`.
- **`filter_headers` only scrubs requests.** The response `Set-Cookie` carries a
  `JSESSIONID` and needs a separate `before_record_response` hook, or you commit
  live session tokens to the repo.

`VCR_RECORD_MODE=none` makes any unrecorded request a hard failure; CI should
set it. To re-record, delete the cassette and rerun.

Note `pytest-vcr` is minimal and last released in 2019 — it reads the
`vcr_config` fixture and provides no CLI flags. If a `--record-mode` switch or
active maintenance is wanted later, `pytest-recording` is the drop-in
alternative with the same `@pytest.mark.vcr`.

---

## Sample output

```
   Metro                    A            Servicio Regular         Ninguna
   Metro                    B            Servicio Regular         Ninguna
!! Metrobús                 1            Obstrucción de carril    Félix Cuevas          Sin servicio en sentido sur
!! Metrobús                 2            Retraso en el servicio   Línea Completa        Retraso en el servicio por manifestantes
!! Trolebús / Tren Ligero   1            Manifestación            Bellas Artes - Fray Servando Teresa de Mier

33 líneas — 4 con incidencia — hash 46acd01f5f08
```
