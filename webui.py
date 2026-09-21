"""Gradio 演示界面：一键研报（交互式图表）+ 情景矩阵 + 自由问答。启动：python webui.py"""
from __future__ import annotations

import gradio as gr
import plotly.graph_objects as go

from agent import run_agent
from interaction import metal_key_from_selection
from report import generate_report_iter
from profit_ui import build_profit_panel
from score_ui import build_score_panel
from onboarding import STEPS, WELCOME_HTML, WELCOME_CSS, GUIDE_JS, load_intro, next_step, step_html, reading_html, REPORT_READING
from ui_glossary import glossary_js, help_heading, search_glossary


def _empty_fig(msg: str) -> go.Figure:
    """占位图：无图表时给出提示文字。"""
    fig = go.Figure()
    fig.add_annotation(text=msg, showarrow=False, font=dict(size=14, color="#64748b"))
    fig.update_layout(template="plotly_white", height=180,
                      margin=dict(l=10, r=10, t=10, b=10),
                      xaxis=dict(visible=False), yaxis=dict(visible=False))
    return fig


def _bar_html(frac: float, desc: str, ok: bool = True) -> str:
    """大号、高可见的进度条 HTML。"""
    pct = max(0, min(100, int(round(frac * 100))))
    grad = "linear-gradient(90deg,#2563eb,#0891b2)" if ok else "linear-gradient(90deg,#dc2626,#f59e0b)"
    icon = "✅" if pct >= 100 else "🔄"
    return f"""
<div style="margin:6px 0 12px;font-family:'Microsoft YaHei',sans-serif;">
  <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:7px;">
    <span style="font-weight:700;font-size:1.05em;color:#1e3a8a;">{icon} {desc}</span>
    <span style="font-weight:800;font-size:1.2em;color:#2563eb;">{pct}%</span>
  </div>
  <div style="height:18px;background:#e2e8f0;border-radius:999px;overflow:hidden;border:1px solid #cbd5e1;">
    <div style="height:100%;width:{pct}%;background:{grad};border-radius:999px;transition:width .45s ease;"></div>
  </div>
</div>
"""


def report_fn(query: str):
    """生成器：流式输出 (进度条, 雷达图, 雷达说明, 基本面, 主营构成图, 宏观图, 估值, 瀑布图, 技术面, 资金面, 风险)。"""
    query = (query or "").strip()
    print(f"[REQUEST] report_fn 收到: {query!r}", flush=True)
    if not query:
        yield (_bar_html(0, "请输入股票名称或代码"), None, "", "",
               "请输入股票名称或代码，如：紫金矿业 / 600111", None, None, "", None, "", "", "")
        return
    try:
        for item in generate_report_iter(query):
            if isinstance(item, dict):
                sec = item["sections"]
                yield (
                    _bar_html(1.0, "生成完成"),
                    item["radar"],
                    item["radar_note"],
                    item.get("radar_rank", ""),
                    sec.get("基本面", ""),
                    item["metal_mix"],
                    item["macro"],
                    sec.get("估值", ""),
                    item.get("profit_analysis"),
                    sec.get("技术面", ""),
                    sec.get("资金面", ""),
                    sec.get("风险", ""),
                )
            else:
                frac, desc = item
                yield (_bar_html(frac, desc), None, "", "", "", None, None, "", None, "", "", "")
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()  # 服务端日志，便于定位
        yield (_bar_html(1.0, "生成失败", ok=False), None, "", "",
               f"生成失败：{type(exc).__name__}: {exc}", None, None, "", None, "", "", "")


def matrix_fn(metal_label: str, shock: float):
    from tools.sector_matrix import draw_matrix_chart, sector_impact_matrix
    metal = METALS.get(metal_label, metal_label)
    try:
        md = sector_impact_matrix(metal, shock)
        fig = draw_matrix_chart(metal, shock) or _empty_fig("无该金属暴露数据，无法绘图")
        return md, fig
    except Exception as exc:  # noqa: BLE001
        return f"生成失败：{type(exc).__name__}: {exc}", _empty_fig("绘图失败")


