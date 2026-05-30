# Omnibus — Devpost Submission

## Elevator pitch / tagline

**Primary tagline:**

> **Omnibus — every bus is already a sensor. We turn a year of RVV telemetry into tomorrow's demand map, and send buses where the timetable doesn't.**

Shorter alternatives:

- *"The demand the timetable can't see."*
- *"Same fleet. Smarter where-and-when."*
- *"We mine dwell time into day-ahead demand — then schedule flex buses to the pulses."*

---

## Project story

### Inspiration

RVV runs a fixed timetable sized for the morning rush. But demand *moves* through the day — quiet corridors get full buses, busy stops get none, and big events (Jahn home games, the Dult, Bürgerfest) flood specific stops at predictable times. The catch: RVV has **no passenger-count data** to see any of this. We asked a stubborn question — *can you measure demand you were never given?* — and realized the answer was hiding in plain sight. Every bus that pauses at a stop is already telling you how many people are waiting.

### What it does

Omnibus reads a full year of RVV bus telemetry and produces a **day-ahead demand map** for Regensburg. For any future date it predicts, stop by stop and quarter-hour by quarter-hour, where pressure will build — a calm "normal day" baseline plus the spikes that events pile on top. You can scrub through the day on a map and watch demand bloom and fade, and open any event to see its demand curve rise before kickoff and crest after the final whistle. On top of that surface, a **flex-bus scheduler** proposes on-demand buses aimed exactly at the pulses the fixed timetable misses — same fleet, pointed where the people actually are.

### How we built it

The core trick is using **dwell time as a demand proxy**: the longer a bus sits with its doors open, the more people are boarding. We aggregate that signal over a whole year into a stable pattern per stop, time, and day of week — noise averages out, structure emerges. A model learns the event-free "normal day," and a separate event layer adds directional bumps (people flowing *toward* a venue before, *away* after). The result is published as clean data the map and scheduler both read, then visualized on an interactive Regensburg map with a time scrubber, per-event curves, and proposed flex routes.

### Challenges we ran into

- **No ground truth.** Without passenger counts, we couldn't simply train on demand — we had to *invent* a credible proxy and stay honest that it's a relative index, not headcounts.
- **Messy real-world data.** German column names, UTF-16 encoding, phantom stops where doors never opened, operating days longer than 24 hours — a lot of careful plumbing before any insight.
- **Separating signal from event.** Teaching the baseline to ignore event days so the event layer wouldn't double-count.
- **Making it legible.** Turning a 300-stop × 96-tick surface into something a judge can *feel* in fifteen seconds on a map.

### Accomplishments that we're proud of

- We measured demand nobody handed us — from data that wasn't designed to carry it.
- A genuine day-ahead prediction, not a replay of historical averages.
- An event engine that captures the inbound/outbound *shape* of a crowd, directionally.
- A demo you can scrub: watch a Jahn matchday light up the map and the scheduler respond.

### What we learned

- The most valuable signal in a dataset is often not the column you were looking for.
- A simple, honest proxy beats a precise-looking number built on data you don't have.
- Constraints sharpen ideas — "no APC data" is exactly what made this project interesting.

### What's next for Omnibus

- Tighter event curves and more event types in the library.
- Feeding the demand surface into a richer flex-bus scheduler that matches idle vehicle slack to pulses automatically.
- Validating the dwell-time proxy against any real counts RVV can share.
- Extending beyond events to recurring weekly patterns — and beyond Regensburg to any operator sitting on the same untapped telemetry.

---

## Built with

- **Data & modeling:** Python data pipeline; a machine-learning model that learns "normal day" demand patterns; an event-curve engine for crowd spikes.
- **The core data source:** a full year of **RVV bus telemetry** (dwell times) — plus external context layers: **weather, daylight, public & school holidays, university calendars, and local Regensburg events.**
- **Maps & geography:** **RVV GTFS** transit data for stops and lines; map-based visualization of Regensburg.
- **Web app:** an interactive **TanStack Start** frontend — map, demand heatmap, time scrubber, per-event curves, flex-route overlays.
- **Backend:** a lightweight **FastAPI** service serving the demand data to the app.
- **External APIs:** Open-Meteo (weather/daylight), Open-Holidays-API; OSRM for routing.
