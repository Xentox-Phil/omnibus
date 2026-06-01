import { createFileRoute } from '@tanstack/react-router'
import { useEffect, useRef, useState } from 'react'
import Map, { Marker  } from 'react-map-gl/mapbox'
import type {MapRef} from 'react-map-gl/mapbox';
import { MapPin } from 'lucide-react'
import 'mapbox-gl/dist/mapbox-gl.css'

import { env } from '#/env'
import { SimClockProvider, useSimClock } from '#/hooks/useSimClock'
import { useDemandSurface, useEventCurves } from '#/hooks/useDemand'
import { useSimTrajectories } from '#/hooks/useSim'
import {
  eventMoments,
  lightPresetForHour,
  stopName

} from '#/lib/demand'
import type {LightPreset} from '#/lib/demand';
import { DemandHeatmap } from '#/components/map/DemandHeatmap'
import { BusLayer } from '#/components/map/BusLayer'
import { SimControls } from '#/components/SimControls'
import { EventsPanel } from '#/components/events/EventsPanel'
import { SimToast } from '#/components/events/SimToast'

export const Route = createFileRoute('/')({ component: Home })

const REGENSBURG = { longitude: 12.0966, latitude: 49.0186, zoom: 13.2 }

function Home() {
  // Start at 17:00 — the replay window opens at 16:00 but trips need ~30 min to
  // be mid-route, so the fleet is sparse before ~16:30 (0 buses exactly at
  // 16:00). 17:00 has the most buses on-screen and leads into the 18:00 kickoff.
  return (
    <SimClockProvider initialMinute={17 * 60}>
      <DemandView />
    </SimClockProvider>
  )
}

function DemandView() {
  const mapRef = useRef<MapRef>(null)
  const [showHeatmap, setShowHeatmap] = useState(true)
  const [showBuses, setShowBuses] = useState(true)
  const [mapReady, setMapReady] = useState(false)
  const lastPreset = useRef<LightPreset | null>(null)
  const { minute } = useSimClock()

  const surfaceQuery = useDemandSurface()
  const eventsQuery = useEventCurves()
  const trajQuery = useSimTrajectories()
  const surface = surfaceQuery.data
  const events = eventsQuery.data
  const traj = trajQuery.data

  // Drive the basemap light preset from the simulated hour (guarded so we only
  // touch the map when the preset actually changes).
  const hour = Math.floor(minute / 60)
  const preset = lightPresetForHour(hour)
  // dusk + night both render a dark navy basemap — markers and bus dots switch
  // to their high-contrast night styling for either.
  const night = preset === 'night' || preset === 'dusk'
  useEffect(() => {
    if (!mapReady) return
    const map = mapRef.current?.getMap()
    if (!map) return
    if (preset === lastPreset.current) return
    map.setConfigProperty('basemap', 'lightPreset', preset)
    lastPreset.current = preset
  }, [preset, mapReady])

  // Venue / affected stops to pin on the map for orientation.
  const eventStops = events
    ? Array.from(
        new Set(events.events.flatMap((e) => e.legs.map((l) => l.from))),
      )
    : []
  const stopCoord = (code: string) => {
    const n = surface?.nodes.find((x) => x.stop_code === code)
    return n ? { lon: n.lon, lat: n.lat } : null
  }

  // Earliest notable moment across all events (first inbound ramp) — the Reset
  // button jumps here so a demo lands right where the action begins.
  const firstEventMinute = events
    ? eventMoments(events.events)[0]?.minute
    : undefined

  return (
    <div className="relative h-screen w-screen overflow-hidden">
      <Map
        ref={mapRef}
        mapboxAccessToken={env.VITE_MAPBOX_TOKEN}
        initialViewState={{ ...REGENSBURG, pitch: 35, bearing: -17 }}
        mapStyle="mapbox://styles/mapbox/standard"
        style={{ width: '100%', height: '100%' }}
        onLoad={() => setMapReady(true)}
      >
        {surface && showHeatmap ? (
          <DemandHeatmap surface={surface} minute={minute} />
        ) : null}

        {traj && showBuses ? <BusLayer traj={traj} minute={minute} night={night} /> : null}

        {eventStops.map((code) => {
          const c = stopCoord(code)
          if (!c) return null
          return (
            <Marker
              key={code}
              longitude={c.lon}
              latitude={c.lat}
              anchor="bottom"
            >
              <div className="flex flex-col items-center gap-1">
                <span
                  className={
                    night
                      ? 'rounded-full bg-white px-2.5 py-1 text-[11px] font-semibold text-slate-900 shadow-lg'
                      : 'rounded-full bg-white/95 px-2.5 py-1 text-[11px] font-semibold text-slate-900 shadow-md backdrop-blur'
                  }
                >
                  {stopName(code)}
                </span>
                <MapPin
                  strokeWidth={2.25}
                  className={
                    night
                      ? 'size-7 fill-white text-slate-800 drop-shadow-[0_1px_5px_rgba(0,0,0,0.85)]'
                      : 'size-7 fill-primary text-white drop-shadow-md'
                  }
                />
              </div>
            </Marker>
          )
        })}
      </Map>

      <SimControls
        showHeatmap={showHeatmap}
        onToggleHeatmap={setShowHeatmap}
        showBuses={showBuses}
        onToggleBuses={setShowBuses}
        resetMinute={firstEventMinute}
      />
      {events ? <EventsPanel data={events} /> : null}
      {events ? <SimToast data={events} /> : null}
    </div>
  )
}
