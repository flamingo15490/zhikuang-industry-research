import json
import math

import pytest

from scoring import score_observation


BASE = dict(roe=10., growth=0., pe=15., ma5=10., ma20=10., ma60=10.,
            dif=0., dea=0., rsi=40., return20=0., flow_ratio_pct=0.,
            debt=60., current=1.)
FUND = '\u57fa\u672c\u9762'
VALUE = '\u4f30\u503c'
TECH = '\u6280\u672f\u9762'
FLOW = '\u8d44\u91d1\u9762'
SAFETY = '\u5b89\u5168\u5ea6'


def test_complete_observation_uses_equal_dimension_weights():
    result = score_observation(BASE)
    assert result['version'] == '2.0'
    assert result['scores'] == {FUND: 71., VALUE: 60., TECH: 50., FLOW: 50., SAFETY: 58.}
    assert result['composite'] == pytest.approx(57.8)
    assert result['coverage'] == 1.
    assert result['eligible'] is True


def test_empty_input_has_no_default_score_or_rank():
    result = score_observation({})
    assert all(value is None for value in result['scores'].values())
    assert all(dim['status'] == 'missing' for dim in result['dimensions'].values())
    assert result['coverage'] == 0
    assert result['composite'] is None
    assert result['eligible'] is False


@pytest.mark.parametrize('key,dimensions', [
    ('roe', [FUND]), ('growth', [FUND, SAFETY]), ('pe', [VALUE]),
    ('ma5', [TECH]), ('ma20', [TECH]), ('ma60', [TECH]), ('dif', [TECH]),
    ('dea', [TECH]), ('rsi', [TECH]), ('return20', [TECH]),
    ('flow_ratio_pct', [FLOW]), ('debt', [SAFETY]), ('current', [SAFETY]),
])
def test_every_required_input_blocks_its_dimension_and_composite(key, dimensions):
    result = score_observation({**BASE, key: None})
    for dimension in dimensions:
        assert result['scores'][dimension] is None
        assert key in result['dimensions'][dimension]['missing']
    assert result['coverage'] == (5 - len(dimensions)) / 5
    assert result['composite'] is None
    assert not result['eligible']


@pytest.mark.parametrize('value', [math.nan, math.inf, -math.inf, True, False, '10'])
def test_nonfinite_boolean_and_text_inputs_are_missing_and_json_safe(value):
    result = score_observation({**BASE, 'roe': value})
    assert result['dimensions'][FUND]['status'] == 'missing'
    assert result['dimensions'][FUND]['metrics'][0]['value'] is None
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize('pe', [-10., 0.])
def test_nonpositive_pe_is_not_applicable_not_a_high_score(pe):
    result = score_observation({**BASE, 'pe': pe})
    assert result['dimensions'][VALUE]['status'] == 'not_applicable'
    assert result['scores'][VALUE] is None
    assert result['dimensions'][VALUE]['missing'] == []
    assert result['coverage'] == .8
    assert result['composite'] is None


@pytest.mark.parametrize('pe,expected', [(9.99, 90), (10, 75), (15, 60), (20, 45), (30, 30)])
def test_positive_pe_exact_boundaries(pe, expected):
    assert score_observation({**BASE, 'pe': pe})['scores'][VALUE] == expected


@pytest.mark.parametrize('roe,expected', [(-1, 15), (0, 29), (4.99, 43), (5, 57), (10, 71), (15, 85)])
def test_roe_absolute_boundaries_without_peer_median(roe, expected):
    assert score_observation({**BASE, 'roe': roe})['scores'][FUND] == expected


@pytest.mark.parametrize('growth,expected', [(-20.01, 59), (-20, 65), (-.01, 65), (0, 71), (.01, 77), (20, 83)])
def test_growth_zero_is_neutral_and_negative_growth_is_not_rewarded(growth, expected):
    assert score_observation({**BASE, 'growth': growth})['scores'][FUND] == expected


@pytest.mark.parametrize('changes,expected', [
    ({'ma5': 12., 'ma20': 11.}, 65),
    ({'ma5': 8., 'ma20': 9.}, 35),
    ({'ma5': 11., 'ma20': 11.}, 50),
    ({'dif': 1.}, 60), ({'dif': -1.}, 40),
    ({'rsi': 50.}, 55), ({'rsi': 60.}, 50),
    ({'rsi': 30.}, 50), ({'rsi': 70.}, 50),
    ({'rsi': 29.}, 45), ({'rsi': 71.}, 45),
    ({'return20': 1.}, 60), ({'return20': -1.}, 40),
])
def test_technical_each_signal_has_visible_effect_and_neutral_equalities(changes, expected):
    dimension = score_observation({**BASE, **changes})['dimensions'][TECH]
    assert dimension['score'] == expected
    assert 50 + sum(metric.get('delta', 0.) for metric in dimension['metrics']) == expected


def test_fund_flow_scale_invariance_and_zero_neutrality():
    small = 100. * 2 / 100
    large = 100. * 20000 / 1000000
    assert score_observation({**BASE, 'flow_ratio_pct': small})['scores'][FLOW] == 58.
    assert score_observation({**BASE, 'flow_ratio_pct': large})['scores'][FLOW] == 58.
    assert score_observation(BASE)['scores'][FLOW] == 50.
    assert score_observation({**BASE, 'flow_ratio_pct': -2.})['scores'][FLOW] == 42.
    assert score_observation({**BASE, 'flow_ratio_pct': 100.})['scores'][FLOW] == 90.
    assert score_observation({**BASE, 'flow_ratio_pct': -100.})['scores'][FLOW] == 10.


@pytest.mark.parametrize('changes,expected', [
    ({'debt': 39.9}, 66), ({'debt': 40.}, 58), ({'debt': 70.}, 50),
    ({'debt': 70.1}, 38), ({'current': .99}, 49), ({'current': 2.}, 70),
])
def test_safety_financial_boundaries(changes, expected):
    assert score_observation({**BASE, **changes})['scores'][SAFETY] == expected


def test_disclosure_quality_and_absolute_flow_do_not_change_scores_or_break_ties():
    first = score_observation({**BASE, 'metal_quality': 'clean', 'flow_total': 10})
    second = score_observation({**BASE, 'metal_quality': 'merged', 'flow_total': 10000})
    assert first == second


@pytest.mark.parametrize('key,value,dimension', [
    ('ma5', 0, TECH), ('ma60', -1, TECH), ('rsi', 101, TECH),
    ('rsi', -1, TECH), ('current', -1, SAFETY), ('debt', -1, SAFETY),
])
def test_impossible_domains_are_missing(key, value, dimension):
    result = score_observation({**BASE, key: value})
    assert result['dimensions'][dimension]['status'] == 'missing'
    assert key in result['dimensions'][dimension]['missing']


def test_result_is_deterministic_does_not_mutate_input_and_explains_every_input():
    raw = dict(BASE)
    result = score_observation(raw)
    assert raw == BASE
    assert score_observation(raw) == result
    observed = set()
    for dimension in result['dimensions'].values():
        assert dimension['reason']
        assert dimension['missing'] == []
        for metric in dimension['metrics']:
            observed.add(metric['key'])
            assert metric['unit']
            assert metric['rule']
    assert observed == set(BASE)
