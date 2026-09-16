/**
 * Cart arithmetic for the sell screen, in cents, so what the cashier sees matches
 * what the backend will compute (docs/PRD.md BR-9). The backend remains the
 * authority: it re-validates lines, discount and tenders on submit.
 */
import { fromCents, lineCents, toCents } from '@/lib/decimal'

import type { Product } from '@/features/products/api'

import type { PaymentMethod } from './api'

export interface CartLine {
  product: Product
  quantity: string
  unit_price: string
}

export interface Tender {
  id: string
  method: PaymentMethod
  amount: string
  reference: string
  /** Once the cashier edits the amount we stop auto-filling it from the total. */
  touched: boolean
}

export interface CartTotals {
  subtotal: number | null
  discount: number | null
  total: number | null
  /** Index of the first line whose quantity or price does not parse. */
  invalidLine: number | null
}

export function cartTotals(lines: CartLine[], discount: string): CartTotals {
  let subtotal = 0
  let invalidLine: number | null = null
  lines.forEach((line, index) => {
    const cents = lineCents(line.quantity, line.unit_price)
    if (cents === null || cents < 0 || Number(line.quantity) <= 0) {
      invalidLine ??= index
      return
    }
    subtotal += cents
  })
  const discountCents = discount.trim() === '' ? 0 : toCents(discount)
  if (invalidLine !== null) return { subtotal: null, discount: discountCents, total: null, invalidLine }
  if (discountCents === null || discountCents < 0) return { subtotal, discount: null, total: null, invalidLine }
  return { subtotal, discount: discountCents, total: subtotal - discountCents, invalidLine }
}

export interface TenderTotals {
  tendered: number | null
  /** total − tendered; positive means the customer still has to pay. */
  remaining: number | null
  credit: number
}

export function tenderTotals(tenders: Tender[], total: number | null): TenderTotals {
  let tendered = 0
  let credit = 0
  for (const tender of tenders) {
    const cents = tender.amount.trim() === '' ? 0 : toCents(tender.amount)
    if (cents === null || cents < 0) return { tendered: null, remaining: null, credit }
    tendered += cents
    if (tender.method === 'CREDIT') credit += cents
  }
  return { tendered, remaining: total === null ? null : total - tendered, credit }
}

export function newTender(method: PaymentMethod, amount = ''): Tender {
  return { id: crypto.randomUUID(), method, amount, reference: '', touched: amount !== '' }
}

/** Auto-fill a single untouched tender with the whole total. */
export function syncSingleTender(tenders: Tender[], total: number | null): Tender[] {
  if (tenders.length !== 1 || tenders[0].touched) return tenders
  const amount = total === null || total < 0 ? '' : fromCents(total)
  return tenders[0].amount === amount ? tenders : [{ ...tenders[0], amount }]
}
