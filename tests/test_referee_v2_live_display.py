"""Pure/AST V2 display controls. No full facade, Qt, device or publisher imports.

External overlays and import/acquisition guards belong to the external runner.
Actual registered-profile callback/drain and offscreen Qt acceptance are separate
integration checks; these controls do not claim those have run.
"""
from __future__ import annotations

import ast
import copy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest

import rm_client
from rm_client import student_ui as ui
from rm_client.backend.referee.rm2026_v2 import codec
from rm_client.backend.referee.rm2026_v2.observations import observe

ROOT = Path(__file__).resolve().parents[1]
PANEL_PATH = ROOT / "rm_client/ui/student_panels.py"
if not PANEL_PATH.is_file():
    PANEL_PATH = Path(rm_client.__file__).resolve().parent / "ui/student_panels.py"
PANEL_SOURCE = PANEL_PATH.read_text(encoding="utf-8")
PANEL_TREE = ast.parse(PANEL_SOURCE)
OWNER = next(node for node in PANEL_TREE.body if isinstance(node, ast.FunctionDef) and node.name == "_v2_live_rows")
RENDERER = next(node for node in PANEL_TREE.body if isinstance(node, ast.ClassDef) and node.name == "StudentPanelRenderer")
CONTENT = copy.deepcopy(next(node for node in RENDERER.body if isinstance(node, ast.FunctionDef) and node.name == "content_rows"))
CONTENT.name = "content_rows"
clock = SimpleNamespace(perf_counter=lambda: 100.0)
ns = dict(vars(ui), time=clock)
exec(compile(ast.fix_missing_locations(ast.Module(body=[OWNER, CONTENT], type_ignores=[])), "<actual pure renderer methods>", "exec"), ns)

V2 = "rm2026-v2.0.0"
ARGS = dict(now=100.0, profile_id=V2, connected=True, receive_generation=3, client_id="6")
G = "GameStatus"
A = "AirSupportStatusSync"
S = "SentryStatusSync"


def state(**changes):
    values = dict(referee_profile=V2, robot_id=6, current_round=1,
                  current_stage="SETTLEMENT", settlement_round=1,
                  game_result=0, end_reason=7, sentry_status={},
                  air_support_active=False, air_support_free_time_sec=0,
                  air_support_cost_coins=0, air_support_is_being_targeted=None,
                  air_support_shooter_status=None, student_ui_data={})
    values.update(changes)
    return SimpleNamespace(**values)


def receive(previous=None, *, message=G, payload=b"\x08\x01\x28\x05\x48\x00\x50\x07", at=100.0):
    # Independent literal bytes; no use of the implementation's field encoder.
    data = codec.decode_message(message, payload)
    return observe(previous, profile_id=V2, receive_generation=3, client_id="6",
                   message=message, data=data, received_at=at)


def change(snapshot, message, field, *, value=None, receipt=None, omit=False):
    observations = []
    for item in snapshot.observations:
        if (item.message, item.field) == (message, field):
            if omit:
                continue
            item = replace(item, value=item.value if value is None else value,
                           received_at=item.received_at if receipt is None else receipt)
        observations.append(item)
    return replace(snapshot, observations=tuple(observations))


def outcomes(s=None, snapshot=None, **kwargs):
    return dict(ui.v2_settlement_rows(s or state(), snapshot or receive(), **(ARGS | kwargs)))


def host(snapshot=None):
    profile = SimpleNamespace(profile_id=V2)
    mqtt = SimpleNamespace(referee=profile, client=object(), receive_generation=3,
                           client_id="6", connected=True, snapshot=snapshot or receive())
    mqtt.v2_wire_snapshot = lambda: mqtt.snapshot
    backend = SimpleNamespace(referee=profile, mqtt=mqtt, scenario_key="official")
    return SimpleNamespace(backend=backend, state=state(),
                           student_ui=SimpleNamespace(panel="settlement", settlement=(("基地血量", "4000"),)))


