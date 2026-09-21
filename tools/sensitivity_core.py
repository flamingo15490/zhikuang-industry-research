"""Shared, period-aligned revenue shock approximation with disclosure gates."""
from __future__ import annotations

from functools import lru_cache
import math
from pathlib import Path

import pandas as pd

from scripts.build_company_profile import metals_of
from tools.profit_analysis import analyze_profit

BASE = Path(__file__).resolve().parent.parent
PROFILE = BASE / 'data/company_profile_summary.parquet'

METAL_ALIASES = {
    'gold': 'gold', '金': 'gold', '黄金': 'gold', 'copper': 'copper', '铜': 'copper',
    'zinc': 'zinc', '锌': 'zinc', 'silver': 'silver', '银': 'silver',
    'lithium': 'lithium', '锂': 'lithium', 'aluminum': 'aluminum', 'aluminium': 'aluminum', '铝': 'aluminum',
    'tin': 'tin', '锡': 'tin', 'molybdenum': 'molybdenum', '钼': 'molybdenum',
    'tungsten': 'tungsten', '钨': 'tungsten', 'rare_earth': 'rare_earth', '稀土': 'rare_earth',
    'antimony': 'antimony', '锑': 'antimony', 'cobalt': 'cobalt', '钴': 'cobalt',
    'lead': 'lead', '铅': 'lead', 'nickel': 'nickel', '镍': 'nickel',
    'platinum': 'platinum', '铂': 'platinum', 'palladium': 'palladium', '钯': 'palladium',
    'titanium': 'titanium', '钛': 'titanium', 'germanium': 'germanium', '锗': 'germanium',
}
BUSINESS_NAMES = {'mining': '矿山采选', 'smelting': '外购精矿冶炼', 'aluminum': '电解铝',
    'processing': '加工及功能材料', 'refining': '化合物及分离加工', 'recycling': '再生回收', 'trading': '贸易及供应链'}


def _finite(value):
    try:
        if isinstance(value, bool):
            return None
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


@lru_cache(maxsize=160)
def _cached_analysis(code, signature):
    return analyze_profit(code)


def _load_analysis(code):
    paths = [BASE / 'data' / folder / f'{prefix}_{code}.parquet' for folder, prefix in
        [('profit_analysis', 'profit'), ('company_profile', 'profit'), ('company_profile', 'zy')]]
    paths.append(BASE / 'data/company_profile_summary.parquet')
    signature = tuple((str(path), path.stat().st_mtime_ns if path.exists() else None) for path in paths)
    return _cached_analysis(code, signature)


def _empty(metal, shock):
    return dict(code=None, name=None, period=None, notice_date=None, status='insufficient',
        model='fixed_volume_revenue_shock', quantity_kind='revenue_change_approximation',
        exposure_scope='explicitly_named_segments_only',
        amount_yuan=None, percentage=None, one_percent_comparator=None, share=None,
        metal_revenue_yuan=None, parent_netprofit_yuan=None, metal=metal, price_change_pct=shock,
        business_types=[], source={}, assumptions=[
            '固定报告期销量，并假设相关产品实现售价按输入金属价格冲击同比例变化。',
            '仅覆盖名称中明确识别的独立分部；未识别产品不按零暴露处理，结果不代表该金属全部业务。',
            '该实现售价假设不代表商品报价必然传导至公司售价；未测算成本、税费、套保或少数股东影响。',
            '金额为该报告期累计收入变化近似，不转换为全年预测。'], warnings=[])


def segment_metals(name):
    metals = list(metals_of(name))
    if 'platinum' in metals:
        metals.remove('platinum')
        metals.extend(key for symbol, key in [('铂', 'platinum'), ('钯', 'palladium')] if symbol in name)
    return metals


