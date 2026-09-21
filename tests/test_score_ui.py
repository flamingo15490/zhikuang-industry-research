from unittest.mock import patch

from score_ui import commit_score, requested_score


def test_score_and_quality_use_one_snapshot():
    snapshot = {'batch_id': 'one'}
    with patch('score_ui.read_snapshot', return_value=snapshot) as read, \
            patch('score_ui.query_view', return_value=(None, 'note', '', [])) as view, \
            patch('score_ui.quality_note', return_value='source') as quality:
        result = requested_score('紫金矿业')
    read.assert_called_once_with()
    view.assert_called_once_with('紫金矿业', snapshot=snapshot)
    quality.assert_called_once_with('紫金矿业', snapshot=snapshot)
    assert commit_score(result, '紫金矿业') == ('note', None, '', [], 'source')


def test_previous_company_cannot_overwrite_current_view():
    result = commit_score({'query': '紫金矿业', 'view': ('old',) * 5}, '南山铝业')
    assert len(result) == 5
    assert all(item == {'__type__': 'update'} for item in result)
