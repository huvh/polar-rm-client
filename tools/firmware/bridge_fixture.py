#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""固件自检共用的"临时打桥"夹具。

为什么要有这个文件：`test_host_bridge` / `test_rc_key_ledger` /
`test_patch_real_headers` / `test_patch_logic` 收尾时都用过
`git checkout -- .`，本意是"把我刚装的桥撤掉"，实际是**把整棵树所有改动一起冲掉**——
包括 `prepare_hero_build.py` 刚写好的兵种 include 与 MOUSE_SENSITIVITY。
症状极难查：流水线照样报 GO，但车端配置已经被前面某个测试偷偷还原了
（本轮真发生过：英雄参数被冲回 100000.0f，新加的体检随即 FAIL）。

正确做法只有一个：**装之前按字节快照，收尾原样放回**。
别人的东西一个字节都不碰；原本不存在的未跟踪文件（新装的桥接头）收尾删掉。
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable


def stage(repo: Path, rels: Iterable[str]) -> dict:
    """给将要被改动的文件拍快照；原本不存在的记 None。"""
    snap: dict = {}
    owned = list(dict.fromkeys(rels))
    # The host bridge now installs both the task parser and the CDC callback.
    # Legacy callers naming usb_task must restore the ingress file as well.
    if "application/communication/usb_task.c" in owned and "Src/usbd_cdc_if.c" not in owned:
        owned.append("Src/usbd_cdc_if.c")
    for rel in owned:
        p = Path(repo) / rel
        snap[rel] = p.read_bytes() if p.exists() else None
    return snap


def restore(snap: dict, repo: Path) -> int:
    """把快照原样写回（None = 原本没有 ⇒ 删掉），返回处理了几个文件。"""
    n = 0
    for rel, data in snap.items():
        p = Path(repo) / rel
        if data is None:
            if p.exists():
                p.unlink()
            n += 1
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists() or p.read_bytes() != data:
            p.write_bytes(data)
        n += 1
    return n