def link_metal_to_matrix(selection: str):
    """将主营构成扇形点击转换为情景矩阵筛选。"""
    key = metal_key_from_selection(selection)
    if key is None:
        return gr.update(), gr.update(), gr.update()
    label = next((name for name, value in METALS.items() if value == key), None)
    if label is None:
        return gr.update(), gr.update(), gr.update()
    return label, -20, gr.update(selected=1)


METALS = {"黄金": "gold", "铜": "copper", "铝": "aluminum", "银": "silver", "锌": "zinc",
          "锡": "tin", "铅": "lead", "镍": "nickel", "锂": "lithium", "稀土": "rare_earth",
           "钼": "molybdenum", "钨": "tungsten", "锑": "antimony", "钴": "cobalt"}

# Plotly 在 gr.Plot 内部渲染，Gradio 4.44 尚未暴露 Plot 选中事件；
# 监听原生 plotly_click 后把金属键写入隐藏 Textbox，再走普通 Gradio 回调。
UI_JS = """
(() => {
const attach = () => {
    const root = document.querySelector('#metal_mix_plot');
    const plot = root && root.querySelector('.js-plotly-plot');
    if (!plot || plot.dataset.metalClickBound) return;
    plot.dataset.metalClickBound = '1';
    plot.on('plotly_click', (event) => {
      const point = event?.points?.[0];
      const metal = point?.customdata || point?.label;
      if (!metal || metal === '其他') return;
      const box = document.querySelector('#metal_link_input textarea, #metal_link_input input');
      const button = document.querySelector('#metal_link_btn button');
      if (!box || !button) return;
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set
        || Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
      setter?.call(box, metal);
      box.dispatchEvent(new Event('input', {bubbles: true}));
      box.dispatchEvent(new Event('change', {bubbles: true}));
      button.click();
    });
  };
  const attachRadar = () => {
    const root = document.querySelector('#radar_plot');
    const plot = root && root.querySelector('.js-plotly-plot');
    const info = document.querySelector('#radar_hover_info');
    if (!plot || !info || plot.dataset.radarHoverBound) return;
    plot.dataset.radarHoverBound = '1';
    plot.on('plotly_hover', (event) => {
      const point = event?.points?.[0];
      if (!point) return;
      const trace = point.data?.name || '当前图层';
      const dimension = point.theta || '';
      const score = Number(point.r);
      info.innerHTML = `<span class="hover-dim">悬停维度：${dimension}</span><span>${trace} ${Number.isFinite(score) ? score.toFixed(0) : '-'} 分</span>`;
    });
    plot.on('plotly_unhover', () => {
      info.innerHTML = '<span>将鼠标移到雷达图维度上查看分数</span>';
    });
  };
  const attachRank = () => {
    document.querySelectorAll('.rank-hover-wrap').forEach((wrap) => {
      if (wrap.dataset.rankBound) return;
      const tip = wrap.querySelector('.rank-tooltip');
      const trigger = wrap.querySelector('.rank-trigger');
      if (!tip || !trigger) return;
      wrap.dataset.rankBound = '1';
      const position = () => {
        const rect = trigger.getBoundingClientRect();
        const below = Math.max(0, window.innerHeight - rect.bottom - 8);
        const above = Math.max(0, rect.top - 8);
        tip.style.maxHeight = `${Math.min(360, Math.max(above, below))}px`;
        const height = tip.getBoundingClientRect().height;
        // Keep the panel adjacent so the pointer can enter its scrollable list.
        const top = below >= height || below >= above ? rect.bottom : rect.top - height;
        tip.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - tip.offsetWidth - 8))}px`;
        tip.style.top = `${Math.max(8, top)}px`;
      };
      trigger.addEventListener('mouseenter', position);
    });
  };
  const profitPlots = new Set();
  const resizing = new WeakSet();
  const resizeProfit = (plot) => {
    const width = plot.getBoundingClientRect().width;
    if (!plot.isConnected || !width || !plot._fullLayout || !window.Plotly
        || resizing.has(plot) || Math.abs(plot._fullLayout.width - width) < 2) return;
    resizing.add(plot);
    window.Plotly.Plots.resize(plot).finally(() => resizing.delete(plot));
  };
  const profitResizeObserver = new ResizeObserver(entries => {
    entries.forEach(entry => resizeProfit(entry.target));
  });
  const attachProfit = () => {
    profitPlots.forEach(plot => {
      if (!plot.isConnected) {
        profitResizeObserver.unobserve(plot);
        profitPlots.delete(plot);
      }
    });
    document.querySelectorAll('.gradio-container .js-plotly-plot').forEach(plot => {
      if (!profitPlots.has(plot)) {
        profitPlots.add(plot);
        profitResizeObserver.observe(plot);
      }
      resizeProfit(plot);
    });
  };
  attach();
  attachRadar();
  attachRank();
  attachProfit();
  new MutationObserver(attach).observe(document.body, {childList: true, subtree: true});
  new MutationObserver(attachRadar).observe(document.body, {childList: true, subtree: true});
  new MutationObserver(attachRank).observe(document.body, {childList: true, subtree: true});
  new MutationObserver(attachProfit).observe(document.body, {childList: true, subtree: true});
})();
"""

