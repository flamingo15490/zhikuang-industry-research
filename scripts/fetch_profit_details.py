"""Fetch complete cumulative income statements into an independent cache."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import urlencode

import pandas as pd
import requests

PROJECT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT / "data" / "profit_analysis"
BASE = "https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/"
DATE_URL = BASE + "lrbDateAjaxNew"
STATEMENT_URL = BASE + "lrbAjaxNew"


def request_data(url: str, params: dict) -> list[dict]:
    for attempt in range(3):
        try:
            response = requests.get(url, params=params, timeout=(10, 30))
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(rows, list) or not rows:
                raise ValueError("Empty or malformed source response")
            return rows
        except (requests.RequestException, ValueError):
            if attempt == 2:
                raise
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError("Request did not complete")


def select_dates(rows: list[dict], periods: int, today: str | None = None) -> list[str]:
    if periods < 1:
        raise ValueError("periods must be positive")
    cutoff = pd.Timestamp(today or datetime.now().date()).normalize()
    dates = set()
    for row in rows:
        date = pd.to_datetime(row.get("REPORT_DATE"), errors="coerce")
        if pd.isna(date):
            raise ValueError("Invalid report date")
        if date.normalize() <= cutoff:
            dates.add(date.strftime("%Y-%m-%d"))
    selected = sorted(dates, reverse=True)[:periods]
    if not selected:
        raise ValueError("No eligible report dates")
    return selected


def validate_rows(rows: list[dict], code: str, dates: list[str]) -> None:
    if not rows:
        raise ValueError("Empty statements")
    observed = []
    number = code.split(".")[1]
    for row in rows:
        symbol = str(row.get("SECURITY_CODE", ""))
        if symbol != number:
            raise ValueError(f"Unexpected security code {symbol!r}")
        date = pd.to_datetime(row.get("REPORT_DATE"), errors="coerce")
        if pd.isna(date):
            raise ValueError("Invalid statement report date")
        observed.append(date.strftime("%Y-%m-%d"))
        core_values = [row.get(key) for key in ("OPERATE_INCOME", "TOTAL_OPERATE_INCOME", "NETPROFIT")]
        if not any(isinstance(value, (int, float)) and not isinstance(value, bool)
                   and math.isfinite(value) for value in core_values):
            raise ValueError("Statement contains no finite numeric financial values")
    if len(observed) != len(set(observed)):
        raise ValueError("Duplicate statement report dates")
    if set(observed) != set(dates):
        raise ValueError("Statement dates do not match requested dates")


def _atomic_frame(frame: pd.DataFrame, path: Path) -> None:
    handle, temporary = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=path.parent)
    os.close(handle)
    try:
        if path.suffix == ".csv":
            frame.to_csv(temporary, index=False, encoding="utf-8-sig")
        else:
            frame.to_parquet(temporary, index=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def fetch_company(code: str, output: Path, periods: int = 8, *, refresh: bool = False) -> dict:
    result = {"code": code, "status": "failed", "rows": 0, "latest_period": "", "earliest_period": "", "error": ""}
    try:
        if not re.fullmatch(r"(?:sh|sz|bj)\.\d{6}", code):
            raise ValueError("Expected exchange-prefixed code, such as sh.601899")
        if periods < 1:
            raise ValueError("periods must be positive")
        output = Path(output)
        if output.resolve() == (PROJECT / "data" / "company_profile").resolve():
            raise ValueError("Original company_profile cache is read-only for this fetcher")
        output.mkdir(parents=True, exist_ok=True)
        path = output / f"profit_{code}.parquet"
        if path.exists() and not refresh:
            try:
                cached = pd.read_parquet(path)
                dates = select_dates(cached.to_dict("records"), periods)
                validate_rows(cached.to_dict("records"), code, dates)
                fetched = pd.to_datetime(cached["fetched_at"], utc=True)
                age = pd.Timestamp.now(tz="UTC") - fetched.min()
                requested = pd.to_numeric(cached["requested_periods"]).min()
                if age >= pd.Timedelta(0) and age < pd.Timedelta(days=1) and requested >= periods and cached["source_url"].notna().all():
                    return dict(result, status="cached", rows=len(cached), latest_period=max(dates), earliest_period=min(dates))
            except (ValueError, KeyError, OSError, TypeError):
                pass
        symbol = code.replace(".", "").upper()
        params = {"companyType": 4, "reportDateType": 0, "code": symbol}
        dates = select_dates(request_data(DATE_URL, params), periods)
        records = []
        fetched_at = datetime.now(timezone.utc).isoformat()
        for start in range(0, len(dates), 5):
            batch = dates[start:start + 5]
            query = dict(params, reportType=1, dates=",".join(batch))
            rows = request_data(STATEMENT_URL, query)
            validate_rows(rows, code, batch)
            source_url = STATEMENT_URL + "?" + urlencode(query)
            records.extend(dict(row, source_url=source_url, fetched_at=fetched_at, requested_periods=periods) for row in rows)
        validate_rows(records, code, dates)
        frame = pd.DataFrame(records).sort_values("REPORT_DATE", ascending=False)
        _atomic_frame(frame, path)
        result.update(status="success", rows=len(frame), latest_period=max(dates), earliest_period=min(dates))
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--codes", nargs="+")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--periods", type=int, default=8)
    parser.add_argument("--workers", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    universe = pd.read_csv(PROJECT / "data" / "nonferrous_universe.csv")
    if args.codes:
        codes = [code.strip() for item in args.codes for code in item.split(",")]
    else:
        codes = universe["code"].drop_duplicates().tolist()
    if args.limit is not None:
        if args.limit < 1:
            parser.error("--limit must be positive")
        codes = codes[:args.limit]
    results = []
    names = dict(zip(universe["code"], universe["stock_name"]))
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = [pool.submit(fetch_company, code, args.output, args.periods, refresh=args.refresh) for code in codes]
        for job in as_completed(jobs):
            result = job.result()
            result["name"] = names.get(result["code"], "")
            results.append(result)
            print(f"[{len(results)}/{len(jobs)}] {result['code']} {result['status']} rows={result['rows']} {result['error']}", flush=True)
    args.output.mkdir(parents=True, exist_ok=True)
    coverage_path = args.output / "fetch_coverage.csv"
    current = pd.DataFrame(results)
    if coverage_path.exists():
        previous = pd.read_csv(coverage_path)
        current = pd.concat([previous[~previous["code"].isin(current["code"])], current], ignore_index=True)
    _atomic_frame(current.sort_values("code"), coverage_path)
    failed = sum(result["status"] == "failed" for result in results)
    print(f"Completed {len(results)} companies; failures={failed}; coverage={coverage_path}", flush=True)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
