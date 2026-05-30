import { CalendarClock } from 'lucide-react'

import type { EventsResponse } from '#/api'
import { Card, CardContent, CardHeader } from '#/components/ui/card'
import { Separator } from '#/components/ui/separator'
import { EventCard } from './EventCard'

export function EventsPanel({ data }: { data: EventsResponse }) {
  return (
    <Card
      size="sm"
      className="absolute top-4 right-4 z-10 flex max-h-[calc(100vh-2rem)] w-[340px] flex-col gap-0 overflow-hidden bg-card/90 backdrop-blur"
    >
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <CalendarClock className="size-4" />
          <h2 className="font-heading text-base font-semibold">Events</h2>
        </div>
        <span className="text-xs text-muted-foreground tabular-nums">
          {data.date}
        </span>
      </CardHeader>
      <CardContent className="flex flex-col gap-0 overflow-y-auto p-0">
        {data.events.length === 0 ? (
          <div className="px-4 py-6 text-center text-sm text-muted-foreground">
            No events for this day.
          </div>
        ) : (
          data.events.map((event, i) => (
            <div key={event.event_id}>
              {i > 0 ? <Separator /> : null}
              <EventCard event={event} />
            </div>
          ))
        )}
      </CardContent>
    </Card>
  )
}
