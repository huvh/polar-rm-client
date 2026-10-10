"""协议规格验证。

核心目的有两个：
1. **证明"抽成数据文件"是行为等价的** —— 规格里的表必须和 polar_link / robot_roles
   里原本硬编码的表逐项相同。不一致就说明抽取过程改了语义，那是引入风险而不是重构。
2. **证明坏规格不会把链路搞砖** —— 文件缺失/语法错/字段非法时必须返回 ok=False
   并带原因，绝不抛异常，让调用方回退到内置表。
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rm_client import robot_roles as roles  # noqa: E402
from rm_client.backend import polar_link as pl  # noqa: E402
from rm_client.backend import polar_spec as ps  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILED.append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


def test_spec_loads_and_validates() -> None:
    spec = ps.load_spec(ps.SPEC_PATH)
    check("规格文件存在", Path(spec.source).exists(), spec.source)
    check("规格校验通过（无 error）", spec.ok, spec.error_text())
    check("规格版本已声明", spec.spec_version >= 1, str(spec.spec_version))
    print(f"  [info] 规格告警：{spec.warning_text() or '（无）'}")


def test_segment_tables_match_code() -> None:
    """规格必须与 polar_link 里原本硬编码的表逐项一致。"""

    spec = ps.load_spec(ps.SPEC_PATH)
    builtin = dict(pl._SEGMENT_FORMATS)
    from_spec = dict(spec.segment_formats)

    only_spec = {k: v for k, v in from_spec.items() if k not in builtin}
    only_code = {k: v for k, v in builtin.items() if k not in from_spec}
    mismatched = {
        k: (builtin[k], from_spec[k])
        for k in set(builtin) & set(from_spec)
        if builtin[k] != from_spec[k]
    }
    check("规格段号集合 == 代码段号集合（无遗漏无多余）",
          not only_spec and not only_code, f"spec_only={only_spec} code_only={only_code}")
    check("每个段的 struct 格式串逐字节一致", not mismatched, str(mismatched))
    check("段数量符合预期（13 个可解码段 + 1 个特殊段）",
          len(from_spec) == len(builtin), f"{len(from_spec)} vs {len(builtin)}")

    # 段名也要对得上（HUD 与自检 JSON 用它）；SEGMENT_NAMES 定义在 bridge 里
    from rm_client.backend import polar_bridge as pb

    known_names = getattr(pb, "SEGMENT_NAMES", {})
    named = {k: v for k, v in spec.segment_names.items() if k in known_names}
    wrong_names = {k: (known_names[k], v) for k, v in named.items()
                   if known_names[k] != v}
    check("段名与 SEGMENT_NAMES 一致",
          bool(named) and not wrong_names, f"对比 {len(named)} 项：{str(wrong_names)[:80]}")


def test_uplink_invariants_match_code() -> None:
    spec = ps.load_spec(ps.SPEC_PATH)
    check("键位表与 RC_KEY_BITS 逐项一致", spec.key_bits == pl.RC_KEY_BITS,
          f"spec={spec.key_bits} code={pl.RC_KEY_BITS}")
    # 规格里存的是**硬件侧上限**。SHIFT 已废除（固件对它是边沿翻转，
    # 只能开不能关），所以上限现在与客户端默认值相同，都是 0x000F。
    check("规格 drive_key_mask == 客户端允许上限 RC_MAX_ALLOWED_KEY_MASK",
          spec.drive_key_mask == pl.RC_MAX_ALLOWED_KEY_MASK,
          f"0x{spec.drive_key_mask:04X} vs 0x{pl.RC_MAX_ALLOWED_KEY_MASK:04X}")
    check("客户端掩码只含 W/S/A/D",
          pl.RC_DRIVE_KEY_MASK == 0x000F and pl.drive_key_mask(False) == 0x000F,
          hex(pl.drive_key_mask(False)))
    # 上一版这条文案写“上限不含 Q/E/F”、条件却是 `== 0x001F`（含 SHIFT），
    # 文案与条件不符。现在改成真的按位检查，并把已废除的 SHIFT 一并卡住。
    dangerous = {n: b for n, b in pl.RC_KEY_BITS.items() if n not in ("W", "S", "A", "D")}
    leaked = sorted(n for n, b in dangerous.items() if spec.drive_key_mask & (1 << b))
    check("上限不含 Q/E/F 与已废除的 SHIFT（按位真检，不是硬编码相等）",
          not leaked and spec.drive_key_mask == 0x000F,
          f"泄露={leaked} mask=0x{spec.drive_key_mask:04X}")
    # allow_spin 参数已失去作用：无论传什么，SHIFT 都进不来。
    check("drive_key_mask(True) 也不放行 SHIFT（参数已无效）",
          pl.drive_key_mask(True) == 0x000F, hex(pl.drive_key_mask(True)))
    check("RC_MAX_ALLOWED_KEY_MASK 不再包含 SHIFT",
          not (pl.RC_MAX_ALLOWED_KEY_MASK & pl.RC_SPIN_KEY_MASK),
          hex(pl.RC_MAX_ALLOWED_KEY_MASK))
    # 告警必须是“信号”而不是噪声：合法规格（0x000F）不应触发任何告警。
    check("合法规格不触发任何告警",
          not spec.warnings,
          "; ".join(w.message for w in spec.warnings)[:120])
    check("fire 在 never_set 里（开火权不外移）", "fire" in spec.never_set_uplink_fields,
          str(spec.never_set_uplink_fields))

    # 规格里声明的 RobotCmd 结构必须和编码器用的完全一致
    rc = spec.raw["uplink"]["robot_cmd"]
    check("RobotCmd 结构串与编码器一致",
          rc["struct"] == _ROBOT_CMD_FMT, f"{rc['struct']} vs {_ROBOT_CMD_FMT}")
    vrc = spec.raw["uplink"]["virtual_rc"]
    check("VirtualRC 结构串与编码器一致",
          vrc["struct"] == pl.RC_CTRL_BODY_FORMAT,
          f"{vrc['struct']} vs {pl.RC_CTRL_BODY_FORMAT}")


_ROBOT_CMD_FMT = "<ffffffffffBBB"


def test_roles_match_code() -> None:
    spec = ps.load_spec(ps.SPEC_PATH)
    bad: list[str] = []
    for rid, limits in roles.ROLE_LIMITS_BY_ID.items():
        entry = spec.roles.get(rid)
        if entry is None:
            bad.append(f"{rid}: 规格里缺失")
            continue
        for key, code_value in (
            ("label", limits.label), ("chassis", limits.chassis),
            ("max_linear_mps", limits.max_linear_mps), ("max_yaw_rps", limits.max_yaw_rps),
            ("drivable", limits.drivable), ("gimbal_controllable", limits.gimbal_controllable),
            ("known", limits.known),
        ):
            if entry.get(key) != code_value:
                bad.append(f"{rid}.{key}: spec={entry.get(key)!r} code={code_value!r}")
    check("每个兵种的限幅与权限与代码表逐项一致", not bad, "; ".join(bad[:4]))
    check("未知编号兜底限速不高于步兵",
          float(spec.fallback_role.get("max_linear_mps", 99)) <= 1.5 + 1e-9,
          str(spec.fallback_role.get("max_linear_mps")))


def test_decoding_via_spec_matches_decoder() -> None:
    """用规格的 outputs 声明解出来的值，必须和现有解码函数完全一致。"""

    import struct as st

    spec = ps.load_spec(ps.SPEC_PATH)

    def apply_outputs(fmt, inputs, outputs, values):
        named = dict(zip(inputs, values))
        result = {}
        for out in outputs:
            src = out.get("from")
            if src is not None and "shift" not in out and "bit" not in out:
                result[out["name"]] = named[src]
            elif "from_index" in out:
                result[out["name"]] = values[int(out["from_index"])]
            elif "shift" in out:
                width = int(out.get("width", 1))
                result[out["name"]] = (named[src] >> int(out["shift"])) & ((1 << width) - 1)
            elif "bit" in out:
                result[out["name"]] = bool(named[src] & (1 << int(out["bit"])))
        return result

    # 0x0A RobotStatus：现有解码函数 vs 规格驱动
    values = st.unpack("<BBHHHHHfffBHHHH",
                       st.pack("<BBHHHHHfffBHHHH", 3, 2, 400, 480, 44, 120, 480,
                               1.5, 2.5, 137.0, (1 << 4) | 4, 168, 0, 25, 40))
    seg_id = pl.SEG_ROBOT_STATUS
    inputs = [str(n) for n in spec.raw["downlink_segments"][7]["inputs"]]
    via_spec = apply_outputs(None, inputs, spec.segment_outputs[seg_id], values)
    via_code = pl._SEGMENT_DECODERS[seg_id](values)
    diff = {k: (via_code.get(k), via_spec.get(k)) for k in set(via_code) | set(via_spec)
            if via_code.get(k) != via_spec.get(k)}
    check("0x0A 规格驱动解码 == 现有解码函数", not diff, str(diff))

    # 0x03 RobotStateInfo：位域最复杂，单独对拍
    values3 = st.unpack("<HB", st.pack("<HB", 0b1010_110_101_010_011, 0b10101))
    seg3 = pl.SEG_ROBOT_STATE_INFO
    entry3 = next(e for e in spec.raw["downlink_segments"] if e["id"] == "0x03")
    via_spec3 = apply_outputs(None, entry3["inputs"], spec.segment_outputs[seg3], values3)
    via_code3 = pl._SEGMENT_DECODERS[seg3](values3)
    diff3 = {k: (via_code3.get(k), via_spec3.get(k))
             for k in set(via_code3) | set(via_spec3) if via_code3.get(k) != via_spec3.get(k)}
    check("0x03 位域解码 == 现有解码函数", not diff3, str(diff3))


def test_bad_spec_fails_safe() -> None:
    """坏规格必须 ok=False + 带原因，且不抛异常（否则一个手滑就 brick 掉链路）。"""

    def load(text):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            fh.write(text)
            name = fh.name
        try:
            return ps.load_spec(name)
        finally:
            Path(name).unlink(missing_ok=True)

    missing = ps.load_spec(Path(tempfile.gettempdir()) / "definitely-not-here-9f3a.json")
    check("文件缺失时 ok=False 而不是抛异常", missing.ok is False and bool(missing.errors))

    broken = load("{ this is not json ")
    check("JSON 语法错时 ok=False", broken.ok is False and "语法" in broken.error_text(),
          broken.error_text()[:60])

    empty = load(json.dumps({"spec_version": 1, "downlink_segments": [],
                             "uplink": {}, "roles": []}))
    check("段表为空时拒绝整份规格", empty.ok is False, empty.error_text()[:60])

    bad_struct = load(json.dumps({
        "spec_version": 1, "uplink": {}, "roles": [{}],
        "downlink_segments": [{"id": "0x02", "name": "X", "struct": "<QQQ",
                               "inputs": ["a", "b"], "outputs": []}],
    }))
    check("inputs 数量与 struct 不符时拒绝", bad_struct.ok is False,
          bad_struct.error_text()[:80])

    bad_ref = load(json.dumps({
        "spec_version": 1, "uplink": {}, "roles": [{}],
        "downlink_segments": [{"id": "0x02", "name": "X", "struct": "<f",
                               "inputs": ["a"], "outputs": [{"name": "y", "from": "nope"}]}],
    }))
    check("输出引用不存在的输入时拒绝", bad_ref.ok is False, bad_ref.error_text()[:80])

    widen = load(json.dumps({
        "spec_version": 1,
        "downlink_segments": [{"id": "0x02", "name": "X", "struct": "<f",
                               "inputs": ["a"], "outputs": []}],
        "uplink": {"robot_cmd": {"never_set": []},
                   "virtual_rc": {"drive_key_mask": "0xFFFF",
                                  "key_bits": {"W": 0, "SHIFT": 4, "Q": 6, "E": 7, "F": 9}}},
        "roles": [{"robot_id": 3, "label": "步兵", "max_linear_mps": 1.5,
                   "max_yaw_rps": 2.0, "drivable": True, "gimbal_controllable": True,
                   "known": True}],
        "fallback_role": {"max_linear_mps": 1.5},
    }))
    check("放宽到含开火相关键位会告警",
          widen.ok and any("drive_key_mask" in (w.where + w.message) for w in widen.warnings),
          widen.warning_text()[:90])
    check("告警文案点名了具体危险键位 Q/E/F",
          any(("Q" in w.message and "E" in w.message and "F" in w.message)
              for w in widen.warnings),
          widen.warning_text()[:120])
    # 上一版这条是**恒真断言**：它检查 `"SHIFT 切小陀螺" not in message`，
    # 而那个字符串从未在任何告警文案里出现过，所以无论代码怎么写都 PASS。
    # 现在语义反了：SHIFT 已废除，它出现在掩码里就**应该**被点名。
    check("告警会点名已废除的 SHIFT（不是恒真断言）",
          any("SHIFT" in w.message for w in widen.warnings),
          widen.warning_text()[:160])
    check("fire 不在 never_set 里会告警",
          any("fire" in w.message for w in widen.warnings), widen.warning_text()[:90])


def test_spec_edit_actually_changes_behavior() -> None:
    """模块化的真正验收：改 JSON 必须改变行为，而不是改了不看。

    电控换固件后的典型动作就是改这个文件，所以“它能驱动代码”不是假设，
    必须被测到。
    """

    base = json.loads(Path(ps.SPEC_PATH).read_text(encoding="utf-8"))

    # 1) 改一个已有段的 struct：加载结果必须跟着变
    edited = json.loads(json.dumps(base))
    for seg in edited["downlink_segments"]:
        if seg["id"] == "0x1E":
            seg["struct"] = "<ffff"                 # 固件加了一个字段
            seg["inputs"].append("slip_ratio")
            seg["outputs"].append({"name": "slip_ratio", "from": "slip_ratio"})
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(edited, fh)
        edited_path = fh.name
    try:
        loaded = ps.load_spec(edited_path)
        check("改 struct 后规格确实带出新格式串",
              loaded.ok and loaded.segment_formats.get(pl.SEG_ROBOT_MOTION) == "<ffff",
              f"{loaded.segment_formats.get(pl.SEG_ROBOT_MOTION)} | {loaded.error_text()[:60]}")
        outs = {o["name"] for o in loaded.segment_outputs[pl.SEG_ROBOT_MOTION]}
        check("新增输出字段被规格声明带出", "slip_ratio" in outs, str(sorted(outs)))
    finally:
        Path(edited_path).unlink(missing_ok=True)

    # 2) 新增一个固件段：必须能被登记（这就是“不用改 Python”的含义）
    added = json.loads(json.dumps(base))
    added["downlink_segments"].append({
        "id": "0x2A", "name": "NewFirmwareSegment", "struct": "<ff",
        "inputs": ["alpha", "beta"],
        "outputs": [{"name": "alpha", "from": "alpha"}, {"name": "beta", "from": "beta"}],
    })
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(added, fh)
        added_path = fh.name
    try:
        loaded2 = ps.load_spec(added_path)
        check("新增段无需改代码即可被登记",
              loaded2.ok and loaded2.segment_formats.get(0x2A) == "<ff",
              str(loaded2.segment_formats.get(0x2A)))
        check("新增段不影响原有段",
              loaded2.segment_formats.get(pl.SEG_ROBOT_STATUS) == "<BBHHHHHfffBHHHH")
    finally:
        Path(added_path).unlink(missing_ok=True)

    # 3) 放宽驾驶掩码：能加载，但必须告警（安全参数可以改，但不能悄悄改）
    widened = json.loads(json.dumps(base))
    widened["uplink"]["virtual_rc"]["drive_key_mask"] = "0x00FF"
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(widened, fh)
        widened_path = fh.name
    try:
        loaded3 = ps.load_spec(widened_path)
        check("放宽掩码会被告警拦住（可改但不静默）",
              loaded3.ok and any("drive_key_mask" in w.message or "键位" in w.message
                                 for w in loaded3.warnings),
              loaded3.warning_text()[:80])
    finally:
        Path(widened_path).unlink(missing_ok=True)


def test_new_segment_needs_no_python() -> None:
    """只在 JSON 里声明一个新下行段，不改任何 Python，它要能解码并落库。

    这才是“模块化电控代码”的真正验收：否则 AGENT.md 里那句“只需改规格”
    就是假的。本测试不往仓库里加段，而是把临时规格注入到两个缓存点。
    """

    import struct as st

    from rm_client.backend import polar_bridge as pb
    from rm_client.backend import polar_link as pl

    base = json.loads(Path(ps.SPEC_PATH).read_text(encoding="utf-8"))
    edited = json.loads(json.dumps(base))
    edited["downlink_segments"].append({
        "id": "0x3C",
        "name": "FirmwareAddedSegment",
        "struct": "<fH",
        "inputs": ["pressure", "fault_bits"],
        "outputs": [
            {"name": "barrel_pressure", "from": "pressure"},
            {"name": "jam", "from": "fault_bits", "bit": 0},
            {"name": "overheat", "from": "fault_bits", "bit": 3},
        ],
        # 只写这一行，就能让新段落进 overlay —— 下面验证它真生效
        "state_fields": {"barrel_pressure": "polar_barrel_pressure",
                         "jam": "polar_barrel_jam"},
    })
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(edited, fh)
        edited_path = fh.name
    try:
        loaded = ps.load_spec(edited_path)
        check("新规格校验通过（含 state_fields）", loaded.ok, loaded.error_text())
        check("新段格式串被登记", loaded.segment_formats.get(0x3C) == "<fH",
              str(loaded.segment_formats.get(0x3C)))
        check("新段 state_fields 被收集",
              loaded.segment_state_fields.get(0x3C) == {
                  "barrel_pressure": "polar_barrel_pressure",
                  "jam": "polar_barrel_jam"},
              str(loaded.segment_state_fields.get(0x3C)))

        # 注入到两个缓存点（等价于“重启后读到新规格”），不改任何产品代码
        pl._SEGMENT_FORMATS[0x3C] = loaded.segment_formats[0x3C]
        pl._SEGMENT_OUTPUTS[0x3C] = loaded.segment_outputs[0x3C]
        pl._SEGMENT_INPUTS[0x3C] = ["pressure", "fault_bits"]
        pb._STATE_FIELDS_CACHE = dict(loaded.segment_state_fields)

        # 直接走通用解码 + 通用落库
        values = st.unpack("<fH", st.pack("<fH", 2.75, 0b1001))
        fields = pl.apply_spec_outputs(["pressure", "fault_bits"],
                                       loaded.segment_outputs[0x3C], values)
        check("新段无需专用解码器即可解出具名字段",
              fields.get("barrel_pressure") == 2.75 and fields.get("jam") is True
              and fields.get("overheat") is True, str(fields))

        bridge = pb.PolarStateBridge()
        seg = pl.PolarSegment(0x3C, 1234, fields)
        before_dropped = bridge.dropped
        bridge.apply(seg)
        check("新段无需专用处理器即可落进 overlay",
              bridge.overlay.get("polar_barrel_pressure") == 2.75
              and bridge.overlay.get("polar_barrel_jam") is True,
              str({k: v for k, v in bridge.overlay.items() if "barrel" in k}))
        check("新段不被计为丢弃", bridge.dropped == before_dropped,
              f"{before_dropped} -> {bridge.dropped}")
        check("新段会刷新链路新鲜期", bridge.link_age_s < 5.0, str(bridge.link_age_s))

        # 没声明 state_fields 的段仍要被丢弃，不能静默产生假数据
        pb._STATE_FIELDS_CACHE = {}
        bridge2 = pb.PolarStateBridge()
        bridge2.apply(pl.PolarSegment(0x3C, 1, fields))
        check("无 state_fields 声明时仍计为丢弃（不造假数据）",
              bridge2.dropped == 1 and "polar_barrel_pressure" not in bridge2.overlay,
              f"dropped={bridge2.dropped}")
    finally:
        pb._STATE_FIELDS_CACHE = None
        for table in (pl._SEGMENT_FORMATS, pl._SEGMENT_OUTPUTS, pl._SEGMENT_INPUTS):
            table.pop(0x3C, None)
        Path(edited_path).unlink(missing_ok=True)


def main() -> int:
    test_spec_loads_and_validates()
    test_segment_tables_match_code()
    test_uplink_invariants_match_code()
    test_roles_match_code()
    test_decoding_via_spec_matches_decoder()
    test_bad_spec_fails_safe()
    test_spec_edit_actually_changes_behavior()
    test_new_segment_needs_no_python()
    print("\n" + "=" * 62)
    if FAILED:
        print(f"FAILED {len(FAILED)}: {', '.join(FAILED)}")
        return 1
    print("ALL POLAR SPEC TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
