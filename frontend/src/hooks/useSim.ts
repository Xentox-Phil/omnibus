import { useQuery } from '@tanstack/react-query'

import { getSimOptions } from '#/api/@tanstack/react-query.gen'
import { DEMO_DATE } from '#/lib/demand'

// Static per-day artifact — never re-fetch within a session.
const STATIC = { staleTime: Infinity, gcTime: Infinity } as const

/** SUMO-simulated bus trajectories for the date (animated bus layer source). */
export function useSimTrajectories(date: string = DEMO_DATE) {
  return useQuery({
    ...getSimOptions({ path: { date } }),
    ...STATIC,
  })
}
