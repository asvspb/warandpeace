// @ts-check
/** @type {import('@playwright/test').PlaywrightTestConfig} */
const config = {
  testDir: 'tests/frontend/e2e',
  timeout: 30_000,
  use: {
    baseURL: process.env.WP_BASE_URL || 'http://localhost:8080',
    trace: 'retain-on-failure'
  }
};
module.exports = config;
