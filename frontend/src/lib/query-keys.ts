/** Query keys in one place so mutations invalidate exactly what they change. */
export const queryKeys = {
  products: {
    all: ['products'] as const,
    list: (params: Record<string, unknown>) => ['products', 'list', params] as const,
    detail: (id: string) => ['products', 'detail', id] as const,
  },
  categories: { all: ['categories'] as const },
  inventory: {
    all: ['inventory'] as const,
    movements: (params: Record<string, unknown>) => ['inventory', 'movements', params] as const,
    lowStock: ['inventory', 'low-stock'] as const,
  },
  sales: {
    all: ['sales'] as const,
    list: (params: Record<string, unknown>) => ['sales', 'list', params] as const,
    detail: (id: string) => ['sales', 'detail', id] as const,
  },
  customers: {
    all: ['customers'] as const,
    list: (params: Record<string, unknown>) => ['customers', 'list', params] as const,
    detail: (id: string) => ['customers', 'detail', id] as const,
    ledger: (id: string) => ['customers', 'ledger', id] as const,
    debtors: (params: Record<string, unknown>) => ['customers', 'debtors', params] as const,
  },
  expenses: {
    all: ['expenses'] as const,
    list: (params: Record<string, unknown>) => ['expenses', 'list', params] as const,
    categories: ['expenses', 'categories'] as const,
  },
  mpesa: {
    all: ['mpesa'] as const,
    list: (params: Record<string, unknown>) => ['mpesa', 'list', params] as const,
    detail: (id: string) => ['mpesa', 'detail', id] as const,
    reconciliation: (date: string) => ['mpesa', 'reconciliation', date] as const,
  },
  analytics: { all: ['analytics'] as const },
  business: { all: ['business'] as const },
  members: { all: ['members'] as const },
}
