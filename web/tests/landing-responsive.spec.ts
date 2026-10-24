import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test.use({ reducedMotion: 'reduce' });

for (const [width, height] of [
  [360, 640],
  [768, 900],
  [1024, 768],
  [1180, 650],
]) {
  test(`public landing navigation and hero fit at ${width} × ${height}`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height });
    await page.goto('/');
    await expect(page.locator('.lp-hero-title')).toBeVisible();
    const hero = page.locator('.lp-hero');
    const cta = hero.locator('.lp-btn:visible');
    await expect(cta).toBeVisible();
    expect(await cta.getAttribute('href')).toBe('/sign-in?mode=create');
    const bounds = await hero.boundingBox();
    const action = await cta.boundingBox();
    expect(action!.y + action!.height).toBeLessThanOrEqual(
      bounds!.y + bounds!.height,
    );
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

    if (width < 900) {
      await page.getByRole('button', { name: 'Open menu' }).click();
      await expect(page.locator('#mobile-menu')).toBeVisible();
      await page
        .locator('#mobile-menu')
        .getByRole('link', { name: 'How it works' })
        .click();
      await expect(page.locator('#mobile-menu')).toHaveCount(0);
      await expect(page).toHaveURL(/#how$/);
    } else {
      await expect(page.locator('.lp-nav')).toBeVisible();
    }
  });
}
