"""从缓存的 akshare 原始数据清洗、派生出干净的"公司画像"表。

输入：data/company_profile/{zy_,profit_}<code>.parquet（31 只）
输出：data/company_profile_summary.parquet（每只股票一行）

派生字段：
  - 有效税率 = INCOME_TAX / TOTAL_PROFIT
  - 少数股东占比 = MINORITY_INTEREST / NETPROFIT
  - 金属收入占比（从主营构成清洗得到，只在金属相关业务内归一化）
  - metal_quality：clean（干净拆分）/ merged（合并披露，均分近似）/ coarse（粗披露，无法拆分）

主营构成的清洗规则（东财数据较脏，且各公司披露粒度不一）：
  - 只看"按产品分类"、最新报告期
  - 剔除"其他/贸易/补充/抵消/抵销/合并/内部/总部"等非金属聚合行
  - 每个金属的权重 = max(顶层行之和, "其中:"子项之和)  ← 修"子项只覆盖部分业务"的问题
  - 合并披露标签（如"铜钴相关产品"）按涉及金属均分
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

PROJECT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT / "data" / "company_profile"
EXPOSURE = PROJECT / "data" / "nonferrous_subindustry_exposure.csv"
UNIVERSE = PROJECT / "data" / "nonferrous_universe.csv"
OUT = PROJECT / "data" / "company_profile_summary.parquet"

# 金属 -> 大类（用于自动推导子行业）
METAL_GROUP: dict[str, str] = {
    "gold": "precious_metals", "silver": "precious_metals", "platinum": "precious_metals",
    "copper": "industrial_metals", "aluminum": "industrial_metals", "zinc": "industrial_metals",
    "lead": "industrial_metals", "tin": "industrial_metals", "nickel": "industrial_metals",
    "rare_earth": "strategic_metals", "lithium": "strategic_metals", "cobalt": "strategic_metals",
    "tungsten": "strategic_metals", "molybdenum": "strategic_metals", "antimony": "strategic_metals",
    "germanium": "strategic_metals", "titanium": "strategic_metals",
}

# 顺序重要：先匹配长/特异的（稀土、钼、钨…），避免子串误配
METAL_KEYWORDS: list[tuple[str, list[str]]] = [
    ("rare_earth", ["稀土"]),
    ("molybdenum", ["钼"]),
    ("tungsten", ["钨"]),
    ("antimony", ["锑"]),
    ("germanium", ["锗"]),
    ("titanium", ["钛"]),
    ("lithium", ["锂"]),
    ("cobalt", ["钴"]),
    ("nickel", ["镍"]),
    ("tin", ["锡"]),
    ("lead", ["铅"]),
    ("platinum", ["铂", "钯"]),
    ("gold", ["金"]),
    ("silver", ["银"]),
    ("copper", ["铜"]),
    ("zinc", ["锌"]),
    ("aluminum", ["铝"]),
]
EXCLUDE_WORDS = ["其他", "贸易", "补充", "抵消", "抵销", "合并", "内部", "总部", "供应链"]


def load_names() -> dict[str, str]:
    src = UNIVERSE if UNIVERSE.exists() else EXPOSURE
    df = pd.read_csv(src)
    return dict(zip(df["code"], df["stock_name"]))


def metals_of(label: str) -> list[str]:
    """返回标签涉及的所有金属（合并披露如"铜钴相关产品"会返回多个）。"""
    found: list[str] = []
    for metal, kws in METAL_KEYWORDS:
        if metal == "gold" and any(w in label for w in ("合金", "金融", "金属")):
            continue  # "金"是"合金/金融/金属"的一部分，不是黄金
        if any(k in label for k in kws):
            found.append(metal)
    return found


def metal_shares(zy: pd.DataFrame) -> dict:
    """清洗主营构成 → 各金属收入占比（金属业务内归一化）。"""
    prod = zy[zy["分类类型"] == "按产品分类"]
    if prod.empty:
        return {"metal_quality": "coarse"}
    prod = prod[prod["报告日期"] == prod["报告日期"].max()].copy()
    prod["收入比例"] = pd.to_numeric(prod["收入比例"], errors="coerce")
    prod["label"] = prod["主营构成"].astype(str).str.replace("其中:", "", regex=False).str.strip()
    prod = prod[~prod["label"].str.contains("|".join(EXCLUDE_WORDS), na=False)]
    prod["is_sub"] = prod["主营构成"].astype(str).str.startswith("其中:")
    prod["metals"] = prod["label"].map(metals_of)
    prod = prod[prod["metals"].map(len) > 0].dropna(subset=["收入比例"])

    top_sum: dict[str, float] = {}
    sub_sum: dict[str, float] = {}
    merged = False
    for _, r in prod.iterrows():
        ms = r["metals"]
        share = r["收入比例"] / len(ms)  # 合并标签均分
        if len(ms) > 1:
            merged = True
        bucket = sub_sum if r["is_sub"] else top_sum
        for m in ms:
            bucket[m] = bucket.get(m, 0.0) + share

    metals = set(top_sum) | set(sub_sum)
    shares = {m: max(top_sum.get(m, 0.0), sub_sum.get(m, 0.0)) for m in metals}
    total = sum(shares.values())
    if total <= 0:
        return {"metal_quality": "coarse"}

    result = {f"{m}_share": v / total for m, v in shares.items()}
    result["metal_quality"] = "merged" if merged else "clean"
    result["metal_total"] = total
    return result


def derive_one(code: str, name: str) -> dict:
    zy_path = RAW_DIR / f"zy_{code}.parquet"
    ps_path = RAW_DIR / f"profit_{code}.parquet"
    row: dict = {"code": code, "stock_name": name}

    if ps_path.exists():
        ps = pd.read_parquet(ps_path).sort_values("REPORT_DATE")
        r = ps.iloc[-1]
        tp = pd.to_numeric(r.get("TOTAL_PROFIT"), errors="coerce")
        it = pd.to_numeric(r.get("INCOME_TAX"), errors="coerce")
        np_ = pd.to_numeric(r.get("NETPROFIT"), errors="coerce")
        mi = pd.to_numeric(r.get("MINORITY_INTEREST"), errors="coerce")
        pn = pd.to_numeric(r.get("PARENT_NETPROFIT"), errors="coerce")
        oi = pd.to_numeric(r.get("OPERATE_INCOME"), errors="coerce")
        row["report_date"] = pd.Timestamp(r["REPORT_DATE"])
        row["notice_date"] = pd.Timestamp(r["NOTICE_DATE"]) if pd.notna(r.get("NOTICE_DATE")) else pd.NaT
        row["operate_income"] = oi
        row["total_profit"] = tp
        row["income_tax"] = it
        row["netprofit"] = np_
        row["parent_netprofit"] = pn
        row["minority_interest"] = mi
        row["tax_rate"] = (it / tp) if pd.notna(tp) and tp != 0 else pd.NA
        row["minority_share"] = (mi / np_) if pd.notna(np_) and np_ != 0 else pd.NA

    if zy_path.exists():
        zy = pd.read_parquet(zy_path)
        row.update(metal_shares(zy))

    return row


def write_exposure(df: pd.DataFrame) -> None:
    """从主营构成金属占比自动推导子行业 exposure CSV（替代手工表）。"""
    import datetime as _dt
    share_cols = [c for c in df.columns if c.endswith("_share") and c != "minority_share"]
    rows = []
    for _, r in df.iterrows():
        pairs = [(c[:-6], float(r[c])) for c in share_cols if pd.notna(r[c])]
        pairs.sort(key=lambda x: -x[1])
        if not pairs:
            rows.append({
                "code": r["code"], "stock_name": r["stock_name"], "subindustry": "other",
                "subindustry_group": "other", "weight": 1.0, "weight_source": "derived",
                "confidence": "low", "effective_date": _dt.date.today().isoformat(),
                "notes": "主营构成无法识别金属细分",
            })
            continue
        conf = "high" if r.get("metal_quality") == "clean" else "medium"
        # 取占比 >= 10% 的金属，最多 3 个
        chosen = [p for p in pairs if p[1] >= 0.10][:3] or pairs[:1]
        for metal, w in chosen:
            rows.append({
                "code": r["code"], "stock_name": r["stock_name"], "subindustry": metal,
                "subindustry_group": METAL_GROUP.get(metal, "other"), "weight": round(w, 4),
                "weight_source": "derived", "confidence": conf,
                "effective_date": _dt.date.today().isoformat(),
                "notes": f"主营构成自动推导（披露质量 {r.get('metal_quality','?')}）",
            })
    exp = pd.DataFrame(rows)
    exp.to_csv(EXPOSURE, index=False)
    print(f"已自动推导 {EXPOSURE}，{exp['code'].nunique()} 只 / {len(exp)} 行")


def main() -> None:
    names = load_names()
    rows = [derive_one(code, name) for code, name in names.items()]
    df = pd.DataFrame(rows)
    df.to_parquet(OUT, index=False)
    print(f"已生成 {OUT}，共 {len(df)} 行")
    write_exposure(df)

    share_cols = [c for c in df.columns if c.endswith("_share")]
    for _, r in df.iterrows():
        q = r.get("metal_quality", "?")
        pairs = [(c[:-6], r[c]) for c in share_cols if pd.notna(r[c])]
        pairs.sort(key=lambda x: -x[1])
        top = " ".join(f"{m}{round(v*100)}%" for m, v in pairs[:3]) or "(无金属占比)"
        print(f"{r['stock_name']:<6} [{q:<6}] {top}")


if __name__ == "__main__":
    main()