UI_JS += '\n' + glossary_js()

# 研报排版 CSS：作用于五个维度标签页（elem_classes=report_md）
REPORT_CSS = """
.report_md { line-height: 1.8; color: #1f2937; font-size: 15px; }
.report_md h1 { border-bottom: 3px solid #2563eb; padding-bottom: .45em; color: #0f172a; font-size: 1.7em; }
.report_md h2 {
    border-left: 5px solid #2563eb;
    background: linear-gradient(90deg, #eff6ff, #ffffff);
    padding: .45em .7em; margin-top: 1.5em;
    border-radius: 0 8px 8px 0; color: #1e3a8a; font-size: 1.15em;
}
.report_md h3 { color: #334155; font-size: 1.02em; }
.report_md table { border-collapse: collapse; width: 100%; margin: .8em 0; font-size: .92em; }
.report_md table th { background: #2563eb; color: #fff; padding: 7px 12px; text-align: left; font-weight: 600; }
.report_md table td { border: 1px solid #e2e8f0; padding: 6px 12px; }
.report_md table tr:nth-child(even) td { background: #f8fafc; }
.report_md blockquote {
    border-left: 4px solid #d97706; background: #fffbeb;
    padding: .55em .9em; border-radius: 0 8px 8px 0; color: #92400e; margin: .8em 0;
}
.report_md img { max-width: 100%; border-radius: 12px; border: 1px solid #e2e8f0;
    box-shadow: 0 4px 14px rgba(15,23,42,.10); margin: .5em 0; }
.report_md strong { color: #0f172a; }
.report_md hr { border: none; border-top: 1px solid #e2e8f0; margin: 1.2em 0; }
.report_md code { background: #f1f5f9; padding: 1px 6px; border-radius: 5px; color: #be185d; }
"""


