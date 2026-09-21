"""One captured local input set for a report, its charts and its audit record."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

import pandas as pd

from charts import MACRO
from score_view import read_snapshot, snapshot_view, _rows
from tools.profit_analysis import analyze_profit

BASE = Path(__file__).resolve().parent


def load_macro(as_of):
    if not MACRO.exists():
        return pd.DataFrame()
    frame = pd.read_parquet(MACRO)
    frame['date'] = pd.to_datetime(frame['date'], errors='coerce')
    return frame[frame['date'].notna() & (frame['date'] <= pd.Timestamp(as_of))].sort_values('date').copy()


def empty_profit(name, code, reason):
    return dict(name=name, code=code, period=None, periods=[], notice_date=None,
        statement={}, source={}, bridge=dict(labels=[], values=[], measures=[], origins=[], units='亿元'),
        bridge_status='missing', segments=[], segment_period=None, segment_status='missing',
        segment_source={}, segment_totals=None, business_types=[], warnings=[reason], summary=reason)


def build_context(name, code):
    snapshot = deepcopy(read_snapshot())
    if snapshot is None:
        raise ValueError('缺少有效的本地评分快照，请先采集或恢复快照后生成研报。')
    target = next((row for row in _rows(snapshot) if row['code'] == code), None)
    if target is None:
        raise ValueError('本地评分快照没有该公司的唯一有效记录。')
    if any(target['raw'].get(key) != target[key] for key in ('code', 'as_of', 'financial_period')):
        raise ValueError('评分快照原始观察与公司或期间不一致。')
    warnings = []
    period, as_of = snapshot['financial_period'], snapshot['as_of']
    try:
        profit = deepcopy(analyze_profit(code, period=period))
        if (profit.get('code') != code or profit.get('period') != period
                or not profit.get('notice_date') or profit['notice_date'] > as_of):
            raise ValueError('同公司、同报告期且已在截止日前公告的财报不可用')
    except (OSError, ValueError, KeyError) as error:
        warnings.append(str(error))
        profit = empty_profit(name, code, str(error))
    if profit.get('segment_period') != period:
        profit['segments'] = []
        profit['segment_period'] = None
        profit['segment_status'] = 'missing'
        profit['business_types'] = []
        profit.setdefault('warnings', []).append('本研究指定报告期无匹配分部，不使用其他期间分部替代。')
    from tools.operating_disclosure import load_operating_disclosure
    profit['_operating_snapshot'] = dict(code=code, period=profit.get('period'),
        data=deepcopy(load_operating_disclosure(code, profit.get('period'))))
    try:
        macro = load_macro(as_of)
    except (OSError, ValueError, KeyError) as error:
        warnings.append('宏观本地数据不可用：' + str(error))
        macro = pd.DataFrame()
    return dict(run_id=uuid4().hex, created_at=datetime.now(timezone.utc).isoformat(),
        name=name, code=code, snapshot=snapshot, target=target, profit=profit, macro=macro,
        warnings=warnings)


def context_payload(context):
    # pandas JSON handles NaT/NaN and timestamps without nonstandard JSON numbers.
    macro = json.loads(context['macro'].to_json(orient='records', date_format='iso'))
    return dict(schema_version=1, run_id=context['run_id'], created_at=context['created_at'],
        name=context['name'], code=context['code'], score_snapshot=context['snapshot'],
        observation=context['target']['raw'], profit=context['profit'], macro=macro,
        warnings=context['warnings'], sensitivity=context.get('sensitivity', []), evidence=context.get('evidence', []),
        limitation='共同研究输入，不等于所有来源具有相同日期或完整历史点时性；分部缺公告日如实保留。')


def save_context(context, root=None):
    folder = Path(root or BASE / 'output/report_runs') / context['run_id']
    folder.mkdir(parents=True, exist_ok=False)
    path = folder / 'context.json'
    path.write_text(json.dumps(context_payload(context), ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')
    return path


def scoring_text(context):
    raw = context['target']['raw']
    return json.dumps(dict(batch_id=context['snapshot']['batch_id'],
        financial_period=context['snapshot']['financial_period'], as_of=context['snapshot']['as_of'],
        market_date=raw.get('market_date'), metrics={key: raw.get(key) for key in
        ('roe','growth','pe','ma5','ma20','ma60','dif','dea','rsi','return20','flow_ratio_pct','debt','current')},
        definitions={'pe': '滚动市盈率PE(TTM)，不是静态PE；不能乘当期年报利润反推已核验市值',
                     'dif_dea': '仅有当前DIF/DEA，不能证明本日发生金叉或死叉'},
        units={'roe':'%','growth':'%','pe':'倍','ma5':'元/股','ma20':'元/股','ma60':'元/股',
               'dif':'元/股','dea':'元/股','rsi':'指数点','return20':'%','flow_ratio_pct':'%','debt':'%','current':'倍'},
        scores=context['target']['scores'], source_dates=raw.get('source_dates', {}),
        issues=raw.get('issues', [])), ensure_ascii=False, allow_nan=False)


def radar_view(context):
    return snapshot_view(context['snapshot'], context['code'])[:3]
