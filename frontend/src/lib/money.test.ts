import { formatKsh, formatQuantity } from './money'

describe('formatKsh', () => {
  it('formats backend decimal strings without touching a float', () => {
    expect(formatKsh('2500.00')).toBe('KSh 2,500')
    expect(formatKsh('2500.50')).toBe('KSh 2,500.50')
    expect(formatKsh('1234567.05')).toBe('KSh 1,234,567.05')
    expect(formatKsh('0.10')).toBe('KSh 0.10')
    expect(formatKsh('0.00')).toBe('KSh 0')
  })
  it('keeps decimals when asked and can drop the prefix', () => {
    expect(formatKsh('2500.00', { decimals: 'always' })).toBe('KSh 2,500.00')
    expect(formatKsh('75', { bare: true })).toBe('75')
  })
  it('shows a proper minus for credit in favour', () => {
    expect(formatKsh('-500.00')).toBe('−KSh 500')
  })
  it('handles missing values and unexpected input', () => {
    expect(formatKsh(null)).toBe('—')
    expect(formatKsh(undefined)).toBe('—')
    expect(formatKsh('n/a')).toBe('n/a')
  })
})

describe('formatQuantity', () => {
  it('trims trailing zeros from NUMERIC(12,3)', () => {
    expect(formatQuantity('12.500')).toBe('12.5')
    expect(formatQuantity('3.000')).toBe('3')
    expect(formatQuantity('1250.250')).toBe('1,250.25')
  })
})
