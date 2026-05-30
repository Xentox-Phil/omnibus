import { useId } from 'react'

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
  className,
}: {
  values: number[]
  width?: number
  height?: number
  markers?: SparkMarker[]
  /** 0-1 live cursor position; omitted = no cursor */
  cursor01?: number
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

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      width="100%"
      height={h}
      preserveAspectRatio="none"
      className={className}
      role="img"
      aria-label="Demand curve"
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
    </svg>
  )
}
