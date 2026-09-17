/**
 * Dates come from the backend as ISO-8601 timestamps with an offset and are shown
 * in the business's timezone (the session carries it). The frontend never decides
 * which business day a timestamp belongs to — the backend does (BR-10).
 */

export function formatDateTime(iso: string | null | undefined, timeZone: string): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return new Intl.DateTimeFormat('en-KE', {
    timeZone,
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

export function formatDate(iso: string | null | undefined, timeZone: string): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return new Intl.DateTimeFormat('en-KE', { timeZone, day: 'numeric', month: 'short', year: 'numeric' }).format(date)
}

/** A local calendar date ("2026-09-16") as the backend's analytics period fields carry it. */
export function formatCalendarDate(ymd: string): string {
  const [year, month, day] = ymd.split('-').map(Number)
  if (!year || !month || !day) return ymd
  return new Intl.DateTimeFormat('en-KE', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(
    new Date(Date.UTC(year, month - 1, day)),
  )
}

/** Calendar date (YYYY-MM-DD) of an instant in the business's timezone. */
export function localDate(date: Date, timeZone: string): string {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(date)
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? ''
  return `${get('year')}-${get('month')}-${get('day')}`
}

/** The instant at which a calendar date (YYYY-MM-DD) begins in the business's timezone. */
export function zonedStartOfDay(ymd: string, timeZone: string): Date {
  const [y, m, d] = ymd.split('-').map(Number)
  const guess = Date.UTC(y, m - 1, d)
  // Wall-clock of the guess in the zone, read back as if it were UTC, gives the offset.
  const parts = new Intl.DateTimeFormat('en-US', { timeZone, hourCycle: 'h23', year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric', second: 'numeric' }).formatToParts(new Date(guess))
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value ?? 0)
  const wall = Date.UTC(get('year'), get('month') - 1, get('day'), get('hour'), get('minute'), get('second'))
  return new Date(guess - (wall - guess))
}

/** Half-open instant range [start of `from`, start of the day after `to`) in the business's timezone. */
export function zonedDayRange(from: string, to: string, timeZone: string): { from: string; to: string } {
  const [y, m, d] = to.split('-').map(Number)
  const dayAfter = new Date(Date.UTC(y, m - 1, d + 1)).toISOString().slice(0, 10)
  return { from: zonedStartOfDay(from, timeZone).toISOString(), to: zonedStartOfDay(dayAfter, timeZone).toISOString() }
}

/** "18:47" in the business timezone. */
export function formatTime(iso: string | null | undefined, timeZone: string): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return new Intl.DateTimeFormat('en-KE', { timeZone, hour: '2-digit', minute: '2-digit', hour12: false }).format(date)
}

/** "17 Sept" — the phone-width form of formatDate. */
export function formatDayMonth(iso: string | null | undefined, timeZone: string): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return new Intl.DateTimeFormat('en-KE', { timeZone, day: 'numeric', month: 'short' }).format(date)
}
