"""Single-company adapter for the shared fixed-volume revenue shock model."""
from tools.sensitivity_core import METAL_ALIASES, analyze_sensitivity

PRICE_SENSITIVITY_TOOL = {
    'type': 'function',
    'function': {
        'name': 'estimate_price_sensitivity',
        'description': ('按同期间独立金属分部收入，测算固定销量、产品实现售价同比例变化下的收入变化近似。'
                        '不是公司净利润预测；合并、未知或跨期占比不计算。价格冲击如-20表示下跌20%。'),
        'parameters': {'type': 'object', 'properties': {
            'query': {'type': 'string', 'description': '股票代码或名称'},
            'metal': {'type': 'string', 'description': '金属名，如gold、copper、黄金、铜'},
            'price_change_pct': {'type': 'number', 'description': '价格变化百分比，如-20'}},
            'required': ['query', 'metal', 'price_change_pct']},
    },
}


def estimate_price_sensitivity(query: str, metal: str, price_change_pct: float) -> str:
    result = analyze_sensitivity(query, metal, price_change_pct)
    title = f'{result["name"] or query}：固定销量收入变化近似'
    if result['status'] != 'applicable':
        return title + '（无法计算）\n' + '\n'.join(result['warnings'])
    period = result['period']
    scope = {'03': '一季度累计', '06': '半年累计', '09': '前三季度累计', '12': '全年累计'}.get(period[5:7], '报告期累计')
    lines = [title,
        f'- 报告期 {period}（{scope}）；金属 {result["metal"]}，价格冲击 {result["price_change_pct"]:+.1f}%。',
        f'- 独立披露的相关产品收入 {result["metal_revenue_yuan"] / 1e8:.2f} 亿元，占同期间营业收入 {result["share"]:.1%}。',
        f'- 收入变化近似 {result["amount_yuan"] / 1e8:+.2f} 亿元。']
    if result['percentage'] is not None:
        lines.append(f'- 该收入变化额 / 正归母净利润 = {result["percentage"]:+.1f}%，仅作量级比较，不是净利润变动率。')
        lines.append(f'- 每1%实现售价冲击对应的收入变化额 / 正归母净利润 = {result["one_percent_comparator"]:.1f}%。')
    lines.extend('- ' + value for value in result['assumptions'] + result['warnings'])
    return '\n'.join(lines)
