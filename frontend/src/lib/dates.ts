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
