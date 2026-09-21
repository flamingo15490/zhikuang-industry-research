"""Deterministic operating scenarios; never estimates of company net income."""
from __future__ import annotations

from datetime import date
import math
import json
from pathlib import Path

import pandas as pd

METAL = Path(__file__).resolve().parent.parent / "data" / "metal_prices.parquet"
POUNDS_PER_TONNE = 2204.6226218488


def _field(key, label, unit, *, signed=False, ratio=False, positive=False, default=None):
    field = {"key": key, "label": label, "unit": unit, "required": default is None,
             "min": None if signed else 0, "max": 1 if ratio else None,
             "exclusive_min": positive or ratio}
    if default is not None:
        field["default"] = default
    return field


def _model(label, formula, unit, fields, axes, assumptions):
    return {"label": label, "formula": formula, "unit": unit, "fields": fields,
            "axes": axes, "assumptions": assumptions}


MODELS = {
    "mining": _model("矿山采选", "实现售价 - 采选成本 - 运输销售成本 - 资源税费 + 副产品抵扣",
        "元/吨可售金属", [
            _field("price", "实现售价", "元/吨可售金属"),
            _field("mining_cost", "采选成本（未抵扣副产品）", "元/吨可售金属"),
            _field("transport_cost", "运输销售成本", "元/吨可售金属"),
            _field("resource_tax", "资源税费金额", "元/吨可售金属"),
            _field("byproduct_credit", "未含在成本中的副产品净抵扣", "元/吨可售金属", signed=True, default=0),
        ], ["price", "mining_cost"], ["全部价格和成本必须按同一可售金属吨计量；不接受吨矿成本直接输入。",
            "采选成本范围由输入者确认；AISC、现金成本不可混用，已含副产品抵扣时额外抵扣应为零。"]),
    "smelting": _model("外购精矿冶炼", "[TC + RC×2204.6226218488×干矿品位×计价比例]×汇率÷(品位×回收率) + 副产品 - 转换成本",
        "元/吨回收金属", [
            _field("tc", "TC处理费", "美元/干吨精矿", signed=True),
            _field("rc", "RC精炼费", "美元/磅计价金属", signed=True),
            _field("exchange_rate", "美元兑人民币汇率", "元/美元", positive=True),
            _field("grade", "干精矿金属品位", "质量比例（0至1）", ratio=True),
            _field("recovery", "金属回收率", "比例（0至1）", ratio=True),
            _field("payable_fraction", "含量金属计价比例", "比例（0至1）", ratio=True),
            _field("conversion_cost", "冶炼转换成本", "元/吨回收金属"),
            _field("byproduct_credit", "副产品净收益", "元/吨回收金属", signed=True, default=0),
        ], ["tc", "conversion_cost"], ["固定干基精矿；湿吨须先按水分折干。RC按美元/磅输入，美分/磅须除以100。",
            "TC按干吨、RC按计价金属量收费，统一折算为每吨回收金属；不包含精矿买卖价差。"]),
    "aluminum": _model("电解铝", "铝价 - 氧化铝价×氧化铝单耗 - 电耗×电价 - 阳极辅料及其他成本",
        "元/吨铝", [
            _field("price", "铝实现售价", "元/吨铝"),
            _field("alumina_price", "氧化铝价格", "元/吨氧化铝"),
            _field("alumina_consumption", "氧化铝单耗", "吨氧化铝/吨铝", positive=True),
            _field("power_consumption", "电力单耗", "千瓦时/吨铝", positive=True),
            _field("electricity_price", "电价", "元/千瓦时"),
            _field("other_cost", "阳极辅料、折旧及已纳入其他成本", "元/吨铝"),
        ], ["price", "alumina_price"], ["行业参考价格与经验单耗仅作假设，不能替代公司实际成本。"]),
    "processing": _model("金属加工及功能材料", "加工费 - 转换成本 - 原料价×(1÷成材率 - 1)",
        "元/吨成品", [
            _field("processing_fee", "实现加工费（或售价减一吨原料价格）", "元/吨成品", signed=True),
            _field("raw_price", "同规格原料价格", "元/吨原料"),
            _field("yield_rate", "成材率", "吨成品/吨原料（0至1）", ratio=True),
            _field("conversion_cost", "加工转换成本", "元/吨成品"),
        ], ["processing_fee", "conversion_cost"], ["以一吨同金属原料计价基础的加工费为输入；额外损耗单列，假设损耗无残值。"]),
    "refining": _model("化合物与分离加工", "产品售价 + 副产品 - 产品有效含量÷(原料品位×回收率)×原料价 - 转换成本",
        "元/吨产品", [
            _field("price", "产品实现售价", "元/吨产品"),
            _field("product_content", "产品中目标元素有效含量（含纯度影响）", "吨目标元素/吨产品", ratio=True),
            _field("feed_grade", "干原料目标元素品位", "吨目标元素/干吨原料", ratio=True),
            _field("recovery", "目标元素回收率", "比例（0至1）", ratio=True),
            _field("feed_price", "干基原料采购成本", "元/干吨原料"),
            _field("conversion_cost", "分离及化合转换成本", "元/吨产品"),
            _field("byproduct_credit", "副产品净收益", "元/吨产品", signed=True, default=0),
        ], ["price", "feed_price"], ["原料与产品必须用同一目标元素质量衡算；氧化物当量须先换算为元素含量。",
            "采用外购原料成本口径；自产原料不可与外购口径直接合并。"]),
    "recycling": _model("再生回收", "产品价格×原料品位×回收率 + 服务费 - 废料成本 - 分选冶炼成本 - 环保成本",
        "元/干吨废料", [
            _field("product_price", "回收目标金属售价", "元/吨回收金属"),
            _field("grade", "干废料目标金属品位", "吨目标金属/干吨废料", ratio=True),
            _field("recovery", "金属回收率", "比例（0至1）", ratio=True),
            _field("service_fee", "处理服务费", "元/干吨废料"),
            _field("feed_cost", "废料采购成本", "元/干吨废料"),
            _field("processing_cost", "分选冶炼成本", "元/干吨废料"),
            _field("environmental_cost", "环保处置成本", "元/干吨废料"),
        ], ["product_price", "feed_cost"], ["按干吨废料输入，单一目标金属回收口径；多金属须分别核实收入且不得重复计入共同成本。"]),
    "trading": _model("贸易与供应链", "销售收入 - 采购成本 - 物流仓储 - 融资及套保相关净成本",
        "元/笔同口径交易", [
            _field("sales", "销售收入", "元/笔交易"),
            _field("purchase", "采购成本", "元/笔交易"),
            _field("logistics", "物流仓储成本", "元/笔交易"),
            _field("financing_hedging_cost", "融资及套保净成本（净收益为负）", "元/笔交易", signed=True),
        ], ["sales", "purchase"], ["购销、融资和套保须为同一批次、币种、期间及税务口径。"]),
}


