"""Build an atomic scoring-v2 snapshot without modifying the legacy parquet."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import sys
import uuid

import pandas as pd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from score_data import collect_observation, retry_observation, _rsi
from scoring import VERSION, score_observation

UNIVERSE = BASE / 'data/nonferrous_universe.csv'
EXPOSURE = BASE / 'data/nonferrous_subindustry_exposure.csv'
OUT = BASE / 'data/scoring/current.json'


def top_subindustry(code):
    frame = pd.read_csv(EXPOSURE)
    selected = frame[frame.code == code]
    if selected.empty:
        return None, None
    top = selected.sort_values('weight', ascending=False, kind='stable').iloc[0]
    return str(top.subindustry), str(top.subindustry_group)


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, allow_nan=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build_snapshot(as_of, financial_period, codes=None, workers=4, retry_network=None):
    as_of = date.fromisoformat(as_of).isoformat()
    financial_period = date.fromisoformat(financial_period).isoformat()
    if financial_period > as_of or not financial_period.endswith('-12-31'):
        raise ValueError('financial period must be an annual period <= as_of')
    universe = pd.read_csv(UNIVERSE)
    if codes:
        requested = {c.strip() for c in codes}
        universe = universe[universe.code.isin(requested) | universe.code.str.split('.').str[-1].isin(requested)]
        found = set(universe.code) | set(universe.code.str.split('.').str[-1])
        if requested - found:
            raise ValueError('unknown codes: ' + ','.join(sorted(requested - found)))
    batch = uuid.uuid4().hex
    previous = {}
    if retry_network:
        saved = json.loads(Path(retry_network).read_text(encoding='utf-8'))
        if saved['as_of'] != as_of or saved['financial_period'] != financial_period or saved['version'] != VERSION:
            raise ValueError('retry snapshot context/version mismatch')
        for row in saved['rows']:
            if any(row.get(k) != saved[k] for k in ('batch_id', 'version', 'as_of', 'financial_period')):
                raise ValueError('mixed retry snapshot row context')
            if any(row['raw'].get(k) != row[k] for k in ('code', 'as_of', 'financial_period')):
                raise ValueError('mixed retry observation context')
        previous = {r['code']: r['raw'] for r in saved['rows']}
        if len(previous) != len(saved['rows']):
            raise ValueError('duplicate retry snapshot codes')

    def collect(item):
        code, name = item
        prior = previous.get(code)
        transient = prior and any(any(term in issue for term in ('RemoteDisconnected', 'URLError', 'HTTPError', 'Timeout', 'ConnectionError')) for issue in prior['issues'])
        raw = (retry_observation(prior)
               if transient else prior if prior is not None else collect_observation(name, code, as_of, financial_period))
        if prior is not None:
            old_scores, new_scores = score_observation(prior)['scores'], score_observation(raw)['scores']
            if any(old_scores[key] is not None and new_scores[key] is None for key in old_scores):
                raw = prior
        technical = raw['source_details'].get('technical')
        if technical:
            technical['historical_limit'] = 'Current provider-adjusted history; date filtering is not a strict historical point-in-time adjustment reconstruction.'
            if raw.get('rsi') is not None and technical.get('rows'):
                raw['rsi'] = _rsi([float(r[2]) for r in technical['rows']])
        group, family = top_subindustry(code)
        result = score_observation(raw)
        print(f'{code}: {result.get("composite")} / issues={len(raw["issues"])}', flush=True)
        return dict(code=code, stock_name=name, subindustry=group, subindustry_group=family,
                    batch_id=batch, as_of=as_of, financial_period=financial_period, version=VERSION,
                    raw=raw, scores=result)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(collect, zip(universe.code, universe.stock_name)))
    return dict(schema_version=2, version=VERSION, batch_id=batch, as_of=as_of,
                financial_period=financial_period, created_at=datetime.now(timezone.utc).isoformat(),
                reused_observations_from_batch=saved['batch_id'] if retry_network else None, rows=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--as-of', required=True)
    parser.add_argument('--financial-period', default='2025-12-31')
    parser.add_argument('--codes', nargs='*', help='Space or comma separated codes; omit for full universe')
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('--retry-network', type=Path, help='Retry failed market sources from an identical as-of/period/version snapshot; retain verified financial observations')
    args = parser.parse_args()
    if args.output.exists():
        previous = json.loads(args.output.read_text(encoding='utf-8'))
        atomic_write(args.output.parent / 'batches' / (previous['batch_id'] + '.json'), previous)
    codes = [part for value in args.codes for part in value.split(',')] if args.codes else None
    snapshot = build_snapshot(args.as_of, args.financial_period, codes, args.workers, args.retry_network)
    atomic_write(args.output.parent / 'batches' / (snapshot['batch_id'] + '.json'), snapshot)
    atomic_write(args.output, snapshot)
    print(f'Wrote {len(snapshot["rows"])} rows to {args.output}', flush=True)


if __name__ == '__main__':
    main()
