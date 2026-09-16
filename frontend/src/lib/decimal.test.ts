import { fromCents, lineCents, toCents } from './decimal'

describe('cents arithmetic', () => {
  it('parses plain decimals only', () => {
    expect(toCents('2500')).toBe(250000)
    expect(toCents('12.5')).toBe(1250)
    expect(toCents('0.10')).toBe(10)
    expect(toCents('-3.75')).toBe(-375)
    expect(toCents('abc')).toBeNull()
    expect(toCents('1.234')).toBeNull()
    expect(toCents('')).toBeNull()
  })
  it('formats back with two decimals', () => {
    expect(fromCents(250000)).toBe('2500.00')
    expect(fromCents(5)).toBe('0.05')
    expect(fromCents(-375)).toBe('-3.75')
  })
  it('multiplies quantity by price with half-up rounding', () => {
    expect(lineCents('3', '0.10')).toBe(30) // the float trap: 0.1 * 3
    expect(lineCents('0.5', '33.33')).toBe(1667) // 16.665 → 16.67
    expect(lineCents('2.250', '100')).toBe(22500)
    expect(lineCents('x', '1')).toBeNull()
  })
})
