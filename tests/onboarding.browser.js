// Real local data tutorial. No LLM call or generated research report.
async (page) => {
  await page.goto('http://localhost:7862');
  const results=[];
  async function step(index) {
    await page.waitForFunction(index => document.querySelector('#newcomer_guide [data-guide-step]')?.dataset.guideStep === String(index)
      && document.body.dataset.guideStep === String(index), index);
  }
  const next = () => page.getByRole('button',{name:'下一步',exact:true}).click();
  for (const width of [1280,390]) {
    await page.setViewportSize({width,height:900});
    await page.getByRole('tab',{name:'欢迎',exact:true}).click();
    await page.getByRole('heading',{name:'欢迎来到有色金属投研平台'}).waitFor();
    await page.screenshot({path:`output/playwright/welcome-${width}.png`});
    await page.getByRole('button',{name:'带我试一次',exact:true}).click();
    await step(0);
    await next();
    await page.getByText('先加载当前公司的入门数据，再继续。',{exact:true}).waitFor();
    await page.getByRole('textbox',{name:'股票名称或代码'}).fill('不存在的公司');
    await page.getByRole('button',{name:'加载入门数据',exact:true}).click();
    await page.locator('.guide-message').filter({hasText:'暂时没有加载成功'}).waitFor();
    await page.getByRole('textbox',{name:'股票名称或代码'}).fill('南山铝业');
    await page.getByRole('button',{name:'加载入门数据',exact:true}).click();
    await page.getByText('已加载本地数据，可以进入下一步。',{exact:true}).waitFor();
    await next(); await step(1);
    await page.locator('#metal_mix_plot .js-plotly-plot').waitFor();
    await page.waitForFunction(()=>{
      const plot=document.querySelector('#metal_mix_plot .js-plotly-plot');
      return plot && Math.abs(plot._fullLayout.width-plot.getBoundingClientRect().width)<2;
    });
    await page.screenshot({path:`output/playwright/guide-business-${width}.png`});
    await next(); await step(2);
    await page.locator('#profit_bridge_plot .js-plotly-plot').waitFor();
    await page.getByRole('button',{name:'上一步',exact:true}).click(); await step(1);
    await next(); await step(2);
    await next(); await step(3);
    await page.getByRole('button',{name:'查看评分快照',exact:true}).click();
    await page.locator('#score_meta').getByText(/南山铝业/).waitFor();
    await next(); await step(4);
    await page.getByRole('button',{name:/^五维分别评什么/}).click();
    await next(); await step(5);
    await page.getByRole('button',{name:'生成影响矩阵',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#matrix_result .prose')?.textContent.includes('收入'),null,{timeout:90000});
    await next();
    await step(6);
    await page.getByRole('textbox',{name:'搜索术语或解释',exact:true}).fill('毛利');
    await page.locator('#glossary_results').getByText('毛利',{exact:true}).waitFor();
    await next(); await step(7);
    for (const [index, tab, section] of [[8,'📈 技术面','tech'],[9,'💰 资金面','capital'],[10,'⚠️ 风险','risk']]) {
      await next(); await step(index);
      if (await page.getByRole('tab',{name:tab,exact:true}).getAttribute('aria-selected') !== 'true')
        throw new Error(`Wrong report tab at step ${index}`);
      await page.locator('#newcomer_guide summary').click();
      await page.locator('#newcomer_guide .report-reading').waitFor();
      if (await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2)) throw new Error(`Reading overflow ${width}`);
      await page.screenshot({path:`output/playwright/guide-${section}-${width}.png`});
    }
    await next(); await step(11);
    await page.getByRole('button',{name:'完成教程',exact:true}).click();
    await page.locator('#newcomer_guide').waitFor({state:'hidden'});
    if (await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2)) throw new Error(`overflow ${width}`);
    // Return using the main navigation, including its narrow-screen overflow menu.
    const home = page.getByRole('tab',{name:'欢迎',exact:true});
    if (!await home.isVisible()) {
      await page.getByRole('button',{name:'More tabs',exact:true}).first().click();
      await page.getByRole('button',{name:'欢迎',exact:true}).click();
    } else await home.click();
    await page.getByRole('button',{name:'带我试一次',exact:true}).click(); await step(0);
    await page.getByRole('button',{name:'退出引导',exact:true}).click();
    await page.locator('#newcomer_guide').waitFor({state:'hidden'});
    await page.getByRole('tab',{name:'欢迎',exact:true}).click();
    await page.getByRole('button',{name:'直接进入平台',exact:true}).click();
    await page.getByRole('button',{name:'生成完整研报',exact:true}).waitFor();
    results.push({width,steps:12,localData:true,exitAndRestart:true});
  }
  return results;
}