# 全局 UI 美化 CSS（浅色、居中、限制宽度）
UI_CSS = """
.evidence-list { max-height:420px; overflow:auto; }
.evidence-list details { padding:10px 0; border-bottom:1px solid #e2e8f0; overflow-wrap:anywhere; }
.evidence-list summary { cursor:pointer; font-size:14px; }
.evidence-list p { font-size:13px; line-height:1.6; margin:6px 0; }
.glossary-status { font-size:13px; color:#64748b; margin:0 0 8px; }
.glossary-results { margin:0; max-height:360px; overflow:auto; overscroll-behavior:contain; }
.glossary-entry { padding:12px 0; border-bottom:1px solid #e2e8f0; }
.glossary-entry dt { font-size:14px; font-weight:600; color:#0f172a; }
.glossary-entry dd { margin:5px 0 0; font-size:14px; line-height:1.7; color:#475569; overflow-wrap:anywhere; }
#profit_meta table { width:100%; table-layout:fixed; border-collapse:collapse; margin:16px 0 8px; }
#profit_meta th, #profit_meta td { padding:8px 4px; border-bottom:1px solid #e2e8f0; overflow-wrap:anywhere; }
#profit_meta th { font-size:13px; font-weight:500; }
#profit_meta td { font-size:17px; font-weight:600; font-variant-numeric:tabular-nums; }
.term-section { display:flex; align-items:center; gap:5px; font-size:14px; font-weight:600; color:#334155; }
.term-help { display:inline-flex !important; align-items:center; justify-content:center; vertical-align:middle; width:22px; height:22px; min-width:22px; padding:0 !important; margin:0 3px; border:1px solid #94a3b8 !important; border-radius:50% !important; background:#f8fafc !important; color:#475569 !important; cursor:help; line-height:1; font:600 12px Arial,sans-serif; }
.term-help::before { content:'?'; }
.term-help { pointer-events:auto; }
.term-help:hover, .term-help[aria-expanded="true"] { background:#e0f2fe !important; border-color:#0284c7 !important; color:#0369a1 !important; }
.term-help:focus-visible { outline:2px solid #0284c7; outline-offset:2px; }
#term-tooltip { position:fixed; z-index:20000; box-sizing:border-box; width:min(360px, calc(100vw - 24px)); overflow:auto; padding:14px 16px; background:#fff; color:#334155; border:1px solid #cbd5e1; border-radius:6px; box-shadow:0 6px 22px #0f172a26; font:14px/1.65 'Microsoft YaHei',sans-serif; overflow-wrap:anywhere; }
#term-tooltip[hidden] { display:none !important; }
#term-tooltip strong { font-size:14px; color:#0f172a; }
#term-tooltip p { margin:4px 0 0; }
#term-tooltip > div + div { border-top:1px solid #e2e8f0; margin-top:10px; padding-top:10px; }
.gradio-container { width: 100% !important; min-width: 0 !important; max-width: 1180px !important; margin: 0 auto !important; }
.gradio-container .main { min-width: 0 !important; max-width: 100% !important; }
#profit_workspace { min-width: 0 !important; }
#profit_workspace .plot-container { min-width: 0 !important; max-width: 100% !important; }
.radar-hover-info { display:flex; justify-content:space-between; gap:16px; margin:4px 0 14px; padding:10px 14px; border:1px solid #dbeafe; border-left:4px solid #2563eb; background:#f8fbff; color:#475569; font-size:14px; }
.radar-hover-info .hover-dim { color:#1e3a8a; font-weight:700; }
.rank-hover-wrap { position:relative; z-index:100; display:inline-block; margin:4px 0 10px; }
.rank-trigger { display:inline-block; padding:2px 3px; border-bottom:1px dashed #2563eb; color:#1e3a8a; font-weight:800; cursor:help; }
.rank-tooltip { display:none; position:fixed; z-index:10000; width:min(420px, 82vw); max-height:360px; overflow:auto; padding:12px 14px; border:1px solid #cbd5e1; background:#fff; box-shadow:0 10px 24px rgba(15,23,42,.16); color:#334155; pointer-events:auto; }
.rank-hover-wrap:hover .rank-tooltip { display:block; }
.gradio-container .plot-container { position:relative; z-index:1; }
.rank-tooltip strong { display:block; margin-bottom:7px; color:#0f172a; }
.rank-tooltip ol { margin:0; padding-left:26px; }
.rank-tooltip li { display:flex; justify-content:space-between; gap:16px; padding:3px 0; border-bottom:1px solid #f1f5f9; }
"""

