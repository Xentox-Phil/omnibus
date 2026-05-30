import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState
  
} from 'react'
import type {ReactNode} from 'react';

import { minToHHMM } from '#/lib/demand'

export const SPEEDS = [1, 5, 10, 30, 60, 120] as const
export type Speed = (typeof SPEEDS)[number]

const MINUTES_PER_DAY = 1440

export interface SimClock {
  /** minute-of-day, float, 0..1439.99 */
  minute: number
  hhmm: string
  playing: boolean
  speed: Speed
  /** true while the user drags the scrubber (so consumers can pause effects) */
  scrubbing: boolean
  play: () => void
  pause: () => void
  toggle: () => void
  reset: () => void
  setSpeed: (s: Speed) => void
  /** jump to an absolute minute-of-day (used by the scrubber) */
  scrubTo: (minute: number, opts?: { scrubbing?: boolean }) => void
}

const Ctx = createContext<SimClock | null>(null)

export function SimClockProvider({
  children,
  initialMinute = 14 * 60, // 14:00 — just before the match ramp begins
}: {
  children: ReactNode
  initialMinute?: number
}) {
  const [minute, setMinute] = useState(initialMinute)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeedState] = useState<Speed>(30)
  const [scrubbing, setScrubbing] = useState(false)

  // Refs the rAF loop reads without re-subscribing every frame.
  const minuteRef = useRef(minute)
  const speedRef = useRef<number>(speed)
  minuteRef.current = minute
  speedRef.current = speed

  useEffect(() => {
    if (!playing) return
    let raf = 0
    let last = performance.now()
    const tick = (now: number) => {
      const dtSec = (now - last) / 1000
      last = now
      const next =
        (minuteRef.current + dtSec * speedRef.current) % MINUTES_PER_DAY
      minuteRef.current = next
      setMinute(next)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [playing])

  const play = useCallback(() => setPlaying(true), [])
  const pause = useCallback(() => setPlaying(false), [])
  const toggle = useCallback(() => setPlaying((p) => !p), [])
  const reset = useCallback(() => {
    minuteRef.current = initialMinute
    setMinute(initialMinute)
    setPlaying(false)
  }, [initialMinute])
  const setSpeed = useCallback((s: Speed) => setSpeedState(s), [])
  const scrubTo = useCallback(
    (m: number, opts?: { scrubbing?: boolean }) => {
      const clamped = ((m % MINUTES_PER_DAY) + MINUTES_PER_DAY) % MINUTES_PER_DAY
      minuteRef.current = clamped
      setMinute(clamped)
      if (opts?.scrubbing !== undefined) setScrubbing(opts.scrubbing)
    },
    [],
  )

  const value: SimClock = {
    minute,
    hhmm: minToHHMM(minute),
    playing,
    speed,
    scrubbing,
    play,
    pause,
    toggle,
    reset,
    setSpeed,
    scrubTo,
  }

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useSimClock(): SimClock {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useSimClock must be used within <SimClockProvider>')
  return ctx
}
