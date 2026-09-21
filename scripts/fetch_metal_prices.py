"""拉取历史金属价格（上海金 + 沪铜/铝/银/锌/锡/铅/镍），存 data/metal_prices.parquet。"""
from __future__ import annotations

import akshare as ak
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FUTURES = {"copper": "CU0", "aluminum": "AL0", "silver": "AG0", "zinc": "ZN0",
           "tin": "SN0", "lead": "PB0", "nickel": "NI0"}

series: dict[str, pd.DataFrame] = {}

for metal, code in FUTURES.items():
    try:
        df = ak.futures_zh_daily_sina(symbol=code)
        df["date"] = pd.to_datetime(df["date"])
        series[metal] = df[["date", "close"]].rename(columns={"close": metal})
        print(f"{metal}({code}): OK {len(df)}行 {df['date'].min().date()} -> {df['date'].max().date()}")
    except Exception as exc:  # noqa: BLE001
        print(f"{metal}({code}): FAIL {type(exc).__name__} {str(exc)[:60]}")

try:
    df = ak.spot_hist_sge(symbol="Au99.99")
    df["date"] = pd.to_datetime(df["date"])
    series["gold"] = df[["date", "close"]].rename(columns={"close": "gold"})
    print(f"gold(Au99.99): OK {len(df)}行 {df['date'].min().date()} -> {df['date'].max().date()}")
except Exception as exc:  # noqa: BLE001
    print(f"gold: FAIL {type(exc).__name__} {str(exc)[:60]}")

if series:
    merged = None
    for m in ["gold", "copper", "aluminum", "silver", "zinc", "tin", "lead", "nickel"]:
        if m in series:
            merged = series[m] if merged is None else merged.merge(series[m], on="date", how="outer")
    merged = merged.sort_values("date").reset_index(drop=True)
    out = ROOT / "data" / "metal_prices.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(out)
    print(f"\n已保存 {out} | 行数 {len(merged)} | 列 {list(merged.columns)}")
else:
    print("\n无可用金属价格，未保存。")
