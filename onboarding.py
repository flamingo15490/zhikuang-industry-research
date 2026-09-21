"""Short guided visits to the real research tools, backed by local data."""
from html import escape

STEPS = [
    ('先选一家公司', '先看看南山铝业吧，也可以换成你感兴趣的公司。填好下面的公司名称，点击“加载入门数据”。这一步只读取本地资料，不需要等待AI写研报。', 0, 0),
    ('看看它靠什么赚钱', '下面的图把收入分成了不同业务。先找最大的一块，再看看其余业务。收入多不一定利润多；如果资料不够完整，这里会说明原因，不会硬凑比例。', 0, 0),
    ('收入怎样变成利润', '打开“财报利润桥”，看看收入扣掉成本和费用后，还剩多少利润。“分部毛利”能比较不同业务；“经营情景”则可以试着修改价格和成本。先留意图上方的报告期。', 0, 1),
    ('快速看一眼五维评分', '评分速查就在“五维评分”页。输入公司并点击“查看评分快照”，可以同时看到盈利、估值、价格走势、资金和财务安全几个方面。同业样本足够时，还能展开排名看看其他公司。', 3, 0),
    ('分数是怎么来的', '打开“五维分别评什么”，再看“各维指标与计分明细”：原始指标、计分标准和贡献都在这里。高分不等于值得买入；缺项表示暂时不能评价，不是零分。', 3, 0),
    ('试试金属价格变化', '情景矩阵可以同时看看多家公司。选一种金属，调整涨跌幅，再点击“生成影响矩阵”。它估算的是固定销量下的收入变化，不是股价涨跌，也不是净利润预测；无法计算的公司会说明缺什么。', 1, 0),
    ('遇到不懂的词，随时查', '展开下面的“术语速查”，试着搜索“毛利”或“PE”。图表和文字旁的小问号也能解释术语：电脑上悬停，手机上点击就可以看。看评分和读研报时都能回来查。', 3, 0),
    ('把这些信息串成一份研报', '回到“一键研报”，上方是五维诊断，下方有基本面、估值、技术面、资金面、风险五个部分。入门数据已经可以看图；想读完整分析时，再点击“生成完整研报”。现在也可以直接下一步，先熟悉后面三个部分。', 0, 0),
    ('技术面：最近的价格走得怎么样', '这里读的是股价走势，不是公司生产技术。生成研报后，先看行情日期，再看价格相对均线的位置、近期涨跌和走势指标。下面的阅读说明会把 MA、MACD、RSI 换成更容易理解的话；本地导览尚未生成正文时，也可以先读说明。', 0, 2),
    ('资金面：最近买卖的参与情况', '价格之外，再看看资金参与。重点看五日净流入相对成交额的比例，留意它的正负、大小和日期。它不能告诉你是谁买了股票，也不能保证下一步涨跌。这里的详细说明还会解释百分比和金额有什么不同。', 0, 3),
    ('风险：先找需要进一步核实的地方', '最后看看债务负担、短期偿债能力、增长变化和缺失数据。风险部分相当于一份待核对清单；没有列出问题，也不代表没有风险。读完后，试着记下一条你还想向财报求证的问题。', 0, 4),
    ('现在可以自己研究了', '你已经走过公司业务、利润图、五维评分、价格情景和研报五个部分。可以在这里追问：“南山铝业收入最多的业务，也是毛利最多的吗？”提问时带上公司、报告期和疑问，会更容易核对回答。也可以回到“一键研报”生成正文，或从欢迎页重新开始。', 2, 0),
]