def _get_model(model):
    if model not in MODELS:
        raise ValueError(f"未知经营情景模型：{model}")
    return MODELS[model]


def calculate_scenario(model: str, values: dict) -> dict:
    """Calculate one explicitly unit-bound scenario from complete numeric inputs."""
    spec = _get_model(model)
    allowed = {field["key"] for field in spec["fields"]}
    unknown = set(values) - allowed
    if unknown:
        raise ValueError("不支持的参数或计量口径：" + "、".join(sorted(unknown)))
    inputs = {}
    assumptions = list(spec["assumptions"])
    for field in spec["fields"]:
        key = field["key"]
        raw = values.get(key)
        if raw is None or isinstance(raw, str) and not raw.strip():
            if field["required"]:
                raise ValueError(f"缺少必填参数：{field['label']}（{field['unit']}）")
            raw = field["default"]
            assumptions.append(f"{field['label']}缺省按{raw}计，属于显式假设。")
        try:
            if isinstance(raw, bool):
                raise ValueError
            number = float(raw)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{field['label']}必须为有限数值") from exc
        if not math.isfinite(number):
            raise ValueError(f"{field['label']}必须为有限数值")
        minimum, maximum = field["min"], field["max"]
        if minimum is not None and (number < minimum or field["exclusive_min"] and number == minimum):
            relation = "大于" if field["exclusive_min"] else "不小于"
            raise ValueError(f"{field['label']}必须{relation}{minimum}")
        if maximum is not None and number > maximum:
            raise ValueError(f"{field['label']}不得大于{maximum}；比例按0至1输入")
        inputs[key] = number
    v = inputs
    if model == "mining":
        components = [("实现售价", v["price"]), ("采选成本", -v["mining_cost"]),
                      ("运输销售成本", -v["transport_cost"]), ("资源税费", -v["resource_tax"]),
                      ("副产品净抵扣", v["byproduct_credit"])]
    elif model == "smelting":
        recovered = v["grade"] * v["recovery"]
        if recovered == 0:
            raise ValueError("品位与回收率乘积过小，无法进行有限数值换算")
        components = [("TC收入", v["tc"] * v["exchange_rate"] / recovered),
                      ("RC收入", v["rc"] * POUNDS_PER_TONNE * v["payable_fraction"] * v["exchange_rate"] / v["recovery"]),
                      ("副产品净收益", v["byproduct_credit"]), ("转换成本", -v["conversion_cost"])]
    elif model == "aluminum":
        components = [("铝实现售价", v["price"]), ("氧化铝成本", -v["alumina_price"] * v["alumina_consumption"]),
                      ("电力成本", -v["power_consumption"] * v["electricity_price"]), ("阳极辅料及其他成本", -v["other_cost"])]
    elif model == "processing":
        components = [("实现加工费", v["processing_fee"]), ("加工转换成本", -v["conversion_cost"]),
                      ("原料损耗成本", -v["raw_price"] * (1 / v["yield_rate"] - 1))]
    elif model == "refining":
        recovered = v["feed_grade"] * v["recovery"]
        if recovered == 0:
            raise ValueError("品位与回收率乘积过小，无法进行有限数值换算")
        components = [("产品实现售价", v["price"]), ("副产品净收益", v["byproduct_credit"]),
                      ("原料消耗成本", -v["product_content"] / recovered * v["feed_price"]), ("转换成本", -v["conversion_cost"])]
    elif model == "recycling":
        components = [("回收金属销售额", v["product_price"] * v["grade"] * v["recovery"]),
                      ("处理服务费", v["service_fee"]), ("废料采购成本", -v["feed_cost"]),
                      ("分选冶炼成本", -v["processing_cost"]), ("环保处置成本", -v["environmental_cost"])]
    else:
        components = [("销售收入", v["sales"]), ("采购成本", -v["purchase"]),
                      ("物流仓储", -v["logistics"]), ("融资及套保净成本", -v["financing_hedging_cost"])]
    total = sum(amount for _, amount in components)
    if not all(math.isfinite(amount) for _, amount in components) or not math.isfinite(total):
        raise ValueError("计算结果超出有限数值范围，请检查参数及计量单位")
    return {"model": model, "label": spec["label"], "formula": spec["formula"], "unit": spec["unit"],
            "labels": [label for label, _ in components] + ["假设经营利润/贡献"],
            "values": [amount for _, amount in components] + [0],
            "measures": ["relative"] * len(components) + ["total"], "total": total,
            "inputs": inputs, "assumptions": assumptions, "status": "scenario",
            "warning": "假设测算，仅为上述成本边界内的经营利润或贡献，不代表公司归母净利润。"}


