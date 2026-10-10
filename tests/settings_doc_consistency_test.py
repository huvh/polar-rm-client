"""孤儿设置项的**文档 / 闸门 / 工具实测**三方一致性检查。

为什么要单独一个测试：`tools/SETTINGS_GAPS.md` 里同一个孤儿数字出现在
5 个地方（结果表、进度表末行、"剩下 N 个"标题、防倒退正文、示例命令），
`tools/verify_all.py` 的 `--max-orphans` 是第 6 个，审计工具自己的输出是第 7 个。
本轮改一次数字就要手写 7 处，用"全文替换改数字"直接把文档改自相矛盾过。
**这种打脸靠人眼盯不住**，所以程序化钉死。

口径：闸门基线 >= 实测（只许减不许增），其余所有出处 == 实测。
基线允许暂时高于实测（刚接完还没下调），但文档必须写实测值——
文档是给人看的进度，写高了就是虚报。

    python tests/settings_doc_consistency_test.py
"""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAPS = os.path.join(ROOT, "tools", "SETTINGS_GAPS.md")
VERIFY = os.path.join(ROOT, "tools", "verify_all.py")
AUDIT = os.path.join(ROOT, "tools", "audit_settings.py")

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILED.append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


def read(path: str) -> str:
    return io.open(path, encoding="utf-8").read()


def actual_orphans() -> int:
    """跑真正的审计，拿实测值。不从任何文档里读数字。"""
    out = os.path.join(tempfile.mkdtemp(prefix="polar_doc_"), "audit.json")
    result = subprocess.run(
        [sys.executable, AUDIT, "--json", out],
        capture_output=True, cwd=ROOT,
    )
    if result.returncode != 0 or not os.path.exists(out):
        raise RuntimeError(f"audit_settings.py 未能产出 JSON：exit={result.returncode}")
    rows = json.load(io.open(out, encoding="utf-8"))
    return sum(1 for r in rows if r["tier"] == "ORPHAN")


def gate_baseline() -> int:
    m = re.search(r'"--max-orphans",\s*"(\d+)"', read(VERIFY))
    if m is None:
        raise RuntimeError("verify_all.py 里找不到 --max-orphans 基线")
    return int(m.group(1))


def doc_numbers() -> dict[str, int]:
    """按**位置和形状**取数，不做全文搜索——同一数字在别处出现是正常的。"""
    text = read(GAPS)
    found: dict[str, int] = {}

    m = re.search(r"\|\s*\*\*ORPHAN\*\*\s*\|\s*\*\*(\d+)\*\*", text)
    if m:
        found["结果表"] = int(m.group(1))

    m = re.search(r"^### 剩下 (\d+) 个", text, re.M)
    if m:
        found["小节标题"] = int(m.group(1))

    # 进度表最后一行：孤儿数用 **N** 加粗，且该行以“第 X 批”开头
    rows = re.findall(r"^\| 第 \d+[^\n]*?\|\s*\*\*(\d+)\*\*[^\n]*\|$", text, re.M)
    if rows:
        found["进度表末行"] = int(rows[-1])

    m = re.search(r"当前基线 \*\*(\d+)\*\*", text)
    if m:
        found["防倒退正文"] = int(m.group(1))

    m = re.search(r"--max-orphans (\d+)", text)
    if m:
        found["示例命令"] = int(m.group(1))

    m = re.search(r"孤儿基线当前为 \*\*(\d+)\*\*", text)
    if m:
        found["基线注释"] = int(m.group(1))
    return found


def main() -> int:
    try:
        real = actual_orphans()
        baseline = gate_baseline()
        docs = doc_numbers()
    except RuntimeError as exc:
        print(f"[FAIL] 取数失败：{exc}")
        return 1

    check("取到了全部 6 处文档数字", len(docs) >= 5, f"命中 {sorted(docs)}")
    check(f"闸门基线 {baseline} 不小于实测 {real}", baseline >= real, f"实测={real} 基线={baseline}")
    for label, value in sorted(docs.items()):
        check(f"文档「{label}」等于实测 {real}", value == real, f"写作 {value}")

    if baseline > real:
        print(f"[提示] 实测已降到 {real}，闸门仍卡在 {baseline}：把 verify_all.py "
              f"的 --max-orphans 与文档一起下调，别只调一边。")
    print(f"\n合计 {len(FAILED)} 项失败")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