HEADER_HTML = """
<div style="background:linear-gradient(135deg,#0f172a 0%,#1e3a8a 45%,#155e75 100%);border-radius:18px;padding:30px 34px;color:#ffffff;box-shadow:0 10px 30px rgba(30,58,138,.25);">
  <div style="font-size:2em;font-weight:800;letter-spacing:.5px;color:#ffffff;">🪙 有色金属投研 Agent</div>
  <div style="margin-top:10px;font-size:1.06em;color:#e2e8f0;line-height:1.7;font-weight:500;">有色行业财报研究 · 140 家公司<br>财报利润拆解 · 同业比较 · 经营情景分析</div>
  <div style="margin-top:18px;display:flex;gap:10px;flex-wrap:wrap;">
    <span style="background:#ffffff;color:#1e3a8a;font-weight:700;padding:7px 16px;border-radius:999px;font-size:.88em;">📊 15 个投研工具</span>
    <span style="background:#ffffff;color:#1e3a8a;font-weight:700;padding:7px 16px;border-radius:999px;font-size:.88em;">🔬 7 类经营情景模型</span>
    <span style="background:#ffffff;color:#1e3a8a;font-weight:700;padding:7px 16px;border-radius:999px;font-size:.88em;">🖱 交互式图表研报</span>
    <span style="background:#ffffff;color:#1e3a8a;font-weight:700;padding:7px 16px;border-radius:999px;font-size:.88em;">🧭 价差思维（铝价≠利润）</span>
  </div>
</div>
"""

CARDS_HTML = """
<div style="display:flex;gap:14px;flex-wrap:wrap;margin:16px 0 4px;">
  <div style="flex:1;min-width:210px;background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:16px 18px;box-shadow:0 2px 8px rgba(15,23,42,.04);">
    <div style="font-size:1.35em;">🗄️</div>
    <div style="font-weight:700;margin:6px 0;color:#0f172a;">数据层</div>
    <div style="font-size:.86em;color:#64748b;line-height:1.65;">财报与公开经营披露按期间展示；缺少公告日期或业务拆分时明确标注</div>
  </div>
  <div style="flex:1;min-width:210px;background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:16px 18px;box-shadow:0 2px 8px rgba(15,23,42,.04);">
    <div style="font-size:1.35em;">🧮</div>
    <div style="font-weight:700;margin:6px 0;color:#0f172a;">工具层</div>
    <div style="font-size:.86em;color:#64748b;line-height:1.65;">15 个投研工具；区分已披露金额、会计推导与用户假设下的经营结果</div>
  </div>
  <div style="flex:1;min-width:210px;background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:16px 18px;box-shadow:0 2px 8px rgba(15,23,42,.04);">
    <div style="font-size:1.35em;">🔬</div>
    <div style="font-weight:700;margin:6px 0;color:#0f172a;">验证层</div>
    <div style="font-size:.86em;color:#64748b;line-height:1.65;">关键金额保留来源与计算输入；收入变化近似不等同于公司净利润预测</div>
  </div>
</div>
"""

FOOTER_HTML = """
<div style="text-align:center;color:#94a3b8;font-size:.82em;margin:26px 0 8px;line-height:1.8;">
  数据为真实财报 + 联网快照，分析不构成投资建议 · 风险扫描为简化版 · 仅用于研究演示<br>
  Powered by DeepSeek · 北京大学金融 AI 智能体创新大赛
</div>
"""

UI_CSS += WELCOME_CSS
UI_JS += '\n' + GUIDE_JS


def chat_fn(message: str, history, on_event=None) -> str:
    message = (message or "").strip()
    if not message:
        return "请输入你的投研问题。"
    try:
        return run_agent(message, history=history, on_event=on_event)
    except Exception as exc:  # noqa: BLE001
        return f"研究请求未完成：{type(exc).__name__}。请检查模型连接或稍后重试。"


def chat_with_trace(message, history):
    from html import escape
    events = []
    response = chat_fn(message, history, on_event=events.append)
    states = {'success':'已返回', 'error':'失败', 'timeout':'超时'}
    rows = [f"<li>{escape(e['tool'])} · {states.get(e['status'], e['status'])} · {e.get('elapsed_ms', 0):,.0f} ms</li>"
            for e in events if e['event'] == 'tool_end']
    usage = [e.get('usage', {}).get('total_tokens') for e in events if e['event'] == 'model_end']
    token_text = str(sum(usage)) if usage and all(isinstance(v, int) for v in usage) else '未提供完整统计'
    trace = f'<p>模型调用 {len(usage)} 次 · token {token_text}；工具返回成功不等于结论已审计。</p><ol>' + ''.join(rows) + '</ol>'
    return response, trace


