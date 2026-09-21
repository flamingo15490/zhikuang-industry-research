// Validate the published v2 score workflow in the real application.
async (page) => {
  await page.goto('http://localhost:7862');
  await page.getByRole('tab', {name: '五维评分', exact: true}).click();
  const results = [];
  for (const [width, height] of [[1280, 900], [390, 844]]) {
    await page.setViewportSize({width, height});
    const input = page.getByRole('textbox', {name: '评分公司', exact: true});
    await input.fill('南山铝业');
    await page.getByRole('button', {name: '查看评分快照', exact: true}).click();
    await page.locator('#score_meta').getByText(/南山铝业/).waitFor();
    await page.locator('#score_radar .js-plotly-plot').waitFor();
    const meta = await page.locator('#score_meta').textContent();
    if (!meta.includes('版本：2.0') || !meta.includes('财务报告期')) throw new Error(meta);
    const details = await page.locator('#score_details').innerText();
    if (!details.includes('净资产收益率') || !details.includes('五日净流入')) throw new Error(details);
    await page.getByRole('button', {name: /^数据日期与缺项/}).click();
    await page.locator('#score_quality').getByText(/来源与数据状态/).waitFor();
    await page.locator('#score_meta').scrollIntoViewIfNeeded();
    await page.screenshot({path: `output/playwright/score-v2-${width}.png`});
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 2);
    if (overflow) throw new Error(`page overflow at ${width}`);
    await input.fill('不存在的公司');
    await page.waitForFunction(() => document.querySelector('#score_meta').innerText.includes('尚未加载'));
    if (await page.locator('#score_rank').innerText()) throw new Error('stale rank');
    await page.getByRole('button', {name: '查看评分快照', exact: true}).click();
    await page.locator('#score_meta').getByText(/未找到唯一有效公司/).waitFor();
    await page.getByRole('button', {name: /^数据日期与缺项/}).click();
    await input.fill('华阳新材');
    await page.getByRole('button', {name: '查看评分快照', exact: true}).click();
    await page.locator('#score_meta').getByText(/华阳新材/).waitFor();
    const missing = await page.locator('#score_meta').innerText();
    if (!missing.includes('综合分：缺项') || !missing.includes('不参与综合排名')) throw new Error(missing);
    if (await page.locator('#score_rank').innerText()) throw new Error('ineligible company has ranking');
    const plot = await page.locator('#score_radar .js-plotly-plot').evaluate(node => ({
      values: node.data[0].r, fill: node.data[0].fill, connect: node.data[0].connectgaps
    }));
    if (!plot.values.includes(null) || plot.fill !== 'none' || plot.connect !== false) throw new Error(JSON.stringify(plot));
    results.push({width, valid: true, clearsOldResult: true});
  }
  return results;
}
