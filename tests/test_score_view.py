import copy
import json

from score_view import read_snapshot, snapshot_view

DIMS = ['基本面', '估值', '技术面', '资金面', '安全度']


def fixture():
    snap = dict(schema_version=2, version='2.0', batch_id='batch', as_of='2026-09-04',
                financial_period='2025-12-31', rows=[])
    for i, value in enumerate([60., 70., 70., 90.]):
        snap['rows'].append(dict(code=str(i), stock_name=f'公司{i}', subindustry='gold',
            subindustry_group='precious_metals', batch_id='batch', version='2.0',
            as_of=snap['as_of'], financial_period=snap['financial_period'],
            raw=dict(market_date='2026-09-04', issues=[], source_dates={}),
            scores=dict(scores=dict.fromkeys(DIMS, value), composite=value, coverage=1,
                eligible=True, dimensions={d:dict(status='complete', metrics=[], missing=[]) for d in DIMS})))
    return snap


def test_single_snapshot_drives_chart_mean_and_rank():
    fig, notes, rank, rows = snapshot_view(fixture(), '1')
    assert list(fig.data[0].r) == [70.] * 6
    assert list(fig.data[1].r) == [72.5] * 6
    assert '2 / 4' in rank and '70.0' in rank
    assert 'batch' in notes and '2026-09-04' in notes


def test_incomplete_is_neither_zero_nor_ranked():
    snap=fixture()
    row=snap['rows'][1]
    row['scores'].update(composite=None,eligible=False,coverage=.8)
    row['scores']['scores']['资金面']=None
    row['scores']['dimensions']['资金面']['status']='missing'
    fig, notes, rank, rows=snapshot_view(snap,'1')
    assert fig.data[0].r[3] is None
    assert '不参与综合排名' in notes and '综合分：缺项' in notes
    assert '公司1' not in rank


def test_mixed_batch_version_period_and_market_date_are_excluded():
    for key,value in [('batch_id','old'),('version','1.0'),('financial_period','2024-12-31')]:
        snap=fixture()
        snap['rows'][3][key]=value
        fig,notes,rank,_=snapshot_view(snap,'1')
        assert '2 / 3' not in rank  # 70 is joint first after removing 90.
        assert '1 / 3' in rank
        assert '公司3' not in rank
    snap=fixture()
    snap['rows'][3]['raw']['market_date']='2026-09-03'
    assert '公司3' not in snapshot_view(snap,'1')[2]


def test_old_snapshot_is_not_silently_upgraded(tmp_path):
    path=tmp_path/'current.json'
    path.write_text(json.dumps(dict(schema_version=1,rows=[])))
    assert read_snapshot(path) is None


def test_small_comparable_group_has_no_rank():
    snap=fixture()
    snap['rows']=snap['rows'][:2]
    assert snapshot_view(snap,'1')[2] == ''


def test_names_are_escaped_in_ranking():
    snap=fixture()
    snap['rows'][0]['stock_name']='<img src=x onerror=alert(1)>'
    rank=snapshot_view(snap,'1')[2]
    assert '<img' not in rank and '&lt;img' in rank


def test_peer_mean_requires_three_valid_observations_per_dimension():
    snap = fixture()
    for row in snap['rows'][2:]:
        row['scores']['scores']['资金面'] = None
        row['scores']['dimensions']['资金面']['status'] = 'missing'
        row['scores'].update(eligible=False, composite=None)
    fig, _, _, _ = snapshot_view(snap, '1')
    assert fig.data[1].r[3] is None
    assert fig.data[1].customdata[3] == 2
    assert fig.data[1].connectgaps is False


def test_market_date_filters_market_means_but_not_financial_means():
    snap = fixture()
    snap['rows'][3]['raw']['market_date'] = '2026-09-03'
    fig, _, _, _ = snapshot_view(snap, '1')
    assert fig.data[1].r[0] == 72.5
    assert fig.data[1].r[1] == 200 / 3
    assert list(fig.data[1].customdata) == [4, 3, 3, 3, 4, 4]


def test_all_missing_target_keeps_axes_with_explicit_annotation():
    snap = fixture()
    target = snap['rows'][1]['scores']
    target.update(scores=dict.fromkeys(DIMS), composite=None, eligible=False)
    for dimension in target['dimensions'].values():
        dimension['status'] = 'missing'
    fig, notes, rank, _ = snapshot_view(snap, '1')
    assert all(value is None for value in fig.data[0].r)
    assert fig.data[0].connectgaps is False
    assert fig.layout.annotations
    assert '0/5' in notes
    assert not rank