def scenario_defaults(model: str) -> dict:
    """Return explicit industry assumptions separately from company observations."""
    spec = _get_model(model)
    values = {f["key"]: f.get("default") for f in spec["fields"]}
    statuses = {key: "missing" if value is None else "assumption" for key, value in values.items()}
    sources = {key: "待输入，未取得公司同口径参数" if value is None else "假设：副产品额外净收益为零"
               for key, value in values.items()}
    if model == "aluminum":
        for key, value in {"alumina_consumption": 1.93, "power_consumption": 13500,
                           "electricity_price": .45, "other_cost": 2500}.items():
            values[key], statuses[key] = value, "assumption"
            sources[key] = "既有电解铝行业经验假设；非公司披露成本"
        try:
            prices = pd.read_parquet(METAL)
            prices["date"] = pd.to_datetime(prices["date"], errors="coerce")
            prices = prices.loc[prices["date"].dt.date <= date.today()].sort_values("date")
            prices = prices.dropna(subset=["date", "aluminum", "alumina"])
            if not prices.empty:
                row = prices.iloc[-1]
                for key, column, label in [("price", "aluminum", "沪铝期货"), ("alumina_price", "alumina", "氧化铝期货")]:
                    number = float(row[column])
                    if math.isfinite(number) and number > 0:
                        values[key], statuses[key] = number, "industry_price"
                        sources[key] = f"{METAL.name}：{label} {row['date'].date()}，行业报价，非公司实现售价"
        except (OSError, ValueError, KeyError, TypeError, ImportError):
            pass
    return {"values": values, "sources": sources, "statuses": statuses,
            "assumptions": list(spec["assumptions"]) + ["全部参数需统一币种、计量单位及含税/不含税口径。"]}


def calculate_profit_scenario(model: str, values: dict) -> str:
    return json.dumps(calculate_scenario(model, values), ensure_ascii=False, allow_nan=False)


PROFIT_SCENARIO_TOOL = {
    'type': 'function', 'function': {
        'name': 'calculate_profit_scenario',
        'description': '按明确给定参数计算单位经营情景，不是公司归母净利润。不得编造缺少的公司参数。各模型输入：' +
            '; '.join(key + '(' + spec['label'] + '): ' + ', '.join(f["key"] + '[' + f['unit'] + ']' for f in spec['fields'])
                      for key, spec in MODELS.items()),
        'parameters': {'type': 'object', 'properties': {
            'model': {'type': 'string', 'enum': list(MODELS)},
            'values': {'type': 'object', 'additionalProperties': {'type': 'number'},
                       'description': '模型对应的参数字典；比例按0至1输入，缺参数交由工具报错，不补造。'}},
            'required': ['model', 'values']}}}
