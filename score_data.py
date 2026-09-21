"""Dated observations for scoring v2; missing inputs remain None."""
from __future__ import annotations

import json
import copy
import math
import subprocess
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from tools.technical import _ema_series, _ma, _rsi

BASE = Path(__file__).resolve().parent
FUND = BASE / 'data/nonferrous_fundamentals.parquet'
METRICS = ('roe', 'growth', 'pe', 'ma5', 'ma20', 'ma60', 'dif', 'dea', 'rsi', 'return20', 'flow_ratio_pct', 'debt', 'current')
TECH = ('ma5', 'ma20', 'ma60', 'dif', 'dea', 'rsi', 'return20')


def number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def select_period(frame, period, as_of, period_col, announcement_col):
    if frame.empty or period_col not in frame or announcement_col not in frame:
        return None
    dates = pd.to_datetime(frame[period_col], errors='coerce').dt.strftime('%Y-%m-%d')
    announced = pd.to_datetime(frame[announcement_col], errors='coerce').dt.strftime('%Y-%m-%d')
    selected = frame[(dates == period) & announced.notna() & (announced <= as_of)]
    if selected.empty:
        return None
    return selected.assign(_ann=announced).sort_values('_ann').iloc[-1].to_dict()


def profit_growth(current, previous):
    current, previous = number(current), number(previous)
    return (current / previous - 1) * 100 if current is not None and previous is not None and previous > 0 else None


def clean_kline(rows, as_of):
    found = {}
    for row in rows:
        day = date.fromisoformat(str(row[0])).isoformat()
        if day > as_of:
            continue
        close = number(row[2])
        if close is None or close <= 0:
            raise ValueError('invalid kline close')
        if day in found and list(found[day]) != list(row):
            raise ValueError('conflicting duplicate kline date')
        found[day] = row
    return [found[d] for d in sorted(found)]


def parse_quote(text, as_of):
    fields = text.split('="', 1)[1].split('"', 1)[0].split('~')
    stamp = fields[30]
    if len(stamp) != 14 or not stamp.isdigit():
        raise ValueError('quote missing actual exchange timestamp')
    day = date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8])).isoformat()
    return (number(fields[39]) if day <= as_of else None), day


def normalize_flow(rows, dates, units_verified=False):
    if not units_verified or len(dates) != 5 or len(set(dates)) != 5:
        return None
    selected = [r for r in rows if r.get('date') in dates]
    if len(selected) != 5 or {r['date'] for r in selected} != set(dates):
        return None
    flows = [number(r.get('r0_net')) for r in selected]
    amounts = [number(r.get('amount')) for r in selected]
    if any(v is None for v in flows) or any(v is None or v <= 0 for v in amounts):
        return None
    if any(abs(flow) > amount for flow, amount in zip(flows, amounts)):
        return None
    return sum(flows) / sum(amounts) * 100


def _fetch(url):
    req = Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.sina.com.cn/'})
    with urlopen(req, timeout=12) as response:
        return response.read().decode('gb18030' if any(host in url for host in ('qt.gtimg.cn', 'q.stock.sohu.com')) else 'utf-8')


def _financial_online(code):
    # A process deadline also bounds upstream akshare calls that omit HTTP timeouts.
    program = ('import akshare as ak; import sys; '
               'd=ak.stock_financial_analysis_indicator_em(symbol=sys.argv[1]); '
               'print(d.to_json(orient="records",date_format="iso"))')
    market, digits = code.split('.')
    result = subprocess.run([sys.executable, '-c', program, digits + '.' + market.upper()],
                            capture_output=True, text=True, encoding='utf-8', timeout=25, check=True)
    return pd.DataFrame(json.loads(result.stdout))


def amount_url(code, dates):
    market, digits = code.split('.')
    return 'https://push2his.eastmoney.com/api/qt/stock/kline/get?' + urlencode({
        'fields1': 'f1,f2,f3,f4,f5,f6', 'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
        'ut': '7eea3edcaed734bea9cbfc24409ed989', 'klt': '101', 'fqt': '0',
        'secid': ('1' if market == 'sh' else '0') + '.' + digits,
        'beg': dates[0].replace('-', ''), 'end': dates[-1].replace('-', '')})


def _amount_rows(url):
    payload = json.loads(_fetch(url))
    return [{'date': r[0], 'amount': number(r[6])}
            for r in (s.split(',') for s in payload['data']['klines'])]


