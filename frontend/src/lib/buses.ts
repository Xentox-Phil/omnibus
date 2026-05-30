import type { BusTrajectory, Trajectories } from '#/api'

// Per-line colors (the GTFS feed paints every line the same green, so we pick a
// readable categorical palette instead). Unknown lines fall back to grey.
export const LINE_COLORS: Record<string, string> = {
  '1': '#2563eb', // blue
  '3': '#f97316', // orange
  '5': '#a855f7', // violet
  X4: '#10b981', // emerald
}
export const LINE_COLOR_FALLBACK = '#94a3b8'

// Scripted flex buses get their own loud color so they read instantly as "not a
// scheduled line" — a hot magenta none of the line palette uses.
export const FLEX_COLOR = '#ec4899'

export function lineColor(line: string): string {
  return LINE_COLORS[line] ?? LINE_COLOR_FALLBACK
}

/** Dot color for a bus — flex buses override their line color. */
export function busColor(b: { flex?: boolean | null; line: string }): string {
  return b.flex ? FLEX_COLOR : lineColor(b.line)
}

export interface BusPos {
  id: string
  line: string
  flex: boolean
  block?: string
  lon: number
  lat: number
  angle: number
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
  return {
    id: bus.id,
    line: bus.line,
    flex: bus.flex ?? false,
    block: bus.block ?? undefined,
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
