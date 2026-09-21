"""Legacy entry point for an explicit industry aluminum scenario reference."""
from __future__ import annotations

from datetime import date
import math
from pathlib import Path

import pandas as pd

from tools.profit_scenarios import calculate_scenario, scenario_defaults

BASE = Path(__file__).resolve().parent.parent
METAL = BASE / 'data/metal_prices.parquet'

ALUMINUM_PROFIT_TOOL = {
    'type': 'function',
    'function': {
        'name': 'get_aluminum_profit',
        'description': ('电解铝行业假设参考：以最新可用沪铝/氧化铝期货报价与明确经验成本假设计算单位经营贡献。'
                        '不是公司披露利润，也不能据此判断整家公司真实盈利或归母净利润。'
                        '电价参数单位元/千瓦时，默认0.45为行业假设。'),
        'parameters': {'type': 'object', 'properties': {
            'electricity_price': {'type': 'number', 'description': '假设电价（元/千瓦时），默认0.45，须有限且非负'}},
            'required': []},
    },
}


def get_aluminum_profit(electricity_price: float = 0.45) -> str:
    try:
        if isinstance(electricity_price, bool):
            raise ValueError
        electricity = float(electricity_price)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError('电价必须是有限非负数值') from exc
    if not math.isfinite(electricity) or electricity < 0:
        raise ValueError('电价必须是有限非负数值')
    if not METAL.exists():
        return '错误：金属价格缓存缺失。'
    try:
        prices = pd.read_parquet(METAL)
        prices['date'] = pd.to_datetime(prices['date'], errors='coerce')
        for field in ('aluminum', 'alumina'):
            prices[field] = pd.to_numeric(prices[field], errors='coerce')
        prices = prices[prices['date'].notna() & (prices['date'].dt.date <= date.today())]
        for field in ('aluminum', 'alumina'):
            prices = prices[prices[field].map(lambda value: math.isfinite(value) and value > 0)]
        prices = prices.sort_values('date')
    except (OSError, ValueError, KeyError) as exc:
        return f'错误：价格缓存不可用：{type(exc).__name__}'
    if prices.empty:
        return '错误：没有截至当前日期有效且同日的铝与氧化铝价格。'
    row = prices.iloc[-1]
    defaults = scenario_defaults('aluminum')
    values = dict(defaults['values'], price=float(row['aluminum']), alumina_price=float(row['alumina']),
                  electricity_price=electricity)
    result = calculate_scenario('aluminum', values)
    lines = [f'【电解铝行业假设参考】报价日 {row["date"].date()}，非公司披露或预测利润。',
        f'- 来源：{METAL.name}中的沪铝与氧化铝连续期货报价；非公司实现售价。',
        f'- 铝价 {values["price"]:.0f} 元/吨；氧化铝价 {values["alumina_price"]:.0f} 元/吨。',
        f'- 经验单耗假设：氧化铝 {values["alumina_consumption"]} 吨/吨铝，电力 {values["power_consumption"]:.0f} 千瓦时/吨铝。',
        f'- 电价假设 {electricity:.4f} 元/千瓦时；阳极辅料及已纳入其他成本假设 {values["other_cost"]:.0f} 元/吨铝。',
        f'- 假设经营贡献 {result["total"]:.0f} 元/吨铝，仅覆盖上述成本边界。',
        '- 未取得公司同口径产销量、税费、少数股东等参数，不转换公司归母净利润。',
        '- 是否适用于具体业务须核验电解铝经营披露；含铝收入不能证明整家公司适用。',
        '- 全部参数须统一币种、计量单位及含税/不含税口径；经验参数不是公司实际成本。']
    return '\n'.join(lines)
