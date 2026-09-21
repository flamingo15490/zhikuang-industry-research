async (page) => {
  await page.goto('http://localhost:7862');
  await page.getByRole('tab', {name:'一键研报',exact:true}).click();
  await page.setViewportSize({width:1280,height:900});
  await page.getByRole('button',{name:'术语速查',exact:false}).click();
  const query=page.getByRole('textbox',{name:'搜索术语或解释',exact:true});
  await query.fill('pe');
  await page.waitForFunction(()=>document.querySelector('#glossary_results dt')?.textContent==='PE');
  await query.fill('1.25');
  await page.waitForFunction(()=>document.querySelector('#glossary_results dt')?.textContent==='成材率');
  await query.fill('not-a-term-xyz');
  await page.getByText('没有匹配的术语。',{exact:true}).waitFor();
  await query.fill('');
  await page.getByText('常用术语',{exact:true}).waitFor();
  await page.locator('#glossary_lookup').screenshot({path:'output/playwright/readability-glossary-desktop.png'});
  await page.setViewportSize({width:390,height:844});
  await page.locator('#glossary_lookup').screenshot({path:'output/playwright/readability-glossary-mobile.png'});
  await page.getByRole('button',{name:'术语速查',exact:false}).click();
  await page.getByRole('textbox',{name:'股票名称或代码'}).fill('600219');
  await page.getByRole('tab',{name:'🎯 估值',exact:true}).click();
  await page.getByRole('button',{name:'加载利润数据',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#profit_meta')?.textContent.includes('南山铝业'));
  const table=page.locator('#profit_meta table');
  if ((await table.locator('td').allTextContents()).join('|') !== '185.74|39.56|22.47')
    throw new Error('Overview did not match acquired statement');
  const bounds=await table.boundingBox();
  if(bounds.x<0||bounds.x+bounds.width>390) throw new Error('Mobile table overflow');
  await page.locator('#profit_meta').screenshot({path:'output/playwright/readability-overview-mobile.png'});
  await page.setViewportSize({width:1280,height:900});
  await page.locator('#profit_meta').screenshot({path:'output/playwright/readability-overview-desktop.png'});
  await page.getByRole('textbox',{name:'股票名称或代码'}).fill('not-a-stock');
  await page.waitForFunction(()=>!document.querySelector('#profit_meta table'));
  return {search:true,emptyResult:true,overviewMatchesCache:true,mobile:true,staleCleared:true};
}
