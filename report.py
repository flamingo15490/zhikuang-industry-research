"""一键研报：捕获本地研究输入，再生成共用这些输入的正文和图表。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from config import create_llm_client, load_llm_config
from tools import execute_tool
from charts import draw_macro_cycle
from tools.profit_analysis import format_profit_summary
from research_evidence import build_evidence, evidence_summary
from tools._resolve import resolve_profile_row

BASE = Path(__file__).resolve().parent
PROFILE = BASE / "data" / "company_profile_summary.parquet"
FUND = BASE / "data" / "nonferrous_fundamentals.parquet"
EXPOSURE = BASE / "data" / "nonferrous_subindustry_exposure.csv"

REPORT_SYSTEM_PROMPT = """你是一名有色金属投研智能体，正在生成个股多维投研简报。
你会收到已经采集好的真实工具数据。要求：
1. 严格基于给定数据撰写，不得编造任何数字；数字必须标注来源与数据日期。
2. 按指定结构输出 Markdown：只输出五个 ## 二级标题小节（基本面/估值/技术面/资金面/风险），不要输出 # 一级标题，不要输出其它小节。
3. 数据披露不全或识别存在误差时，明确标注"无法识别"或"识别存在误差"，不得硬给数。
4. 不做买入/卖出/仓位/择时建议；宏观状态仅作周期背景描述，不作为信号。
5. 实时行情、技术面、资金面仅作时点快照或形态/资金参考，不构成买卖建议；风险扫描为简化版，须标注"非完整风控"。
6. 语言专业、简洁、结构化，善用表格与要点。
7. 排版精致：每个 ## 小节先给一句话核心结论（加粗）；关键指标用表格呈现；数字用千分位分隔（如 34,908 亿）；重要提醒/免责用 > 引用块；不写冗长段落，多用要点列表。"""


def _resolve_stock(query: str) -> tuple[str, str]:
    """把名称/代码解析成 (stock_name, code)。"""
    frames = [pd.read_parquet(path)[['code', 'stock_name']] for path in (PROFILE, FUND) if path.exists()]
    if frames:
        row = resolve_profile_row(pd.concat(frames).drop_duplicates('code'), query)
        if row is not None:
            return str(row['stock_name']), str(row['code'])
    raise ValueError(f"未找到与 '{query}' 唯一匹配的有色股票，请输入完整名称或代码")


def _subindustry(code: str) -> str | None:
    if not EXPOSURE.exists():
        return None
    ex = pd.read_csv(EXPOSURE)
    row = ex[ex["code"] == code]
    return str(row.iloc[0]["subindustry"]) if not row.empty else None


def _top_metals(code: str, k: int = 2) -> list[str]:
    df = pd.read_parquet(PROFILE)
    r = df[df["code"] == code].iloc[0]
    if r.get("metal_quality") == "coarse":
        return []
    cols = [c for c in df.columns if c.endswith("_share") and c != "minority_share"]
    pairs = [(c[:-6], float(r[c])) for c in cols if pd.notna(r[c])]
    pairs.sort(key=lambda x: -x[1])
    return [m for m, _ in pairs[:k]]


def _insert_after_heading(md: str, heading: str, content: str) -> str:
    idx = md.find(heading)
    if idx == -1:
        return md
    line_end = md.find("\n", idx)
    if line_end == -1:
        return md + "\n\n" + content
    return md[: line_end + 1] + "\n\n" + content + "\n" + md[line_end + 1:]


def _split_sections(md: str) -> dict[str, str]:
    """按 ## 二级标题拆成 {小节名: 内容}。"""
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in md.splitlines():
        if line.startswith("## "):
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = line[3:].strip()
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return sections


def _tick(progress, frac: float, desc: str) -> None:
    """进度回调（可选），用于 Gradio 进度条。"""
    if progress is None:
        return
    try:
        progress(frac, desc=desc)
    except Exception:  # noqa: BLE001
        pass


