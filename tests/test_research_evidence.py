import json
from research_evidence import build_evidence, evidence_html, save_research_run


def analysis():
    return {'code':'sh.600219', 'name':'测试', 'period':'2026-06-30', 'notice_date':None,
            'source':{'url':'https://example.com/data?token=private&date=2026'},
            'statement':{'OPERATE_INCOME':100, 'OPERATE_COST':120, 'PARENT_NETPROFIT':-30}}


def test_derived_amount_has_real_input_references():
    rows = build_evidence(analysis())
    gross = next(r for r in rows if r['metric']=='毛利')
    assert gross['value'] == -20
    assert gross['source_kind'] == 'derived'
    assert set(gross['input_ids']) <= {r['evidence_id'] for r in rows}
    assert gross['notice_date'] is None
    assert 'private' not in json.dumps(rows)
    assert rows == build_evidence(analysis())


def test_export_whitelists_metadata_and_records_real_values(tmp_path):
    folder = save_research_run({'analysis':analysis(), 'api_key':'never-export'}, tmp_path)
    text=(folder/'evidence.json').read_text(encoding='utf-8')
    assert 'never-export' not in text and 'private' not in text
    assert json.loads(text)['evidence']
    assert '-30' in (folder/'report.md').read_text(encoding='utf-8')


def test_missing_values_not_fabricated_and_html_escaped():
    data=analysis()
    data['statement']['OPERATE_COST']=None
    assert not any(r['metric']=='毛利' for r in build_evidence(data))
    rows=build_evidence(data)
    rows[0]['metric']='<img src=x onerror=alert(1)>'
    assert '<img' not in evidence_html(rows)


def test_evidence_only_labels_known_monetary_fields_as_yuan():
    data = analysis()
    data['statement'].update(BASIC_EPS=1.473, BASIC_EPS_YOY=67.95,
                             OPERATE_INCOME_YOY=12.3, SECURITY_CODE=600219,
                             SALE_EXPENSE=7, ASSET_IMPAIRMENT_LOSS=2)
    rows = build_evidence(data)
    assert not any(r['metric'] in {'BASIC_EPS', 'BASIC_EPS_YOY',
                                   'OPERATE_INCOME_YOY', 'SECURITY_CODE'} for r in rows)
    assert any(r['metric'] == '销售费用' and r['value'] == 7 for r in rows)
    assert any(r['value'] == 2 and r['unit'] == '元' for r in rows)