def sohu_amount_url(code, dates):
    return 'https://q.stock.sohu.com/hisHq?' + urlencode({'code': 'cn_' + code.split('.')[1],
        'start': dates[0].replace('-', ''), 'end': dates[-1].replace('-', ''),
        'stat': '1', 'order': 'D', 'period': 'd', 'rt': 'json'})


def _sohu_amount_rows(url):
    payload = json.loads(_fetch(url))
    if len(payload) != 1 or payload[0].get('status') != 0:
        raise ValueError('invalid Sohu historical response')
    result = []
    for row in payload[0]['hq']:
        amount = number(row[8])
        result.append({'date': row[0], 'amount': round(amount * 10000, 2) if amount is not None else None,
                       'raw_amount': row[8], 'raw_unit': '10000 CNY', 'raw_row': row})
    return result


def _date_string(value):
    parsed = pd.to_datetime(value, errors='coerce')
    return parsed.strftime('%Y-%m-%d') if pd.notna(parsed) else None


def _financial(raw):
    code, period, as_of = raw['code'], raw['financial_period'], raw['as_of']
    fund = pd.read_parquet(FUND)
    row = select_period(fund[fund.code == code], period, as_of, 'report_period', 'ann_date')
    if row:
        raw['roe'] = number(row.get('roe'))
        raw['source_dates']['roe'] = _date_string(row['ann_date'])
        raw['source_urls']['roe'] = 'https://money.finance.sina.com.cn/corp/go.php/vFD_FinancialGuideLine/stockid/' + code.split('.')[1] + '/displaytype/4.phtml'
        raw['source_details']['roe'] = {'local_file': str(FUND.relative_to(BASE)), 'report_period': period,
                                      'ann_date': _date_string(row['ann_date']), 'cached_value': raw['roe']}
    else:
        raw['issues'].append('roe: specified period with known announcement <= as_of unavailable')
    profit = BASE / f'data/profit_analysis/profit_{code}.parquet'
    if profit.exists():
        frame = pd.read_parquet(profit)
        now = select_period(frame, period, as_of, 'REPORT_DATE', 'NOTICE_DATE')
        previous_period = str(int(period[:4]) - 1) + period[4:]
        previous = select_period(frame, previous_period, as_of, 'REPORT_DATE', 'NOTICE_DATE')
        if now and previous:
            raw['growth'] = profit_growth(now.get('PARENT_NETPROFIT'), previous.get('PARENT_NETPROFIT'))
            raw['source_dates']['growth'] = _date_string(now['NOTICE_DATE'])
            raw['source_urls']['growth'] = now.get('source_url')
            raw['source_details']['growth'] = {'local_file': str(profit.relative_to(BASE)), 'report_period': period,
                'current_profit': number(now.get('PARENT_NETPROFIT')), 'previous_profit': number(previous.get('PARENT_NETPROFIT')),
                'previous_period': previous_period, 'previous_ann_date': _date_string(previous['NOTICE_DATE']), 'unit': 'CNY'}
    if raw['growth'] is None:
        raw['issues'].append('growth: missing comparable parent net profit or nonpositive prior-year base')
    try:
        frame = _financial_online(code)
        row = select_period(frame, period, as_of, 'REPORT_DATE', 'NOTICE_DATE')
        if not row:
            raise ValueError('specified financial period with known announcement unavailable')
        online_roe = number(row.get('ROEJQ'))
        raw['source_details']['roe_verification'] = {'field': 'ROEJQ', 'report_period': period, 'value': online_roe,
                                                    'ann_date': _date_string(row['NOTICE_DATE'])}
        if raw['roe'] is None or online_roe is None or abs(raw['roe'] - online_roe) > 0.015:
            raw['roe'] = None
            raw['issues'].append('roe: legacy cached period cannot be verified against same-period weighted ROE')
        for metric, field in [('debt', 'ZCFZL'), ('current', 'LD')]:
            raw[metric] = number(row.get(field))
            raw['source_dates'][metric] = _date_string(row['NOTICE_DATE'])
            market, digits = code.split('.')
            raw['source_urls'][metric] = 'https://datacenter.eastmoney.com/securities/api/data/get?' + urlencode({
                'type': 'RPT_F10_FINANCE_MAINFINADATA', 'sty': 'APP_F10_MAINFINADATA',
                'filter': f'(SECUCODE="{digits}.{market.upper()}")', 'st': 'REPORT_DATE', 'sr': '-1', 'ps': '200'})
            raw['source_details'][metric] = {'report_period': period, 'ann_date': _date_string(row['NOTICE_DATE']), 'field': field, 'value': raw[metric]}
            if raw[metric] is None:
                raw['issues'].append(metric + ': source field missing')
    except Exception as exc:
        raw['roe'] = None
        raw['issues'].append('roe: same-period verification unavailable')
        raw['issues'].append('financial_online: ' + type(exc).__name__ + ': ' + str(exc)[:200])