def build() -> gr.Blocks:
    with gr.Blocks(
        title="有色金属投研 Agent",
    ) as demo:
        gr.HTML('<div class="brand-name">有色金属投研平台</div><p>公司研究 · 利润分析 · 同业比较</p>', elem_id='app_brand')
        guide_step = gr.State(0)
        guide_company = gr.State(None)
        intro_candidate = gr.State(None)
        with gr.Column(visible=False, elem_id='newcomer_guide') as guide:
            guide_copy = gr.HTML(step_html(0))
            with gr.Row(elem_id='guide_buttons'):
                guide_previous = gr.Button('上一步', size='sm', interactive=False, min_width=90)
                guide_load = gr.Button('加载入门数据', variant='primary', size='sm', min_width=120)
                guide_next = gr.Button('下一步', size='sm', min_width=90)
                guide_exit = gr.Button('退出引导', size='sm', min_width=90)
        with gr.Accordion('术语速查', open=False, elem_id='glossary_lookup') as glossary_panel:
            glossary_query = gr.Textbox(label='搜索术语或解释', placeholder='例如：PE、成本、回收率',
                                        show_label=True)
            glossary_results = gr.HTML(search_glossary(), elem_id='glossary_results')
            glossary_query.change(search_glossary, inputs=glossary_query, outputs=glossary_results,
                                  trigger_mode='always_last')
        with gr.Tabs(selected=4) as main_tabs:
          with gr.Tab('欢迎', id=4):
            gr.HTML(WELCOME_HTML)
            with gr.Row(elem_id='welcome_actions'):
                start_guide = gr.Button('带我试一次', variant='primary', min_width=150)
                skip_guide = gr.Button('直接进入平台', min_width=150)
            gr.HTML('''<section class="welcome-topics"><h2>在这里，你可以……</h2><dl>
<div><dt>读懂一家公司</dt><dd>从主营业务到利润来源，再看一份有依据的研究简报。</dd></div>
<div><dt>查评分，也查依据</dt><dd>五维评分快速看各方面表现；展开明细，了解指标和计分标准。</dd></div>
<div><dt>试试价格涨跌</dt><dd>情景矩阵比较多家公司的收入影响；经营情景细看价格、成本的变化。</dd></div>
<div><dt>不懂就查，想问就问</dt><dd>术语速查和小问号解释陌生词语，自由问答帮助你继续追问。</dd></div>
</dl></section>''')
            with gr.Accordion('一份研报里有什么？按部分查看详细介绍', open=False, elem_id='welcome_report_reading'):
                for section, (title, _) in REPORT_READING.items():
                    gr.HTML('<details class="guide-reading"><summary>' + title + '</summary>'
                            + reading_html(section) + '</details>')
            with gr.Accordion('关于项目与数据', open=False):
                gr.Markdown('本平台覆盖140家有色行业公司，提供财报研究、7类经营情景及五维评分。'
                            '各项数据的日期和完整程度不同，缺失与不适用会单独标明。'
                            '评分是研究规则，情景结果基于所选假设，均不代表投资建议。')
          with gr.Tab("一键研报", id=0):
            with gr.Row(elem_id='report_company_controls'):
                stock_input = gr.Textbox(
                    label="股票名称或代码", placeholder="紫金矿业 / 600111 / 北方稀土 / 天齐锂业"
                )
                gen_btn = gr.Button("生成完整研报", variant="primary")
            status_box = gr.HTML(elem_id="status_bar")
            from wind_local import local_view
            with gr.Accordion('本地补充数据：推导结果与暂缺项', open=False, elem_id='wind_local_panel'):
                wind_period = gr.Dropdown(label='补充数据报告期', choices=[f'{year}-{end}' for year in (2024, 2025, 2026)
                    for end in ('03-31','06-30','09-30','12-31') if f'{year}-{end}' <= '2026-06-30'], value='2025-12-31')
                wind_note = gr.HTML(local_view(''), elem_id='wind_local_result', elem_classes='report_md')
                wind_period.change(local_view, inputs=[stock_input, wind_period], outputs=wind_note)
                stock_input.change(local_view, inputs=[stock_input, wind_period], outputs=wind_note, trigger_mode='always_last')
            with gr.Accordion('研报结果怎么看？从这里开始', open=False, elem_id='report_reading_overview'):
                gr.HTML(reading_html('overview'))
            radar_plot = gr.Plot(label="五维诊断（图例在右侧，点击切换对比图层）", elem_id="radar_plot", elem_classes='report-overview')
            radar_note = gr.Markdown(elem_classes='report-overview')
            radar_rank = gr.HTML(elem_classes='report-overview')
            gr.HTML('<div id="radar_hover_info" class="radar-hover-info"><span>将鼠标移到雷达图维度上查看分数</span></div>', elem_classes='report-overview')
            with gr.Tabs(elem_id='report_sections') as report_tabs:
                with gr.Tab("📊 基本面", id=0):
                    gr.HTML(help_heading('公司靠什么赚钱', '基本面'))
                    with gr.Accordion('基本面怎么看？主营构成与宏观周期', open=False, elem_id='report_reading_base'):
                        gr.HTML(reading_html('base'))
                    mix_plot = gr.Plot(label="主营构成（同报告期分部收入）", elem_id="metal_mix_plot")
                    macro_plot = gr.Plot(label="宏观周期状态（滚动 z-score）")
                    t_base = gr.Markdown(elem_classes="report_md")
                with gr.Tab("🎯 估值", id=1):
                    with gr.Accordion('估值怎么看？利润图与经营情景', open=False, elem_id='report_reading_value'):
                        gr.HTML(reading_html('value'))
                    profit_state = build_profit_panel(stock_input)
                    t_val = gr.Markdown(elem_classes="report_md")
                with gr.Tab("📈 技术面", id=2):
                    gr.HTML(help_heading('价格与成交趋势', '技术面'))
                    with gr.Accordion('技术面怎么看？均线、MACD 与 RSI', open=False, elem_id='report_reading_tech'):
                        gr.HTML(reading_html('tech'))
                    t_tech = gr.Markdown(elem_classes="report_md")
                with gr.Tab("💰 资金面", id=3):
                    gr.HTML(help_heading('市场资金参与情况', '资金面'))
                    with gr.Accordion('资金面怎么看？净流入比例与金额', open=False, elem_id='report_reading_capital'):
                        gr.HTML(reading_html('capital'))
                    t_cap = gr.Markdown(elem_classes="report_md")
                with gr.Tab("⚠️ 风险", id=4):
                    with gr.Accordion('风险怎么看？债务、偿债能力与缺项', open=False, elem_id='report_reading_risk'):
                        gr.HTML(reading_html('risk'))
                    t_risk = gr.Markdown(elem_classes="report_md")

            outputs = [status_box, radar_plot, radar_note, radar_rank, t_base, mix_plot, macro_plot,
                       t_val, profit_state, t_tech, t_cap, t_risk]
            gen_btn.click(report_fn, inputs=stock_input, outputs=outputs)
            stock_input.submit(report_fn, inputs=stock_input, outputs=outputs)

          with gr.Tab("五维评分", id=3):
            score_panel = build_score_panel()

          with gr.Tab("情景矩阵", id=1):
            gr.HTML(help_heading('金属价格变化会影响哪些公司', '情景矩阵'))
            with gr.Row():
                metal_dd = gr.Dropdown(choices=list(METALS.keys()), value="黄金", label="金属")
                shock_sl = gr.Slider(minimum=-50, maximum=50, value=-20, step=5, label="价格变动(%)")
                matrix_btn = gr.Button("生成影响矩阵", variant="primary")
            matrix_plot = gr.Plot(label="同报告期收入变化近似（不等于净利润预测）")
            matrix_out = gr.Markdown(elem_id='matrix_result')
            matrix_btn.click(matrix_fn, inputs=[metal_dd, shock_sl], outputs=[matrix_out, matrix_plot])
            metal_dd.input(lambda: ('', None), outputs=[matrix_out, matrix_plot], queue=False)
            shock_sl.input(lambda: ('', None), outputs=[matrix_out, matrix_plot], queue=False)

          with gr.Tab("自由问答", id=2):
            with gr.Accordion('本轮执行记录', open=False):
                chat_trace = gr.HTML('尚无执行记录')
            gr.ChatInterface(
                chat_with_trace,
                additional_outputs=[chat_trace],
                title="投研问答",
                description="研究问答（实验性）：生成的金额与单位需对照财报明细核验。",
            )

        guide_outputs = [guide_step, guide_copy, main_tabs, report_tabs, glossary_panel,
                         guide_previous, guide_load, guide_next]

        def guide_view(step, message=''):
            return (step, step_html(step, message), gr.update(selected=STEPS[step][2]),
                    gr.update(selected=STEPS[step][3]), gr.update(open=step == 6),
                    gr.update(interactive=step > 0), gr.update(visible=step == 0),
                    gr.update(value='完成教程' if step == len(STEPS)-1 else '下一步'))

        def begin(query):
            return (gr.update(visible=True), *guide_view(0), query.strip() if query and query.strip() else '南山铝业', None)

        start_guide.click(begin, inputs=stock_input,
                          outputs=[guide, *guide_outputs, stock_input, guide_company])
        skip_guide.click(lambda: (gr.update(selected=0), gr.update(visible=False)), outputs=[main_tabs, guide])
        guide_exit.click(lambda: gr.update(visible=False), outputs=guide)
        guide_previous.click(lambda step: guide_view(max(0, step-1)), inputs=guide_step, outputs=guide_outputs)

        def advance(step, company, matrix, score, score_query):
            if step == len(STEPS)-1:
                return (*guide_view(step), gr.update(visible=False), gr.skip())
            new_step = next_step(step, company, matrix)
            message = ''
            if new_step == step:
                message = '先加载当前公司的入门数据，再继续。' if step == 0 else '先点击“生成影响矩阵”，看看计算结果或缺项说明。'
            if step == 3 and (not score or score.get('query') != score_query or score['view'][1] is None):
                new_step, message = step, '先输入公司，点击“查看评分快照”，再看计分依据。'
            return (*guide_view(new_step, message), gr.update(visible=True),
                    company['name'] if new_step == 3 and step != 3 and company else gr.skip())

        guide_next.click(advance, inputs=[guide_step, guide_company, matrix_out, score_panel['candidate'], score_panel['query']],
                         outputs=[*guide_outputs, guide, score_panel['query']])

        def request_intro(query):
            return {'query': query, 'result': load_intro(query)}

        def commit_intro(candidate, query, step):
            if not candidate or candidate['query'] != query or step != 0:
                return (gr.skip(),) * (len(outputs) + 2)
            data = candidate['result']
            if not data['ok']:
                return (None, step_html(0, data['message']), _bar_html(0, '入门数据未加载', False),
                        None, '', '', data['message'], None, None, '', None, '', '', '')
            return (dict(name=data['name'], code=data['code']), step_html(0, data['message']),
                    _bar_html(1, '本地入门数据已加载'), data['radar'], data['note'], data['rank'],
                    data['base'], data['mix'], data['macro'], '本地数据导览，尚未生成AI研报。',
                    data['profit'], '', '', '')

        guide_load.click(request_intro, inputs=stock_input, outputs=intro_candidate).then(
            commit_intro, inputs=[intro_candidate, stock_input, guide_step], outputs=[guide_company, guide_copy, *outputs])
        stock_input.input(lambda: None, outputs=guide_company, queue=False)
        metal_link_input = gr.Textbox(elem_id="metal_link_input", visible=False)
        metal_link_btn = gr.Button(elem_id="metal_link_btn", visible=False)
        metal_link_btn.click(
            link_metal_to_matrix,
            inputs=metal_link_input,
            outputs=[metal_dd, shock_sl, main_tabs],
        )
        gr.HTML(FOOTER_HTML)
    return demo


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=7860)
    args = parser.parse_args()
    app = build()
    app.queue()
    app.launch(
        server_name="0.0.0.0",
        server_port=args.port,
        inbrowser=False,
        css=REPORT_CSS + UI_CSS,
        js=UI_JS,
        theme=gr.themes.Soft(primary_hue="blue"),
    )
