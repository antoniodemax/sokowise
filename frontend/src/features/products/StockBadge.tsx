import { Badge } from '@/components/ui/badge'

import type { Product } from './api'

/** In stock / Low stock / Out of stock / Not tracked, from the product's own threshold. */
export function StockBadge({ product, defaultThreshold }: { product: Product; defaultThreshold?: number }) {
  if (!product.track_inventory) return <Badge variant="neutral">Not tracked</Badge>
  const stock = Number(product.stock_quantity)
  const threshold = product.low_stock_threshold !== null ? Number(product.low_stock_threshold) : defaultThreshold
  if (stock <= 0) return <Badge variant="destructive">Out of stock</Badge>
  if (threshold !== undefined && stock <= threshold) return <Badge variant="warning">Low stock</Badge>
  return <Badge variant="success">In stock</Badge>
}
