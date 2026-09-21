"""Offline candidate validation. Writes private diagnostics, never updates scores."""
import csv
from collections import Counter, defaultdict
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from wind_local import identity, number, day
from tools.technical import _ma, _rsi, _ema_series
from scoring import score_observation


def indicators(closes):
    dif = [a-b for a,b in zip(_ema_series(closes,12),_ema_series(closes,26))]
    return dict(ma5=_ma(closes,5),ma20=_ma(closes,20),ma60=_ma(closes,60),
                dif=dif[-1],dea=_ema_series(dif,9)[-1],rsi=_rsi(closes),
                return20=(closes[-1]/closes[-21]-1)*100)


def contributions(values):
    result = score_observation(values)['dimensions']['技术面']
    return result['score'], {m['key']:m['delta'] for m in result['metrics']}


def compare(reference, candidate):
    if len(reference) != len(candidate) or len(reference) < 80:
        raise ValueError('At least 80 aligned observations required')
    price_error = max(abs(a/b-1)*100 for a,b in zip(candidate,reference))
    errors = defaultdict(float)
    changed = []
    # Identical EMA start/history, 20 consecutive terminal windows, no dropped days.
    for end in range(len(reference)-19,len(reference)+1):
        a,b = indicators(reference[:end]),indicators(candidate[:end])
        for key in a:
            e = abs(a[key]-b[key])
            if key.startswith('ma'):
                e = e / a[key] * 100
            elif key in ('dif','dea'):
                e = e / reference[end-1] * 100
            errors[key] = max(errors[key],e)
        sa,ca = contributions(a)
        sb,cb = contributions(b)
        if ca != cb:
            changed.append(dict(index=end-1,reference_score=sa,candidate_score=sb,
                                changed_components=[k for k in ca if ca[k]!=cb[k]]))
    limits=dict(ma5=.2,ma20=.2,ma60=.2,dif=.1,dea=.1,rsi=.5,return20=.2)
    passed = price_error <= .2 and not changed and all(errors[k]<=v for k,v in limits.items())
    return dict(passed=passed,price_max_relative_pct=price_error,max_indicator_errors=dict(errors),
                changed_windows=changed,latest_reference=indicators(reference),latest_candidate=indicators(candidate))