# Shared by the walkthrough and the permanent report reading guide.
REPORT_READING = {
    'overview': ('先认识这份研报', [
        ('从哪里开始', '填入公司名称或代码，点击“生成完整研报”，等待进度完成。结果分成五个页签，可以来回切换。新手教程的“加载入门数据”只加载本地资料和图表，因此技术面等文字区域此时仍可能为空。'),
        ('五维雷达图怎么读', '每条轴代表一个评价角度：基本面、估值、技术面、资金面和风险。沿同一条轴越向外，表示该维度的规则得分越高；风险维度高分表示按现有指标评估更稳健，不是风险更大。先找最内侧的一角，再去对应部分找原因。'),
        ('比较时看什么', '用图例辨认公司与对比图层，再比较同一维度。排名要连同所属子板块、参与样本数和数据完整度一起看。样本不足或数据缺失时，暂不能排名不等于最后一名。评分速查里的明细可以进一步查到指标、阈值和贡献。'),
        ('图和文字如何互相核对', '先看日期和缺项提示，再读各部分结论，最后回到图表、利润明细和财报证据查依据。五个正文部分与五维分数相互补充，但正文长短不是得分依据，雷达图面积也不是预期收益。'),
        ('遇到空白或日期不同', '先区分“还没生成正文”“该项数据缺失”和“模型未生成该部分”。财务报告期、行情日期、宏观日期可能不同；本地快照不是此刻行情。生成后可展开“本次研究来源”，核对研究编号及采用的期间。'),
    ]),
    'base': ('基本面：公司靠什么赚钱，经营有没有变好', [
        ('这一部分先找什么', '先找主要产品和业务，再看收入、利润增长以及 ROE（用股东投入的钱赚取利润的能力）。例如收入上升、利润下降时，下一步应去估值页核对成本和费用，而不是只凭收入增加就判断经营改善。'),
        ('主营构成环形图', '每一块表示同一报告期内某项业务的收入占比，悬停可看具体数值。假设某业务占 60%，意思是展示口径下每 100 元收入中约 60 元来自它，不表示它贡献了 60% 的净利润。想知道哪项业务更赚钱，继续看“分部毛利”。'),
        ('宏观周期折线图', '横轴是日期，三条线分别描述工业金属、贵金属和战略金属的背景状态。纵轴 z-score 表示相对各自滚动历史均值的偏离：0 附近接近均值，+1 约高出一个历史标准差，-1 则约低一个。先看公司业务属于哪类，再看相应曲线的变化。'),
        ('宏观图不能直接回答什么', '曲线上升不等于金属价格上涨同样幅度，更不代表这家公司一定涨价或涨股价。它是行业背景描述。主营占比图也只在同期间收入可完整核对时显示，空白不代表公司没有主营收入。'),
        ('读完可以问自己', '公司最依赖哪项业务？收入增长有没有变成利润增长？宏观背景与公司自己的业绩是否一致？把其中一个疑问带到利润明细或自由问答中继续查。'),
    ]),
    'value': ('估值：先读利润，再看价格是否有依据', [
        ('估值正文看什么', '关注 PE（市值相当于多少倍年度盈利）以及它对应的盈利和日期。周期公司在盈利高点可能出现很低的 PE，不能直接当作便宜；亏损或缺失时也不能照搬正常盈利公司的比较方式。下面的利润工具帮助你核对盈利来源，本身不直接给出目标股价。'),
        ('财报利润桥', '从营业收入开始，一项项加减成本、费用及其他损益，走到利润结果。横轴看金额单位，蓝色通常表示增加、红色表示减少、绿色表示小计或合计。小计是走到这里还剩多少，不能把所有柱子再加一次。悬停可区分财报披露、推导数值和未细分差额。'),
        ('分部毛利条形图', '比较不同业务的毛利金额，悬停再看收入和毛利率。毛利是收入减直接营业成本，还没扣完期间费用、税等；所以毛利最多的业务不一定能单独对应最多的归母净利润。留意分部报告期，缺成本的业务不能硬算毛利。'),
        ('已披露单位经济性', '在“经营情景”中的“公司已披露经营数据”查看可用产品。单位售价减单位销售成本得到单位毛利，例如每吨售价 100 元、成本 70 元，差额是 30 元/吨，并不是公司总利润。先核对产品、报告期和单位；没有披露就没有对应图。'),
        ('经营情景利润拆分图', '选择适合业务的模型，如矿山采选、冶炼、电解铝、加工、化合物分离、回收或贸易，再修改参数并计算。图会展示假设收入或售价怎样扣成测算结果。先看单位：每吨的结果不能直接和财报亿元利润比较；示例参数也不自动代表这家公司的真实经营条件。'),
        ('双因素敏感性热力图', '横轴、纵轴是当前模型的两个关键参数，每格是这组假设下的测算结果，其他参数保持不变；范围围绕输入基准上下浮动 30%。十字标出输入基准，跨越盈亏时会出现零利润分界线。先看色标与单位，再悬停读数，不要只凭颜色判断好坏；空白格表示该组合无法有效计算。'),
        ('先动一个参数试试', '先记录基准结果，只改一项价格或成本，再看结果变化。确认它为什么变化之后，再用热力图比较两项同时变化。这里是“假如这样会怎样”，不预测未来一定发生，也不等于公司归母净利润。'),
    ]),
    'tech': ('技术面：读价格趋势和短期变化', [
        ('先看日期，再看方向', '这里主要是根据本地行情快照写出的文字分析，当前没有独立 K 线图。先核对正文上方的行情日期，再找最近 20 日涨跌幅；它描述已经发生的变化，不是未来收益。'),
        ('MA 均线', 'MA 是过去若干交易日的平均价格，可以当成一条平滑后的价格参照。价格在均线上方，说明高于这段时间的平均水平；多条均线的相对位置有助于观察趋势，但“站上均线”不等于必然继续上涨。'),
        ('MACD 中的 DIF 和 DEA', 'DIF 反映快慢价格均线的差，DEA 是对 DIF 再平滑。两者的位置和变化帮助观察动能增强或减弱。它们来自过去价格，存在滞后；不要把一次交叉当成确定的买卖指令。'),
        ('RSI 相对强弱指标', 'RSI 用近期上涨和下跌的相对幅度衡量强弱，通常在 0 到 100 之间。数值偏高表示近期上涨力量较强，但也可能延续高位，并不意味着马上下跌。把它与均线、近期涨跌一起看。'),
        ('数据不够时怎么读', '如果正文标明某项指标缺失，就暂时不对它下判断，也不要把缺失当成 0。技术面与基本面结论不同并不一定矛盾：前者描述价格变化，后者研究经营，两者关注的时间和对象不同。'),
    ]),
    'capital': ('资金面：看成交中的净流入比例', [
        ('这一部分展示什么', '当前以文字解读给定的五日净流入/成交额比例，没有独立资金流向图。先核对数据日期、统计窗口和是否缺项，再看比例的方向及幅度。'),
        ('百分比怎么理解', '正值表示按数据源统计口径净流入，负值表示净流出。例如比例为 2%，含义是净流入约占对应成交额的 2%，绝不是“净流入 2 亿元”。没有配套的同口径成交额，就不能换算绝对金额。'),
        ('它能帮助回答什么', '可以辅助观察近期资金参与的方向，再与技术面的近期涨跌放在一起核对。资金比例变化和股价变化可能不同步；统计口径下的净流入也不能识别具体投资者或证明“机构正在买入”。'),
        ('读完再核对', '把资金观察写成“截至某日、过去五日、按该口径的净流入比例”，保留时间范围。缺失时先记为信息不足，别把它写成资金没有流入，也别单凭这一项预测涨跌。'),
    ]),
    'risk': ('风险：把待核对事项列清楚', [
        ('债务负担', '资产负债率表示资产中有多少由负债支撑。例如 60% 大致表示每 100 元资产对应 60 元负债；不能直接理解为马上有 60 元需要偿还。还应去财报核对债务期限、现金和经营特点。'),
        ('短期偿债能力', '流动比率是流动资产除以流动负债。小于 1 表示账面流动资产低于流动负债，值得进一步看回款和现金安排；高于 1 也不能保证安全，因为存货与应收账款不一定能马上变成现金。'),
        ('增长和缺项', '留意收入或利润增长下滑，并追查是价格、销量、成本还是其他损益造成。信息缺失表示我们还不知道，不代表风险不存在。评分中的风险维度反映已有指标下的稳健程度。'),
        ('这份检查覆盖到哪里', '当前风险正文依据债率、增长、流动比率及缺项，是简化检查，不是完整风控。诉讼、矿权变化、安全事故、海外政策等事项仍需额外核查，不能因为正文没提就认定没有。'),
        ('回到财报查证', '阅读正文引用的证据编号、报告期和来源；在利润明细中区分披露值与推导值。先写下一条具体问题，如“短期负债到期时，现有现金是否够用？”，再查原始财报或继续提问。'),
    ]),
}


