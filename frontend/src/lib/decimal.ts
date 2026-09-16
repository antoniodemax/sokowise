/**
 * Exact money/quantity arithmetic on strings, in cents — for the few places the UI
 * must add figures before the backend answers (sale subtotal, tender remaining).
 * The backend recomputes and validates everything; this only drives the form.
 */

/** "12.5" → 1250 (cents); rejects anything that is not a plain decimal. */
export function toCents(value: string | number): number | null {
  const raw = typeof value === 'number' ? String(value) : value.trim()
  const match = /^(-)?(\d+)(?:\.(\d{0,2}))?$/.exec(raw)
  if (!match) return null
  const [, sign, whole, fraction = ''] = match
  const cents = Number(whole) * 100 + Number((fraction + '00').slice(0, 2))
  return sign ? -cents : cents
}

/** 1250 → "12.50" */
export function fromCents(cents: number): string {
  const sign = cents < 0 ? '-' : ''
  const abs = Math.abs(cents)
  return `${sign}${Math.floor(abs / 100)}.${String(abs % 100).padStart(2, '0')}`
}

/** Quantity × unit price in cents with half-up rounding (BR-9). `quantity` up to 3 dp. */
export function lineCents(quantity: string, unitPrice: string): number | null {
  const qty = /^(\d+)(?:\.(\d{0,3}))?$/.exec(quantity.trim())
  const price = toCents(unitPrice)
  if (!qty || price === null) return null
  const milli = Number(qty[1]) * 1000 + Number(((qty[2] ?? '') + '000').slice(0, 3))
  return Math.round((milli * price) / 1000)
}
