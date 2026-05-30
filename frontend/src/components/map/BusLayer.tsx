import { useEffect, useState } from 'react'
import {
  Layer,
  Popup,
  Source,
  useMap,
  type MapMouseEvent,
} from 'react-map-gl/mapbox'

import type { Trajectories } from '#/api'
import { busColor, busPositionsAt, FLEX_COLOR } from '#/lib/buses'

const SOURCE_ID = 'buses'
const DOT_LAYER = 'bus-dot'

type BusProps = {
  id: string
  line: string
  color: string
  angle: number
  flex: boolean
  block: string
}
type PointFeature = {
  type: 'Feature'
  geometry: { type: 'Point'; coordinates: [number, number] }
  properties: BusProps
}
type FeatureCollection = { type: 'FeatureCollection'; features: PointFeature[] }

type Hovered = { lon: number; lat: number; line: string; flex: boolean; block: string }

export function BusLayer({
  traj,
  minute,
}: {
  traj: Trajectories
  minute: number
}) {
  const { current: map } = useMap()
  const [hovered, setHovered] = useState<Hovered | null>(null)

  // Hover tooltip: hit-test the bus dots and surface line / flex-block. Attached
  // once the map exists; cleaned up on unmount so we don't stack listeners.
  useEffect(() => {
    if (!map) return
    const onMove = (e: MapMouseEvent) => {
      const f = e.features?.[0]
      if (!f || f.geometry.type !== 'Point') return
      const [lon, lat] = f.geometry.coordinates
      const p = (f.properties ?? {}) as Partial<BusProps>
      map.getCanvas().style.cursor = 'pointer'
      setHovered({
        lon,
        lat,
        line: String(p.line ?? '?'),
        flex: Boolean(p.flex),
        block: String(p.block ?? ''),
      })
    }
    const onLeave = () => {
      map.getCanvas().style.cursor = ''
      setHovered(null)
    }
    map.on('mousemove', DOT_LAYER, onMove)
    map.on('mouseleave', DOT_LAYER, onLeave)
    return () => {
      map.off('mousemove', DOT_LAYER, onMove)
      map.off('mouseleave', DOT_LAYER, onLeave)
    }
  }, [map])

  // Recompute every render (the sim minute advances each animation frame while
  // playing); 118 binary-searched lookups per frame is negligible. Interpolated
  // positions keep motion smooth between the 3s FCD samples.
  const second = minute * 60
  const fc: FeatureCollection = {
    type: 'FeatureCollection',
    features: busPositionsAt(traj, second).map((b) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [b.lon, b.lat] },
      properties: {
        id: b.id,
        line: b.line,
        color: busColor(b),
        angle: b.angle,
        flex: b.flex,
        block: b.block ?? '',
      },
    })),
  }

  return (
    <>
      <Source id={SOURCE_ID} type="geojson" data={fc}>
        {/* flex buses get an extra magenta glow ring so they stand out from the
            scheduled lines even before you hover */}
        <Layer
          id="bus-flex-glow"
          type="circle"
          slot="top"
          filter={['==', ['get', 'flex'], true]}
          paint={{
            'circle-color': FLEX_COLOR,
            'circle-radius': [
              'interpolate', ['linear'], ['zoom'],
              10, 15, 13, 21, 16, 32,
            ],
            'circle-blur': 0.7,
            'circle-opacity': 0.55,
          }}
        />
        {/* dark contrast ring under the dot — keeps it visible on the light (day)
            basemap, where a plain white stroke would wash out */}
        <Layer
          id="bus-halo"
          type="circle"
          slot="top"
          paint={{
            'circle-color': 'rgba(15,23,42,0.55)',
            'circle-radius': [
              'interpolate', ['linear'], ['zoom'],
              10, 9, 13, 13, 16, 20,
            ],
            'circle-blur': 0.4,
          }}
        />
        {/* the colored bus dot, big enough to host the line number. Flex buses
            wear a brighter, thicker stroke on top of their magenta fill */}
        <Layer
          id={DOT_LAYER}
          type="circle"
          slot="top"
          paint={{
            'circle-color': ['get', 'color'],
            'circle-radius': [
              'interpolate', ['linear'], ['zoom'],
              10, 7, 13, 11, 16, 17,
            ],
            'circle-stroke-color': ['case', ['get', 'flex'], '#fde68a', '#ffffff'],
            'circle-stroke-width': ['case', ['get', 'flex'], 3, 2],
            'circle-opacity': 1,
          }}
        />
        {/* line number, centered on the dot — white glyph + dark halo reads on any
            dot color and on both day/night basemaps */}
        <Layer
          id="bus-label"
          type="symbol"
          slot="top"
          layout={{
            'text-field': ['get', 'line'],
            'text-font': ['DIN Pro Bold', 'Arial Unicode MS Bold'],
            'text-size': [
              'interpolate', ['linear'], ['zoom'],
              10, 9, 13, 12, 16, 16,
            ],
            'text-allow-overlap': true,
            'text-ignore-placement': true,
          }}
          paint={{
            'text-color': '#ffffff',
            'text-halo-color': 'rgba(15,23,42,0.9)',
            'text-halo-width': 1.4,
          }}
        />
      </Source>

      {hovered ? (
        <Popup
          longitude={hovered.lon}
          latitude={hovered.lat}
          closeButton={false}
          closeOnClick={false}
          offset={16}
          anchor="bottom"
        >
          {hovered.flex ? (
            <div className="flex flex-col gap-0.5">
              <span
                className="text-[10px] font-bold uppercase tracking-wide"
                style={{ color: FLEX_COLOR }}
              >
                ⚡ Flexbus
              </span>
              <span className="text-xs font-medium">{hovered.block}</span>
            </div>
          ) : (
            <span className="text-xs font-medium">Linie {hovered.line}</span>
          )}
        </Popup>
      ) : null}
    </>
  )
}
