"""命令行入口：python main.py "问题"，或 python main.py 交互式输入。"""
from __future__ import annotations

import sys

from agent import run_agent


def main() -> None:
    question = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else input("请输入你的投研问题：").strip()
    print("\n思考中…\n")
    answer = run_agent(question)
    print("\n" + "=" * 64)
    print(answer)
    print("=" * 64)


if __name__ == "__main__":
    main()
