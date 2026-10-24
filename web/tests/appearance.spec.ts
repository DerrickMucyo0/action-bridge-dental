import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { tmpdir } from 'node:os';
import { mockBackend } from './mock-api';

const phase = process.env.APPEARANCE_PHASE ?? 'after';
// Keep screenshots of unverified reference imagery outside the working project.
const directory = process.env.APPEARANCE_OUTPUT_DIR
  ? path.resolve(process.env.APPEARANCE_OUTPUT_DIR)
  : phase === 'reference'
    ? path.join(tmpdir(), 'actionbridge-appearance-reference')
    : path.resolve('..', 'docs', 'visual-restoration', phase);
test.use({ reducedMotion: 'reduce' });

for (const [device, width, height] of [
  ['desktop', 1440, 900],
  ['mobile', 390, 844],
] as const) {
  test(`${device}: landing, account and dashboard appearance`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height });
    await mockBackend(page);
    await mkdir(directory, { recursive: true });
    const metrics: Record<string, unknown> = {};
    const capture = async (name: string, fullPage = false) => {
      await page.evaluate(async () => {
        const family = document.querySelector('.lp, .si')
          ? 'Geist'
          : '"Plus Jakarta Sans"';
        await Promise.all(
          [400, 500, 600].map((weight) =>
            document.fonts.load(`${weight} 16px ${family}`),
          ),
        );
        await document.fonts.ready;
      });
      expect(
        await page.evaluate(() =>
          document.fonts.check(
            document.querySelector('.lp, .si')
              ? '500 16px Geist'
              : '500 16px "Plus Jakarta Sans"',
          ),
        ),
      ).toBe(true);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: path.join(directory, `${name}-${device}.png`),
        fullPage,
        animations: 'disabled',
      });
      metrics[name] = await page
        .locator('h1, .lp-hero-title, .home-intro h2')
        .first()
        .evaluate((element) => {
          const { x, y, width, height } = element.getBoundingClientRect();
          const style = getComputedStyle(element);
          return { x, y, width, height, font: style.font, color: style.color };
        });
    };

    await page.goto('/');
    await expect(page.locator('.lp-hero-title')).toBeVisible();
    await capture('landing');
    await capture('landing-full', true);
    await page.locator('#product').scrollIntoViewIfNeeded();
    await capture('product');
    await page.locator('.lp-numbers-media').scrollIntoViewIfNeeded();
    await capture('estimate');
    await page.goto('/sign-in');
    await expect(page.getByLabel('Email', { exact: true })).toBeVisible();
    await capture('sign-in');
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

    await page.getByLabel('Email', { exact: true }).fill('jordan@example.com');
    await page
      .getByLabel('Password', { exact: true })
      .fill('Fictional-review-password-1');
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await expect(
      page.getByRole('heading', {
        name: "Let's make sense of your dental costs.",
      }),
    ).toBeVisible();
    await capture('dashboard', true);
    await writeFile(
      path.join(directory, `metrics-${device}.json`),
      JSON.stringify(metrics, null, 2) + '\n',
    );
  });
}
