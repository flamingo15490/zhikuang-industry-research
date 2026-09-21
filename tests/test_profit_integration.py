from types import SimpleNamespace


def test_report_uses_company_profit_analysis_and_does_not_call_aluminum_for_processing(monkeypatch, tmp_path):
    import report
    import webui
    import report_context
    import pandas as pd
    analysis = {'code': 'sh.600219', 'name': '南山铝业', 'summary': '板带与型材利润',
                'bridge': {}, 'business_types': ['processing']}
    calls = []
    monkeypatch.setattr(report, '_resolve_stock', lambda query: ('南山铝业', 'sh.600219'))
    monkeypatch.setattr(report, '_subindustry', lambda code: 'aluminum')
    monkeypatch.setattr(report, '_top_metals', lambda code: [])
    monkeypatch.setattr(report, 'execute_tool', lambda name, args: calls.append(name) or '数据')
    context = dict(run_id='integration', created_at='2026-09-06', name='南山铝业',code='sh.600219',
        snapshot=dict(batch_id='test', as_of='2026-09-06', financial_period='2025-12-31'),
        target={'raw':{}, 'scores':{}}, profit=analysis, macro=pd.DataFrame(), warnings=[])
    monkeypatch.setattr(report_context, 'build_context', lambda name,code: context)
    save = report_context.save_context
    monkeypatch.setattr(report_context, 'save_context', lambda context: save(context, tmp_path))
    monkeypatch.setattr(report, 'format_profit_summary', lambda data: data['summary'], raising=False)
    monkeypatch.setattr(report, 'load_llm_config', lambda: SimpleNamespace(model='test'))
    prompts = []
    def create(**kwargs):
        prompts.append(kwargs['messages'][-1]['content'])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='## 估值\n已完成'))])
    monkeypatch.setattr(report, 'create_llm_client', lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    monkeypatch.setattr(report, 'draw_macro_cycle', lambda frame: None)
    monkeypatch.setattr(report_context, 'radar_view', lambda context: (None, '', ''))
    result = list(report.generate_report_iter('南山铝业'))[-1]
    assert result.get('profit_analysis') is analysis
    assert 'get_aluminum_profit' not in calls
    assert not calls
    assert '板带与型材利润' in prompts[0]
    monkeypatch.setattr(webui, 'generate_report_iter', lambda query: iter([result]))
    output = list(webui.report_fn('南山铝业'))[-1]
    assert len(output) == 12
    assert output[8] is analysis