def reading_html(section):
    title, items = REPORT_READING[section]
    return ('<section class="report-reading"><h3>' + escape(title) + '</h3><dl>'
            + ''.join('<div><dt>' + escape(label) + '</dt><dd>' + escape(body) + '</dd></div>'
                      for label, body in items) + '</dl></section>')


STEP_READING = {1: 'base', 2: 'value', 7: 'overview', 8: 'tech', 9: 'capital', 10: 'risk'}


def next_step(step, company, matrix):
    if step == 0 and not (company or {}).get('code'):
        return step
    if step == 5 and not matrix:
        return step
    return min(step + 1, len(STEPS) - 1)


def step_html(step, message=''):
    title, body, _, _ = STEPS[step]
    return (f'<div class="guide-copy" data-guide-step="{step}" aria-live="polite">'
            f'<div class="guide-count">新手教程 · {step + 1} / {len(STEPS)}</div>'
            f'<h2>{escape(title)}</h2><p>{escape(body)}</p>'
            + (('<details class="guide-reading"><summary>展开这一步的详细讲解</summary>'
                + reading_html(STEP_READING[step]) + '</details>') if step in STEP_READING else '')
            + (f'<p class="guide-message" role="status">{escape(message)}</p>' if message else '') + '</div>')


def load_intro(query):
    from report import _resolve_stock
    from report_context import build_context, radar_view
    from charts import draw_report_mix, draw_macro_cycle
    try:
        name, code = _resolve_stock(query)
        context = build_context(name, code)
        figure, note, ranking = radar_view(context)
        mix = draw_report_mix(context['profit'])
        return dict(ok=True, name=name, code=code, profit=context['profit'], radar=figure,
            note=note, rank=ranking, mix=mix, macro=draw_macro_cycle(context['macro']),
            message='已加载本地数据，可以进入下一步。',
            base=('本地数据导览，尚未生成AI研报。财务报告期：' + context['snapshot']['financial_period']
                  + ('。同期间分部收入无法完整核对，暂不展示占比图；仍可查看利润明细。' if mix is None else '。')))
    except (ValueError, OSError, KeyError) as error:
        return dict(ok=False, message='暂时没有加载成功：' + str(error))


