#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# broker 地址（MQTTLink Host/Port）必须真的决定连到哪儿，界面不许显示没在用的地址。
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent          # 本文件在 <仓库>/tools/ 下
sys.path.insert(0, str(ROOT))

from rm_client.backend.manager import BackendManager        # noqa: E402
from rm_client.model import RobotState, build_default_registry  # noqa: E402
from rm_client.scenarios import SCENARIOS                   # noqa: E402

FAILED = 0


def check(name, ok, detail=""):
    global FAILED
    print(f"{'[ OK ]' if ok else '[FAIL]'} {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        FAILED += 1


def main() -> int:
    import tempfile
    print("\n--- broker 地址接线 ---")
    manager, registry = None, None
    with tempfile.TemporaryDirectory() as td:
        manager = BackendManager(workspace=td, scenario_key="LabDebug", client_id="3")
        manager.state = RobotState()
        manager._apply_config(manager.config)
        registry = build_default_registry()
        module = registry.get("MQTTLink")
        check("MQTTLink 有 Host/Port 两项", module.get_setting("Host") is not None
              and module.get_setting("Port") is not None)
        check("实验室场景初值 127.0.0.1:3333",
              (manager.mqtt.host, manager.mqtt.port) == ("127.0.0.1", 3333),
              f"{manager.mqtt.host}:{manager.mqtt.port}")
        # 1) 改设置项 -> 后端真的换地址
        module.get_setting("Host").value = "192.168.12.1"
        module.get_setting("Port").value = 3334
        manager.sync_mqtt_link(registry)
        check("改 Host/Port 设置项就换 broker（以前改了没人读）",
              (manager.mqtt.host, manager.mqtt.port) == ("192.168.12.1", 3334),
              f"{manager.mqtt.host}:{manager.mqtt.port}")
        # 2) 已经连着 -> 必须重连，不能只改字段
        hits = []
        manager.mqtt._started = True
        manager.mqtt.stop = lambda publish_status=True: hits.append(("stop", publish_status))
        manager.mqtt.start = lambda: hits.append(("start",))
        module.get_setting("Host").value = "10.0.0.9"
        manager.sync_mqtt_link(registry)
        check("已连接时换地址会断开重连（赋值不等于重连）",
              ("stop", False) in hits and ("start",) in hits, str(hits))
        manager.mqtt._started = False
        # 3) 幂等：同一套设置不得每拍都重连
        hits.clear()
        manager.sync_mqtt_link(registry)
        manager.sync_mqtt_link(registry)
        check("重复 tick 不会反复重连", hits == [], str(hits))
        # 4) 非法输入 -> 沿用有效值，并把有效值写回设置项（界面不骗人）
        manager.mqtt.stop = lambda publish_status=True: None
        good = (manager.mqtt.host, manager.mqtt.port)
        module.get_setting("Host").value = "   "
        module.get_setting("Port").value = 1
        note = manager.sync_mqtt_link(registry)
        check("空地址/非法端口不改用、并写明原因",
              (manager.mqtt.host, manager.mqtt.port) == good and "非法" in note, note)
        check("设置项被回写成真正在用的地址（界面显示的不许是假的）",
              str(module.get_setting("Host").value) == good[0]
              and int(module.get_setting("Port").value) == good[1],
              f"{module.get_setting('Host').value}:{module.get_setting('Port').value}")
        # 5) 真实切场景（UI 走的是 ScenarioManager，不是 _apply_config）：
        #    界面设置项 + 后端地址 + 重连三件事必须同时对，切完还得连着正式赛那台
        from rm_client.scenarios import ScenarioManager
        official = SCENARIOS["OfficialEvent"]
        sm = ScenarioManager()
        sm.set_scenario("OfficialEvent")
        hits.clear()
        manager.mqtt._started = True
        sm.apply_to_registry(registry)
        ctl = type('Ctl', (), {'mock_output': True})()
        sm.apply_to_runtime(manager.mqtt, manager.udp, ctl)
        manager.sync_mqtt_link(registry)
        manager.mqtt._started = False
        check("切到正式赛场景 -> broker 变 192.168.12.1",
              manager.mqtt.host == official.connection.mqtt_host == "192.168.12.1",
              str(manager.mqtt.host))
        check("已经连着时切场景会断开重连（赋值不等于重连，这是老 bug）",
              ("start",) in hits, str(hits))
        # 断言必须咬住场景标志：永真的"False or True"是假绿，写测试时最容易骗自己
        check("切场景按 allow_mqtt_publish 决定键鼠是否真发（不许写永真断言）",
              ctl.mock_output is not bool(official.safety.allow_mqtt_publish)
              and bool(official.safety.allow_mqtt_publish) is True,
              f"mock={ctl.mock_output} allow_publish={official.safety.allow_mqtt_publish}")
        check("切场景后界面显示值 = 真正在用的地址",
              str(module.get_setting("Host").value) == manager.mqtt.host,
              str(module.get_setting("Host").value))
    print("\n" + ("有失败项" if FAILED else "broker 地址接线全部通过"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
