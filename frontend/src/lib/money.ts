/**
 * KES money formatting. The backend serialises money as decimal strings
 * ("2500.00"); we format those strings directly and never go through a float,
 * so nothing is rounded or drifts on the way to the screen.
 *
 * Convention (docs/ARCHITECTURE.md §4): whole amounts show no decimals
 * ("KSh 2,500"); fractional amounts show two ("KSh 2,500.50").
 */

const CURRENCY = 'KSh'

export interface MoneyFormatOptions {
  /** "auto" (default) hides ".00"; "always" keeps two decimals. */
  decimals?: 'auto' | 'always'
  /** Omit the "KSh " prefix. */
  bare?: boolean
}

function groupThousands(digits: string): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

export function formatKsh(value: string | number | null | undefined, options: MoneyFormatOptions = {}): string {
  if (value === null || value === undefined || value === '') return '—'
  const raw = typeof value === 'number' ? value.toFixed(2) : String(value).trim()
  const match = /^(-)?(\d+)(?:\.(\d+))?$/.exec(raw)
  if (!match) return raw
  const [, sign, whole, fraction = ''] = match
  const cents = (fraction + '00').slice(0, 2)
  const showDecimals = options.decimals === 'always' || cents !== '00'
  const body = `${groupThousands(whole)}${showDecimals ? `.${cents}` : ''}`
  const prefix = options.bare ? '' : `${CURRENCY} `
  return `${sign ? '−' : ''}${prefix}${body}`
}

/** Quantities (NUMERIC(12,3)) — trailing zeros trimmed: "12.500" → "12.5", "3.000" → "3". */
export function formatQuantity(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const raw = typeof value === 'number' ? String(value) : String(value).trim()
  const match = /^(-)?(\d+)(?:\.(\d+))?$/.exec(raw)
  if (!match) return raw
  const [, sign, whole, fraction = ''] = match
  const trimmed = fraction.replace(/0+$/, '')
  return `${sign ?? ''}${groupThousands(whole)}${trimmed ? `.${trimmed}` : ''}`
}