def collect_observation(name, code, as_of, financial_period, *, financial_cache=None):
    as_of, financial_period = date.fromisoformat(as_of).isoformat(), date.fromisoformat(financial_period).isoformat()
    raw = {k: None for k in METRICS}
    raw.update(code=code, stock_name=name, as_of=as_of, financial_period=financial_period, market_date=None,
               source_dates={}, source_urls={}, source_units={'roe': '%', 'growth': '%', 'debt': '%', 'current': 'ratio', 'pe': 'multiple'},
               source_details={}, issues=[])
    if financial_cache is not None:
        if any(financial_cache[key] != raw[key] for key in ('code', 'as_of', 'financial_period')):
            raise ValueError('financial cache context mismatch')
        for key in ('roe', 'growth', 'debt', 'current'):
            raw[key] = financial_cache[key]
        for section in ('source_dates', 'source_urls', 'source_units', 'source_details'):
            for key in ('roe', 'growth', 'debt', 'current', 'roe_verification'):
                if key in financial_cache[section]:
                    raw[section][key] = copy.deepcopy(financial_cache[section][key])
        raw['issues'] = [i for i in financial_cache['issues'] if i.split(':', 1)[0] in ('roe', 'growth', 'financial_online', 'financial_local', 'debt', 'current')]
    else:
        try:
            _financial(raw)
        except Exception as exc:
            raw['issues'].append('financial_local: ' + type(exc).__name__ + ': ' + str(exc)[:200])
    sym = code.replace('.', '')
    quote_url = f'https://qt.gtimg.cn/q={sym}'
    kline_url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,,{as_of},160,qfq'
    flow_url = ('https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/'
                f'MoneyFlow.ssl_qsfx_zjlrqs?page=1&num=10&sort=opendate&asc=0&daima={sym}')
    quote_day, trading_dates = None, []
    try:
        pe, quote_day = parse_quote(_fetch(quote_url), as_of)
        raw['source_dates']['pe'] = quote_day
        raw['source_urls']['pe'] = quote_url
        raw['source_details']['pe'] = {'field_index': 39, 'timestamp_field_index': 30, 'observed_pe': pe}
        raw['pe'] = pe
    except Exception as exc:
        raw['issues'].append('quote: ' + type(exc).__name__ + ': ' + str(exc)[:200])
    try:
        node = json.loads(_fetch(kline_url))['data'][sym]
        if not node.get('qfqday'):
            raise ValueError('verified qfqday unavailable; unadjusted day cannot substitute')
        rows = clean_kline(node['qfqday'], as_of)
        trading_dates = [r[0] for r in rows]
        raw['source_details']['technical'] = {'trading_dates': trading_dates, 'close_unit': 'CNY/share', 'adjustment': 'qfq', 'rows': rows,
            'data_field': 'qfqday', 'historical_limit': 'Current provider-adjusted history; date filtering is not a strict historical point-in-time adjustment reconstruction.'}
        raw['source_urls']['technical'] = kline_url
        if not rows:
            raise ValueError('no kline <= as_of')
        day = rows[-1][0]
        raw['market_date'] = day
        raw['source_dates']['technical'] = day
        for key in TECH:
            raw['source_dates'][key] = day
            raw['source_urls'][key] = kline_url
            raw['source_units'][key] = '%' if key == 'return20' else 'index points' if key == 'rsi' else 'CNY/share'
        if len(rows) < 60:
            raise ValueError('fewer than 60 unique trading days')
        closes = [float(r[2]) for r in rows]
        raw.update(ma5=_ma(closes, 5), ma20=_ma(closes, 20), ma60=_ma(closes, 60), rsi=_rsi(closes), return20=(closes[-1]/closes[-21]-1)*100)
        dif = [a-b for a,b in zip(_ema_series(closes,12),_ema_series(closes,26))]
        raw.update(dif=dif[-1], dea=_ema_series(dif,9)[-1])
        if quote_day != day:
            raw['pe'] = None
            raw['issues'].append('pe: quote trading date does not match technical market_date')
        if (date.fromisoformat(as_of) - date.fromisoformat(day)).days > 4:
            raw.update({key: None for key in ('pe', *TECH)})
            raw['issues'].append('market: stale >4 calendar days; market metrics withheld')
    except Exception as exc:
        raw.update({key: None for key in ('pe', *TECH)})
        raw['issues'].append('technical: ' + type(exc).__name__ + ': ' + str(exc)[:200])
    return _collect_flow(raw, trading_dates, flow_url)


