"""共享小工具：股票代码/名称解析。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent.parent
PROFILE = BASE / "data" / "company_profile_summary.parquet"


def resolve_profile_row(df: pd.DataFrame, query: str) -> pd.Series | None:
    """Prefer exact identity; accept only a unique literal substring otherwise."""
    q = str(query).strip().lower()
    if not q:
        return None
    codes = df["code"].fillna("").astype(str).str.strip().str.lower()
    names = df["stock_name"].fillna("").astype(str).str.strip().str.lower()
    exact = codes.eq(q) | names.eq(q) | codes.map(to_digits).eq(q)
    candidates = df[exact]
    if candidates.empty:
        candidates = df[codes.str.contains(q, regex=False, na=False) |
                        names.str.contains(q, regex=False, na=False)]
    return candidates.iloc[0] if len(candidates) == 1 else None


def resolve_stock(query: str) -> tuple[str | None, str | None]:
    """把名称/代码解析成 (stock_name, code)，无唯一匹配返回 (None, None)。"""
    if not str(query).strip():
        return None, None
    r = resolve_profile_row(pd.read_parquet(PROFILE), query)
    if r is not None:
        return str(r["stock_name"]), str(r["code"])
    return None, None


def to_digits(code: str) -> str:
    """'sh.601899' -> '601899'。"""
    return str(code).replace("sh", "").replace("sz", "").replace("bj", "").replace(".", "").strip()


def classify_business(code: str) -> tuple[None, str]:
    """Compatibility pair: no inferred transmission rate; explicit business labels."""
    from tools.profit_analysis import analyze_profit
    from tools.sensitivity_core import BUSINESS_NAMES

    analysis = analyze_profit(code)
    names = [BUSINESS_NAMES.get(kind, kind) for kind in analysis.get('business_types', [])]
    return None, '、'.join(names) if names else '经营环节未确认'
