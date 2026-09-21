from ui_glossary import search_glossary


def test_glossary_searches_definitions_and_prioritizes_exact_acronyms():
    assert '<dt>PE</dt>' in search_glossary(' pe ')
    assert search_glossary(' pe ').index('<dt>PE</dt>') < search_glossary(' pe ').index('<dt>TTM</dt>')
    assert '<dt>成材率</dt>' in search_glossary('1.25')
    assert '没有匹配' in search_glossary('<script>alert(1)</script>')
    assert '<script>' not in search_glossary('<script>alert(1)</script>')


def test_overview_preserves_losses_and_missing_values_in_yuan_statements():
    from profit_ui import financial_overview
    result = financial_overview({'statement': {'OPERATE_INCOME': 1_200_000_000,
                                              'PARENT_NETPROFIT': -123_000_000}})
    assert '| 12.00 | 未披露 | -1.23 |' in result
    assert '累计值' in result
    assert '未披露' in financial_overview({'statement': {'OPERATE_INCOME': float('nan')}})
