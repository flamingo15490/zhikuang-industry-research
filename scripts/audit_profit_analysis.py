"""Audit the local research universe without fetching or altering source caches."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys

import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from tools.profit_analysis import analyze_profit, format_profit_summary


def audit_company(code: str, name: str, audited_at: str) -> dict:
    row = {"code": code, "name": name, "audited_at": audited_at,
           "status": "error", "error": ""}
    try:
        result = analyze_profit(code)
        bridge = result["bridge"]
        running, largest = 0.0, 0.0
        finite = True
        for amount, measure in zip(bridge["values"], bridge["measures"]):
            if not math.isfinite(amount):
                finite = False
                continue
            if measure == "absolute":
                running = amount
            elif measure == "relative":
                running += amount
            elif measure == "total":
                largest = max(largest, abs(running - amount))
            else:
                raise ValueError(f"Unknown waterfall measure: {measure}")
        if not (len(bridge["labels"]) == len(bridge["values"]) == len(bridge["measures"]) == len(bridge["origins"])):
            raise ValueError("Waterfall columns have different lengths")
        source = result.get("source") or {}
        segments = result.get("segments") or []
        missing_core = [key for key in ("OPERATE_INCOME", "OPERATE_COST", "TOTAL_PROFIT",
            "INCOME_TAX", "NETPROFIT", "MINORITY_INTEREST", "PARENT_NETPROFIT")
            if result["statement"].get(key) is None]
        missing_reasons = list(result.get("missing_details") or [])
        missing_reasons += ["未披露核心字段：" + ",".join(missing_core)] if missing_core else []
        missing_reasons += [f"{segment['name']}：{segment['reason']}" for segment in segments
                            if segment.get("status") == "missing"]
        if not result.get("business_types"):
            missing_reasons.append("经营类型尚无明确披露证据")
        if not segments:
            missing_reasons.append("无可用分部披露")
        row.update(status="ok" if finite else "nonfinite", period=result.get("period"),
            notice_date=result.get("notice_date"), source_kind=source.get("kind"),
            source_path=source.get("path"), source_url=source.get("url"),
            fetched_at=source.get("fetched_at"), bridge_status=result["bridge_status"],
            bridge_endpoint=bridge["labels"][-1] if bridge["labels"] else "",
            bridge_item_count=len(bridge["labels"]), bridge_finite=finite,
            max_arithmetic_difference_yuan=largest * 1e8,
            segment_period=result.get("segment_period"), segment_status=result["segment_status"],
            segment_count=len(segments), segment_valid_gross_count=sum(
                not s["excluded"] and s["gross_profit"] is not None for s in segments),
            segment_missing_count=sum(s.get("status") == "missing" for s in segments),
            segment_excluded_count=sum(bool(s["excluded"]) for s in segments),
            segment_elimination_count=sum(bool(s.get("is_elimination")) for s in segments),
            business_types="|".join(result.get("business_types") or []),
            missing_core_fields="|".join(missing_core), missing_reason="；".join(missing_reasons),
            warnings="；".join(result.get("warnings") or []),
            summary_characters=len(format_profit_summary(result)))
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", type=Path, default=PROJECT / "data/nonferrous_universe.csv")
    parser.add_argument("--output", type=Path, default=PROJECT / "data/profit_analysis/analysis_coverage.csv")
    args = parser.parse_args()
    universe = pd.read_csv(args.universe).drop_duplicates("code")
    audited_at = datetime.now(timezone.utc).isoformat()
    rows = [audit_company(row.code, row.stock_name, audited_at) for row in universe.itertuples()]
    frame = pd.DataFrame(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.output, index=False, encoding="utf-8-sig")
    summary = {"companies": len(rows), "status": dict(Counter(row["status"] for row in rows)),
        "bridge_status": dict(Counter(row.get("bridge_status", "error") for row in rows)),
        "segment_status": dict(Counter(row.get("segment_status", "error") for row in rows)),
        "unclassified": sum(row.get("business_types") == "" for row in rows),
        "max_arithmetic_difference_yuan": max((row.get("max_arithmetic_difference_yuan", 0) for row in rows), default=0),
        "summary_characters_max": max((row.get("summary_characters", 0) for row in rows), default=0),
        "output": str(args.output.resolve())}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if any(row["status"] != "ok" for row in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
