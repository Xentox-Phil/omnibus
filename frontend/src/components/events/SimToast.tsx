import { useEffect, useMemo, useRef, useState } from 'react'
import { Bell, Activity, Flag, TrainFront } from 'lucide-react'

import type { EventsResponse } from '#/api'
import { useSimClock } from '#/hooks/useSimClock'
import { eventMoments  } from '#/lib/demand'
import type {MomentKind} from '#/lib/demand';

const ICON: Record<MomentKind, typeof Bell> = {
  leg_ramp: TrainFront,
  kickoff: Flag,
  peak: Activity,
  whistle: Flag,
  leg_end: Bell,
}

export function SimToast({ data }: { data: EventsResponse }) {
  const { minute } = useSimClock()
  const moments = useMemo(() => eventMoments(data.events), [data.events])

  const [msg, setMsg] = useState<{ text: string; kind: MomentKind } | null>(
    null,
  )
  const prevMin = useRef(minute)
  const clearTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  useEffect(() => {
    const prev = prevMin.current
    prevMin.current = minute

    // Backward scrub or midnight wrap: don't replay, just dismiss.
    if (minute < prev) return

    // Last moment crossed in (prev, minute].
    let hit: (typeof moments)[number] | undefined
    for (const m of moments) {
      if (m.minute > prev && m.minute <= minute) hit = m
    }
    if (!hit) return

    setMsg({ text: hit.message, kind: hit.kind })
    if (clearTimer.current) clearTimeout(clearTimer.current)
    clearTimer.current = setTimeout(() => setMsg(null), 4500)
  }, [minute, moments])

  useEffect(
    () => () => {
      if (clearTimer.current) clearTimeout(clearTimer.current)
    },
    [],
  )

  if (!msg) return null
  const Icon = ICON[msg.kind]

  return (
    <div className="pointer-events-none absolute bottom-8 left-1/2 z-20 -translate-x-1/2">
      <div className="flex items-center gap-2.5 rounded-full border bg-card/90 py-2 pr-4 pl-3 text-sm shadow-lg ring-1 ring-foreground/10 backdrop-blur duration-200 animate-in fade-in slide-in-from-bottom-2">
        <span className="flex size-7 items-center justify-center rounded-full bg-primary/10 text-primary">
          <Icon className="size-4" />
        </span>
        <span className="font-medium">{msg.text}</span>
      </div>
    </div>
  )
}
