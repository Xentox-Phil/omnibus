import { createFileRoute } from '@tanstack/react-router'
import { useEffect, useRef, useState } from 'react'
import Map, { Marker  } from 'react-map-gl/mapbox'
import type {MapRef} from 'react-map-gl/mapbox';
import { MapPin } from 'lucide-react'
import 'mapbox-gl/dist/mapbox-gl.css'

import { env } from '#/env'
import { SimClockProvider, useSimClock } from '#/hooks/useSimClock'
import { useDemandSurface, useEventCurves } from '#/hooks/useDemand'
import {
  lightPresetForHour,
  stopName
  
} from '#/lib/demand'
import type {LightPreset} from '#/lib/demand';
import { DemandHeatmap } from '#/components/map/DemandHeatmap'
import { SimControls } from '#/components/SimControls'
import { EventsPanel } from '#/components/events/EventsPanel'
import { SimToast } from '#/components/events/SimToast'

export const Route = createFileRoute('/')({ component: Home })

const REGENSBURG = { longitude: 12.0966, latitude: 49.0186, zoom: 13.2 }

function Home() {
  return (
    <SimClockProvider>
      <DemandView />
    </SimClockProvider>
  )
}

function DemandView() {
  const mapRef = useRef<MapRef>(null)
  const [showHeatmap, setShowHeatmap] = useState(true)
  const [mapReady, setMapReady] = useState(false)
  const lastPreset = useRef<LightPreset | null>(null)
  const { minute } = useSimClock()

  const surfaceQuery = useDemandSurface()
  const eventsQuery = useEventCurves()
  const surface = surfaceQuery.data
  const events = eventsQuery.data

  // Drive the basemap light preset from the simulated hour (guarded so we only
  // touch the map when the preset actually changes).
  const hour = Math.floor(minute / 60)
  useEffect(() => {
    if (!mapReady) return
    const map = mapRef.current?.getMap()
    if (!map) return
    const next = lightPresetForHour(hour)
    if (next === lastPreset.current) return
    map.setConfigProperty('basemap', 'lightPreset', next)
    lastPreset.current = next
  }, [hour, mapReady])

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
              <div className="flex flex-col items-center">
                <span className="rounded-full bg-card/90 px-2 py-0.5 text-[10px] font-medium shadow ring-1 ring-foreground/10 backdrop-blur">
                  {stopName(code)}
                </span>
                <MapPin className="size-5 text-primary drop-shadow" />
              </div>
            </Marker>
          )
        })}
      </Map>

      <SimControls
        showHeatmap={showHeatmap}
        onToggleHeatmap={setShowHeatmap}
      />
      {events ? <EventsPanel data={events} /> : null}
      {events ? <SimToast data={events} /> : null}
    </div>
  )
}
