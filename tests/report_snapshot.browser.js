// One real model-backed report; viewports reuse the result without another API call.
async (page) => {
  async function selectTab(name) {
    const tab = page.getByRole('tab',{name,exact:true});
    if (await tab.isVisible()) return tab.click();
    const menuItem = page.getByRole('button',{name,exact:true});
    if (!await menuItem.isVisible()) await page.getByRole('button',{name:'More tabs',exact:true}).last().click();
    await menuItem.click();
  }
  const loaded = await page.locator('#status_bar').count()
    && (await page.locator('#status_bar').innerText()).includes('生成完成')
    && await page.getByRole('textbox',{name:'股票名称或代码'}).inputValue() === '南山铝业';
  if (!loaded) {
    await page.goto('http://localhost:7862');
    await page.getByRole('tab',{name:'一键研报',exact:true}).click();
    await page.getByRole('textbox',{name:'股票名称或代码'}).fill('南山铝业');
    await page.getByRole('button',{name:'生成完整研报',exact:true}).click();
  }
  await page.setViewportSize({width:1280,height:900});
  await page.waitForFunction(() => document.querySelector('#status_bar')?.textContent.includes('生成完成'),
                             null,{timeout:180000});
  await page.locator('#radar_plot .js-plotly-plot').waitFor();
  await selectTab('📊 基本面');
  await page.locator('#metal_mix_plot .js-plotly-plot').waitFor();
  const mix = await page.locator('#metal_mix_plot .js-plotly-plot').evaluate(p => ({
    title:p.layout.title.text,total:p.data[0].values.reduce((a,b)=>a+b,0)
  }));
  if (!mix.title.includes('2025-12-31') || Math.abs(mix.total-1)>1e-6) throw new Error(JSON.stringify(mix));
  const results=[];
  for (const width of [1280,390]) {
    await page.setViewportSize({width,height:900});
    await selectTab('📊 基本面');
    await page.locator('#metal_mix_plot').scrollIntoViewIfNeeded();
    await page.screenshot({path:`output/playwright/report-snapshot-mix-${width}.png`});
    await selectTab('📈 技术面');
    const text = await page.locator('.prose.report_md:visible').innerText();
    if (!text.includes('2025-12-31') || !text.includes('2026-09-04') || text.includes('HTTPError')) throw new Error(text);
    await page.locator('.prose.report_md:visible').scrollIntoViewIfNeeded();
    await page.screenshot({path:`output/playwright/report-snapshot-tech-${width}.png`});
    if (await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2)) throw new Error('page overflow');
    await selectTab('🎯 估值');
    await page.waitForFunction(()=>document.querySelector('#profit_meta').textContent.includes('2025-12-31'));
    results.push({width,samePeriod:true,datedTechnical:true});
  }
  return {mix,results};
}
