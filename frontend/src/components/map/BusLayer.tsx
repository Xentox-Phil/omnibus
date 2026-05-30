import { Layer, Source } from 'react-map-gl/mapbox'

import type { Trajectories } from '#/api'
import { busPositionsAt, lineColor } from '#/lib/buses'

const SOURCE_ID = 'buses'

type BusProps = { id: string; line: string; color: string; angle: number }
type PointFeature = {
  type: 'Feature'
  geometry: { type: 'Point'; coordinates: [number, number] }
  properties: BusProps
}
type FeatureCollection = { type: 'FeatureCollection'; features: PointFeature[] }

export function BusLayer({
  traj,
  minute,
}: {
  traj: Trajectories
  minute: number
}) {
  // Recompute every render (the sim minute advances each animation frame while
  // playing); 118 binary-searched lookups per frame is negligible. Interpolated
  // positions keep motion smooth between the 3s FCD samples.
  const second = minute * 60
  const fc: FeatureCollection = {
    type: 'FeatureCollection',
    features: busPositionsAt(traj, second).map((b) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [b.lon, b.lat] },
      properties: { id: b.id, line: b.line, color: lineColor(b.line), angle: b.angle },
    })),
  }

  return (
    <Source id={SOURCE_ID} type="geojson" data={fc}>
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
      {/* the colored bus dot, big enough to host the line number */}
      <Layer
        id="bus-dot"
        type="circle"
        slot="top"
        paint={{
          'circle-color': ['get', 'color'],
          'circle-radius': [
            'interpolate', ['linear'], ['zoom'],
            10, 7, 13, 11, 16, 17,
          ],
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 2,
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
  )
}