def analyze_sensitivity_row(row, metal, price_change_pct, *, analysis=None):
    """Same core for one company and a preloaded universe row."""
    normalized = METAL_ALIASES.get(str(metal).strip().lower())
    shock = _finite(price_change_pct)
    out = _empty(normalized or str(metal), shock)
    out.update(code=str(row.get('code', '')), name=str(row.get('stock_name', '')))
    if normalized is None or shock is None or shock < -100:
        out['status'] = 'unsupported'
        out['warnings'].append('金属不受支持，或价格冲击不是有限数值/低于-100%。')
        return out
    if row.get('metal_quality') != 'clean':
        out['warnings'].append('画像金属占比为合并、粗略或未知披露，默认不采用均分占比。')
        return out
    try:
        analysis = _load_analysis(out['code']) if analysis is None else analysis
    except (OSError, ValueError, KeyError) as exc:
        out['warnings'].append(f'财报或分部数据不可用：{exc}')
        return out
    if analysis.get('code') != out['code']:
        out['warnings'].append('输入财报公司与研究对象不一致。')
        return out
    out.update(period=analysis.get('period'), notice_date=analysis.get('notice_date'),
        business_types=analysis.get('business_types', []), source=analysis.get('source', {}))
    out['warnings'].append('主营构成缺少原公告日时，仅支持当前缓存分析，不代表历史点时性可用。')
    if not out['business_types']:
        out['warnings'].append('经营环节无法确认，不推断成本结构或利润传导率。')
    elif any(kind != 'mining' for kind in out['business_types']):
        out['warnings'].append('加工、贸易或其他经营环节的原料成本和售价联动未知；收入冲击不能解释为利润影响。')
    if not out['period'] or out['period'] != analysis.get('segment_period'):
        out['warnings'].append('财报与金属分部不存在可用的同报告期数据。')
        return out
    statement = analysis.get('statement', {})
    revenue = _finite(statement.get('OPERATE_INCOME'))
    if revenue is None or revenue <= 0:
        out['warnings'].append('同期间营业收入缺失或非正。')
        return out
    segments = analysis.get('segments', [])
    if not segments:
        out['warnings'].append('未披露可核验的产品或行业收入。')
        return out
    seen = set()
    metal_revenue = 0.
    total = 0.
    evidence = []
    found = False
    for segment in segments:
        name = segment['name']
        amount = _finite(segment.get('revenue'))
        if segment.get('excluded') or segment.get('is_elimination') or name in seen or amount is None or amount < 0:
            out['warnings'].append('分部含重复层级、排除项、内部抵销或无效收入，无法确认独立金属占比。')
            return out
        seen.add(name)
        total += amount
        metals = segment_metals(name)
        if normalized in metals:
            if len(metals) != 1:
                out['warnings'].append(f'分部“{name}”合并多种金属，无法独立分配该金属收入。')
                return out
            metal_revenue += amount
            found = True
            evidence.append({'name': name, 'revenue_yuan': amount})
    if abs(total - revenue) > max(1., abs(revenue) * 1e-4):
        out['warnings'].append('分部收入合计与同期间营业收入不能勾稽，不能确认金属占比分母。')
        return out
    if not found:
        out['warnings'].append('未识别到独立披露的该金属收入；未知暴露不等于零暴露。')
        return out
    share = metal_revenue / revenue
    amount = metal_revenue * shock / 100.
    if not math.isfinite(amount) or not 0 <= share <= 1:
        out['warnings'].append('冲击金额溢出或金属收入比例超出有效范围。')
        return out
    profit = _finite(statement.get('PARENT_NETPROFIT'))
    out.update(status='applicable', amount_yuan=amount, share=share,
        metal_revenue_yuan=metal_revenue, parent_netprofit_yuan=profit, segment_evidence=evidence)
    if profit is not None and profit > 0:
        comparator = amount / profit * 100.
        one_percent = metal_revenue / profit
        if math.isfinite(comparator) and math.isfinite(one_percent):
            out.update(percentage=comparator, one_percent_comparator=one_percent)
    if out['percentage'] is None:
        out['warnings'].append('归母净利润缺失、为零或为负，不显示以净利润为分母的比值。')
    return out


def analyze_sensitivity(query: str, metal: str, price_change_pct: float) -> dict:
    """Fixed-volume revenue approximation; never automatic company net profit."""
    out = _empty(METAL_ALIASES.get(str(metal).strip().lower(), str(metal)), _finite(price_change_pct))
    if not str(query).strip():
        out['warnings'].append('请输入股票代码或名称。')
        return out
    try:
        profiles = pd.read_parquet(PROFILE)
    except (OSError, ValueError):
        out['warnings'].append('公司画像数据缺失或不可读。')
        return out
    query = str(query).strip().lower()
    codes, names = profiles['code'].astype(str).str.lower(), profiles['stock_name'].astype(str).str.lower()
    exact = profiles[(codes == query) | (names == query)]
    selected = exact if not exact.empty else profiles[codes.str.contains(query, regex=False) | names.str.contains(query, regex=False)]
    if len(selected) != 1:
        out['warnings'].append('未找到唯一股票，请提供完整代码或名称。')
        return out
    return analyze_sensitivity_row(selected.iloc[0], metal, price_change_pct)
