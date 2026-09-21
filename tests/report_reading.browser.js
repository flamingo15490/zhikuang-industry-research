// Reading help is available before generating a report and after leaving the tour.
async (page) => {
  const results = [];
  for (const width of [1280, 390]) {
    await page.setViewportSize({width, height:900});
    await page.goto('http://localhost:7862');
    await page.locator('#welcome_report_reading button').first().click();
    const topics = page.locator('#welcome_report_reading summary');
    if (await topics.count() !== 6) throw new Error('Incomplete reading directory');
    for (let i=0; i<6; i++) {
      await topics.nth(i).click();
      await page.locator('#welcome_report_reading .report-reading').nth(i).waitFor();
      await topics.nth(i).click();
    }
    await page.getByRole('button',{name:'直接进入平台',exact:true}).click();
    await page.locator('#report_reading_overview button').first().click();
    await page.locator('#report_reading_overview .report-reading').waitFor();
    await page.locator('#report_reading_overview button').first().click();
    for (const [tab, section] of [['📊 基本面','base'],['🎯 估值','value'],['📈 技术面','tech'],['💰 资金面','capital'],['⚠️ 风险','risk']]) {
      await page.getByRole('tab',{name:tab,exact:true}).click();
      const panel = page.locator(`#report_reading_${section}`);
      await panel.locator('button').first().click();
      await panel.locator('.report-reading').waitFor();
      const bad = await panel.locator('dt,dd').evaluateAll(nodes => nodes.some(node => {
        const rect = node.getBoundingClientRect();
        return rect.left < 0 || rect.right > innerWidth + 2 || node.scrollWidth > node.clientWidth + 2;
      }));
      if (bad) throw new Error(`Reading text overflow ${width} ${section}`);
      if (section === 'value') {
        await panel.scrollIntoViewIfNeeded();
        await panel.screenshot({path:`output/playwright/report-reading-value-${width}.png`});
      }
      await panel.locator('button').first().click();
    }
    results.push({width, directory:6, reportSections:5, overflow:false});
  }
  await page.goto('http://localhost:7862');
  return results;
}
