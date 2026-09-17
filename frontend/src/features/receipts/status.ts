import { ApiError } from '@/lib/api'
import { describeError } from '@/lib/errors'

import { ACCEPTED_TYPES, MAX_RECEIPT_BYTES, type ReceiptStatus } from './api'

export const STATUS_LABELS: Record<ReceiptStatus, { label: string; variant: 'neutral' | 'info' | 'warning' | 'success' | 'destructive' }> = {
  UPLOADED: { label: 'Not read yet', variant: 'neutral' },
  PROCESSING: { label: 'Reading…', variant: 'info' },
  READY_FOR_REVIEW: { label: 'Needs your review', variant: 'warning' },
  CONFIRMED: { label: 'Stock added', variant: 'success' },
  FAILED: { label: 'Could not read', variant: 'destructive' },
  CANCELLED: { label: 'Cancelled', variant: 'neutral' },
}

export const WARNING_TEXT: Record<string, string> = {
  line_total_mismatch: 'Quantity × cost does not equal the printed line total',
  zero_unit_cost: 'No cost was read for this line',
  low_confidence: 'This line was hard to read',
  subtotal_mismatch: 'The lines do not add up to the printed subtotal',
  total_mismatch: 'The lines do not add up to the printed total',
  currency_not_kes: 'The receipt is not in KSh',
}

/** Receipt/AI/storage errors carry a safe, specific message from the backend. */
export function describeReceiptError(error: unknown): string {
  return error instanceof ApiError && ['RECEIPT_', 'AI_', 'STORAGE_', 'PRODUCT_'].some((p) => error.code.startsWith(p)) ? error.message : describeError(error)
}

/** Checks the file before it leaves the phone; the backend re-checks the bytes regardless. */
export function checkReceiptFile(file: File): string | null {
  if (!ACCEPTED_TYPES.includes(file.type)) return 'Choose a JPEG, PNG or WebP photo of the receipt.'
  if (file.size > MAX_RECEIPT_BYTES) return `That photo is too large (over ${Math.round(MAX_RECEIPT_BYTES / 1024 / 1024)} MB). Take a smaller one or lower the camera resolution.`
  if (file.size === 0) return 'That file is empty.'
  return null
}
