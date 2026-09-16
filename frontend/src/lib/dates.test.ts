import { describe, expect, it } from 'vitest'

import { localDate, zonedDayRange, zonedStartOfDay } from './dates'

describe('zoned dates', () => {
  it('finds the start of a Nairobi day (UTC+3) and a half-open range', () => {
    expect(zonedStartOfDay('2026-09-16', 'Africa/Nairobi').toISOString()).toBe('2026-09-15T21:00:00.000Z')
    expect(zonedDayRange('2026-09-16', '2026-09-30', 'Africa/Nairobi')).toEqual({ from: '2026-09-15T21:00:00.000Z', to: '2026-09-30T21:00:00.000Z' })
    expect(zonedStartOfDay('2026-01-01', 'UTC').toISOString()).toBe('2026-01-01T00:00:00.000Z')
  })

  it('reports the calendar date of an instant in the business timezone', () => {
    expect(localDate(new Date('2026-09-16T22:30:00Z'), 'Africa/Nairobi')).toBe('2026-09-17')
    expect(localDate(new Date('2026-09-16T22:30:00Z'), 'UTC')).toBe('2026-09-16')
  })
})