class LiveV2Display(unittest.TestCase):
    def test_explicit_draw_and_all_nine_reasons(self):
        self.assertEqual(outcomes()["本局结果（当前）"], "平局")
        for value, label in ((0, "平局"), (1, "红方胜利"), (2, "蓝方胜利")):
            snapshot = receive(payload=b"\x08\x01\x28\x05\x48" + bytes([value]))
            self.assertEqual(outcomes(state(game_result=value), snapshot)["本局结果（当前）"], label)
        expected = ("基地被摧毁", "基地剩余血量", "前哨站剩余血量", "前哨站是否被击毁过",
                    "全队总攻击伤害", "全队机器人总剩余血量", "平局", "异常终止", "主裁判手动判定胜负")
        for reason, label in enumerate(expected, 1):
            snapshot = receive(payload=b"\x08\x01\x28\x05\x50" + bytes([reason]))
            self.assertEqual(outcomes(state(end_reason=reason), snapshot)["结束原因（当前）"], label)

    def test_model_defaults_and_raw_unknowns_never_become_winner(self):
        missing = receive(payload=b"\x08\x01\x28\x05")
        self.assertIn("未收到", outcomes(snapshot=missing)["本局结果（当前）"])
        for raw in (3, 99, 255):
            snapshot = change(receive(), G, "game_result", value=raw)
            text = outcomes(state(game_result=raw), snapshot)["本局结果（当前）"]
            self.assertNotIn("胜利", text)
            self.assertNotEqual(text, "平局")
        for raw in (0, 10, 255):
            snapshot = change(receive(), G, "end_reason", value=raw)
            self.assertNotIn("平局", outcomes(state(end_reason=raw), snapshot)["结束原因（当前）"])
        for wrong in (None, True, 0.0, "0"):
            self.assertIn("不可用", outcomes(state(game_result=wrong))["本局结果（当前）"])

    def test_each_own_receipt_is_inclusively_fresh(self):
        for field in ("current_round", "current_stage", "game_result", "end_reason"):
            for receipt, valid in ((100.0, True), (98.0, True), (97.999, False), (100.001, False),
                                   (-1, False), (True, False), ("100", False), (float("nan"), False),
                                   (float("inf"), False), (10**1000, False)):
                snapshot = change(receive(), G, field, receipt=receipt)
                rows = outcomes(snapshot=snapshot)
                key = "结束原因（当前）" if field == "end_reason" else "本局结果（当前）"
                self.assertEqual("不可用" not in rows[key], valid, (field, receipt))
        for now in (None, True, "100", -1, float("nan"), float("inf"), 10**1000):
            self.assertIn("不可用", outcomes(now=now)["本局结果（当前）"])

    def test_round_stage_owner_and_canonical_equality(self):
        for field in ("current_round", "current_stage"):
            self.assertIn("不可用", outcomes(snapshot=change(receive(), G, field, omit=True))["本局结果（当前）"])
        for changed in (dict(current_round=2), dict(settlement_round=None), dict(settlement_round=2),
                        dict(current_stage="MATCH"), dict(referee_profile="rm2026-v1.3.1"),
                        dict(robot_id=106), dict(game_result=2)):
            self.assertIn("不可用", outcomes(state(**changed))["本局结果（当前）"])
        for changed in (dict(connected=False), dict(receive_generation=4), dict(client_id="106")):
            self.assertIn("不可用", outcomes(**changed)["本局结果（当前）"])
        for profile in ("rm2026-v1.3.1", "student", "unknown", "rm2026-v2"):
            self.assertEqual(outcomes(profile_id=profile), {})
        new_round = receive(receive(), payload=b"\x08\x02", at=100.1)
        self.assertIn("不可用", outcomes(state(current_round=2), new_round, now=100.1)["本局结果（当前）"])
        stage_exit = receive(receive(), payload=b"\x28\x04", at=100.1)
        self.assertIn("不可用", outcomes(state(current_stage="MATCH"), stage_exit, now=100.1)["本局结果（当前）"])

    def test_late_partials_update_actual_panel_content_without_mutating_frozen_stats(self):
        h = host(receive(payload=b"\x08\x01\x28\x05"))
        frozen = h.student_ui.settlement
        h.state.game_result = h.state.end_reason = None
        initial = ns["content_rows"](None, h)
        h.backend.mqtt.snapshot = receive(h.backend.mqtt.snapshot, payload=b"\x48\x01", at=100.1)
        clock.perf_counter = lambda: 100.1
        queued = ns["content_rows"](None, h)
        self.assertIn("尚未同步", queued[0][1])
        h.state.game_result = 1
        result = ns["content_rows"](None, h)
        self.assertEqual(result[0][1], "红方胜利")
        self.assertNotEqual(str(initial), str(result))
        h.backend.mqtt.snapshot = receive(h.backend.mqtt.snapshot, payload=b"\x50\x09", at=100.2)
        h.state.end_reason = 9
        clock.perf_counter = lambda: 100.2
        final = ns["content_rows"](None, h)
        self.assertEqual(final[1][1], "主裁判手动判定胜负")
        self.assertEqual(final[2:], frozen)
        self.assertIs(h.student_ui.settlement, frozen)
        # A fresh reason/round/stage sibling never refreshes result's receipt.
        h.backend.mqtt.snapshot = receive(h.backend.mqtt.snapshot,
            payload=b"\x08\x01\x28\x05\x50\x09", at=102.2)
        clock.perf_counter = lambda: 102.2
        expired = ns["content_rows"](None, h)
        self.assertIn("已过期", expired[0][1])
        self.assertEqual(expired[1][1], "主裁判手动判定胜负")
        clock.perf_counter = lambda: 100.0

    def test_legacy_panel_never_reads_mqtt_or_unfreezes_statistics(self):
        for profile in ("rm2026-v1.3.1", "student", "unknown"):
            h = host()
            h.backend.referee.profile_id = profile
            h.backend.mqtt.v2_wire_snapshot = lambda: self.fail("legacy snapshot read")
            h.state.current_stage = "MATCH"
            self.assertIs(ns["content_rows"](None, h), h.student_ui.settlement)

    def test_renderer_rechecks_current_owner_and_disconnect_reconnect(self):
        h = host()
        self.assertEqual(ns["content_rows"](None, h)[0][1], "平局")
        h.backend.mqtt.connected = False
        self.assertIn("未连接", ns["content_rows"](None, h)[0][1])
        h.backend.mqtt.connected = True
        h.backend.mqtt.receive_generation += 1
        h.backend.mqtt.snapshot = None
        self.assertIn("不可用", ns["content_rows"](None, h)[0][1])
        for target, attr, value in (("mqtt", "client", object()), ("mqtt", "receive_generation", 4),
                                     ("mqtt", "connected", False), ("backend", "scenario_key", "preview"),
                                     ("backend", "referee", SimpleNamespace(profile_id=V2))):
            h = host()
            mqtt, snapshot = h.backend.mqtt, h.backend.mqtt.snapshot
            calls = []
            def read():
                calls.append(1)
                if len(calls) == 1:
                    setattr(mqtt if target == "mqtt" else h.backend, attr, value)
                return snapshot
            mqtt.v2_wire_snapshot = read
            self.assertIn("不可用", ns["content_rows"](None, h)[0][1], (target, attr))

    def test_sentry_false_is_observed_and_omission_does_not_refresh(self):
        s = state(sentry_status={"is_powered": True})
        snapshot = receive(receive(), message=S, payload=b"\x18\x01")
        self.assertEqual(dict(ui.v2_status_rows(s, snapshot, **ARGS))["哨兵强化（观测）"], "已强化")
        snapshot = receive(snapshot, message=S, payload=b"\x08\x01", at=101.0)
        self.assertEqual(dict(ui.v2_status_rows(s, snapshot, **ARGS))["哨兵强化（观测）"], "已强化")
        self.assertIn("已过期", dict(ui.v2_status_rows(s, snapshot, **(ARGS | {"now": 102.001})))["哨兵强化（观测）"])
        snapshot = receive(receive(), message=S, payload=b"\x18\x00")
        s.sentry_status["is_powered"] = False
        self.assertEqual(dict(ui.v2_status_rows(s, snapshot, **ARGS))["哨兵强化（观测）"], "未强化")
        self.assertIn("未收到", dict(ui.v2_status_rows(s, receive(), **ARGS))["哨兵强化（观测）"])

    def test_air_observations_are_independent_partial_and_never_eligibility(self):
        s = state(air_support_is_being_targeted=0, air_support_shooter_status=0)
        snapshot = receive(receive(), message=A, payload=b"\x08\x00\x10\x00\x18\x00\x20\x00\x28\x00")
        rows = dict(ui.v2_status_rows(s, snapshot, **ARGS))
        self.assertEqual(rows["空中支援（观测）"], "未支援")
        self.assertEqual(rows["免费剩余（观测）"], "0 s")
        self.assertEqual(rows["累计支出（观测）"], "0 金币")
        self.assertEqual(rows["空中照射（观测）"], "未被照射")
        for shooter, text in ((0, "锁定 / 不可解除"), (1, "正常"), (2, "锁定 / 可付费解除"), (99, "未知值（99）")):
            snapshot = change(snapshot, A, "shooter_status", value=shooter)
            s.air_support_shooter_status = shooter
            self.assertEqual(dict(ui.v2_status_rows(s, snapshot, **ARGS))["发射机构（观测）"], text)
        snapshot = change(snapshot, A, "is_being_targeted", value=99)
        s.air_support_is_being_targeted = 99
        self.assertEqual(dict(ui.v2_status_rows(s, snapshot, **ARGS))["空中照射（观测）"], "未知值（99）")
        snapshot = change(snapshot, A, "shooter_status", omit=True)
        self.assertIn("未收到", dict(ui.v2_status_rows(s, snapshot, **ARGS))["发射机构（观测）"])
        for field in ("airsupport_status", "left_time", "cost_coins", "is_being_targeted"):
            stale = change(snapshot, A, field, receipt=97.99)
            self.assertGreater(str(ui.v2_status_rows(s, stale, **ARGS)).count("已过期"), 0)
        self.assertNotIn("资格", str(rows))
        self.assertNotIn("确认成功", str(rows))

    def test_ast_visible_cache_and_no_publish_or_canonical_writes(self):
        for node in ast.walk(OWNER):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertFalse(node.func.attr.startswith(("publish", "send", "set_")))
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                self.assertFalse(any(isinstance(target, ast.Attribute) for target in targets))
        draw = next(node for node in RENDERER.body if isinstance(node, ast.FunctionDef) and node.name == "draw")
        self.assertEqual(sum(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                             and node.func.attr == "content_rows" for node in ast.walk(draw)), 1)
        self.assertIn("str(content_rows)", ast.unparse(draw))
        self.assertIn("rows=content_rows", ast.unparse(draw))
        status = next(node for node in RENDERER.body if isinstance(node, ast.FunctionDef) and node.name == "draw_status")
        self.assertIn("_v2_live_rows", ast.unparse(status))
        pure = ast.parse(Path(ui.__file__).read_text(encoding="utf-8"))
        # Catalog construction imports this module through model.py. Keep the
        # entire deferred graph free of backend/Qt dependencies, not just its
        # top-level imports; actual ownership is checked in the renderer.
        for node in ast.walk(pure):
            if isinstance(node, ast.Import):
                self.assertTrue(all(alias.name.split(".")[0] in {"math", "dataclasses", "typing"}
                                    for alias in node.names))
            elif isinstance(node, ast.ImportFrom):
                self.assertIn(node.module, {"__future__", "dataclasses", "typing", "module_settings"})
        for function in pure.body:
            if isinstance(function, ast.FunctionDef) and (function.name.startswith("v2_") or function.name.startswith("_v2_")):
                self.assertNotIn("publish", ast.unparse(function))
                for node in ast.walk(function):
                    if isinstance(node, ast.Assign):
                        self.assertFalse(any(isinstance(target, ast.Attribute) for target in node.targets))


if __name__ == "__main__":
    unittest.main()
