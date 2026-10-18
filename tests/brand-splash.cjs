// Run against `python3 -m http.server 8765 --directory docs`.
// Requires Playwright; PLAYWRIGHT_MODULE may point to an existing installation.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:8765';
(async () => {
  const browser = await chromium.launch({ headless: true });
  const errors = [];
  async function fresh(options = {}, setup) {
    const context = await browser.newContext(options);
    await context.route(/fonts\.(googleapis|gstatic)\.com/, route => route.abort());
    const page = await context.newPage();
    page.on('pageerror', e => errors.push(e.message));
    if (setup) await setup(page);
    await page.clock.install({ time: new Date('2026-10-18T12:00:00Z') });
    await page.clock.pauseAt(new Date('2026-10-18T12:00:01Z'));
    await page.goto(base, { waitUntil: 'networkidle' });
    return { context, page };
  }
  async function open(page) { await page.locator('.art-splash[open]').waitFor(); }
  async function closed(page) { assert.equal(await page.locator('.art-splash').evaluate(d => d.open), false); }
  const { context, page } = await fresh();
  await open(page);
  assert.equal(await page.locator('.art-skip').evaluate(b => b === document.activeElement), true);
  await page.keyboard.press('Tab');
  // Native dialog keeps focus within itself (or on the browser's tab-cycle boundary).
  assert.equal(await page.locator('.brand-art').evaluate(b => b === document.activeElement), false);
  await page.keyboard.press('Escape');
  await closed(page);
  assert.equal(await page.locator('body').evaluate(b => b.style.overflow), '');
  await page.reload({ waitUntil: 'networkidle' });
  await closed(page);
  await page.goto(base + '/pages/team.html', { waitUntil: 'networkidle' });
  await closed(page);
  const trigger = page.locator('.brand-art');
  await trigger.click(); await closed(page);
  await page.clock.runFor(1000);
  await trigger.dblclick(); await closed(page);
  // Reset click timing before checking a distinct triple-click.
  await page.clock.runFor(1000);
  await trigger.click({ clickCount: 3, delay: 70 });
  await open(page);
  assert.match(await page.locator('.art-splash-image').getAttribute('src'), /\/images\/brand\/[^/]+\.webp$/);
  assert.ok(await page.locator('.art-splash-image').evaluate(i => i.naturalWidth > 0));
  await page.keyboard.press('Escape');
  assert.equal(await trigger.evaluate(b => b === document.activeElement), true);
  await page.keyboard.press('Enter'); await open(page);
  await page.locator('.art-skip').click(); await closed(page);
  await trigger.focus(); await page.keyboard.press('Space'); await open(page);
  await page.mouse.click(5, 5); await closed(page);
  await page.locator('.brand-lockup a').click();
  await page.waitForURL('**/index.html'); await closed(page);
  console.log('PASS session persistence, interior replay, pointer/keyboard activation, dismissal, focus restoration, home navigation');
  await context.close();

  const editions = ['Dali', 'Kandinsky', 'Monet', 'Picasso', 'Warhol'];
  for (let i = 0; i < editions.length; i++) {
    const r = i === 4 ? 0.999 : i / 5;
    const duration = 3000 + r * 4000;
    const test = await fresh({}, p => p.addInitScript(value => { Math.random = () => value; }, r));
    await open(test.page);
    assert.match(await test.page.locator('.art-edition').textContent(), new RegExp(editions[i]));
    await test.page.clock.runFor(Math.floor(duration) - 200);
    assert.equal(await test.page.locator('.art-splash').evaluate(d => d.open), true);
    await test.page.clock.runFor(201);
    await closed(test.page);
    console.log('PASS random edition and lifetime', editions[i], duration);
    await test.context.close();
  }
  for (const width of [1280, 800, 390]) {
    const test = await fresh({ viewport: { width, height: 900 } });
    await open(test.page);
    await test.page.screenshot({ path: `/private/tmp/awake-splash-${width}.png` });
    assert.equal(await test.page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    const box = await test.page.locator('.art-splash-image').boundingBox();
    assert.ok(box.width <= Math.min(440, width * 0.8) + 1);
    await test.page.locator('.art-skip').click();
    await test.page.screenshot({ path: `/private/tmp/awake-brand-${width}.png` });
    assert.equal(await test.page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    if (width === 390) {
      await test.page.locator('.nav-toggle').click();
      assert.equal(await test.page.locator('.nav-toggle').getAttribute('aria-expanded'), 'true');
    }
    const broken = await test.page.locator('.brand-lockup img, .footer-lockup img').evaluateAll(imgs => imgs.filter(i => !i.complete || !i.naturalWidth).length);
    assert.equal(broken, 0);
    console.log('PASS responsive artwork and header', width);
    await test.context.close();
  }
  const reduced = await fresh({ reducedMotion: 'reduce' });
  await open(reduced.page);
  assert.equal(await reduced.page.locator('.art-splash-content').evaluate(e => getComputedStyle(e).animationName), 'none');
  await reduced.context.close();
  const storage = await fresh({}, p => p.addInitScript(() => Object.defineProperty(window, 'sessionStorage', { get() { throw new Error('blocked'); } })));
  await closed(storage.page);
  await storage.page.locator('.brand-art').focus(); await storage.page.keyboard.press('Enter'); await open(storage.page);
  await storage.context.close();
  const failure = await fresh({}, p => p.route(/\/(dali|kandinsky|monet|picasso|warhol)\.webp/, route => route.abort()));
  await closed(failure.page);
  assert.equal(await failure.page.locator('body').evaluate(b => b.style.overflow), '');
  await failure.context.close();
  const nojs = await fresh({ javaScriptEnabled: false });
  await closed(nojs.page);
  assert.equal(await nojs.page.locator('.brand-art').isVisible(), false);
  assert.equal(await nojs.page.locator('.brand-lockup .brand').isVisible(), true);
  await nojs.context.close();
  assert.deepEqual(errors, []);
  console.log('PASS reduced motion, blocked storage, image failure, JavaScript disabled, no browser errors');
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