def generate_report_iter(query: str):
    """Capture inputs once, then derive the report and every displayed chart."""
    import json
    from html import escape
    from report_context import build_context, context_payload, save_context, scoring_text, radar_view
    from charts import draw_report_mix
    from tools.sensitivity_core import analyze_sensitivity_row, segment_metals

    yield (0.02, "解析股票…")
    name, code = _resolve_stock(query)
    yield (0.12, "固定本次研究批次与财务期间…")
    context = build_context(name, code)
    profit_analysis = context['profit']
    snapshot = context['snapshot']
    target = context['target']
    metals = sorted({metal for row in profit_analysis.get('segments', [])
                     if not row.get('excluded') for metal in segment_metals(row['name'])})
    context['sensitivity'] = [
        analyze_sensitivity_row(dict(code=code, stock_name=name, metal_quality='clean'),
                                metal, -10, analysis=profit_analysis)
        for metal in metals]
    yield (0.35, "核对同期间分部与研究来源…")
    evidence = build_evidence(profit_analysis)
    context['evidence'] = evidence
    macro_records = context_payload(context)['macro']
    macro_text = json.dumps(macro_records[-1] if macro_records else {'status': '缺失'},
                           ensure_ascii=False, allow_nan=False)
    scoring = scoring_text(context)
    archive = save_context(context)
    profit_summary = format_profit_summary(profit_analysis)
    user = f"""请为{name}（{code}）生成五维研究简报。
【共同研究口径】
研究编号：{context['run_id']}；评分快照批次：{snapshot['batch_id']}；
截止日：{snapshot['as_of']}；财务报告期：{snapshot['financial_period']}。
行情是下方标注日期的本地快照，不是本次实时取数。缺项保留，不能换其他日期补值。
【五维原始观察、分数与计分明细】
{scoring}
【同报告期利润及分部】
{profit_summary}
【同份利润数据计算的收入变化近似】
{json.dumps(context['sensitivity'], ensure_ascii=False, allow_nan=False)}
【宏观背景：本地截至截止日前最后一条，与宏观图共用数据】
{macro_text}
【财报证据】
{evidence_summary(evidence)}
【数据限制】
{json.dumps(context['warnings'] + profit_analysis.get('warnings', []), ensure_ascii=False)}

只输出五个二级标题：基本面、估值、技术面、资金面、风险。
基本面引用同期间财报与ROE/增长；估值只引用该快照PE及已披露利润结构。
技术面使用给定MA、DIF/DEA、RSI、20日收益；资金面使用给定五日净流入/成交额比例，
该比例是百分数，不是净流入亿元。没有绝对额时不能猜测绝对额。
风险只依据给定债率、增长、流动比率与缺项，注明非完整风控；不要声称执行了其他扫描。
引用金额时保留报告期和证据编号；分部缺公告日不宣称完整历史点时性。
收入变化近似不能写成净利润预测，不补经验传导率或未知经营成本。
评分阈值是研究假设，不能把高分或低PE解释成买入建议。"""
    yield (0.62, "AI根据固定输入撰写正文…")
    cfg = load_llm_config()
    client = create_llm_client()
    request = dict(model=cfg.model, messages=[{"role": "system", "content": REPORT_SYSTEM_PROMPT},
                  {"role": "user", "content": user}], temperature=0.2)
    (archive.parent / 'request.json').write_text(json.dumps(request,
        ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')
    resp = client.chat.completions.create(**request)
    raw = resp.choices[0].message.content or ""
    sections = _split_sections(raw)
    period_note = (f"> 本次研究财务期间：{escape(snapshot['financial_period'])}；"
                   f"行情日期：{escape(target['raw'].get('market_date') or '缺失')}。"
                   "本地快照，非本次实时获取。\n\n")
    for section in ('基本面', '估值', '技术面', '资金面', '风险'):
        sections[section] = period_note + sections.get(section, '模型未生成该部分，不能据此认定数据缺失。')
    yield (0.92, "用同一研究输入生成图表…")
    radar_fig, radar_notes, radar_rank = radar_view(context)
    macro_fig = draw_macro_cycle(frame=context['macro'])
    mix_fig = draw_report_mix(profit_analysis)
    if mix_fig is None:
        sections['基本面'] += "\n\n> 同期间分部收入未能完整核对，不生成收入占比图。"
    radar_notes += (f"\n\n<details><summary>本次研究来源</summary>\n\n"
                    f"研究编号：{context['run_id']}；财务期间：{snapshot['financial_period']}。"
                    "正文、五维图表与同业排名共用已捕获批次；分部和宏观保留各自日期。\n\n</details>")
    result = dict(name=name, code=code, sections=sections, macro=macro_fig, metal_mix=mix_fig,
        profit_analysis=profit_analysis, evidence=evidence, radar=radar_fig,
        radar_note=radar_notes, radar_rank=radar_rank, run_id=context['run_id'],
        snapshot_batch=snapshot['batch_id'], context_path=str(archive))
    (archive.parent / 'report.json').write_text(json.dumps(
        dict(run_id=context['run_id'], batch_id=snapshot['batch_id'], sections=sections,
             model=cfg.model, usage=resp.usage.model_dump() if getattr(resp, 'usage', None) is not None else None),
        ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')
    yield result
