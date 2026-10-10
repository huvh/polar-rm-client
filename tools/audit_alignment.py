#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""前后端对齐**证据采集**：逐个模块列出它在代码里被引用的位置。

这个工具刻意**不下结论**
------------------------
它有过两版会自动给模块打 ALIGNED/OFFICIAL/GAP 标签，两版都产出了
看起来很像真的、实际错误的结论：

  - `FireControlStub` 被判 ALIGNED，因为匹配到了 `fire`
    —— 而 `fire` 恰恰是设计上**永不置位**的字段（开火权不外移）；
  - `SentinelCommand` 被判 ALIGNED，因为匹配到了下行 `sentry` 段
    —— 那是机器人**上报**哨兵信息，不代表客户端能指挥哨兵；
  - `MQTTLink` 被判成队内链路 —— 它其实是官方链路；
  - `HeroLob` 因为我编的别名 `lob` 命中了无关代码。

根因：**字面引用扫描无法区分"被提到"和"有真实下发出口"**。
"提到"可能出现在注释、告警文案、上行读取、never_set 声明里，
这些都不是出口。让脚本猜，就会把猜测包装成结论。

所以本工具只输出可复核的事实：每个模块名在哪些文件的哪些行出现过。
**判定由人做**，写在 tools/firmware/host_bridge/GAPS.md 里，
并在那里标注每条判定的依据与置信度。

用法
----
    python tools/audit_alignment.py                     # 全部模块的引用位置
    python tools/audit_alignment.py --module SpinMode   # 只看一个
    python tools/audit_alignment.py --json out.json

退出码始终 0：这是取证工具，不是断言。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

# 必须在导入 rm_client 之前设置：本脚本会构造真实 registry。
# 用临时目录，绝不污染开发机存档。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if not os.environ.get("POLAR_USER_DATA_ROOT", "").strip():
    os.environ["POLAR_USER_DATA_ROOT"] = tempfile.mkdtemp(prefix="polar_audit_")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: 扫描范围。分成两组，因为"出现在哪里"本身就是重要信息：
#:   backend/  里出现 -> 可能与队内 0x5A 链路有关（但也可能只是注释/告警）
#:   ui/       里出现 -> 界面侧，通常是本地行为或官方链路
SCAN_GROUPS: tuple[tuple[str, Path, str], ...] = (
    ("backend", ROOT / "rm_client" / "backend", "*.py"),
    ("ui", ROOT / "rm_client" / "ui", "**/*.py"),
    ("toplevel", ROOT / "rm_client", "*.py"),
    ("spec", ROOT / "rm_client" / "backend", "polar_protocol.json"),
)

#: 这些行的引用**几乎肯定不是出口**，单独标出来供人快速排除。
#: 只做提示，不做判定——判定权在人。
NON_EGRESS_HINTS = (
    ("never_set", "出现在 never_set 声明里：这是\"永不发送\"，不是出口"),
    ("consumer_status", "出现在 consumer_status 说明里：描述固件有没有消费者"),
    ("availability", "出现在 availability 说明里：描述该段是否真的会发"),
    ("#", "注释行"),
    ("告警", "告警/提示文案"),
    ("warning", "告警/提示文案"),
)


def _iter_files() -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for group, base, pattern in SCAN_GROUPS:
        if not base.exists():
            continue
        for p in sorted(base.glob(pattern)):
            if p.is_file() and p not in seen:
                seen.add(p)
                out.append((group, p))
    return out


def scan(name: str, files: list[tuple[str, Path]]) -> list[dict[str, str]]:
    """返回该模块名的所有引用位置（文件:行号 + 该行内容 + 非出口提示）。"""
    # 词边界匹配，避免 "ESP" 命中 "SPECIAL" 这类假阳性。
    # 短名字（<=3 字符）不开忽略大小写，否则 "HUD" 会命中 "hud_" 之外的一堆东西。
    pat = re.compile(
        rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])",
        re.IGNORECASE if len(name) > 3 else 0,
    )
    hits: list[dict[str, str]] = []
    for group, path in files:
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            if not pat.search(line):
                continue
            stripped = line.strip()
            hint = ""
            for needle, text in NON_EGRESS_HINTS:
                if needle in stripped:
                    hint = text
                    break
            hits.append({
                "group": group,
                "file": str(path.relative_to(ROOT)).replace(os.sep, "/"),
                "line": str(i),
                "text": stripped[:150],
                "hint": hint,
            })
    return hits


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--module", default=None, help="只看这一个模块")
    ap.add_argument("--json", type=Path, default=None, help="把结果写成 JSON")
    ap.add_argument("--backend-only", action="store_true",
                    help="只列 backend/ 里的引用（最可能与队内链路相关）")
    args = ap.parse_args(argv)

    from rm_client.model import build_default_registry

    registry = build_default_registry()
    modules = registry.modules
    items = (modules.items() if hasattr(modules, "items")
             else [(getattr(m, "name", "?"), m) for m in modules])
    names = [str(getattr(mod, "name", key) or key) for key, mod in items]
    categories = {str(getattr(mod, "name", key) or key):
                  str(getattr(mod, "category", "") or "") for key, mod in items}
    if args.module:
        names = [n for n in names if n == args.module]
        if not names:
            print(f"[FAIL] 没有名为 {args.module!r} 的模块")
            return 2

    files = _iter_files()
    result: dict[str, object] = {}
    for name in names:
        hits = scan(name, files)
        if args.backend_only:
            hits = [h for h in hits if h["group"] in ("backend", "spec")]
        result[name] = {"category": categories.get(name, ""), "hits": hits}

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[OK] 已写出 {args.json}")

    print(f"扫描文件数：{len(files)}    模块数：{len(names)}")
    print("=" * 100)
    for name in names:
        info = result[name]
        hits = info["hits"]  # type: ignore[index]
        backend = [h for h in hits if h["group"] in ("backend", "spec")]
        print(f"\n### {name}  (分类={info['category']})")  # type: ignore[index]
        print(f"    引用总数 {len(hits)}，其中 backend/规格 {len(backend)}")
        if not hits:
            print("    （代码里完全没有出现这个名字）")
        for h in (backend if args.backend_only else hits)[:12]:
            flag = f"  <- {h['hint']}" if h["hint"] else ""
            print(f"    {h['file']}:{h['line']}  {h['text'][:88]}{flag}")
        if len(hits) > 12 and not args.backend_only:
            print(f"    ...（另有 {len(hits) - 12} 处）")

    print("\n" + "=" * 100)
    print(
        "如何读这份输出（重要）：\n"
        "  1) \"backend 里有引用\" **不等于** \"有下发出口\"。引用可能来自注释、\n"
        "     告警文案、上行读取、或 never_set（永不发送）声明——带 `<-` 提示的\n"
        "     基本可以排除。\n"
        "  2) 判定一条通路是否真的通，唯一可靠的办法是看 tests/ 里的端到端断言：\n"
        "     从模块状态一直追到上线字节。自转（SpinMode）就是这么修的。\n"
        "  3) 人工判定结果写在 tools/firmware/host_bridge/GAPS.md，\n"
        "     那里每条都标了依据与置信度。\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
