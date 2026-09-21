"""全量拉取个股基本面（最新年度口径），重建 nonferrous_fundamentals.parquet。

口径统一原则：全部锚定「最新年度报告期」（利润表 yearly 的最新 REPORT_DATE）。
  - gross_margin / ann_date 来自年度利润表
  - roe / bps / ocfps / eps 取新浪财务指标中「同年年度(12-31)」行，找不到才退到最近年度行
绝不混用半年度/季度口径。

输出列与旧版一致：plain, roe, bps, gross_margin, eps, ocfps, report_period, ann_date, code, stock_name
每只股票一行（最新年度），与 company_profile_summary 的报告期保持一致。
"""
from __future__ import annotations

import time
from pathlib import Path

import akshare as ak
import pandas as pd

PROJECT = Path(__file__).resolve().parent.parent
UNIVERSE = PROJECT / "data" / "nonferrous_universe.csv"
PROFILE_DIR = PROJECT / "data" / "company_profile"
OUT = PROJECT / "data" / "nonferrous_fundamentals.parquet"

COLS = ["plain", "roe", "bps", "gross_margin", "eps", "ocfps",
        "report_period", "ann_date", "code", "stock_name"]


def to_digits(code: str) -> str:
    return str(code).replace("sh", "").replace("sz", "").replace("bj", "").replace(".", "").strip()


def _f(v):
    try:
        return float(v) if pd.notna(v) else None
    except (TypeError, ValueError):
        return None


def _pick(s: pd.Series, cands: list[str]):
    for c in cands:
        if c in s.index and pd.notna(s.get(c)):
            return _f(s.get(c))
    return None


def build_one(code: str, name: str) -> dict | None:
    # 1) 年度利润表（口径锚点）
    ps_path = PROFILE_DIR / f"profit_{code}.parquet"
    if not ps_path.exists():
        return None
    ps = pd.read_parquet(ps_path).sort_values("REPORT_DATE")
    if ps.empty:
        return None
    latest = ps.iloc[-1]
    anchor_period = pd.Timestamp(latest["REPORT_DATE"])
    anchor_year = anchor_period.year

    oi = _f(latest.get("OPERATE_INCOME"))
    oc = _f(latest.get("OPERATE_COST"))
    gross_margin = round((oi - oc) / oi * 100, 2) if (oi and oc) else None
    eps_ps = _f(latest.get("BASIC_EPS"))
    ann_date = pd.Timestamp(latest["NOTICE_DATE"]) if pd.notna(latest.get("NOTICE_DATE")) else pd.NaT

    # 2) 新浪财务指标（取同年年度行，找不到退最近年度行）
    try:
        fin = ak.stock_financial_analysis_indicator(symbol=to_digits(code), start_year="2022")
    except Exception:  # noqa: BLE001
        fin = pd.DataFrame()
    roe = bps = ocfps = eps = None
    if not fin.empty:
        d = pd.to_datetime(fin["日期"], errors="coerce")
        fin = fin.assign(_dt=d)
        annual = fin[fin["_dt"].dt.month == 12].sort_values("_dt")
        same = annual[annual["_dt"].dt.year == anchor_year]
        s = same.iloc[-1] if not same.empty else (annual.iloc[-1] if not annual.empty else fin.sort_values("_dt").iloc[-1])
        roe = _pick(s, ["加权净资产收益率(%)", "净资产收益率(%)"])
        bps = _pick(s, ["每股净资产_调整前(元)", "每股净资产_调整后(元)"])
        ocfps = _pick(s, ["每股经营性现金流(元)"])
        eps = _pick(s, ["摊薄每股收益(元)", "加权每股收益(元)"])

    if eps is None:
        eps = eps_ps

    return {
        "plain": to_digits(code),
        "roe": roe, "bps": bps, "gross_margin": gross_margin,
        "eps": eps, "ocfps": ocfps,
        "report_period": anchor_period, "ann_date": ann_date,
        "code": code, "stock_name": name,
    }


def main() -> None:
    if not UNIVERSE.exists():
        raise SystemExit("缺少 data/nonferrous_universe.csv，请先拉取股票池。")
    uni = pd.read_csv(UNIVERSE)
    rows, fails = [], 0
    for i, (code, name) in enumerate(zip(uni["code"], uni["stock_name"]), 1):
        try:
            r = build_one(str(code), str(name))
        except Exception as e:  # noqa: BLE001
            print(f"[{i}/{len(uni)}] ✗ {name} {type(e).__name__}: {e}", flush=True)
            fails += 1
            time.sleep(0.3)
            continue
        if r is None:
            print(f"[{i}/{len(uni)}] ✗ {name} 无利润表", flush=True)
            fails += 1
            continue
        rows.append(r)
        print(f"[{i}/{len(uni)}] ✓ {name}（{code}）{r['report_period'].date()} "
              f"ROE={r['roe']} GM={r['gross_margin']}", flush=True)
        time.sleep(0.3)

    all_df = pd.DataFrame(rows, columns=COLS) if rows else pd.DataFrame(columns=COLS)
    all_df.to_parquet(OUT, index=False)
    print(f"\nDONE. {OUT} 共 {len(all_df)} 行 / {all_df['code'].nunique()} 只；失败 {fails}", flush=True)


if __name__ == "__main__":
    main()
