import { describe, it, expect } from 'vitest'
import { b64urlToBuf, bufToB64url } from '../../../src/webapp/static/utils/base64url.js'

function abEqual(a, b){
  const ua = a instanceof Uint8Array ? a : new Uint8Array(a)
  const ub = b instanceof Uint8Array ? b : new Uint8Array(b)
  if (ua.length !== ub.length) return false
  for (let i=0;i<ua.length;i++) if (ua[i] !== ub[i]) return false
  return true
}

describe('base64url utils', () => {
  it('roundtrip ascii', () => {
    const txt = 'hello-world_'
    const enc = new TextEncoder().encode(txt)
    const b64u = bufToB64url(enc)
    expect(typeof b64u).toBe('string')
    const back = b64urlToBuf(b64u)
    expect(abEqual(new Uint8Array(back), enc)).toBe(true)
  })

  it('roundtrip random bytes', () => {
    const buf = new Uint8Array(32)
    for (let i=0;i<buf.length;i++) buf[i] = (Math.random()*256)|0
    const b64u = bufToB64url(buf)
    const back = new Uint8Array(b64urlToBuf(b64u))
    expect(abEqual(back, buf)).toBe(true)
  })
})
