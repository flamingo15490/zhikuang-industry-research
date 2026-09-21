"""拉取 31 只有色股票的"特异数据"：主营构成 + 利润表（税率/少数股东/公告日）。

缓存到 data/company_profile/，每只股票两个文件：
  zy_<code>.parquet        主营构成（金属收入占比，带报告期）
  profit_<code>.parquet    利润表关键列（利润总额/所得税/净利润/少数股东损益/公告日）

用途：支撑"盈利桥/价格敏感性"工具（收入弹性法），并保证点时性（用公告日）。
"""
from __future__ import annotations

import time
from pathlib import Path

import akshare as ak
import pandas as pd

PROJECT = Path(__file__).resolve().parent.parent
EXPOSURE = PROJECT / "data" / "nonferrous_subindustry_exposure.csv"
UNIVERSE = PROJECT / "data" / "nonferrous_universe.csv"
OUT_DIR = PROJECT / "data" / "company_profile"

PROFIT_COLS = [
    "REPORT_DATE", "REPORT_DATE_NAME", "NOTICE_DATE",
    "OPERATE_INCOME", "OPERATE_COST", "TOTAL_PROFIT", "INCOME_TAX",
    "NETPROFIT", "PARENT_NETPROFIT", "MINORITY_INTEREST", "BASIC_EPS",
]


def to_ak_symbol(code: str) -> str:
    """'sh.601899' -> 'SH601899'；'sz.000630' -> 'SZ000630'"""
    market, num = code.split(".")
    return f"{market.upper()}{num}"


def load_universe() -> list[tuple[str, str]]:
    """优先读全量 universe（140 只申万有色成分），缺失时兜底旧 31 只 exposure。"""
    src = UNIVERSE if UNIVERSE.exists() else EXPOSURE
    df = pd.read_csv(src)
    pairs = df[["code", "stock_name"]].drop_duplicates().sort_values("code")
    return list(zip(pairs["code"], pairs["stock_name"]))


def _profit_ok(path: Path) -> bool:
    try:
        ps = pd.read_parquet(path)
        return "OPERATE_COST" in ps.columns and len(ps) > 0
    except Exception:  # noqa: BLE001
        return False


def fetch_one(code: str, name: str, out: Path) -> dict:
    sym = to_ak_symbol(code)
    res = {"code": code, "name": name, "zygc_rows": 0, "profit_rows": 0, "error": ""}
    zy_path = out / f"zy_{code}.parquet"
    ps_path = out / f"profit_{code}.parquet"

    zy_done = zy_path.exists()
    ps_done = _profit_ok(ps_path)

    # 两个都齐全则跳过（断点续传）
    if zy_done and ps_done:
        try:
            zy = pd.read_parquet(zy_path)
            ps = pd.read_parquet(ps_path)
            res.update({"zygc_rows": len(zy), "profit_rows": len(ps), "error": "skipped"})
            return res
        except Exception:  # noqa: BLE001
            pass

    if not zy_done:
        try:
            zy = ak.stock_zygc_em(symbol=sym)
            zy.to_parquet(zy_path, index=False)
            res["zygc_rows"] = len(zy)
        except Exception as e:  # noqa: BLE001
            res["error"] = f"zygc:{type(e).__name__}"
        time.sleep(0.3)

    if not ps_done:
        try:
            ps = ak.stock_profit_sheet_by_yearly_em(symbol=sym)  # 年度口径，快且含营业成本
            ps = ps[PROFIT_COLS]
            ps.to_parquet(ps_path, index=False)
            res["profit_rows"] = len(ps)
        except Exception as e:  # noqa: BLE001
            res["error"] += f" profit:{type(e).__name__}"
    return res


def main() -> None:
    out = OUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    universe = load_universe()
    print(f"universe: {len(universe)} 只", flush=True)
    results = []
    for i, (code, name) in enumerate(universe, 1):
        r = fetch_one(code, name, out)
        results.append(r)
        ok = "·" if r["error"] == "skipped" else ("✓" if not r["error"] else "✗")
        print(
            f"[{i}/{len(universe)}] {ok} {name}（{code}） "
            f"zy={r['zygc_rows']} profit={r['profit_rows']} {r['error']}",
            flush=True,
        )
        time.sleep(0.5)

    report = pd.DataFrame(results)
    report.to_csv(out / "_coverage.csv", index=False)
    ok_z = (report["zygc_rows"] > 0).sum()
    ok_p = (report["profit_rows"] > 0).sum()
    print(f"\nDONE. 主营构成 OK {ok_z}/{len(universe)}；利润表 OK {ok_p}/{len(universe)}", flush=True)


if __name__ == "__main__":
    main()
