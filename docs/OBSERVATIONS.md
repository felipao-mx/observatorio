# How the feed behaves over time

`FINDINGS.md` covers the endpoint's structure and how to parse it. This covers
behaviour that only shows up by watching it for days — things that will shape
any consumer's data model.

Observed 30 July – 3 August 2026, 816 polls at 5-minute intervals across all
four systems, 134 incidents.

Statistics about the transit network itself — incident rates, durations by
cause, weekday and weekend patterns — are deliberately not here. They describe
CDMX, not the library.

---

## 1. The status vocabulary never converged

**17 `estado` phrases** and **37 `informacion_adicional` phrases** after five
days, still growing on the last day.

```
Servicio Regular
Retraso en el servicio
Obstrucción de carril
Congestionamiento vial
Manifestación
Eventos temporales
Intervención en la estación
Estación temporalmente sin servicio
Servicio detenido por recuperación de objeto en vías
Avance lento por lluvia
Avance lento por afluencia alta
Avance lento por revisión de tren
Avance lento por revisión de vías
Avance lento por retiro de tren a talleres
Avance lento por recuperación de objeto en vías
Avance lento por rescate de persona en vías
Avance lento por rescate de animal en vías
```

Four appeared during a single Friday morning; two more appeared on the final
Monday. **Do not hard-code this list.** Any consumer needs a default for
unrecognised phrases, and should decide deliberately whether an unknown phrase
alerts or stays silent.

Two entries deserve special handling:

- **`Avance lento por afluencia alta` is not a fault.** It means the train is
  busy. It is the most common weekday-morning state. Alerting on "anything that
  is not `Servicio Regular`" would notify commuters that rush hour is crowded.
- **`Avance lento por rescate de persona en vías`** is a person on the tracks.
  The wording is identical in form to a minor delay.

---

## 2. Two kinds of bulk clear, and one of them is fake

Thirteen occasions where three or more incidents cleared in the same minute. The
durations tell them apart:

```
30 Jul 19:04   7 cleared   [127.1 ×5, 132.1 ×2]          identical  -> real shared cause
 1 Aug 23:01   4 cleared   [245.2, 415.3, 450.3, 500.4]  all differ -> end-of-day sweep
```

**Identical durations** mean the incidents opened and closed together — a
genuine correlated event, almost always rain.

**Different durations clearing at the same minute** mean someone closed the
leftovers at end of service. That is an administrative action, not a recovery.

Consequence: **a "cleared" event near 23:00–00:30 with a long duration is
probably not service recovering.** Announcing "your line is back to normal" at
23:01 would be wrong.

---

## 3. Correlated events open in stages and close at once

During a storm, lines open in waves a few minutes apart and then all clear in a
single second. The 30 July event opened across two polls (16:52 and 16:57) and
cleared simultaneously at 19:04.

An alerting layer must group nearby events before sending, or a rainy evening
produces several notifications for one storm. Rain hit on **five of the five
days observed**, so this is the normal case, not an edge case.

The largest single event was **8 Metro lines** opening within five minutes on
the evening of 3 August.

---

## 4. One line can carry two incidents at once

**149 `duplicate_line` events**, on Metrobús L1, L2, L3, L7 and Metro L3, L8,
L9. Confirmed against the rendered page: it shows *"10 de 13"* for 12 lines,
with two rows both labelled ⑧.

The two rows carry different causes — for example Metro L8 simultaneously on
`retiro de tren a talleres` and `lluvia`. Metrobús L1 held two rows for three
continuous hours on 3 August, which resolved as two separate incidents of 445
and 185 minutes.

`rows_total` moves between 33 and 35 as this happens. **A data model keyed on
line alone will silently discard incidents**, and one keyed on row position
will report cascades of phantom changes when a row is inserted.

---

## 5. Staff edit the free text, and it is not a status change

**7 `text_edit` events**: the `informacion_adicional` wording changed while the
status and affected segment stayed identical. Observed edits include fixing
`congesionamiento` → `congestionamiento`, and introducing `ambos` → `ambas`.

Typos also arrive first-hand: `Sn Servicio`, `ambas sentidos`.

Comparing whole rows would notify users because somebody corrected a spelling
mistake. Compare `estado` and `estaciones_afectadas`; treat
`informacion_adicional` as display text.

---
