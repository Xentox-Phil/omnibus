import { ArrowRight, MapPin, Play } from 'lucide-react'

import type { EventCurves, Leg } from '#/api'
import { Button } from '#/components/ui/button'
import { useSimClock } from '#/hooks/useSimClock'
import { lineColor } from '#/lib/buses'
import {
  hhmmToMin,
  legDirection,
  legState,
  stopName,
} from '#/lib/demand'
import { Sparkline } from './Sparkline'

// Demo: only line 5 serves Jahnstadion in our dataset.
const VENUE_LINE: Record<string, string> = {
  JAHN: '5',
}

function lineForVenue(venue: string): string | null {
  return VENUE_LINE[venue] ?? null
}

function LineChip({ line }: { line: string }) {
  return (
    <span
      className="inline-flex h-4 min-w-5 items-center justify-center rounded px-1 text-[10px] font-semibold tabular-nums text-white"
      style={{ backgroundColor: lineColor(line) }}
    >
      {line}
    </span>
  )
}

function LegBlock({
  leg,
  event,
  line,
  label,
  minute,
}: {
  leg: Leg
  event: EventCurves
  line: string | null
  label: string
  minute: number
}) {
  const dir = legDirection(leg, event.venue)
  const state = legState(leg, minute)
  const color = dir === 'inbound' ? 'text-sky-600' : 'text-orange-600'
  return (
    <div className="flex flex-col gap-1">
      <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="flex items-center gap-1.5 text-xs">
        {line ? <LineChip line={line} /> : null}
        <span>{stopName(leg.from)}</span>
        <ArrowRight className={`size-3 ${color}`} />
        <span>{leg.to ? stopName(leg.to) : '—'}</span>
      </div>
      <div className={color}>
        <Sparkline
          values={leg.pressure_norm}
          height={28}
          cursor01={state.active ? state.progress01 : undefined}
          startMin={hhmmToMin(leg.start)}
          endMin={hhmmToMin(leg.end)}
        />
      </div>
    </div>
  )
}

function MatchBar({
  start,
  end,
  minute,
}: {
  start: string
  end: string
  minute: number
}) {
  const s = hhmmToMin(start)
  const e = hhmmToMin(end)
  const span = Math.max(1, e - s)
  const p = Math.max(0, Math.min(1, (minute - s) / span))
  const active = minute >= s && minute <= e
  return (
    <div className="flex flex-col gap-2 py-4">
      <div className="relative h-2">
        <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-border" />
        <div
          className="absolute left-0 top-1/2 h-px -translate-y-1/2 bg-foreground/60"
          style={{ width: `${p * 100}%` }}
        />
        <span className="absolute left-0 top-1/2 size-2 -translate-y-1/2 rounded-full bg-foreground/70" />
        <span className="absolute right-0 top-1/2 size-2 -translate-y-1/2 rounded-full bg-foreground/70" />
        {active ? (
          <span
            className="absolute top-1/2 size-2.5 -translate-y-1/2 rounded-full bg-foreground shadow ring-2 ring-card"
            style={{ left: `${p * 100}%`, transform: 'translate(-50%, -50%)' }}
          />
        ) : null}
      </div>
      <div className="flex justify-between text-[10px] tabular-nums text-muted-foreground">
        <span>{start}</span>
        <span className="font-medium uppercase tracking-wide">Match</span>
        <span>{end}</span>
      </div>
    </div>
  )
}

export function EventCard({ event }: { event: EventCurves }) {
  const { minute, scrubTo, play } = useSimClock()
  const dwellStart = Math.min(...event.legs.map((l) => hhmmToMin(l.start)))
  const jump = () => {
    scrubTo(dwellStart)
    play()
  }
  const line = lineForVenue(event.venue)
  const inbound = event.legs.find(
    (l) => legDirection(l, event.venue) === 'inbound',
  )
  const outbound = event.legs.find(
    (l) => legDirection(l, event.venue) === 'outbound',
  )

  return (
    <div className="px-4 py-3">
      <div className="mb-3 flex items-start justify-between gap-2">
        <div className="flex flex-col gap-0.5">
          <div className="text-sm font-semibold">
            {event.label.replace(/\s*\(demo\)\s*$/i, '')}
          </div>
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <MapPin className="size-3" />
            <span>{stopName(event.venue)}</span>
          </div>
        </div>
        <Button
          size="icon-sm"
          variant="outline"
          onClick={jump}
          aria-label="Jump to dwell start and play"
          title="Jump to dwell start and play"
        >
          <Play />
        </Button>
      </div>

      <div className="flex flex-col gap-3">
        {inbound ? (
          <LegBlock
            leg={inbound}
            event={event}
            line={line}
            label="Inbound"
            minute={minute}
          />
        ) : null}
        <MatchBar
          start={event.event_start}
          end={event.event_end}
          minute={minute}
        />
        {outbound ? (
          <LegBlock
            leg={outbound}
            event={event}
            line={line}
            label="Outbound"
            minute={minute}
          />
        ) : null}
      </div>
    </div>
  )
}
