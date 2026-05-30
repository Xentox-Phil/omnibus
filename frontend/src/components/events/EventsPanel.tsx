import { CalendarClock } from 'lucide-react'

import type { EventsResponse } from '#/api'
import { useSimClock } from '#/hooks/useSimClock'
import { EventCard } from './EventCard'

export function EventsPanel({ data }: { data: EventsResponse }) {
  const { minute } = useSimClock()

  return (
    <div className="absolute top-4 right-4 z-10 flex max-h-[calc(100vh-2rem)] w-[340px] flex-col gap-3 overflow-y-auto pb-2">
      <div className="flex items-center gap-2 px-1">
        <CalendarClock className="size-5" />
        <h2 className="font-heading text-lg font-semibold">Events</h2>
        <span className="ml-auto text-xs text-muted-foreground tabular-nums">
          {data.date}
        </span>
      </div>

      {data.events.length === 0 ? (
        <div className="rounded-xl border border-dashed p-4 text-center text-sm text-muted-foreground">
          No events for this day.
        </div>
      ) : (
        data.events.map((event) => (
          <EventCard key={event.event_id} event={event} minute={minute} />
        ))
      )}
    </div>
  )
}
