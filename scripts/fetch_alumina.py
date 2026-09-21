"""拉取氧化铝期货(AO0)日线，并入 metal_prices.parquet 的 alumina 列。"""
from __future__ import annotations

from pathlib import Path

import akshare as ak
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
METAL = BASE / "data" / "metal_prices.parquet"

df = pd.read_parquet(METAL)
df["date"] = pd.to_datetime(df["date"])

ao = ak.futures_zh_daily_sina(symbol="AO0")
ao["date"] = pd.to_datetime(ao["date"])
ao = ao[["date", "close"]].rename(columns={"close": "alumina"})

merged = df.merge(ao, on="date", how="left")
merged.to_parquet(METAL)
print(f"氧化铝并入完成：{ao['alumina'].notna().sum()} 行，区间 {ao['date'].min().date()} ~ {ao['date'].max().date()}")
print(f"合并后总行数 {len(merged)}，alumina 最新 {merged['alumina'].dropna().iloc[-1]:.0f} 元/吨")
