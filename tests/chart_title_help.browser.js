async (page) => {
  await page.goto('http://localhost:7862');
  await page.getByRole('tab', {name:'一键研报',exact:true}).click();
  const results = [];
  for (const width of [1280, 390]) {
    await page.setViewportSize({width, height:900});
    await page.getByRole('tab', {name:'📊 基本面', exact:true}).click();
    for (const title of ['主营构成', '宏观周期状态']) {
      const button = page.locator('label').filter({hasText:title}).locator('.term-help');
      await button.hover({timeout:3000});
      const tip = page.locator('#term-tooltip');
      await tip.waitFor({state:'visible', timeout:3000});
      if (!(await tip.innerText()).includes(title)) throw new Error(`Wrong explanation: ${title}`);
      await button.click();
      await page.mouse.move(1,1);
      if (!await tip.isVisible()) throw new Error('Click did not pin tooltip');
      const box = await tip.boundingBox();
      if (box.x < 0 || box.x + box.width > width || box.y < 0 || box.y + box.height > 900)
        throw new Error('Tooltip outside viewport');
      await page.screenshot({path:`output/playwright/chart-title-help-${width}-${title === '主营构成' ? 'mix' : 'macro'}.png`});
      await page.keyboard.press('Escape');
      await tip.waitFor({state:'hidden'});
      results.push(`${width}: ${title}`);
    }
  }
  return results;
}