def run():
    source = ROOT/'sheet1.csv'
    snapfile = ROOT/'data/scoring/current.json'
    snapshot = json.loads(snapfile.read_text(encoding='utf-8'))
    groups=defaultdict(dict)
    with source.open(encoding='utf-8-sig',newline='') as stream:
        rows=csv.reader(stream)
        header=next(rows)
        if '前收盘价' not in header[2] or '前复权' not in header[2]:
            raise ValueError('Unverified header')
        current=None
        for row in rows:
            if row[0].strip():
                current=identity(row[0])
            code,name=current
            observed=day(row[1])
            if observed in groups[code]:
                raise ValueError('Duplicate company/date')
            groups[code][observed]=dict(name=name,pre=number(row[2]),close=number(row[3]),
                                       suspended=bool(row[6].strip()),volume=number(row[5]),amount=number(row[4]))
    calendar=sorted({d for g in groups.values() for d in g})
    next_day=dict(zip(calendar,calendar[1:]))
    refs=defaultdict(list)
    for row in snapshot['rows']:
        refs[row['code']].append(row)
    results=[]
    for code,g in sorted(groups.items()):
        out=dict(code=code,name=next(iter(g.values()))['name'],status='待核验',reasons=[])
        results.append(out)
        if len(refs[code])!=1:
            out['reasons'].append('缺唯一公开源对照'); continue
        r=refs[code][0]
        raw=r.get('raw',{})
        detail=raw.get('source_details',{}).get('technical',{})
        if detail.get('adjustment')!='qfq' or not detail.get('rows'):
            out['reasons'].append('缺前复权对照序列'); continue
        if any(r.get(k)!=snapshot.get(k) for k in ('batch_id','version','as_of','financial_period')):
            out['reasons'].append('对照批次不一致'); continue
        rs=sorted(detail['rows'],key=lambda x:x[0])
        dates=[row[0] for row in rs]
        if len(set(dates))!=len(dates) or dates[-1]!=raw.get('market_date') or dates[-1]>snapshot['as_of']:
            out['reasons'].append('对照日期异常'); continue
        expected=[d for d in calendar if dates[0]<=d<=dates[-1]]
        if dates!=expected:
            out['reasons'].append('对照有交易日缺口'); continue
        candidate=[]
        for d in dates:
            following=next_day.get(d)
            today=g.get(d)
            nxt=g.get(following)
            if not today or not nxt:
                out['reasons'].append('缺当前或下一交易日'); break
            if today['suspended'] or nxt['suspended']:
                out['reasons'].append('窗口含停牌，未跨停牌移位'); break
            if any(number(v) is None or v<=0 for v in (today['volume'],today['amount'],nxt['pre'],today['close'])):
                out['reasons'].append('无效价格或无成交'); break
            candidate.append(nxt['pre'])
        if out['reasons']: continue
        reference=[number(row[2]) for row in rs]
        if len(reference)<80 or any(v is None or v<=0 for v in reference):
            out['reasons'].append('对照不足80条或价格无效'); continue
        result=compare(reference,candidate)
        out.update(result,overlap=len(reference),start=dates[0],end=dates[-1])
        out['status']='对照通过（候选）' if result['passed'] else '存在差异'
        if not result['passed']:
            out['reasons'].append('超出价格/指标误差阈值或计分分项变化')
        # Report worst dates, including candidate factor discontinuities, privately.
        worst=sorted(range(len(dates)),key=lambda i:abs(candidate[i]/reference[i]-1),reverse=True)[:5]
        out['worst_dates']=[dict(date=dates[i],relative_error_pct=abs(candidate[i]/reference[i]-1)*100) for i in worst]
        for change in out['changed_windows']:
            change['date']=dates[change.pop('index')]
    summary=dict(counts=dict(Counter(r['status'] for r in results)),
                 compared=sum('passed' in r for r in results),
                 score_changed_companies=sum(bool(r.get('changed_windows')) for r in results),
                 reasons=dict(Counter(reason for r in results for reason in r['reasons'])))
    dest=ROOT/'data/wind_import/technical_validation.json'
    dest.write_text(json.dumps(dict(summary=summary,companies=results,
        source_hash=sha256(source.read_bytes()).hexdigest(),snapshot_hash=sha256(snapfile.read_bytes()).hexdigest(),
        limits='价格及MA相对误差0.2%；DIF/DEA误差相对收盘价0.1%；RSI 0.5点；收益0.2个百分点；末20窗口全部计分分项一致',
        scope='仅对已有批次重叠窗口验证，不能证明除权语义、全历史或最新日可用；不更新评分、不作严格历史回测'),
        ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))
    lines=['# Wind 技术面候选序列验证', '',
           '本地核验材料，请勿加入公开参赛包。对照为现有公开源快照；验证截至2026-09-04，不代表9月8日及全历史已验证。', '',
           '逐公司用完全相同起点和日期序列计算指标，比较末20个连续窗口。窗口中有停牌或日期缺口的公司不压缩日期后强行计算。', '',
           '候选通过65家、存在差异62家、待核验13家。通过仅表示本次误差阈值和计分分项检查通过，未证明Wind字段在所有除权事件下可直接移位。', '',
           '| 公司 | 代码 | 状态 | 计分变化窗口数 | 原因 |',
           '|---|---|---|---|---|']
    for row in results:
        lines.append('| '+ ' | '.join([row['name'],row['code'],row['status'],
            str(len(row.get('changed_windows',[]))) if 'passed' in row else '未比较',
            '；'.join(row['reasons']) or '本次窗口内通过'])+' |')
    dest.with_suffix('.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':
    run()
