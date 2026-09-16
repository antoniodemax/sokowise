import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

import type { AnalyticsPeriod, PeriodParams } from './api'

const PRESETS: { value: AnalyticsPeriod; label: string }[] = [
  { value: 'today', label: 'Today' },
  { value: 'yesterday', label: 'Yesterday' },
  { value: 'this_week', label: 'This week' },
  { value: 'this_month', label: 'This month' },
  { value: 'custom', label: 'Custom' },
]

export function PeriodPicker({ value, onChange }: { value: PeriodParams; onChange: (value: PeriodParams) => void }) {
  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
      <div role="radiogroup" aria-label="Period" className="flex w-full gap-1 overflow-x-auto rounded-lg border border-border bg-card p-1 sm:w-auto">
        {PRESETS.map((preset) => (
          <button key={preset.value} type="button" role="radio" aria-checked={value.period === preset.value} onClick={() => onChange(preset.value === 'custom' ? { period: 'custom', date_from: value.date_from, date_to: value.date_to } : { period: preset.value })} className={cn('min-h-11 flex-1 rounded-md px-3 text-sm font-medium whitespace-nowrap transition-colors sm:min-h-9 sm:flex-none', value.period === preset.value ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted hover:text-foreground')}>
            {preset.label}
          </button>
        ))}
      </div>
      {value.period === 'custom' && (
        <div className="grid grid-cols-2 gap-2">
          <Input type="date" aria-label="From date" value={value.date_from ?? ''} max={value.date_to} onChange={(e) => onChange({ ...value, date_from: e.target.value })} />
          <Input type="date" aria-label="To date" value={value.date_to ?? ''} min={value.date_from} onChange={(e) => onChange({ ...value, date_to: e.target.value })} />
        </div>
      )}
    </div>
  )
}
