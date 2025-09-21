// Utility: base64url <-> ArrayBuffer
// Not wired into production scripts (register.js/login.js) to avoid changing browser script type.
// Used by unit tests and future refactors.
export function b64urlToBuf(s) {
  const pad = '='.repeat((4 - (s.length % 4)) % 4);
  const b = (s + pad).replace(/-/g, '+').replace(/_/g, '/');
  const raw = Buffer.from(b, 'base64');
  return raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength);
}

export function bufToB64url(buf) {
  const u8 = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
  const b64 = Buffer.from(u8).toString('base64');
  return b64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}
