// Run with playwright-cli run-code --filename tests/rank_hover.browser.js
async (page) => {
  await page.goto('http://127.0.0.1:7861');
  await page.getByRole('tab', {name: '一键研报', exact: true}).click();
  const cases = [
    ['600111', '稀土', 8], ['600219', '铝', 28], ['600255', '铜', 20],
    ['600547', '黄金', 13], ['603399', '锂', 7], ['603799', '镍', 3],
    ['600366', '其他', 36], ['600281', '贵金属', 19], ['600338', '白银', 5],
    ['600301', '工业金属', 58], ['600456', '钛', 5], ['600549', '钨', 4],
    ['600497', '锌', 5], ['002428', '战略金属', 27],
  ];
  const results = [];
  for (const [width, height] of [[1280, 720], [390, 844]]) {
    await page.setViewportSize({width, height});
    for (const [code, sector, count] of cases) {
      await page.getByRole('textbox', {name: '股票名称或代码'}).fill(code);
      await page.getByRole('button', {name: '生成完整研报', exact: true}).click();
      const trigger = page.locator('.rank-trigger').filter({hasText: sector + '排名'});
      await trigger.waitFor();
      await trigger.evaluate((element, fraction) => {
        window.scrollBy(0, element.getBoundingClientRect().top - innerHeight * fraction);
      }, count % 2 ? 0.8 : 0.2);
      await trigger.hover();
      const state = await page.locator('.rank-tooltip').evaluate(tip => {
        const rect = tip.getBoundingClientRect();
        const trigger = tip.previousElementSibling.getBoundingClientRect();
        return {
          bound: tip.parentElement.dataset.rankBound === '1',
          visible: getComputedStyle(tip).display !== 'none' && rect.top >= 0 && rect.bottom <= innerHeight
            && rect.left >= 0 && rect.right <= innerWidth,
          overlaps: rect.top < trigger.bottom && rect.bottom > trigger.top,
          top: rect.top,
          bottom: rect.bottom,
          viewport: innerHeight,
          count: tip.querySelectorAll('li').length,
        };
      });
      if (!state.bound || !state.visible || state.overlaps || state.count !== count) {
        throw new Error(`${sector} ${width}: ` + JSON.stringify(state));
      }
      const box = await page.locator('.rank-tooltip').boundingBox();
      const origin = await trigger.boundingBox();
      await page.mouse.move(origin.x + origin.width / 2,
        box.y < origin.y ? box.y + box.height - 2 : box.y + 2, {steps: 12});
      await page.mouse.move(box.x + 30, box.y + 30, {steps: 8});
      await page.mouse.wheel(0, 10000);
      await page.waitForFunction(() => {
        const tip = document.querySelector('.rank-tooltip');
        return tip && tip.scrollHeight - tip.clientHeight - tip.scrollTop <= 1;
      }, null, {timeout: 3000});
      if (!await page.locator('.rank-tooltip').isVisible()) {
        throw new Error(`${sector}: ranking closed while entering the list`);
      }
      if (sector === '工业金属') {
        await page.screenshot({path: `output/playwright/rank-hover-${width}.png`});
      }
      await page.mouse.move(1, 1);
      if (await page.locator('.rank-tooltip').isVisible()) {
        throw new Error(`${sector}: ranking did not close on mouse leave`);
      }
      results.push(`${width}: ${sector} (${count})`);
    }
  }
  return {passed: results};
}
