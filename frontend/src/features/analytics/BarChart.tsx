import { useId } from 'react'

import { formatKsh } from '@/lib/money'

export interface ChartSeries {
  key: string
  label: string
  /** A CSS colour (design token) for the bars. */
  color: string
}
export interface ChartRow {
  label: string
  values: Record<string, string>
}

const W = 640
const H = 220
const PAD = { top: 12, right: 8, bottom: 28, left: 8 }

/**
 * A small grouped bar chart drawn as SVG so it scales to any width without a
 * charting dependency; the same figures are in a visually hidden table for
 * screen readers.
 */
export function BarChart({ title, series, rows }: { title: string; series: ChartSeries[]; rows: ChartRow[] }) {
  const id = useId()
  const numbers = rows.flatMap((r) => series.map((s) => Number(r.values[s.key] ?? 0)))
  const max = Math.max(0, ...numbers)
  const min = Math.min(0, ...numbers)
  const span = max - min || 1
  const plotH = H - PAD.top - PAD.bottom
  const plotW = W - PAD.left - PAD.right
  const groupW = plotW / Math.max(rows.length, 1)
  const barW = Math.max(2, (groupW * 0.7) / series.length)
  const y = (v: number) => PAD.top + ((max - v) / span) * plotH
  const zero = y(0)
  const labelEvery = Math.ceil(rows.length / 8)

  return (
    <figure aria-labelledby={`${id}-title`}>
      <figcaption id={`${id}-title`} className="sr-only">{title}</figcaption>
      <div className="mb-2 flex flex-wrap gap-4 text-xs text-muted-foreground" aria-hidden="true">
        {series.map((s) => (
          <span key={s.key} className="inline-flex items-center gap-1.5"><span className="inline-block size-2.5 rounded-sm" style={{ background: s.color }} /> {s.label}</span>
        ))}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" aria-hidden="true" focusable="false">
        <line x1={PAD.left} x2={W - PAD.right} y1={zero} y2={zero} stroke="var(--color-border)" />
        {rows.map((row, i) => (
          <g key={row.label}>
            {series.map((s, j) => {
              const v = Number(row.values[s.key] ?? 0)
              const x = PAD.left + i * groupW + (groupW - barW * series.length) / 2 + j * barW
              const top = Math.min(y(v), zero)
              const height = Math.abs(y(v) - zero)
              return <rect key={s.key} x={x} y={top} width={barW - 1} height={Math.max(height, v === 0 ? 0 : 1)} fill={s.color} rx={1} />
            })}
            {i % labelEvery === 0 && (
              <text x={PAD.left + i * groupW + groupW / 2} y={H - 8} textAnchor="middle" fontSize={11} fill="var(--color-muted-foreground)">{row.label}</text>
            )}
          </g>
        ))}
      </svg>
      <table className="sr-only">
        <caption>{title}</caption>
        <thead><tr><th scope="col">Period</th>{series.map((s) => <th key={s.key} scope="col">{s.label}</th>)}</tr></thead>
        <tbody>{rows.map((row) => <tr key={row.label}><th scope="row">{row.label}</th>{series.map((s) => <td key={s.key}>{formatKsh(row.values[s.key] ?? '0')}</td>)}</tr>)}</tbody>
      </table>
    </figure>
  )
}
