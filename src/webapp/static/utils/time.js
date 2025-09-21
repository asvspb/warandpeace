// Utility: format uptime seconds into 'Hч Mм'
export function formatUptime(seconds) {
  const s = Math.max(0, parseInt(seconds || 0, 10));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h}ч ${m}м`;
}
