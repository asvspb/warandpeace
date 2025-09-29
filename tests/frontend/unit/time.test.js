import { describe, it, expect } from 'vitest'
import { formatUptime } from '../../../src/webapp/static/utils/time.js'

describe('formatUptime', () => {
  it('0 seconds', () => {
    expect(formatUptime(0)).toBe('0ч 0м')
  })
  it('59 seconds', () => {
    expect(formatUptime(59)).toBe('0ч 0м')
  })
  it('61 seconds', () => {
    expect(formatUptime(61)).toBe('0ч 1м')
  })
  it('3661 seconds', () => {
    expect(formatUptime(3661)).toBe('1ч 1м')
  })
})
