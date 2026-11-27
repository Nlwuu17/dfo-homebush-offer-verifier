import { createRequire } from 'node:module';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';

const require = createRequire(path.resolve(process.env.DFO_WEB_DIR || 'web', 'package.json'));
const { chromium, expect } = require('@playwright/test');
const out = path.resolve(process.env.DFO_SCREENSHOT_DIR || 'docs/screenshots');
await mkdir(out, { recursive: true });
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ baseURL: 'http://127.0.0.1:3000', viewport: { width: 1440, height: 1050 }, deviceScaleFactor: 2 });
  async function capture(name) {
    await page.evaluate(() => document.fonts.ready);
    await page.locator('main').screenshot({ path: path.join(out, name), animations: 'disabled' });
  }
  await page.goto('/compare');
  await page.getByRole('combobox').selectOption('BF26-02');
  await expect(page.getByText('LLM 不可用', {exact:true})).toBeVisible();
  await expect(page.getByRole('checkbox', { checked: true })).toHaveCount(2);
  await page.getByRole('button', { name: /运行对照/ }).click();
  for (const name of ['固定查询', '规则策略']) {
    const card = page.getByRole('article', { name, exact: true });
    await expect(card.locator('.verdict')).toHaveText('不适用');
    await expect(card.locator('details')).toHaveCount(3);
    await card.locator('summary').first().click();
  }
  await capture('compare-bf26-02.png');
  await page.goto('/');
  await page.getByLabel('品牌', {exact:true}).fill('Tommy Hilfiger');
  await page.getByLabel('官方优惠链接').fill('https://www.homebush.dfo.com.au/offers/tommy-hilfiger-black-friday-november-2026-tommy-hilfiger');
  await page.getByLabel('核对日期').fill('2026-11-26');
  await page.getByRole('button', { name:'核对并保存' }).click();
  await expect(page.locator('.verdict')).toHaveText('适用');
  await page.getByRole('button', { name:/选用：/ }).click();
  await page.getByRole('button', { name:'保存新的核对版本' }).click();
  await expect(page.getByText('适用 → 适用')).toBeVisible();
  const cards = page.locator('.citation');
  await expect(cards).toHaveCount(2);
  await expect(cards.first()).toContainText('TH-BF · 结论引用');
  await expect(cards.last()).toContainText('TH-FLYER · 已读资料');
  await capture('record-tommy-v2.png');
  await page.getByLabel('历史版本').selectOption('0');
  await expect(page.locator('.verdict')).toHaveText('适用');
  await expect(cards).toHaveCount(1);
  await expect(cards.first()).toContainText('TH-BF · 结论引用');
  await capture('record-tommy-v1.png');
  console.log(out);
} finally {
  await browser.close();
}