WELCOME_HTML = '''<section class="welcome-intro">
<p class="welcome-eyebrow">从一家公司开始，慢慢看懂一个行业</p>
<h1>欢迎来到有色金属投研平台</h1>
<p>这是一处帮你读懂有色金属公司的研究工作台。无论你想了解一家公司的生意，还是比较同行、试试金属涨价会带来什么影响，都可以从这里开始。</p>
<p>你可以查看公司靠哪些业务赚钱、收入怎样变成利润；用五维评分快速了解各方面表现，再查每一分的依据；也可以用情景矩阵比较价格变化对多家公司的影响，或直接向研究助手提问。</p>
<p class="welcome-invitation">第一次来，不熟悉财务术语也没关系。我们选一家公司，一步步看。</p>
</section>'''

WELCOME_CSS = '''
#app_brand {padding:10px 0 14px;border-bottom:1px solid #dce3e9;margin-bottom:12px;}
#app_brand .brand-name {font-size:18px;font-weight:700;color:#182e3a;}
#app_brand p {margin:4px 0 0;color:#586775;font-size:13px;}
.welcome-intro {max-width:830px;padding:24px 0 10px;}
.welcome-intro h1 {font-size:30px;line-height:1.4;color:#163e43;margin:12px 0 20px;letter-spacing:0;}
.welcome-intro p {font-size:16px;line-height:1.9;color:#44515b;margin:0 0 14px;}
.welcome-intro .welcome-eyebrow {font-size:13px;color:#25786b;}
.welcome-intro .welcome-invitation {color:#263d43;font-weight:600;}
#welcome_actions {max-width:570px;margin:0 0 22px;}
.welcome-topics {border-top:1px solid #dce3e9;padding-top:18px;margin-top:8px;}
.welcome-topics h2 {font-size:18px;color:#263d43;margin:0 0 14px;}
.welcome-topics dl {display:grid;grid-template-columns:1fr 1fr;gap:16px 28px;margin:0;}
.welcome-topics dt {font-size:14px;font-weight:600;color:#213e45;}
.welcome-topics dd {font-size:14px;color:#596773;line-height:1.7;margin:5px 0 0;}
#newcomer_guide {border-left:3px solid #168775;background:#f1f8f6;padding:14px 18px;margin:8px 0 14px;}
.guide-copy h2 {font-size:19px;line-height:1.5;margin:5px 0;color:#153e3c;}
.guide-copy p {font-size:14px;line-height:1.75;margin:5px 0;color:#344e50;}
.guide-count {font-size:12px;color:#3a716b;}
.guide-copy .guide-message {color:#8a5207;}
#guide_buttons {max-width:640px;}
#guide_buttons button {min-height:38px;}
.report-reading {max-width:900px;overflow-wrap:anywhere;}
.report-reading h3 {font-size:16px;line-height:1.6;margin:8px 0 12px;color:#214c48;}
.report-reading dl {margin:0;}
.report-reading dl > div {padding:10px 0;border-bottom:1px solid #e1e8e6;}
.report-reading dt {font-size:14px;font-weight:600;color:#254942;line-height:1.6;}
.report-reading dd {font-size:14px;line-height:1.85;color:#465955;margin:5px 0 0;}
.guide-reading summary {cursor:pointer;font-size:14px;color:#176e60;padding:10px 0;}
.guide-reading summary:focus-visible {outline:2px solid #168775;outline-offset:2px;}
body[data-guide-step="0"] #report_sections,
body[data-guide-step="0"] .report-overview,
body[data-guide-step="1"] .report-overview,
body[data-guide-step="2"] .report-overview,
body[data-guide-step="1"] #report_company_controls,
body[data-guide-step="2"] #report_company_controls {display:none!important;}
@media(max-width:600px){.welcome-intro {padding-top:12px;}.welcome-intro h1{font-size:25px;}
.welcome-intro p{font-size:15px;}.welcome-topics dl{grid-template-columns:1fr;gap:14px;}
#newcomer_guide{padding:10px 12px;}.guide-copy h2{font-size:17px;}}
'''

GUIDE_JS = '''(() => {
  let previous = null;
  let scheduled = false;
  const sync = () => {
    scheduled = false;
    const panel = document.querySelector('#newcomer_guide');
    const copy = panel?.querySelector('[data-guide-step]');
    const step = panel?.getClientRects().length && copy ? copy.dataset.guideStep : null;
    if (step === previous) return;
    previous = step;
    if (step === null) delete document.body.dataset.guideStep;
    else {
      document.body.dataset.guideStep = step;
      panel.scrollIntoView({block:'start',behavior:'instant'});
    }
  };
  const observer = new MutationObserver(() => {
    if (!scheduled) { scheduled = true; requestAnimationFrame(sync); }
  });
  observer.observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['class','style','data-guide-step']});
  sync();
})()'''
