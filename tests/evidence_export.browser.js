async (page) => {
  await page.goto('http://localhost:7862');
  await page.getByRole('tab', {name:'一键研报',exact:true}).click();
  await page.setViewportSize({width:1280,height:900});
  await page.getByRole('tab',{name:'🎯 估值',exact:true}).click();
  const query=page.getByRole('textbox',{name:'股票名称或代码',exact:true});
  async function load(code,name) {
    await query.fill(code);
    await page.getByRole('button',{name:'加载利润数据',exact:true}).click();
    await page.waitForFunction(name=>document.querySelector('#profit_meta')?.textContent.includes(name),name);
  }
  await load('601899','紫金矿业');
  await page.getByText('证据与导出',{exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#research_evidence')?.textContent.includes('营业收入'));
  const evidence=await page.locator('#research_evidence').innerText();
  if (/BASIC_EPS|_YOY/.test(evidence)) throw new Error('Nonmonetary fields in currency evidence');
  await page.getByRole('button',{name:'导出财报证据快照',exact:true}).click();
  const downloads=page.locator('a[download]');
  await page.waitForFunction(()=>document.querySelectorAll('a[download]').length===2);
  const files=await downloads.evaluateAll(nodes=>nodes.map(n=>n.getAttribute('href')));
  for(const file of files) {
    const response=await page.request.get(file.startsWith('http')?file:'http://localhost:7862'+file);
    if(!response.ok()) throw new Error('Export unreadable');
    const body=await response.text();
    if(!body.includes('2026-06-30') || /LLM_API_KEY/.test(body)) throw new Error('Wrong export period or private metadata');
  }
  await page.locator('#research_evidence').screenshot({path:'output/playwright/evidence-desktop.png'});
  const period=page.getByRole('combobox',{name:'财报报告期',exact:true});
  await period.fill('2025-12-31');
  await page.getByRole('option',{name:'2025-12-31',exact:true}).click();
  await page.waitForFunction(()=>document.querySelectorAll('a[download]').length===0);
  await page.waitForFunction(()=>document.querySelector('#profit_meta')?.textContent.includes('2025-12-31'));
  await page.getByRole('button',{name:'导出财报证据快照',exact:true}).click();
  await page.waitForFunction(()=>document.querySelectorAll('a[download]').length===2);
  await query.fill('600219');
  await page.waitForFunction(()=>document.querySelectorAll('a[download]').length===0);
  await page.waitForFunction(()=>!document.querySelector('#research_evidence')?.textContent.includes('营业收入'));
  return {currency_fields:true,downloads:2,period_invalidation:true,company_invalidation:true};
}
