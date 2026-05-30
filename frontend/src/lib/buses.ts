import type { BusTrajectory, Trajectories } from '#/api'

// Per-line colors (the GTFS feed paints every line the same green, so we pick a
// readable categorical palette instead). Unknown lines fall back to grey.
// The day palette is tuned for the light basemap; the night palette lifts each
// hue's luminance so the dots stay AA-legible on the dark navy night basemap.
// Classic transit-map palette — well-separated hues for instant line ID.
export const LINE_COLORS: Record<string, string> = {
  '1': '#e2362d', // red
  '3': '#f59e0b', // amber
  '5': '#7c3aed', // indigo
  X4: '#0ea5e9', // cyan
}
// Night = same hues, lifted luminance but kept saturated (not blended toward
// white). Vivid dots read on the dark navy basemap without looking washed out.
export const LINE_COLORS_NIGHT: Record<string, string> = {
  '1': '#ff4d4d', // neon red
  '3': '#ffc02e', // neon amber
  '5': '#9b6bff', // neon indigo
  X4: '#22c3ff', // neon cyan
}
export const LINE_COLOR_FALLBACK = '#94a3b8'
export const LINE_COLOR_FALLBACK_NIGHT = '#b0c0d2'

// Scripted flex buses get their own loud color so they read instantly as "not a
// scheduled line" — a hot magenta none of the line palette uses.
export const FLEX_COLOR = '#ec4899'
export const FLEX_COLOR_NIGHT = '#ff3d9a'

export function lineColor(line: string, night = false): string {
  if (night) return LINE_COLORS_NIGHT[line] ?? LINE_COLOR_FALLBACK_NIGHT
  return LINE_COLORS[line] ?? LINE_COLOR_FALLBACK
}

/** Dot color for a bus — flex buses override their line color. */
export function busColor(
  b: { flex?: boolean | null; line: string },
  night = false,
): string {
  if (b.flex) return night ? FLEX_COLOR_NIGHT : FLEX_COLOR
  return lineColor(b.line, night)
}

export interface BusPos {
  id: string
  line: string
  flex: boolean
  block?: string
  // flex buses only: the leg active right now ("service" | "reposition" |
  // "relief"). "reposition" is the unboardable deadhead back toward Hbf.
  segRole?: string
  // flex buses only: the active leg's GTFS line ("10" | "OUT" | "5")
  segLine?: string
  // true while a flex bus is on its unboardable repositioning leg
  outOfService?: boolean
  lon: number
  lat: number
  angle: number
}

// The flex leg active at `t` — the last segment whose start <= t.
function segAt(bus: BusTrajectory, t: number): { role: string; line: string } | undefined {
  const segs = bus.segments
  if (!segs || segs.length === 0) return undefined
  let active: { role: string; line: string } | undefined
  for (const s of segs) {
    if (t >= s.start) active = s
  }
  return active
}

// Binary search: index of the last point with t <= target (or -1).
function lastAtOrBefore(points: number[][], t: number): number {
  let lo = 0
  let hi = points.length - 1
  let res = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (points[mid][0] <= t) {
      res = mid
      lo = mid + 1
    } else {
      hi = mid - 1
    }
  }
  return res
}

// Shortest-arc interpolation between two compass bearings (degrees).
function lerpAngle(a: number, b: number, f: number): number {
  const d = ((b - a + 540) % 360) - 180
  return (a + d * f + 360) % 360
}

function posForBus(bus: BusTrajectory, t: number): BusPos | null {
  const pts = bus.points
  if (pts.length === 0) return null
  // outside the bus's active span -> not on the map
  if (t < pts[0][0] || t > pts[pts.length - 1][0]) return null
  const i = lastAtOrBefore(pts, t)
  const p = pts[i]
  const q = pts[Math.min(i + 1, pts.length - 1)]
  const span = q[0] - p[0]
  const f = span > 0 ? (t - p[0]) / span : 0
  const seg = bus.flex ? segAt(bus, t) : undefined
  return {
    id: bus.id,
    line: bus.line,
    flex: bus.flex ?? false,
    block: bus.block ?? undefined,
    segRole: seg?.role,
    segLine: seg?.line,
    outOfService: seg?.role === 'reposition',
    lon: p[1] + (q[1] - p[1]) * f,
    lat: p[2] + (q[2] - p[2]) * f,
    angle: lerpAngle(p[3], q[3], f),
  }
}

/** Interpolated position of every bus active at `second` (seconds since midnight). */
export function busPositionsAt(traj: Trajectories, second: number): BusPos[] {
  const out: BusPos[] = []
  for (const bus of traj.buses) {
    const p = posForBus(bus, second)
    if (p) out.push(p)
  }
  return out
}
