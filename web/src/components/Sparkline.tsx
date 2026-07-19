interface SparklineProps {
  values: number[]
  width?: number
  height?: number
}

/** Minimal inline SVG sparkline — no chart library, per the brief's constraint. */
export function Sparkline({ values, width = 120, height = 30 }: SparklineProps) {
  if (values.length === 0) return null

  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1

  const points = values
    .map((v, i) => {
      const x = (i / Math.max(values.length - 1, 1)) * width
      const y = height - ((v - min) / range) * height
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')

  return (
    <svg width={width} height={height} className="sparkline" role="img" aria-label="trend">
      <polyline points={points} fill="none" strokeWidth={2} />
    </svg>
  )
}
