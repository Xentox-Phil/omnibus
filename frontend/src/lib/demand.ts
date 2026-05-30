import type { DemandSurface, EventCurves, Leg } from '#/api'

// The one day we have artifacts for.
export const DEMO_DATE = '2025-07-28'

// --- stop names -----------------------------------------------------------
// No nodes_meta artifact is built; only these two stops carry demo events.
const STOP_NAMES: Record<string, string> = {
  HBF: 'Hauptbahnhof',
  JAHN: 'Jahnstadion',
}

export function stopName(code: string): string {
  return STOP_NAMES[code] ?? code
}

// --- time helpers ---------------------------------------------------------
export function hhmmToMin(s: string): number {
  const [h, m] = s.split(':').map(Number)
  return h * 60 + m
}

export function minToHHMM(min: number): string {
  const m = ((Math.floor(min) % 1440) + 1440) % 1440
  const h = Math.floor(m / 60)
  const mm = m % 60
  return `${String(h).padStart(2, '0')}:${String(mm).padStart(2, '0')}`
}

export type LightPreset = 'dawn' | 'day' | 'dusk' | 'night'

export function lightPresetForHour(hour: number): LightPreset {
  if (hour < 6 || hour >= 21) return 'night'
  if (hour < 8) return 'dawn'
  if (hour < 18) return 'day'
  return 'dusk'
}

// --- surface interpolation ------------------------------------------------
// The surface is sampled every `resolution_min` (15) minutes. For a smooth,
// "live-adjusted" heatmap we linearly interpolate each node's pressure_norm
// between the two surrounding ticks. Returns one weight (0-1) per node, in
// surface.nodes order (stable — callers build their GeoJSON in the same order).
export function interpolatedWeights(
  surface: DemandSurface,
  minute: number,
): number[] {
  const res = surface.resolution_min || 15
  const last = surface.n_ticks - 1
  const tickF = minute / res
  const t0 = Math.max(0, Math.min(last, Math.floor(tickF)))
  const t1 = Math.min(last, t0 + 1)
  const frac = Math.max(0, Math.min(1, tickF - t0))
  return surface.nodes.map((n) => {
    const a = n.pressure_norm[t0] ?? 0
    const b = n.pressure_norm[t1] ?? a
    return a + (b - a) * frac
  })
}

// --- per-leg live state ---------------------------------------------------
// A leg's implicit x-axis is `leg.start + i * 1min` (events file is 1-min).
export interface LegState {
  active: boolean
  /** 0-1 position of `minute` within [leg.start, leg.end]. */
  progress01: number
  /** index into pressure_s / pressure_norm at `minute` (clamped). */
  sampleIndex: number
  /** the leg's value (0-1, per-leg normalized) at `minute`, 0 if inactive. */
  value: number
}

export function legState(leg: Leg, minute: number): LegState {
  const start = hhmmToMin(leg.start)
  const end = hhmmToMin(leg.end)
  const span = Math.max(1, end - start)
  const progress01 = Math.max(0, Math.min(1, (minute - start) / span))
  const last = leg.pressure_norm.length - 1
  const sampleIndex = Math.max(0, Math.min(last, Math.round(minute - start)))
  const active = minute >= start && minute <= end
  return {
    active,
    progress01,
    sampleIndex,
    value: active ? (leg.pressure_norm[sampleIndex] ?? 0) : 0,
  }
}

export function legDirection(leg: Leg, venue: string): 'inbound' | 'outbound' {
  // inbound = riders flow TO the venue.
  return leg.to === venue ? 'inbound' : 'outbound'
}

// --- event timeline moments (for the notification toast) ------------------
export type MomentKind = 'leg_ramp' | 'kickoff' | 'peak' | 'whistle' | 'leg_end'

export interface EventMoment {
  minute: number
  kind: MomentKind
  eventLabel: string
  message: string
}

function argmax(xs: number[]): number {
  let bi = 0
  let bv = -Infinity
  for (let i = 0; i < xs.length; i++) {
    if (xs[i] > bv) {
      bv = xs[i]
      bi = i
    }
  }
  return bi
}

// Flattened, de-duped, sorted timeline of notable moments across all events.
export function eventMoments(events: EventCurves[]): EventMoment[] {
  const out: EventMoment[] = []
  for (const ev of events) {
    out.push({
      minute: hhmmToMin(ev.event_start),
      kind: 'kickoff',
      eventLabel: ev.label,
      message: `Kickoff ${ev.event_start} — ${stopName(ev.venue)}`,
    })
    out.push({
      minute: hhmmToMin(ev.event_end),
      kind: 'whistle',
      eventLabel: ev.label,
      message: `Final whistle ${ev.event_end} — ${stopName(ev.venue)}`,
    })
    for (const leg of ev.legs) {
      const dir = legDirection(leg, ev.venue)
      out.push({
        minute: hhmmToMin(leg.start),
        kind: 'leg_ramp',
        eventLabel: ev.label,
        message: `${dir === 'inbound' ? 'Inbound' : 'Outbound'} demand ramping at ${stopName(leg.from)}`,
      })
      const peakMin = hhmmToMin(leg.start) + argmax(leg.pressure_s)
      out.push({
        minute: peakMin,
        kind: 'peak',
        eventLabel: ev.label,
        message: `Peak ${dir} demand at ${stopName(leg.from)} (${minToHHMM(peakMin)})`,
      })
    }
  }
  return out.sort((a, b) => a.minute - b.minute)
}
