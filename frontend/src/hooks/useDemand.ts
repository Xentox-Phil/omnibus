import { useQuery } from '@tanstack/react-query'

import { getDemandOptions, getEventsOptions } from '#/api/@tanstack/react-query.gen'
import { DEMO_DATE } from '#/lib/demand'

// Static per-day artifacts — never re-fetch within a session.
const STATIC = { staleTime: Infinity, gcTime: Infinity } as const

/** The node-keyed 15-min pressure surface (heatmap source). */
export function useDemandSurface(date: string = DEMO_DATE) {
  return useQuery({
    ...getDemandOptions({ path: { date } }),
    ...STATIC,
  })
}

/** The event-first 1-min demand curves (events panel + toast). */
export function useEventCurves(date: string = DEMO_DATE) {
  return useQuery({
    ...getEventsOptions({ path: { date } }),
    ...STATIC,
  })
}
