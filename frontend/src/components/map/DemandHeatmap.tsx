import { useMemo } from 'react'
import { Layer, Source } from 'react-map-gl/mapbox'

import type { DemandSurface } from '#/api'
import { interpolatedWeights } from '#/lib/demand'

const SOURCE_ID = 'demand'

// Minimal local GeoJSON typing (avoids a @types/geojson dependency).
type NodeProps = { stop_code: string; w: number }
type PointFeature = {
  type: 'Feature'
  geometry: { type: 'Point'; coordinates: [number, number] }
  properties: NodeProps
}
type FeatureCollection = {
  type: 'FeatureCollection'
  features: PointFeature[]
}

export function DemandHeatmap({
  surface,
  minute,
}: {
  surface: DemandSurface
  minute: number
}) {
  // Rebuild the weighted FeatureCollection on each integer-minute change and
  // bind it declaratively — react-map-gl diffs the `data` prop and calls
  // setData itself, so there's no source-not-ready timing race (the bug that
  // left the heatmap blank while paused at start).
  const floorMin = Math.floor(minute)
  const fc = useMemo<FeatureCollection>(() => {
    const weights = interpolatedWeights(surface, floorMin)
    return {
      type: 'FeatureCollection',
      features: surface.nodes.map<PointFeature>((n, i) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [n.lon, n.lat] },
        properties: { stop_code: n.stop_code, w: weights[i] },
      })),
    }
    // floorMin drives the throttle; surface is stable per day.
  }, [surface, floorMin])

  return (
    <Source id={SOURCE_ID} type="geojson" data={fc}>
      <Layer
        id="demand-heat"
        type="heatmap"
        slot="middle"
        maxzoom={24}
        paint={{
          // `w` is pressure_norm (0-1 vs the DAY's global max), so baseline
          // dwell is tiny (~0.005). Lift low values enough to be visible, but
          // keep the top end gentle so it doesn't blow out to solid red — the
          // spread comes from a larger radius (bigger circle per stop), not
          // from intensity.
          'heatmap-weight': [
            'interpolate',
            ['linear'],
            ['get', 'w'],
            0,
            0,
            0.005,
            0.15,
            0.03,
            0.35,
            0.12,
            0.55,
            0.4,
            0.8,
            1,
            1,
          ],
          'heatmap-intensity': [
            'interpolate',
            ['linear'],
            ['zoom'],
            10,
            0.9,
            13,
            1.3,
            16,
            1.8,
          ],
          'heatmap-radius': [
            'interpolate',
            ['linear'],
            ['zoom'],
            10,
            26,
            13,
            52,
            16,
            85,
          ],
          'heatmap-opacity': [
            'interpolate',
            ['linear'],
            ['zoom'],
            10,
            0.85,
            16,
            0.7,
          ],
          'heatmap-color': [
            'interpolate',
            ['linear'],
            ['heatmap-density'],
            0,
            'rgba(33,102,172,0)',
            0.12,
            'rgba(59,130,246,0.45)',
            0.3,
            'rgb(56,189,148)',
            0.5,
            'rgb(250,204,21)',
            0.7,
            'rgb(249,115,22)',
            1,
            'rgb(220,38,38)',
          ],
        }}
      />
    </Source>
  )
}
