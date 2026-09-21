"""Sector comparison using the same disclosure-gated revenue approximation."""
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

from tools.sensitivity_core import BUSINESS_NAMES, METAL_ALIASES, analyze_sensitivity_row

BASE = Path(__file__).resolve().parent.parent
PROFILE = BASE / 'data/company_profile_summary.parquet'
METAL_CN = {'gold': '金', 'copper': '铜', 'aluminum': '铝', 'silver': '银', 'zinc': '锌',
    'tin': '锡', 'lead': '铅', 'nickel': '镍', 'lithium': '锂', 'rare_earth': '稀土',
    'molybdenum': '钼', 'tungsten': '钨', 'antimony': '锑', 'cobalt': '钴'}

SECTOR_MATRIX_TOOL = {'type': 'function', 'function': {
    'name': 'sector_impact_matrix',
    'description': ('比较金属价格冲击下各公司固定销量收入变化近似；各公司必须有同报告期独立分部收入。'
                    '按报告期分组，不比较跨期金额。不是净利润影响排名；未知或合并披露单列。'),
    'parameters': {'type': 'object', 'properties': {
        'metal': {'type': 'string', 'description': '金属名，如gold/copper/黄金/铜'},
        'price_change_pct': {'type': 'number', 'description': '价格变动百分比，如-20'}},
        'required': ['metal', 'price_change_pct']}}}


def compute_matrix(metal: str, price_change_pct: float) -> pd.DataFrame:
    profiles = pd.read_parquet(PROFILE)
    rows = []
    for _, profile in profiles.iterrows():
        result = analyze_sensitivity_row(profile, metal, price_change_pct)
        result['amount_yi'] = result['amount_yuan'] / 1e8 if result['amount_yuan'] is not None else None
        result['note'] = '' if result['status'] == 'applicable' else '；'.join(result['warnings'])
        result['biz'] = '、'.join(BUSINESS_NAMES.get(k, k) for k in result['business_types']) or '经营环节未确认'
        rows.append(result)
    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=['code', 'name', 'period', 'status', 'quantity_kind', 'amount_yuan',
            'amount_yi', 'percentage', 'share', 'note', 'biz'])
    return out.sort_values(['period', 'amount_yi'], ascending=[False, True], na_position='last').reset_index(drop=True)


def sector_impact_matrix(metal: str, price_change_pct: float) -> str:
    df = compute_matrix(metal, price_change_pct)
    applicable = df[df['status'] == 'applicable']
    missing = df[df['status'] != 'applicable']
    cn = METAL_CN.get(METAL_ALIASES.get(str(metal).lower()), str(metal))
    lines = [f'【{cn}固定销量收入冲击比较】可计算 {len(applicable)} 家；无法计算 {len(missing)} 家。',
        '假设相关产品实现售价按输入冲击同比例变化；不代表商品报价必然传导，也不是公司利润预测。']
    for period, group in applicable.groupby('period', sort=False):
        lines.extend([f'\n报告期 {period}（累计口径，组内按收入金额排序）',
            '| 股票 | 相关产品占营收 | 收入变化近似（亿元） | 经营环节 |',
            '|---|---:|---:|---|'])
        for _, row in group.iterrows():
            lines.append(f'| {row["name"]} | {row["share"]:.1%} | {row["amount_yi"]:+.2f} | {row["biz"]} |')
    if not missing.empty:
        lines.append('\n无法计算名单（未知暴露不等于零暴露）：')
        lines.extend(f'- {row["name"]}：{row["note"]}' for _, row in missing.iterrows())
    lines.append('未测算成本、税费、套保、少数股东或公司净利润影响。分部公告日不完整，不代表历史点时性数据。')
    return '\n'.join(lines)


def draw_matrix_chart(metal: str, price_change_pct: float):
    """Plot latest available comparable report period, never mixed-period ranks."""
    df = compute_matrix(metal, price_change_pct)
    d = df[df['status'] == 'applicable'].copy()
    if d.empty:
        return None
    period = d['period'].max()
    d = d[d['period'] == period]
    d = d.reindex(d['amount_yi'].abs().sort_values(ascending=False).index).head(20).sort_values('amount_yi')
    cn = METAL_CN.get(METAL_ALIASES.get(str(metal).lower()), str(metal))
    fig = go.Figure(go.Bar(x=d['amount_yi'], y=d['name'], orientation='h',
        marker_color=['#e11d48' if value < 0 else '#059669' for value in d['amount_yi']],
        text=[f'{value:+.2f}亿' for value in d['amount_yi']], textposition='outside',
        customdata=d[['period', 'share']].to_numpy(),
        hovertemplate='%{y}<br>期间 %{customdata[0]}<br>相关产品收入占比 %{customdata[1]:.1%}<br>收入变化近似 %{x:+.2f} 亿元<extra></extra>'))
    fig.add_vline(x=0, line_color='#cbd5e1', line_width=.8)
    fig.update_layout(template='plotly_white',
        font=dict(family='Microsoft YaHei, SimHei, sans-serif', color='#0f172a', size=11),
        title=dict(text=f'{cn}固定销量收入变化近似 · {period}', font=dict(size=13)),
        margin=dict(l=10, r=55, t=55, b=40),
        xaxis=dict(title='收入变化近似（亿元；实现售价同比例变化假设）', gridcolor='#e2e8f0'),
        yaxis=dict(automargin=True), paper_bgcolor='white', plot_bgcolor='white', showlegend=False)
    return fig
