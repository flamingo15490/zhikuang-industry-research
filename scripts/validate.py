"""黄金测试集：对 Agent 的回答做自动化断言，检验是否忠实复现工具数据、有无幻觉。

用法：python scripts/validate.py
每个用例给"问题 + 必须出现的关键词组"，任一组未命中即判定失败。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import run_agent  # noqa: E402

CASES = [
    {"name": "紫金经营画像", "question": "紫金矿业的经营画像是什么？给出税率、少数股东占比和金属收入占比。",
     "expect": [["21.5"], ["21.4"], ["金"], ["铜"]]},
    {"name": "金价敏感性", "question": "金价下跌20%，紫金矿业归母净利润大概下降多少？",
     "expect": [["1.14", "22.7"], ["89", "亿"]]},
    {"name": "铜价敏感性", "question": "铜价下跌10%，紫金矿业净利润大概下降多少？",
     "expect": [["0.99", "9.9"]]},
    {"name": "纯金公司定位", "question": "山东黄金主营什么金属？",
     "expect": [["黄金", "gold"], ["100"]]},
    {"name": "披露不全-诚实", "question": "中金黄金的金属收入占比是多少？",
     "expect": [["无法识别", "披露不全", "无金属细分", "不能估算"]]},
    {"name": "基本面对比", "question": "紫金矿业的ROE是多少？和板块中位相比如何？",
     "expect": [["10.35"], ["4.78"]]},
    {"name": "宏观状态", "question": "当前贵金属的宏观状态如何？",
     "expect": [["-1.51"]]},
    {"name": "稀土定位", "question": "北方稀土主营什么金属？",
     "expect": [["稀土", "rare_earth"]]},
    {"name": "合并披露标注", "question": "铜价下跌15%对洛阳钼业净利润的影响？",
     "expect": [["误差", "合并披露", "近似"]]},
    {"name": "多金属定位", "question": "云南锡业主营什么金属？",
     "expect": [["锡", "tin"]]},
]


def check(answer: str, groups: list[list[str]]) -> tuple[bool, list[str]]:
    a = answer.lower()
    failed = [g for g in groups if not any(k.lower() in a for k in g)]
    return (not failed), ["/".join(g) for g in failed]


def main() -> None:
    print(f"共 {len(CASES)} 个用例\n")
    passed = 0
    for i, case in enumerate(CASES, 1):
        t0 = time.time()
        try:
            ans = run_agent(case["question"])
        except Exception as exc:  # noqa: BLE001
            print(f"[{i}/{len(CASES)}] ✗ {case['name']} 异常: {exc}")
            continue
        ok, failed = check(ans, case["expect"])
        if ok:
            passed += 1
        print(f"[{i}/{len(CASES)}] {'✓' if ok else '✗'} {case['name']} ({time.time()-t0:.0f}s)"
              + ("" if ok else f"  缺失: {failed}"))
    print(f"\n通过 {passed}/{len(CASES)}")


if __name__ == "__main__":
    main()
