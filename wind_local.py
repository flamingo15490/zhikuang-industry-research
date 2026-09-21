"""Local-only Wind supplement; never a model input or scoring snapshot.

Run: python wind_local.py --market sheet1.csv --financial sheet2.xlsx
No raw values are written outside ignored data/wind_import/.
"""
from __future__ import annotations

import csv
from datetime import date, datetime
from hashlib import sha256
from html import escape
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
STORE = ROOT / 'data/wind_import/local_supplement.json'


def number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(str(value).replace(',', '').strip())
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def identity(value):
    match = re.search(r'(\d{6})\.(SH|SZ|BJ)', str(value), re.I)
    if not match:
        raise ValueError('证券代码缺失或格式不支持')
    return match[2].lower() + '.' + match[1], str(value).splitlines()[0].strip()


def day(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    return date.fromisoformat('-'.join(f'{int(part):02d}' for part in str(value).split('/'))).isoformat()


def subtract(a, b):
    return a - b if a is not None and b is not None else None


def divide(a, b, factor=1):
    return a / b * factor if a is not None and b is not None and b > 0 else None


FIELDS = {
    'assets': '资产总计', 'liabilities': '负债合计', 'current_assets': '流动资产合计',
    'current_liabilities': '流动负债合计', 'revenue': '营业收入', 'cost': '营业成本',
    'total_profit': '利润总额', 'net_profit': '净利润', 'minority': '少数股东损益',
}


def financial_records(rows, cutoff):
    header, *body = rows
    columns = {}
    for key, label in FIELDS.items():
        matches = [i for i, text in enumerate(header) if str(text).split('\n')[0] == label
                   and '[单位] 元' in str(text) and '合并报表' in str(text)]
        if len(matches) != 1:
            raise ValueError('财务表字段或合并金额单位不匹配：' + label)
        columns[key] = matches[0]
    result, skipped, seen = [], 0, set()
    for row in body:
        if not any(v is not None and str(v).strip() for v in row):
            continue
        code, name = identity(row[0])
        period = day(row[1])
        if period > cutoff or period[5:] not in ('03-31', '06-30', '09-30', '12-31'):
            skipped += 1
            continue
        if (code, period) in seen:
            raise ValueError('财务表存在重复公司报告期，未导入')
        seen.add((code, period))
        values = {key: number(row[index]) for key, index in columns.items()}
        values.update(parent_profit=subtract(values['net_profit'], values['minority']),
                      tax_difference=subtract(values['total_profit'], values['net_profit']),
                      gross_profit=subtract(values['revenue'], values['cost']),
                      debt_pct=divide(values['liabilities'], values['assets'], 100),
                      current_ratio=divide(values['current_assets'], values['current_liabilities']),
                      weighted_roe=None)
        result.append(dict(code=code, name=name, period=period, values=values,
                           announcement_date=None, cumulative_verified=False))
    index = {(r['code'], r['period']): r for r in result}
    for row in result:
        period = row['period']
        prior = index.get((row['code'], str(int(period[:4])-1)+period[4:]))
        base = prior['values']['parent_profit'] if prior else None
        # Only annual observations: cumulative/interim export setting is unknown.
        row['values']['annual_growth_pct'] = divide(
            subtract(row['values']['parent_profit'], base), base, 100) if period.endswith('12-31') else None
    return result, skipped


def market_records(rows, cutoff):
    header, *body = rows
    expected = [('前收盘价', '前复权', '[单位] 元'), ('收盘价', '不复权', '[单位] 元'),
                ('成交额', '[单位] 元'), ('成交量', '[单位] 股'), ('停牌原因',), ('市盈率PE(TTM)', '[单位] 倍')]
    if len(header) != 8 or any(not all(part in header[i+2] for part in parts) for i, parts in enumerate(expected)):
        raise ValueError('行情字段、单位或复权口径改变，需重新核验')
    result, skipped, seen, current = [], 0, set(), None
    for row in body:
        if len(row) != 8:
            raise ValueError('行情行列数错误')
        if row[0].strip():
            current = identity(row[0])
        if current is None:
            raise ValueError('行情首行缺证券身份')
        code, name = current
        observed = day(row[1])
        if observed > cutoff:
            skipped += 1
            continue
        if (code, observed) in seen:
            raise ValueError('行情存在重复公司日期，未导入')
        seen.add((code, observed))
        close, amount, volume, pe = (number(row[i]) for i in (3, 4, 5, 7))
        reason = row[6].strip()
        eligible = not reason and all(v is not None and v > 0 for v in (close, amount, volume))
        result.append(dict(code=code, name=name, date=observed,
                           close_unadjusted=close if eligible else None,
                           amount_cny=amount if eligible else None, volume_shares=volume if eligible else None,
                           pe_ttm=pe if eligible else None, suspended_reason=reason,
                           technical=None, qfq_close=None))
    return result, skipped


def import_files(market_path, financial_path, cutoff):
    import openpyxl  # Optional dependency used only during local import.
    cutoff = date.fromisoformat(cutoff).isoformat()
    if cutoff >= date.today().isoformat():
        raise ValueError('请指定已结束的交易日；不导入当天可能未收盘的数据')
    market_path, financial_path = Path(market_path), Path(financial_path)
    with market_path.open(encoding='utf-8-sig', newline='') as stream:
        market, market_skipped = market_records(list(csv.reader(stream)), cutoff)
    workbook = openpyxl.load_workbook(financial_path, read_only=True, data_only=True)
    try:
        financial, financial_skipped = financial_records(list(workbook.worksheets[0].values), cutoff)
    finally:
        workbook.close()
    payload = dict(schema=1, local_only=True, market_cutoff=cutoff, financial=financial, market=market,
                   sources=[dict(file=p.name, sha256=sha256(p.read_bytes()).hexdigest()) for p in (market_path, financial_path)],
                   notes=['Wind本地补充，禁止进入公开包或模型请求', '缺公告日及累计设置，不能用于严格历史评分',
                          '技术指标与加权ROE暂缺；不得移位前收盘价或以摊薄ROE代替',
                          '所得税为利润总额减净利润的差额推导，未采用原始所得税列'])
    STORE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STORE.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    temporary.replace(STORE)
    return dict(companies=len({r['code'] for r in financial}), financial_records=len(financial),
                market_records=len(market), excluded_financial_rows=financial_skipped,
                excluded_market_rows=market_skipped, cutoff=cutoff)


def local_view(query, period='2025-12-31', path=None):
    """Only this local UI reads the supplement. No agent tool or report input."""
    if not str(query or '').strip():
        return '输入公司后，可在这里核对本地补充数据。'
    try:
        payload = json.loads(Path(path or STORE).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return '本地补充数据暂缺，尚未完成导入。'
    q = str(query).strip().lower()
    codes = {r['code'] for r in payload['financial'] if q in (r['code'], r['code'].split('.')[1],
             r['name'].lower(), r['code'].split('.')[1]+'.'+r['code'].split('.')[0])}
    if len(codes) != 1:
        return '未找到唯一公司，请填写完整名称或六位证券代码。'
    code = codes.pop()
    row = next((r for r in payload['financial'] if r['code'] == code and r['period'] == period), None)
    if row is None:
        return '该公司在所选报告期的本地补充数据暂缺。'
    v = row['values']
    def show(value, unit):
        return '暂缺' if value is None else f'{value / 1e8 if unit == "亿元" else value:,.2f} {unit}'
    items = [
        ('归母净利润', 'parent_profit', '亿元', '净利润－少数股东损益'),
        ('所得税差额', 'tax_difference', '亿元', '利润总额－净利润；待财报核验'),
        ('毛利', 'gross_profit', '亿元', '营业收入－营业成本'),
        ('资产负债率', 'debt_pct', '%', '负债合计÷资产总计×100%'),
        ('流动比率', 'current_ratio', '倍', '流动资产÷流动负债'),
        ('年报归母净利润同比', 'annual_growth_pct', '%', '同年度口径比较；上年盈利才计算'),
        ('加权平均ROE', 'weighted_roe', '%', '加权口径无法确认，暂缺'),
    ]
    html = '<h3>' + escape(row['name'] + ' · ' + period) + '</h3>'
    html += '<p>仅本地查阅 · 推导值未写入五维评分、AI研报或导出包。公告日期暂缺；中报、季报累计设置待核实，不年化、不与年报混比。</p>'
    html += '<div style="overflow-x:auto"><table><thead><tr><th>项目</th><th>推导结果</th><th>依据与限制</th></tr></thead><tbody>'
    for label, key, unit, formula in items:
        html += '<tr>' + ''.join('<td>'+escape(text)+'</td>' for text in (label, show(v[key], unit), formula)) + '</tr>'
    html += '</tbody></table></div>'
    market = [r for r in payload['market'] if r['code'] == code]
    if market:
        latest = max(market, key=lambda r:r['date'])
        html += '<p>行情截止 '+escape(latest['date'])+'：未复权收盘价 '+show(latest['close_unadjusted'], '元')+'；PE(TTM) '+show(latest['pe_ttm'], '倍')+'（Wind直接字段）。</p>'
        if latest['suspended_reason']:
            html += '<p>当日停牌：'+escape(latest['suspended_reason'])+'；当日行情暂缺，不以填充值代替成交。</p>'
    return html + '<p>Wind技术指标暂缺：导出字段为前复权“前收盘价”，不能直接计算当日均线、MACD、RSI。缺成本、产量等经营数据仍需逐项查财报。</p>'


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--market', required=True)
    parser.add_argument('--financial', required=True)
    parser.add_argument('--cutoff', required=True)
    args = parser.parse_args()
    print(json.dumps(import_files(args.market, args.financial, args.cutoff), ensure_ascii=False))
