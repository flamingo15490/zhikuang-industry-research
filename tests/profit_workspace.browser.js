// Run against python webui.py --port 7862 with playwright-cli run-code --filename.
async (page) => {
  await page.goto('http://127.0.0.1:7862');
  await page.getByRole('tab', {name:'一键研报',exact:true}).click();
  await page.setViewportSize({width: 1280, height: 900});
  const query = page.getByRole('textbox', {name: '股票名称或代码'});
  await page.getByRole('tab', {name: '🎯 估值', exact: true}).click();
  const results = [];
  async function load(code, name) {
    await query.fill(code);
    await page.getByRole('button', {name: '加载利润数据', exact: true}).click();
    await page.waitForFunction(name => document.querySelector('#profit_meta')?.textContent.includes(name), name);
    await page.getByRole('tab', {name: '财报利润桥', exact: true}).click();
    await page.waitForFunction(() => document.querySelector('#profit_bridge_plot .js-plotly-plot')?.data?.length > 0);
    await page.waitForFunction(() => {
      const plot = document.querySelector('#profit_bridge_plot .js-plotly-plot');
      return Math.abs(plot._fullLayout.width - plot.getBoundingClientRect().width) < 2;
    });
    const check = await page.locator('#profit_bridge_plot .js-plotly-plot').evaluate(plot => ({
      count: plot.data[0].x.length, title: plot.layout.title.text,
      finite: plot.data[0].x.every(Number.isFinite),
    }));
    if (!check.finite || check.count < 3 || !check.title.includes(name)) throw new Error(JSON.stringify(check));
    return check;
  }
  for (const [code, name] of [['600219','南山铝业'], ['601600','中国铝业'], ['601899','紫金矿业'],
                             ['600362','江西铜业'], ['002466','天齐锂业'], ['600111','北方稀土'], ['600459','贵研铂业']]) {
    const check = await load(code, name);
    await page.getByRole('tab', {name: '分部毛利', exact: true}).click();
    await page.waitForFunction(() => !!document.querySelector('#profit_segment_plot .js-plotly-plot'));
    results.push({company: name, bridge: check.count});
  }
  await load('600219', '南山铝业');
  await page.locator('#profit_bridge_plot').screenshot({path:'output/playwright/profit-bridge-desktop.png'});
  await page.getByRole('tab', {name:'分部毛利',exact:true}).click();
  await page.locator('#profit_segment_plot').screenshot({path:'output/playwright/profit-segment-desktop.png'});
  await page.getByRole('tab', {name:'经营情景',exact:true}).click();
  const model = page.getByRole('combobox', {name:'经营模型',exact:true});
  const scenarios = [
    ['矿山采选', [100,70,10,5,0], 15],
    ['外购精矿冶炼', [50,.05,7,.25,.96,.95,2000,0], null],
    ['电解铝', [20000,3000,1.93,13500,.45,2500], 5635],
    ['金属加工及功能材料', [2000,10000,.8,500], -1000],
    ['化合物与分离加工', [50000,.4,.1,.8,5000,10000,0], 15000],
    ['再生回收', [10000,.5,.8,300,2000,500,200], 1600],
    ['贸易与供应链', [100,80,5,20], -5],
  ];
  for (const [name, values, total] of scenarios) {
    await model.fill(name);
    await page.getByRole('option', {name,exact:true}).click();
    const fields = page.locator('#profit_workspace input[type=number]:visible');
    await page.waitForFunction(count => Array.from(document.querySelectorAll('#profit_workspace input[type=number]')).filter(e => e.getClientRects().length).length === count, values.length);
    for (let i=0;i<values.length;i++) await fields.nth(i).fill(String(values[i]));
    await page.getByRole('button',{name:'计算情景',exact:true}).click();
    await page.waitForFunction(name => document.querySelector('#profit_scenario_plot .js-plotly-plot')?.layout?.title?.text.includes(name), name);
    const actual = await page.locator('#profit_scenario_plot .js-plotly-plot').evaluate(plot => plot.data[0].customdata.at(-1)[0]);
    if (total !== null && Math.abs(actual-total)>0.001) throw new Error(`${name}: ${actual} != ${total}`);
    await page.waitForFunction(() => document.querySelector('#profit_heatmap .js-plotly-plot')?.data?.[0]?.z?.length === 21);
    results.push({model:name, total:actual});
  }
  await page.locator('#profit_heatmap').screenshot({path:'output/playwright/profit-heatmap-desktop.png'});
  await page.getByRole('button',{name:'恢复初始参数',exact:true}).click();
  await page.waitForFunction(() => !document.querySelector('#profit_scenario_plot .js-plotly-plot'));
  await page.getByRole('button',{name:'计算情景',exact:true}).click();
  await page.getByText('暂无法测算：', {exact:false}).waitFor();
  if (await page.locator('#profit_scenario_plot .js-plotly-plot').count()) throw new Error('Old scenario survived invalid inputs');
  await load('601899', '紫金矿业');
  await page.getByRole('tab', {name:'经营情景',exact:true}).click();
  await page.getByRole('button', {name:'公司已披露经营数据',exact:false}).click();
  await page.waitForFunction(() => document.querySelector('#profit_unit_plot .js-plotly-plot')?.data?.length > 0);
  await page.locator('#profit_unit_plot').screenshot({path:'output/playwright/profit-unit-desktop.png'});
  const period = page.getByRole('combobox', {name:'财报报告期',exact:true});
  await period.fill('2025-12-31');
  await page.getByRole('option', {name:'2025-12-31',exact:true}).click();
  await page.waitForFunction(() => document.querySelector('#profit_meta')?.textContent.includes('报告期 2025-12-31'));
  await page.waitForFunction(() => !document.querySelector('#profit_unit_plot .js-plotly-plot'));
  await page.setViewportSize({width:390,height:844});
  await load('600219','南山铝业');
  async function checkMobilePlot(selector) {
    await page.waitForFunction(selector => {
      const plot = document.querySelector(selector + ' .js-plotly-plot');
      return plot && plot.getBoundingClientRect().width <= innerWidth
        && Math.abs(plot._fullLayout.width - plot.getBoundingClientRect().width) < 2
        && plot.querySelector('svg.main-svg')?.getBoundingClientRect().width <= innerWidth;
    }, selector);
    const box = await page.locator(selector).boundingBox();
    if (box.x < 0 || box.x + box.width > 391) throw new Error(`Mobile overflow: ${selector} ${JSON.stringify(box)}`);
  }
  await checkMobilePlot('#profit_bridge_plot');
  await page.locator('#profit_bridge_plot').screenshot({path:'output/playwright/profit-bridge-mobile.png'});
  await page.getByRole('tab', {name:'分部毛利',exact:true}).click();
  await checkMobilePlot('#profit_segment_plot');
  await page.locator('#profit_segment_plot').screenshot({path:'output/playwright/profit-segment-mobile.png'});
  await page.getByRole('tab', {name:'经营情景',exact:true}).click();
  await model.fill('电解铝');
  await page.getByRole('option', {name:'电解铝',exact:true}).click();
  await page.waitForFunction(() => Array.from(document.querySelectorAll('#profit_workspace input[type=number]')).filter(e=>e.getClientRects().length).length === 6);
  await page.getByRole('button',{name:'计算情景',exact:true}).click();
  await page.waitForFunction(() => document.querySelector('#profit_heatmap .js-plotly-plot')?.data?.[0]?.z?.length === 21);
  await checkMobilePlot('#profit_scenario_plot');
  await checkMobilePlot('#profit_heatmap');
  await page.locator('#profit_scenario_plot').screenshot({path:'output/playwright/profit-scenario-mobile.png'});
  await page.locator('#profit_heatmap').screenshot({path:'output/playwright/profit-heatmap-mobile.png'});
  await page.locator('#profit_workspace input[type=number]:visible').nth(0).fill('');
  await page.waitForFunction(() => !document.querySelector('#profit_scenario_plot .js-plotly-plot'));
  await query.fill('not-a-stock');
  await page.waitForFunction(() => document.querySelector('#profit_meta')?.textContent.includes('尚未加载'));
  if (await page.locator('#profit_segment_plot .js-plotly-plot').count()) throw new Error('Prior company not cleared');
  await page.getByRole('button',{name:'加载利润数据',exact:true}).click();
  await page.getByText('未找到股票：not-a-stock', {exact:false}).waitFor();
  return results;
}
