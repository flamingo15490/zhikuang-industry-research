"""Synthetic v2 UI fixture; no real company observations or financial claims.

Run --check for the 14 ranking groups, or launch on port 7861 for
tests/rank_hover.browser.js. The fixture never reads/writes production scores.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from score_view import peer_context, query_view
from scoring import score_observation


CASES = [
    ('600111', 'rare_earth', '稀土', 8), ('600219', 'aluminum', '铝', 28),
    ('600255', 'copper', '铜', 20), ('600547', 'gold', '黄金', 13),
    ('603399', 'lithium', '锂', 7), ('603799', 'nickel', '镍', 3),
    ('600366', 'other', '其他', 36), ('600281', 'precious_metals', '贵金属', 19),
    ('600338', 'silver', '白银', 5), ('600301', 'industrial_metals', '工业金属', 58),
    ('600456', 'titanium', '钛', 5), ('600549', 'tungsten', '钨', 4),
    ('600497', 'zinc', '锌', 5), ('002428', 'strategic_metals', '战略金属', 27),
]


def synthetic_snapshot():
    context = dict(version='2.0', batch_id='synthetic-ui-only-14-groups',
                   as_of='2026-09-04', financial_period='2025-12-31')
    rows = []
    for group_index, (target, category, label, size) in enumerate(CASES):
        for i in range(size):
            code = target if i == 0 else f'fixture-{group_index:02d}-{i:03d}'
            raw = dict(roe=10., growth=0., pe=15., ma5=10., ma20=10., ma60=10.,
                       dif=0., dea=0., rsi=40., return20=0., flow_ratio_pct=float(i % 7 - 3),
                       debt=60., current=1., market_date='2026-09-04',
                       issues=['合成UI测试数据，不代表实际公司'], source_dates={})
            group_fallback = category.endswith('_metals')
            rows.append(dict(**context, code=code, stock_name=f'合成{label}样本{i + 1:02d}',
                subindustry=f'fixture-{group_index}-{i}' if group_fallback else category,
                subindustry_group=category if group_fallback else f'fixture-group-{group_index}',
                raw=raw, scores=score_observation(raw)))
    return dict(schema_version=2, **context, created_at='2026-09-04T15:00:00+08:00',
                synthetic=True, rows=rows)


SNAPSHOT = synthetic_snapshot()


def cached_report(query):
    figure, note, ranking, _ = query_view(query, snapshot=SNAPSHOT)
    yield dict(sections={}, radar=figure, radar_note='合成UI回归测试，非实际公司评级。\n\n' + note,
               radar_rank=ranking, metal_mix=None, macro=None, profit_analysis=None)


def check_groups():
    buckets = {}
    for code, _, label, count in CASES:
        result = next(cached_report(code))
        assert result['radar'] is not None, result['radar_note']
        assert result['radar_rank'].count('<li>') == count, (label, result['radar_rank'])
        assert label + '排名' in result['radar_rank']
        assert peer_context(SNAPSHOT, code)[0] == label
        buckets[label] = count
    return dict(synthetic_ui_only=True, failures=[], buckets=buckets, rows=len(SNAPSHOT['rows']))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--port', type=int, default=7861)
    args = parser.parse_args()
    print(check_groups(), flush=True)
    if not args.check:
        import webui
        webui.generate_report_iter = cached_report
        webui.build().queue().launch(server_name='127.0.0.1', server_port=args.port,
                                    css=webui.REPORT_CSS + webui.UI_CSS, js=webui.UI_JS)
