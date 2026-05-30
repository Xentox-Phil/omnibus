import { ArrowRight, Activity, MapPin, Timer } from 'lucide-react'

import type { EventCurves, Leg } from '#/api'
import { Badge } from '#/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '#/components/ui/card'
import { Separator } from '#/components/ui/separator'
import {
  hhmmToMin,
  legDirection,
  legState,
  stopName,
} from '#/lib/demand'
import { Sparkline  } from './Sparkline'
import type {SparkMarker} from './Sparkline';

function LegRow({
  leg,
  event,
  minute,
}: {
  leg: Leg
  event: EventCurves
  minute: number
}) {
  const dir = legDirection(leg, event.venue)
  const state = legState(leg, minute)
  const start = hhmmToMin(leg.start)
  const end = hhmmToMin(leg.end)
  const span = Math.max(1, end - start)
  const toX = (m: number) => Math.max(0, Math.min(1, (m - start) / span))

  // 4 timeline markers: the match (event_start/end) + this leg's pressure span.
  const markers: SparkMarker[] = [
    { x01: 0, dashed: true }, // leg.start
    { x01: 1, dashed: true }, // leg.end
    { x01: toX(hhmmToMin(event.event_start)) }, // kickoff
    { x01: toX(hhmmToMin(event.event_end)) }, // whistle
  ]

  const peakS = Math.round(leg.peak_s)

  return (
    <div className={state.active ? 'text-foreground' : 'text-muted-foreground'}>
      <div className="mb-1 flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-xs font-medium">
          <Badge variant={dir === 'inbound' ? 'default' : 'secondary'}>
            {dir}
          </Badge>
          <span className="flex items-center gap-1">
            {stopName(leg.from)}
            <ArrowRight className="size-3" />
            {leg.to ? stopName(leg.to) : '—'}
          </span>
        </div>
        {state.active ? (
          <Badge variant="destructive" className="gap-1">
            <Activity className="size-3 animate-pulse" />
            live
          </Badge>
        ) : null}
      </div>

      <div
        className={
          dir === 'inbound' ? 'text-sky-600' : 'text-orange-600'
        }
      >
        <Sparkline
          values={leg.pressure_norm}
          markers={markers}
          cursor01={state.active ? state.progress01 : undefined}
        />
      </div>

      <div className="mt-1 flex items-center justify-between text-[11px] tabular-nums">
        <span className="flex items-center gap-1">
          <MapPin className="size-3" /> Affected: {stopName(leg.from)}
        </span>
        <span className="flex items-center gap-1">
          <Timer className="size-3" /> peak dwell {peakS}s
        </span>
      </div>
      <div className="mt-0.5 text-[10px] text-muted-foreground tabular-nums">
        ramp {leg.start}–{leg.end}
      </div>
    </div>
  )
}

export function EventCard({
  event,
  minute,
}: {
  event: EventCurves
  minute: number
}) {
  const live = event.legs.some((l) => legState(l, minute).active)

  return (
    <Card size="sm" className="gap-3 bg-card/85 backdrop-blur">
      <CardHeader className="gap-1">
        <CardTitle className="flex items-center justify-between">
          <span>{event.label}</span>
          {live ? (
            <Badge variant="destructive" className="gap-1">
              <Activity className="size-3 animate-pulse" />
              active
            </Badge>
          ) : null}
        </CardTitle>
        <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
          <MapPin className="size-3" />
          {stopName(event.venue)}
          <Badge variant="outline" className="tabular-nums">
            Kickoff {event.event_start}
          </Badge>
          <Badge variant="outline" className="tabular-nums">
            Whistle {event.event_end}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {event.legs.map((leg, i) => (
          <div key={`${leg.from}-${leg.to}-${i}`}>
            {i > 0 ? <Separator className="mb-3" /> : null}
            <LegRow leg={leg} event={event} minute={minute} />
          </div>
        ))}
      </CardContent>
    </Card>
  )
}
