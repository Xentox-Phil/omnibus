import { useId, useState } from 'react'

import { minToHHMM } from '#/lib/demand'

export interface SparkMarker {
  /** 0-1 position along the x-axis */
  x01: number
  color?: string
  dashed?: boolean
}

// Tiny inline-SVG area sparkline. No chart dependency. `values` are 0-1.
export function Sparkline({
  values,
  width = 252,
  height = 56,
  markers = [],
  cursor01,
  startMin,
  endMin,
  className,
}: {
  values: number[]
  width?: number
  height?: number
  markers?: SparkMarker[]
  /** 0-1 live cursor position; omitted = no cursor */
  cursor01?: number
  /** when provided, renders start/end time labels and a hover tooltip */
  startMin?: number
  endMin?: number
  className?: string
}) {
  const gradId = useId()
  const n = values.length
  const pad = 3
  const w = width
  const h = height
  const innerH = h - pad * 2

  const x = (i: number) => (n <= 1 ? 0 : (i / (n - 1)) * w)
  const y = (v: number) => pad + (1 - Math.max(0, Math.min(1, v))) * innerH

  const line = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`)
  const linePath = `M ${line.join(' L ')}`
  const areaPath = `${linePath} L ${w},${h} L 0,${h} Z`

  const [hover01, setHover01] = useState<number | null>(null)
  const hasTimes = startMin !== undefined && endMin !== undefined
  const hoverTime =
    hover01 !== null && hasTimes
      ? minToHHMM(startMin! + hover01 * (endMin! - startMin!))
      : null

  return (
    <div className={`relative ${className ?? ''}`}>
      <svg
        viewBox={`0 0 ${w} ${h}`}
        width="100%"
        height={h}
        preserveAspectRatio="none"
        role="img"
        aria-label="Demand curve"
        onMouseMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect()
          setHover01(Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)))
        }}
        onMouseLeave={() => setHover01(null)}
      >
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="currentColor" stopOpacity="0.35" />
            <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
          </linearGradient>
        </defs>

        {markers.map((m, i) => (
          <line
            key={i}
            x1={m.x01 * w}
            x2={m.x01 * w}
            y1={pad}
            y2={h}
            stroke={m.color ?? 'currentColor'}
            strokeOpacity={0.4}
            strokeWidth={1}
            strokeDasharray={m.dashed ? '3 3' : undefined}
          />
        ))}

        <path d={areaPath} fill={`url(#${gradId})`} />
        <path
          d={linePath}
          fill="none"
          stroke="currentColor"
          strokeWidth={1.75}
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        {cursor01 !== undefined && (
          <>
            <line
              x1={cursor01 * w}
              x2={cursor01 * w}
              y1={pad}
              y2={h}
              stroke="currentColor"
              strokeWidth={1.5}
            />
            <circle
              cx={cursor01 * w}
              cy={y(values[Math.round(cursor01 * (n - 1))] ?? 0)}
              r={3}
              fill="currentColor"
            />
          </>
        )}

        {hover01 !== null && (
          <line
            x1={hover01 * w}
            x2={hover01 * w}
            y1={pad}
            y2={h}
            stroke="currentColor"
            strokeOpacity={0.5}
            strokeWidth={1}
            strokeDasharray="2 2"
          />
        )}
      </svg>

      {hasTimes ? (
        <div className="mt-0.5 flex justify-between text-[9px] tabular-nums text-muted-foreground">
          <span>{minToHHMM(startMin!)}</span>
          <span>{minToHHMM(endMin!)}</span>
        </div>
      ) : null}

      {hoverTime ? (
        <div
          className="pointer-events-none absolute -top-5 -translate-x-1/2 rounded bg-foreground px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-background shadow"
          style={{ left: `${hover01! * 100}%` }}
        >
          {hoverTime}
        </div>
      ) : null}
    </div>
  )
}
