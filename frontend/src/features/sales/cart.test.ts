import { describe, expect, it } from 'vitest'

import { product } from '@/test/fixtures'

import { cartTotals, newTender, syncSingleTender, tenderTotals } from './cart'

describe('cartTotals', () => {
  it('sums lines in cents and applies the discount', () => {
    const totals = cartTotals([{ product: product(), quantity: '2', unit_price: '55' }, { product: product({ id: 'p2', unit: 'kg' }), quantity: '1.5', unit_price: '120.50' }], '10')
    expect(totals).toEqual({ subtotal: 11000 + 18075, discount: 1000, total: 28075, invalidLine: null })
  })

  it('flags the first invalid line and a discount above the subtotal', () => {
    expect(cartTotals([{ product: product(), quantity: '0', unit_price: '55' }], '').invalidLine).toBe(0)
    expect(cartTotals([{ product: product(), quantity: '1', unit_price: 'abc' }], '').invalidLine).toBe(0)
    expect(cartTotals([{ product: product(), quantity: '1', unit_price: '55' }], '60').total).toBe(-500)
  })
})

describe('tenders', () => {
  it('reports what is still to pay and how much is on credit', () => {
    const tenders = [newTender('CASH', '30'), newTender('CREDIT', '20.50')]
    expect(tenderTotals(tenders, 5500)).toEqual({ tendered: 5050, remaining: 450, credit: 2050 })
  })

  it('auto-fills a single untouched tender with the total, but leaves edited ones alone', () => {
    const untouched = [newTender('CASH')]
    expect(syncSingleTender(untouched, 5500)[0].amount).toBe('55.00')
    const touched = [{ ...newTender('CASH', '20'), touched: true }]
    expect(syncSingleTender(touched, 5500)[0].amount).toBe('20')
    expect(syncSingleTender([newTender('CASH'), newTender('MPESA')], 5500).map((t) => t.amount)).toEqual(['', ''])
  })
})
