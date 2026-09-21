// Local-only checks; return statuses, never licensed observations or screenshots.
async (page) => {
  const results=[];
  for (const width of [1280,390]) {
    await page.setViewportSize({width,height:900});
    await page.goto('http://localhost:7862/');
    await page.getByRole('button',{name:'直接进入平台',exact:true}).click();
    await page.getByRole('textbox',{name:'股票名称或代码',exact:true}).fill('601899');
    await page.locator('#wind_local_panel button').first().click();
    await page.locator('#wind_local_result h3').filter({hasText:'紫金矿业'}).waitFor();
    if (!await page.locator('#wind_local_result').getByText('Wind技术指标暂缺', {exact:false}).count()) throw new Error('Missing limitations');
    const period=page.getByRole('combobox',{name:'补充数据报告期',exact:true});
    await period.fill('2026-06-30');
    await page.getByRole('option',{name:'2026-06-30',exact:true}).click();
    await page.locator('#wind_local_result h3').filter({hasText:'2026-06-30'}).waitFor();
    await page.getByRole('textbox',{name:'股票名称或代码',exact:true}).fill('无效公司');
    await page.locator('#wind_local_result').getByText('未找到唯一公司，请填写完整名称或六位证券代码。',{exact:true}).waitFor();
    if (await page.locator('#wind_local_result table').count()) throw new Error('Stale company data');
    results.push({width,company:true,period:true,clearStale:true});
  }
  for (const file of ['sheet1.csv','sheet2.xlsx','data/wind_import/local_supplement.json']) {
    const response=await page.request.get('http://localhost:7862/gradio_api/file='+file);
    if (response.status()===200) throw new Error('Raw file served: '+file);
  }
  await page.goto('http://localhost:7862/');
  return {results,rawFileAccessBlocked:true};
}