def _collect_flow(raw, trading_dates, flow_url, existing_payload=None):
    code, as_of = raw['code'], raw['as_of']
    try:
        payload = existing_payload if existing_payload is not None else json.loads(_fetch(flow_url))
        raw['source_urls']['flow_ratio_pct'] = flow_url
        raw['source_details']['flow_ratio_pct'] = {'raw_rows': payload, 'required_dates': trading_dates[-5:], 'units_verified': False}
        raw['source_units']['flow_ratio_pct'] = {'r0_net': 'CNY (provider convention)', 'amount': 'unverified; normalization withheld'}
        if isinstance(payload, list):
            raw['source_dates']['flow_ratio_pct'] = [row.get('opendate') for row in payload if isinstance(row, dict)]
        dates = trading_dates[-5:]
        if len(dates) != 5 or raw['market_date'] is None or (date.fromisoformat(as_of) - date.fromisoformat(raw['market_date'])).days > 4:
            raise ValueError('five current common trading dates unavailable')
        url = amount_url(code, dates)
        raw['source_urls']['flow_amount'] = url
        try:
            amounts = _amount_rows(url)
            amount_reference = 'https://akshare.akfamily.xyz/data/stock/stock.html'
        except Exception as primary_error:
            raw['source_details']['flow_ratio_pct']['primary_amount_error'] = type(primary_error).__name__ + ': ' + str(primary_error)[:200]
            raw['source_details']['flow_ratio_pct']['primary_amount_url'] = url
            url = sohu_amount_url(code, dates)
            raw['source_urls']['flow_amount'] = url
            amounts = _sohu_amount_rows(url)
            amount_reference = 'http://q.stock.sohu.com/cn/' + code.split('.')[1] + '/lshq.shtml'
            raw['source_details']['flow_ratio_pct']['amount_header'] = '成交金额(万); API hq row index 8; multiply by 10000 to CNY'
        raw['source_details']['flow_ratio_pct']['amount_rows'] = amounts
        raw['source_details']['flow_ratio_pct']['amount_unit_reference'] = amount_reference
        raw['source_units']['flow_ratio_pct'] = {'r0_net': 'CNY', 'amount': 'CNY', 'ratio': '%'}
        if not isinstance(payload, list):
            raise ValueError('invalid Sina flow response')
        rows = []
        for flow in payload:
            day = flow.get('opendate')
            matches = [a for a in amounts if a['date'] == day]
            if day in dates and len(matches) == 1:
                rows.append({'date': day, 'r0_net': number(flow.get('r0_net')), 'amount': matches[0]['amount']})
        raw['flow_ratio_pct'] = normalize_flow(rows, dates, units_verified=True)
        raw['source_details']['flow_ratio_pct']['units_verified'] = True
        raw['source_details']['flow_ratio_pct']['normalized_rows'] = rows
        if raw['flow_ratio_pct'] is None:
            raise ValueError('incomplete/duplicate five-day flow, invalid amount, or absolute net flow exceeds turnover')
        raw['source_dates']['flow_ratio_pct'] = dates[-1]
    except Exception as exc:
        raw['issues'].append('flow_ratio_pct: ' + type(exc).__name__ + ': ' + str(exc)[:200])
    return raw


def retry_observation(prior):
    """Retry the failed flow source without discarding successful dated observations."""
    if all(prior.get(key) is not None for key in TECH):
        raw = copy.deepcopy(prior)
        if raw['flow_ratio_pct'] is not None:
            return raw
        previous_flow = raw['source_details'].get('flow_ratio_pct', {})
        raw['issues'] = [i for i in raw['issues'] if not i.startswith('flow_ratio_pct:')]
        flow_url = raw['source_urls'].get('flow_ratio_pct')
        dates = raw['source_details']['technical']['trading_dates']
        result = _collect_flow(raw, dates, flow_url, previous_flow.get('raw_rows'))
        result['source_details']['flow_ratio_pct']['reused_sina_observation'] = previous_flow.get('raw_rows') is not None
        return result
    return collect_observation(prior['stock_name'], prior['code'], prior['as_of'], prior['financial_period'], financial_cache=prior)
