// Smoke tests for web UI endpoints
const { test, expect } = require('@playwright/test');

// Helper to assert JSON body has key
async function expectJsonOk(resp) {
  expect(resp.ok()).toBeTruthy();
  const ct = (resp.headers()['content-type'] || '').toLowerCase();
  expect(ct.includes('application/json')).toBeTruthy();
  return await resp.json();
}

test('healthz returns ok', async ({ request, baseURL }) => {
  const resp = await request.get(`${baseURL}/healthz`);
  const body = await expectJsonOk(resp);
  expect(body.status).toBe('ok');
});

test('backfill status public is accessible', async ({ request, baseURL }) => {
  const resp = await request.get(`${baseURL}/backfill/status-public`);
  expect(resp.ok()).toBeTruthy();
});

test('root or login page loads', async ({ page, baseURL }) => {
  await page.goto(`${baseURL}/`, { waitUntil: 'domcontentloaded' });
  const html = await page.content();
  expect(/Dashboard|Вход администратора|Календарь/.test(html)).toBeTruthy();
});
