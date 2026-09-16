import { PAYMENT_LABELS, type Sale } from './api'

/** "Cash + M-Pesa" — the distinct tender methods on a sale. */
export function tenderSummary(sale: Sale): string {
  const methods = [...new Set(sale.payments.map((p) => p.method))]
  return methods.map((m) => PAYMENT_LABELS[m]).join(' + ') || '—'
}
