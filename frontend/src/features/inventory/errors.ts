import { ApiError } from '@/lib/api'
import { describeError } from '@/lib/errors'

/** Plain-language explanations for the backend's stock errors. */
export function stockErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case 'INSUFFICIENT_STOCK':
        return 'There is not enough stock for that. Check the quantity on hand and try a smaller amount.'
      case 'PRODUCT_ARCHIVED':
        return 'This product is archived. Restore it under Products before changing its stock.'
      case 'PRODUCT_UNTRACKED':
        return 'This product does not track stock. Turn on stock tracking under Products first.'
      case 'PRODUCT_ALREADY_STOCKED':
        return 'This product already has stock movements. Use a restock or an adjustment instead.'
      case 'FORBIDDEN':
        return error.status === 403 ? 'Only the owner can do this for this business.' : error.message
    }
  }
  return describeError(error)
}
