import { formatDate, formatDayMonth, formatTime } from '@/lib/dates'

/**
 * A timestamp for table rows: date over time, with the year dropped below the `sm`
 * breakpoint so phone-width tables keep their important columns on screen.
 */
export function When({ iso, timeZone, className }: { iso: string; timeZone: string; className?: string }) {
  return (
    <time dateTime={iso} className={className ? `inline-block leading-tight ${className}` : 'inline-block leading-tight'}>
      <span className="block whitespace-nowrap">
        <span className="sm:hidden">{formatDayMonth(iso, timeZone)}</span>
        <span className="hidden sm:inline">{formatDate(iso, timeZone)}</span>
      </span>
      <span className="block text-xs text-muted-foreground">{formatTime(iso, timeZone)}</span>
    </time>
  )
}