def test_nonfinite_or_inconsistent_composite_does_not_rank():
    for invalid in [float('nan'), float('inf'), 99., True]:
        snap = fixture()
        snap['rows'][3]['scores']['composite'] = invalid
        assert '公司3' not in snapshot_view(snap, '1')[2]


def test_rank_ties_use_competition_ranks_everywhere():
    rank = snapshot_view(fixture(), '1')[2]
    assert '2. 公司1' in rank
    assert '2. 公司2' in rank
    assert '4. 公司0' in rank


def test_query_uses_one_snapshot_read_and_literal_unique_matching(monkeypatch):
    import score_view
    reads = []
    def read():
        reads.append(1)
        return fixture()
    monkeypatch.setattr(score_view, 'read_snapshot', read)
    assert score_view.query_view('公司1')[0] is not None
    assert reads == [1]
    assert score_view.query_view('公司', snapshot=fixture())[0] is None
    assert score_view.query_view('[', snapshot=fixture())[0] is None
    assert score_view.query_view('', snapshot=fixture())[0] is None


def test_header_and_row_asof_mismatch_reject_stale_rows():
    snap = fixture()
    snap['rows'][1]['as_of'] = '2026-09-03'
    assert snapshot_view(snap, '1')[0] is None


def test_metric_details_show_real_values_units_rules_and_missing_contributions():
    from scoring import score_observation
    snap = fixture()
    snap['rows'][1]['scores'] = score_observation(dict(roe=10., growth=None, pe=-10.))
    _, _, _, rows = snapshot_view(snap, '1')
    assert len(rows) == 14
    assert all(len(row) == 7 for row in rows)
    roe = next(row for row in rows if row[2].startswith('净资产收益率'))
    assert roe[1] == '缺失' and roe[3] == 10. and roe[4] == '%' and roe[6] == '未计分'
    growth = next(row for row in rows if row[2].startswith('净利润同比增长率'))
    assert growth[3] == '缺失'
    pe = next(row for row in rows if row[2].startswith('市盈率'))
    assert pe[0] == '估值观察' and pe[1] == '不适用' and pe[3] == -10.


def test_duplicate_identity_cannot_double_count_or_resolve():
    snap = fixture()
    snap['rows'].append(copy.deepcopy(snap['rows'][1]))
    assert snapshot_view(snap, '1')[0] is None


def test_corrupt_missing_and_nonstandard_json_snapshots_are_unavailable(tmp_path):
    assert read_snapshot(tmp_path / 'missing.json') is None
    path = tmp_path / 'current.json'
    for text in ['{', 'null', '{"schema_version": NaN}']:
        path.write_text(text, encoding='utf-8')
        assert read_snapshot(path) is None


def test_quality_note_shows_source_dates_issues_and_escapes_source_text():
    from score_view import quality_note
    snap = fixture()
    snap['rows'][1]['raw'].update(source_dates={'annual': '2026-03-31'},
        source_details={'annual': '<script>alert(1)</script>'}, issues=['增长基期亏损'])
    text = quality_note('公司1', snapshot=snap)
    assert '2026-03-31' in text and '增长基期亏损' in text
    assert '<script>' not in text and '&lt;script&gt;' in text
    assert '不混入安全度扣分' in text


def test_quality_links_allow_only_http_and_https_and_details_are_not_json():
    from score_view import quality_note
    snap = fixture()
    snap['rows'][1]['raw'].update(source_urls={'roe': 'https://example.com/report?a=1&b=2',
        'growth': 'javascript:alert(1)', 'pe': 'file:///secret'},
        source_details={'roe': {'report_period': '2025-12-31', 'value': 10.}},
        issues=['growth: missing comparable parent net profit or nonpositive prior-year base'])
    text = quality_note('公司1', snapshot=snap)
    assert 'href="https://example.com/report?a=1&amp;b=2"' in text
    assert 'javascript:' not in text and 'file:///' not in text
    assert '报告期：2025-12-31' in text and '观测值：10.0' in text
    assert '上年同期利润不为正' in text
    assert '{"' not in text
