import { Badge } from '@/components/ui/badge'
import { formatKsh } from '@/lib/money'

/** What a customer owes (or is owed), as a badge. */
export function BalanceBadge({ balance }: { balance: string }) {
  const value = Number(balance)
  if (value > 0) return <Badge variant="warning">Owes {formatKsh(balance)}</Badge>
  if (value < 0) return <Badge variant="info">Credit {formatKsh(balance.replace('-', ''))}</Badge>
  return <Badge variant="neutral">Nothing owed</Badge>
}
