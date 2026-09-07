"""阶段 3f 大域 mixin 化：动作处理 / 配置动作 / 资格赛（D16）→ ConfigActionsMixin。

（REFACTOR_BLUEPRINT §5 阶段 3 表 3f 行 / §2 D16 节 / §5.6 冻结面）

迁移范围（以 grep 重定位后的实际行号为准，蓝图原行号已漂移；单一连续区块
polar_app.py 4093–4843）：
- 设置变更回调：``after_setting_changed``
- 配置动作路由：``handle_config_action``
- 资格赛流程：``handle_qualification_action`` /
  ``start_kmc_qualification_test``（KMC 75Hz 心跳资格赛）
- 紧凑 HUD 恢复：``restore_compact_hud``
- 模块开关联动：``on_module_toggled``
- GUI 音效 / 击杀特效预览 / 标定动作：
  ``play_gui_transition_sound`` / ``preview_elimination_fx`` /
  ``handle_calibration_action``

纪律与特别注意（蓝图 3f 行，保守边界中文注明）：
- 类内方法体**零修改**（含注释与空行），纯移动进本 Mixin；
- **唯一例外**（语义等价、非行为修改）：``handle_qualification_action``
  内的局部导入 ``from ..preflight import run_preflight`` 因文件包层级从
  rm_client/ui/ 深化为 rm_client/ui/polar/mixins/ 重定位为
  ``from ....preflight import run_preflight``——两者均解析到同一模块
  rm_client.preflight，运行时语义完全一致；
- polar_app.py 中位于 start_kmc_qualification_test 与 restore_compact_hud
  之间的"阶段 3d"迁出注记注释块随本连续区块**整体随行搬运**（纯移动），
  polar_app.py 原位以新的"阶段 3f"注记替代；
- 状态字段初始化不动：``_qualification_runtime_baseline`` /
  ``_qualification_kmc_timer`` / ``_qualification_soak_started_at`` /
  ``_last_module_toggle_at`` / ``_hud_static_defer_since`` 及
  ``registry.add_toggle_listener(self.on_module_toggled)`` 接线仍全部在
  ``PolarRMWindow.__init__`` 原位（D0 状态 schema 不动）；KMC 计时器回调
  finish/send_neutral 为方法内闭包，随体整体搬入；
- 与阶段 3e 注册表的对账（任务纪律 2）：``InputDispatchMixin`` 的模块级
  ``_DISPATCH_HANDLERS`` 中 _on_action_config_action → self.handle_config_action、
  _on_action_setting_toggle/_on_action_setting_slider/_on_action_setting_mode_next/
  _on_action_jello_mode_select → self.after_setting_changed，均为经实例的
  属性查找，ConfigActionsMixin 位于 PolarRMWindow 继承列表 InputDispatchMixin
  之后、QOpenGLWidget 之前，名字经 MRO 正常解析，路由不受影响；
  __init__ 中 add_toggle_listener(self.on_module_toggled) 取绑定方法同理；
- 共享辅助经继承访问、不重复处理：``_capture_qualification_runtime_baseline``
  / ``_qualification_baseline``（D1，仍在本文件）、``save_current_config`` /
  ``reload_current_config`` / ``import_config_from_dialog`` / ``auto_save_config``
  （D17 PersistenceMixin）、``import_wallpaper_from_dialog`` /
  ``reset_wallpaper_profile`` / ``import_custom_ui_sound`` /
  ``custom_ui_sound_selection``（D17）、``apply_scenario`` / ``apply_match_mode``
  / ``apply_robot_profile`` / ``current_robot_profile_key``（D17/D4）、
  ``open/close_hero_deploy_interface`` / ``hero_range_profile_selected`` /
  ``hero_lob_preview``（D7）、``publish_spin_control_state``（D15）、
  ``start_economy_qualification_test`` / ``economy_uses_mock_transport``（D6
  EconomyMixin）、``update_backend_readiness`` / ``readiness_video_source``（D1）、
  ``invalidate_gui_cache``（兼容壳）、``invalidate_transient_overlay_scene``、
  ``setting_bool`` / ``setting_mode`` / ``get_setting_number``（TextMetrics/
  PersistenceMixin）、``active_clickgui_mode``（ClickGuiBuildersMixin）、
  ``toast`` / ``accept_combat_event``（VideoBackendMixin）等均经 ``self``
  继续调用，调用面不变；
- **保守边界决策**：QFileDialog / QInputDialog / HeroLobPlanner 在
  polar_app.py 中的全部使用点均已随块迁出（grep 核实无其他使用），但按
  "只增不删"纪律**保留 polar_app.py 原 import 行不删**——polar_app 作为
  兼容壳继续 re-export 这些符号，避免任何潜在动态引用面漂移；
- ``__qualname__`` 钉回：全部迁入方法在模块底部把 ``__qualname__`` 钉回
  ``PolarRMWindow.<name>``，api_freeze_test 的 qualname 基线比对不变；
- MRO：ConfigActionsMixin 位于继承列表 InputDispatchMixin 之后、
  QOpenGLWidget 之前，且与既有 Mixin 无同名成员（九个方法此前均唯一
  定义于 PolarRMWindow 类体内，已逐一核对）→ 属性解析到本 Mixin，
  ``window.<成员>`` 表面不变。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtWidgets import QFileDialog, QInputDialog

# 相对导入层级：rm_client/ui/polar/mixins/ → ... = rm_client.ui、.... = rm_client
from ....combat_events import CombatEvent
from ....control import (build_dt7_selftest_report, evaluate_dt7_hold,
                         evaluate_dt7_selftest, evaluate_radio_km_selftest,
                         KEYBOARD_BITS)
from ....hero_lob import HeroLobPlanner
from ....model import PRIMARY_GUI_MODE, Module, Setting
from ...overlay_coordinator import OverlayKind

__all__ = [
    "ConfigActionsMixin",
]


class ConfigActionsMixin:
    """D16 动作处理 / 配置动作 / 资格赛（设置变更回调 + 配置动作 + KMC 资格赛）。"""

    def after_setting_changed(self, setting: Setting) -> None:
        self.invalidate_gui_cache()
        # 驾驶/键鼠槽位的改绑要立即生效，不能等下次加载配置；
        # 否则用户改完键后前几次按键仍按旧绑定开车。
        link_module = self.registry.get("RobotLink")
        if link_module is not None and str(getattr(setting, "name", "")).startswith("Bind "):
            if setting is link_module.get_setting(str(setting.name)):
                self.sync_control_binds()
                self.auto_save_config()
                return
        hud = self.registry.get("HUD")
        if hud and setting is hud.get_setting("Visual Tone"):
            # The palette is memoized for one UI frame.  A direct UI setting
            # change can occur before the next timer tick, so invalidate it
            # explicitly rather than displaying the previous tone for a frame.
            self._hud_palette_cache = None
        scenario = self.registry.get("Scenario")
        if scenario and setting is scenario.get_setting("Mode"):
            self.apply_scenario(str(setting.value), close_home=False)
            self.auto_save_config()
            return
        match_mode = self.registry.get("MatchMode")
        if match_mode and setting is match_mode.get_setting("Mode"):
            self.apply_match_mode(str(setting.value), close_home=False)
            self.auto_save_config()
            return
        alliance_profile = self.registry.get("AllianceProfile")
        if alliance_profile and setting is alliance_profile.get_setting("Side"):
            self.state.alliance_color = str(setting.value)
            self.vision_kill_detector.reset()
            self.toast(f"阵营：{setting.value}")
            self.auto_save_config()
            return
        if match_mode and setting is match_mode.get_setting("Alliance"):
            self.state.alliance_color = str(setting.value)
            if alliance_profile:
                side = alliance_profile.get_setting("Side")
                if side:
                    side.value = setting.value
            self.vision_kill_detector.reset()
            self.auto_save_config()
            return
        robot_profile = self.registry.get("RobotProfile")
        if robot_profile and setting in robot_profile.settings:
            self.apply_robot_profile(self.current_robot_profile_key(), close_home=False, announce=False)
            self.auto_save_config()
            return
        click_gui = self.registry.get("ClickGui")
        if click_gui and setting is click_gui.get_setting("Mode"):
            self.mode_manager.set_mode(str(setting.value))
            self.module_expanded.clear()
            self.play_gui_transition_sound("expand")
            self.toast(f"GUI 模式：{setting.value}")
        if hud and setting is hud.get_setting("Combat Preset"):
            minecraft = self.registry.get("MinecraftCombatHUD")
            selected = str(setting.value) == "Minecraft 1.21.11"
            if minecraft is not None and minecraft.enabled != selected:
                self.registry.toggle_module(minecraft, source="preset")
            self.invalidate_transient_overlay_scene()
        if hud and setting is hud.get_setting("Right Display"):
            self.toast(f"右侧 HUD：{setting.value}")
        config_manager = self.registry.get("ConfigManager")
        if config_manager and setting is config_manager.get_setting("Profile"):
            self.reload_current_config()
            return
        elimination_fx = self.registry.get("EliminationFX")
        if elimination_fx and setting is elimination_fx.get_setting("Preset"):
            self.kill_fx.preload_preset_sounds(str(setting.value))
        quick_wheel = self.registry.get("QuickActionWheel")
        if quick_wheel and setting in quick_wheel.settings:
            self.sync_quick_action_wheel_settings()
        spin = self.registry.get("SpinMode")
        if spin and setting in spin.settings:
            mock_setting = spin.get_setting("Mock Output")
            if setting is mock_setting and not bool(setting.value) and spin.enabled:
                # Arming live transport must never inherit the default/on-screen
                # enabled state. Force the module off; the operator must make a
                # second explicit toggle to send an enable command.
                self.registry.toggle_module(spin, source="live_output_armed")
                self.toast("Spin live output armed; toggle SpinMode again to enable")
                self.auto_save_config()
                return
            # Switching back to Mock sends one explicit live disable before
            # local output is suppressed, clearing any robot-side latch.
            force_disable = bool(setting is mock_setting and bool(setting.value))
            self.publish_spin_control_state(
                False if force_disable else spin.enabled,
                source=f"setting:{setting.name}",
                force_live_disable=force_disable,
            )
        if link_module is not None and setting is link_module.get_setting("Radio KM Egress"):
            # 开关只给"意愿"，三道闸还差两块，这里当场把缺的说出来，
            # 免得界面勾上了、车不动、只能回去翻代码。
            on = bool(setting.value)
            missing = []
            if not link_module.enabled:
                missing.append("启用模块 RobotLink")
            drive = link_module.get_setting("Allow Drive")
            if drive is None or not bool(drive.value):
                missing.append("勾选 Allow Drive")
            if on and missing:
                self.toast("无线键鼠出口已开，但还差：" + "、".join(missing))
            elif on:
                # 规则级互锁必须在这儿提醒一次：《2026 通信协议》2.2.1 写明
                # 键鼠控制指令来源只能是"官方选手端"或"自定义客户端"之一。
                # 两边同时开不会报错，只会有一边白干。
                self.toast("无线键鼠出口已开（图传 0x0311）；"
                           "记得把键鼠来源选成\u201c自定义客户端\u201d，"
                           "官方选手端同时开着时只认一个来源")
            else:
                self.toast("无线键鼠出口已关")
        self.auto_save_config()

    def handle_config_action(self, action_name: str) -> None:
        qualification_actions = {
            "New Qualification Session",
            "Reset Qualification Session",
            "Run Preflight",
            "Run Video Test",
            "Run KMC Test",
            "Run Economy Send Test",
            "Record E-Stop Test",
            "Observe Firmware Zero",
            "Record Firmware Zero Test",
            "Run Loss Recovery Test",
            "Record Hero Test",
            "Record Economy Test",
            "Review PRM1 Vision Schema",
            "Run PRM1 Vision Bench",
            "Review PRM1 Spin Schema",
            "Run PRM1 Spin Bench",
            "Start Match Soak",
            "Stop Match Soak",
            "Export Evidence",
            "Field Sign-off",
            "Arm Match Control",
            "Lock Match Control",
        }
        if action_name in qualification_actions:
            self.handle_qualification_action(action_name)
        elif action_name == "Trigger E-Stop":
            self.control.reset_inputs()
            ok, reason = self.backend.trigger_estop()
            self.control.clear_pending()
            self.toast("E-STOP ACTIVE" if ok else f"E-STOP ACTIVE ({reason})")
        elif action_name == "Release E-Stop":
            self.backend.release_estop()
            self.toast("E-STOP RELEASED — verify robot before control")
        elif action_name == "Run DT7 Link Selftest":
            self.run_dt7_link_selftest()
        elif action_name == "Rescan Serial Ports":
            self.rescan_serial_ports()
        elif action_name == "Run Wireless KM Selftest":
            self.run_radio_km_selftest()
        elif action_name == "Save Current":
            self.save_current_config()
        elif action_name == "Reload Profile":
            self.reload_current_config()
        elif action_name == "Import Config":
            self.import_config_from_dialog()
        elif action_name == "Import Wallpaper":
            self.import_wallpaper_from_dialog()
        elif action_name == "Reset Wallpaper":
            self.reset_wallpaper_profile()
        elif action_name == "Restore Compact HUD":
            self.restore_compact_hud()
        elif action_name in ("Capture Chessboard", "Solve Calibration", "Export Tongji YAML"):
            self.handle_calibration_action(action_name)
        elif action_name in ("Preview FX", "Test Elimination"):
            self.preview_elimination_fx(single=action_name == "Test Elimination")
        elif action_name == "Open Deploy Interface":
            self.open_hero_deploy_interface()
        elif action_name in (
            "Calibrate Lob Yaw",
            "Calibrate Lob Pitch",
            "Confirm Relocalization",
            "Invalidate Relocalization",
            "Preview Lob",
            "Arm Assisted Lob",
            "Disarm Assisted Lob",
        ):
            module = self.registry.get("HeroLob")
            timeout = self.get_setting_number(module, "Telemetry Timeout", 0.50)
            telemetry_fresh = bool(
                self.state.native_gimbal_online
                and self.state.native_telemetry_at > 0.0
                and time.perf_counter() - self.state.native_telemetry_at <= timeout
            )
            if action_name == "Calibrate Lob Yaw":
                if telemetry_fresh:
                    bearing = self.get_setting_number(module, "Bearing", 0.0)
                    offset = module.get_setting("Yaw Offset") if module else None
                    current_offset = float(offset.value) if offset is not None else 0.0
                    correction = HeroLobPlanner.normalize_degrees(
                        self.state.native_yaw_deg - (bearing + current_offset)
                    )
                    candidate = current_offset + correction
                    if (
                        offset is not None
                        and offset.min_value is not None
                        and offset.max_value is not None
                        and float(offset.min_value) <= candidate <= float(offset.max_value)
                    ):
                        offset.value = candidate
                        tolerance = self.get_setting_number(
                            module, "Yaw Calibration Tolerance", 1.0
                        )
                        residual = abs(
                            HeroLobPlanner.normalize_degrees(
                                bearing + float(offset.value) - self.state.native_yaw_deg
                            )
                        )
                        self.state.hero_lob_yaw_calibrated = residual <= tolerance
                        self.toast(
                            f"Hero lob yaw calibrated {float(offset.value):+.2f} deg"
                            if self.state.hero_lob_yaw_calibrated
                            else f"Yaw calibration residual {residual:.2f} deg"
                        )
                    else:
                        self.state.hero_lob_yaw_calibrated = False
                        self.toast("Yaw calibration blocked: correction exceeds offset range")
                else:
                    self.toast("Yaw calibration blocked: fresh gimbal telemetry required")
            elif action_name == "Calibrate Lob Pitch":
                if telemetry_fresh:
                    solution, _readiness = HeroLobPlanner.preview_from_state(
                        self.state,
                        module,
                        hero_range_profile=self.hero_range_profile_selected(),
                    )
                    offset = module.get_setting("Pitch Offset") if module else None
                    current_offset = float(offset.value) if offset is not None else 0.0
                    candidate = current_offset + (
                        self.state.native_pitch_deg - solution.pitch_deg
                    )
                    if (
                        solution.reachable
                        and offset is not None
                        and offset.min_value is not None
                        and offset.max_value is not None
                        and float(offset.min_value) <= candidate <= float(offset.max_value)
                    ):
                        offset.value = candidate
                        tolerance = self.get_setting_number(
                            module, "Pitch Calibration Tolerance", 1.5
                        )
                        corrected, _ = HeroLobPlanner.preview_from_state(
                            self.state,
                            module,
                            hero_range_profile=self.hero_range_profile_selected(),
                        )
                        residual = abs(self.state.native_pitch_deg - corrected.pitch_deg)
                        self.state.hero_lob_pitch_calibrated = residual <= tolerance
                        self.toast(
                            f"Hero lob pitch calibrated {float(offset.value):+.2f} deg"
                            if self.state.hero_lob_pitch_calibrated
                            else f"Pitch calibration residual {residual:.2f} deg"
                        )
                    else:
                        self.state.hero_lob_pitch_calibrated = False
                        self.toast("Pitch calibration blocked: unreachable or offset out of range")
                else:
                    self.toast("Pitch calibration blocked: fresh gimbal telemetry required")
            elif action_name == "Confirm Relocalization":
                if (
                    telemetry_fresh
                    and self.state.hero_lob_yaw_calibrated
                    and self.state.hero_lob_pitch_calibrated
                ):
                    self.state.hero_lob_relocalization_valid = True
                    self.toast("Hero lob relocalization confirmed")
                else:
                    self.toast("Relocalization blocked: fresh telemetry and both calibrations required")
            elif action_name == "Invalidate Relocalization":
                self.state.hero_lob_relocalization_valid = False
                self.state.hero_lob_armed = False
                self.state.hero_lob_status = "BLOCKED: relocalization invalid"
                self.toast(self.state.hero_lob_status)
            elif action_name == "Preview Lob":
                self.hero_lob_preview()
            elif action_name == "Arm Assisted Lob":
                solution, readiness = self.hero_lob_preview(announce=False)
                if module is not None and module.enabled and solution.reachable and readiness.ready:
                    self.state.hero_lob_armed = True
                    self.state.hero_lob_status = "ARMED PREVIEW ONLY"
                    self.toast("Hero lob armed (decision support only; no automatic fire)")
                else:
                    self.state.hero_lob_armed = False
                    self.state.hero_lob_status = readiness.summary
                    self.toast(self.state.hero_lob_status)
            else:
                self.state.hero_lob_armed = False
                self.state.hero_lob_status = "DISARMED"
                self.toast("Hero lob disarmed")
            self.frame_scheduler.force()
        elif action_name in ("Import Enable Sound", "Import Disable Sound", "Import Invalid Sound"):
            slot = action_name.removeprefix("Import ").removesuffix(" Sound").lower()
            self.import_custom_ui_sound(slot)
        elif action_name.startswith("Preview ") and action_name in (
            "Preview Enable", "Preview Disable", "Preview Invalid"
        ):
            audio = self.registry.get("AudioFeedback")
            volume = self.get_setting_number(audio, "UI Volume", 45.0)
            self.ui_audio.preview(
                action_name.removeprefix("Preview ").lower(),
                volume,
                self.setting_mode(audio, "Sound Theme", "Polar UI"),
                self.custom_ui_sound_selection(audio),
            )

    def handle_qualification_action(self, action_name: str) -> None:
        """Run qualification operations without trusting persisted booleans."""

        qualification = self.backend.qualification
        try:
            if action_name == "New Qualification Session":
                operator, ok = QInputDialog.getText(self, "Field qualification", "Operator name:")
                if not ok:
                    return
                firmware_hash, ok = QInputDialog.getText(
                    self, "Field qualification", "Robot firmware SHA-256:"
                )
                if not ok:
                    return
                qualification.new_session(
                    robot_id=str(self.state.robot_id),
                    firmware_hash=firmware_hash,
                    match_mode=self.match_mode_manager.current.key,
                    video_source=self.readiness_video_source() or "UNDECLARED",
                    operator=operator,
                )
                self.backend.lock_control("new qualification session")
                self._qualification_runtime_baseline = self._capture_qualification_runtime_baseline()
                self.toast("Qualification session created; control remains LOCKED")
            elif action_name == "Reset Qualification Session":
                qualification.reset()
                self.backend.lock_control("qualification reset")
                self._qualification_runtime_baseline = self._capture_qualification_runtime_baseline()
                self.toast("Qualification evidence reset")
            elif action_name == "Run Preflight":
                from ....preflight import run_preflight

                result = run_preflight(
                    self.paths,
                    official=self.scenario_manager.current.key == "OfficialEvent",
                    codec_selftest=True,
                    active_udp_owned_by_client=bool(self.backend.udp.running),
                )
                qualification.record_automatic(
                    "preflight",
                    result.passed,
                    measured=result.as_dict(),
                    threshold="all startup checks pass",
                )
                self.toast("Preflight PASS" if result.passed else "Preflight BLOCKED")
            elif action_name == "Run Video Test":
                source = self.readiness_video_source()
                stats = self.backend.stats()
                section = stats.get("native_0310" if source == "native_0310" else "udp", {})
                decoded = int(section.get("decoded_frames", 0) or 0)
                fresh = bool(section.get("decoded_connected", False))
                baseline = self._qualification_baseline()
                baseline_frames = int(
                    baseline.get("native_frames" if source == "native_0310" else "udp_frames", 0)
                )
                session = qualification.session
                session_age = time.time() - session.created_at if session is not None else 0.0
                # A single button cannot fabricate the mandated 60-second
                # transmitter run. It records a pass only when an external
                # qualification runner has populated an observed duration.
                duration = float(section.get("continuous_decoded_seconds", 0.0) or 0.0)
                passed = (
                    session is not None
                    and source in {"udp", "native_0310"}
                    and fresh
                    and decoded > baseline_frames
                    and duration >= 60.0
                    and session_age >= 60.0
                )
                qualification.record_automatic(
                    "codec_field_test",
                    passed,
                    measured={
                        "source": source,
                        "frames": decoded,
                        "frames_since_baseline": max(0, decoded - baseline_frames),
                        "seconds": duration,
                        "session_age_seconds": session_age,
                    },
                    threshold={"seconds": 60, "fresh": True, "new_frames": True},
                )
                self.toast("Video field test PASS" if passed else "Video test needs a 60 s field capture")
            elif action_name == "Run KMC Test":
                self.start_kmc_qualification_test()
                return
            elif action_name == "Run Economy Send Test":
                self.start_economy_qualification_test()
                return
            elif action_name == "Observe Firmware Zero":
                baseline = self._qualification_baseline()
                if self.backend.safety.estop_at <= float(baseline.get("estop_at", 0.0)):
                    self.toast("Trigger a new F12 E-stop in this qualification session first")
                    return
                phrase, accepted = QInputDialog.getText(
                    self,
                    "Physical firmware watchdog observation",
                    "After physically observing neutral output, type ZERO OBSERVED:",
                )
                if not accepted or phrase.strip() != "ZERO OBSERVED":
                    self.toast("Firmware zero observation cancelled")
                    return
                elapsed_ms = self.backend.record_firmware_zero_observation()
                self.toast(f"Physical neutral output observed at {elapsed_ms:.1f} ms")
                return
            elif action_name in {
                "Record E-Stop Test", "Record Firmware Zero Test", "Run Loss Recovery Test", "Record Hero Test", "Record Economy Test"
            }:
                stats = self.backend.stats()
                safety_evidence = dict(stats.get("safety_evidence", {}))
                baseline = self._qualification_baseline()
                latest_economy = self.economy_bridge.latest
                estop_is_new = (
                    self.backend.safety.estop_at > float(baseline.get("estop_at", 0.0))
                )
                observed = {
                    "Record E-Stop Test": (
                        "estop_robot_test",
                        estop_is_new
                        and bool(safety_evidence.get("estop_zero_publish_ok", False)),
                    ),
                    "Record Firmware Zero Test": (
                        "firmware_loss_zero_test",
                        estop_is_new
                        and bool(self.state.backend_stats.get("firmware_zero_observed_ms", 0.0))
                        and float(self.state.backend_stats.get("firmware_zero_observed_ms", 9999.0)) <= 500.0,
                    ),
                    "Run Loss Recovery Test": (
                        "loss_recovery_test",
                        self.backend.mqtt.reconnect_count
                        > int(baseline.get("mqtt_reconnect_count", 0))
                        and float(safety_evidence.get("mqtt_disconnect_lock_at", 0.0))
                        > float(baseline.get("captured_at_perf", 0.0))
                        and float(safety_evidence.get("mqtt_reconnected_locked_at", 0.0))
                        > float(baseline.get("captured_at_perf", 0.0))
                        and self.backend.safety.control_state.value == "LOCKED",
                    ),
                    "Record Hero Test": (
                        "hero_deploy_status_test",
                        self.state.deploy_status_revision
                        >= int(baseline.get("deploy_revision", 0)) + 2
                        and self.state.deploy_status_at
                        > float(baseline.get("captured_at_perf", 0.0))
                        and int(self.state.deploy_mode) == 0,
                    ),
                    "Record Economy Test": (
                        "economy_live_test",
                        latest_economy is not None
                        and latest_economy.status == "succeeded"
                        and not latest_economy.request.mock
                        and latest_economy.request.timestamp
                        >= float(baseline.get("captured_at_wall", 0.0))
                        and self.state.economy_status_revision
                        > int(baseline.get("economy_revision", 0))
                        and not self.economy_uses_mock_transport(),
                    ),
                }
                key, passed = observed[action_name]
                measured: Any = {"runtime_observed": passed}
                threshold: Any = "live lifecycle observed"
                if action_name == "Record Firmware Zero Test":
                    measured = {
                        "zero_observed_ms": float(
                            self.state.backend_stats.get("firmware_zero_observed_ms", 0.0)
                        )
                    }
                    threshold = {"maximum_ms": 500, "physical_observer_required": True}
                qualification.record_automatic(
                    key,
                    passed,
                    measured=measured,
                    threshold=threshold,
                )
                self.toast(f"{key}: {'PASS' if passed else 'BLOCKED'}")
            elif action_name in {
                "Review PRM1 Vision Schema",
                "Run PRM1 Vision Bench",
                "Review PRM1 Spin Schema",
                "Run PRM1 Spin Bench",
            }:
                # PRM1 authorisation is deliberately harder than core KMC: a
                # named reviewer records the exact firmware-bound schema, then
                # a supervised fixture must have observed both active and
                # watchdog/disable states. A persisted module toggle can never
                # manufacture either record.
                key_map = {
                    "Review PRM1 Vision Schema": "prm1_vision_schema_review",
                    "Run PRM1 Vision Bench": "prm1_vision_bench_test",
                    "Review PRM1 Spin Schema": "prm1_spin_schema_review",
                    "Run PRM1 Spin Bench": "prm1_spin_bench_test",
                }
                reviewer, accepted = QInputDialog.getText(
                    self,
                    "PRM1 capability evidence",
                    "Named schema reviewer / bench safety observer:",
                )
                if not accepted or not reviewer.strip():
                    return
                phrase, accepted = QInputDialog.getText(
                    self,
                    "PRM1 capability evidence",
                    "Type OBSERVED ON FIXTURE to confirm supervised evidence:",
                )
                passed = bool(accepted and phrase.strip() == "OBSERVED ON FIXTURE")
                qualification.record_supervised_prm1(
                    key_map[action_name],
                    passed,
                    reviewer=reviewer,
                    measured={"active_and_watchdog_observed": passed},
                    threshold="same robot + firmware hash; supervised active/disable/watchdog evidence",
                )
                self.backend.lock_control("PRM1 evidence recorded; explicit re-arm required")
                self.toast(f"{key_map[action_name]}: {'PASS' if passed else 'BLOCKED'} · LOCKED")
            elif action_name == "Start Match Soak":
                self._qualification_soak_started_at = time.perf_counter()
                self.toast("Match-duration soak started")
            elif action_name == "Stop Match Soak":
                started = float(getattr(self, "_qualification_soak_started_at", 0.0))
                elapsed = time.perf_counter() - started if started > 0.0 else 0.0
                required = max(420.0, float(self.state.match_duration_sec or 0.0))
                qualification.record_automatic(
                    "latency_soak_test",
                    elapsed >= required,
                    measured={"seconds": elapsed},
                    threshold={"minimum_seconds": required},
                )
                self.toast("Soak PASS" if elapsed >= required else "Soak stopped too early")
            elif action_name == "Export Evidence":
                destination = QFileDialog.getExistingDirectory(self, "Export field evidence")
                if destination:
                    target = qualification.store.export_current(Path(destination))
                    self.toast(f"Evidence exported: {target.name}")
            elif action_name == "Field Sign-off":
                lead, ok = QInputDialog.getText(self, "Dual sign-off", "Safety lead name:")
                if ok:
                    qualification.sign_off(lead)
                    self.toast("Dual sign-off recorded")
            elif action_name == "Arm Match Control":
                session = qualification.session
                ok, reason = self.backend.arm_match_control(
                    robot_id=str(self.state.robot_id),
                    firmware_hash=session.firmware_hash if session is not None else "",
                    match_mode=self.match_mode_manager.current.key,
                    video_source=self.readiness_video_source(),
                )
                self.toast("MATCH CONTROL ARMED" if ok else f"Arm blocked: {reason}")
            elif action_name == "Lock Match Control":
                self.control.reset_inputs()
                self.backend.mqtt.publish_estop_zero()
                self.backend.lock_control("operator lock")
                self.toast("Match control LOCKED")
        except Exception as exc:
            self.backend.lock_control(f"qualification error: {exc}")
            self.toast(f"Qualification blocked: {exc}")
        self.update_backend_readiness(force=True)
        self.frame_scheduler.force()

    RADIO_KM_SELFTEST_MS = 2500

    def run_radio_km_selftest(self) -> None:
        """端到端自检：看**车上**的 0x0311 到达计数涨不涨，不是客户端自证。

        刻意不发任何按键、也不新造帧：出口本来就以 75Hz 在流，
        自检只做"记两个时刻的车上计数"这件事，所以车不会因为自检而动。
        判据抽成 control.evaluate_radio_km_selftest()，那边有独立断言。
        """
        control = self.control
        link = self.registry.get("RobotLink")
        setting = link.get_setting("Radio KM Egress") if link is not None else None
        if setting is None:
            self.toast("没有 Radio KM Egress 开关，自检无从做起")
            return
        if not bool(setting.value):
            self.toast("自检前请先打开 Radio KM Egress（开关本身要参与）")
            return
        if not control.radio_km_enabled:
            self.toast(f"出口未生效：{control.radio_km_gate_reason or '闸门未过'}")
            return
        if getattr(self, "_radio_km_selftest_running", False):
            self.toast("无线自检已在进行中")
            return
        rx0 = int(getattr(control, "radio_km_robot_rx", -1))
        if rx0 < 0:
            self.toast("读不到车上计数：插一下 C 板 USB(0x5A) 才能做这个自检")
            return
        self._radio_km_selftest_running = True
        sent0 = int(control.radio_km_sent)
        self.toast(f"无线自检开始：车上已计 {rx0} 帧，观察 2.5 秒")

        def finish() -> None:
            self._radio_km_selftest_running = False
            ok, detail = evaluate_radio_km_selftest(
                rx0,
                int(getattr(control, "radio_km_robot_rx", -1)),
                sent0,
                int(control.radio_km_sent),
            )
            self.toast(("无线自检 PASS · " if ok else "无线自检 FAIL · ") + detail)

        QTimer.singleShot(self.RADIO_KM_SELFTEST_MS, finish)

    DT7_SELFTEST_PRESS_MS = 900
    DT7_SELFTEST_HOLD_MS = 1600
    DT7_SELFTEST_TICK_MS = 40

    def rescan_serial_ports(self) -> None:
        """重扫三个串口下拉的候选口（不重启程序也能认出新插上的 DT7）。

        真正的逻辑在 rm_client/serial_ports.refresh_port_options()：那边是纯逻辑、
        可离线测；这里只负责提示与落盘。
        """
        from rm_client.serial_ports import refresh_port_options

        module = self.registry.get("RobotLink")
        diffs = refresh_port_options(self.registry)
        # 重扫完必须当场告诉他"DT7 现在到底认没认出来"，不然他还得自己去猜：
        # Auto 只认 DJI 那对 VID/PID，认不出是**故意拒发**而不是乱开别人的口。
        setting = module.get_setting("DT7 Port") if module is not None else None
        seen = [str(x) for x in (getattr(setting, "options", None) or [])
                if str(x) and str(x) != "Auto"]
        self.toast("串口已重扫：" + ("；".join(diffs) if diffs else "候选口没有变化")
                   + "｜DT7 可选 " + (", ".join(seen) if seen else "（没认出 DJI 口）"))
        self.auto_save_config()

    def run_dt7_link_selftest(self) -> None:
        """按钮式 C 路自检：用客户端自己那条 DT7 出口 + 车上 km_key 回读。

        为什么不新开一个串口去测：现场能同时开着客户端，两个程序抢同一个 DJI VCOM
        只会互相把口占死（选手端也是独占口）。所以这里只拨控制层的两个把手，
        发送仍走主循环那条路；渲染线程一次都不阻塞。

        探针刻意选 **X 键**：全固件对 R/G/Z/X/C/V/B 零消费（逐字 grep 无命中），
        所以"链路通了"和"车动了"完全解耦——没架空轮子也不会因为按一下就往前窜。
        两阶段：① 强制发 X 若干秒 -> 判通不通；② **一帧都不发**再若干秒 -> 判 DT7
        会不会把最后一帧粘住（那是客户端崩掉时车会不会自己往前顶的关键）。
        """
        control = self.control
        link = self.registry.get("RobotLink")
        on = link.get_setting("Direct DT7 Egress") if link is not None else None
        if on is None:
            self.toast("没有 Direct DT7 Egress 开关，自检无从做起")
            return
        if not bool(on.value):
            self.toast("自检前请先打开 Direct DT7 Egress（开关本身要参与）")
            return
        if not getattr(control, "dt7_enabled", False):
            self.toast(f"C 路出口未生效：{control.dt7_last_error or '闸门未过'}")
            return
        if getattr(self, "_dt7_selftest_running", False):
            self.toast("C 路自检已在进行中")
            return
        probe = int(1 << KEYBOARD_BITS["X"])
        control.dt7_send_paused = False
        control.dt7_forced_keys = probe
        base: list = []
        sent0 = int(getattr(control, "dt7_sent", 0))
        tail: list = []
        self._dt7_selftest_running = True
        state = {"phase": "press"}

        def read_key():
            value = int(getattr(control, "radio_km_robot_key", -1))
            return value if value >= 0 else None

        def poll() -> None:
            if not getattr(self, "_dt7_selftest_running", False):
                return
            value = read_key()
            if value is not None:
                (base if state["phase"] == "press" else tail).append(value)
            QTimer.singleShot(self.DT7_SELFTEST_TICK_MS, poll)

        def to_hold() -> None:
            # 进入"模拟进程被杀"阶段：把手复位成"暂停写"，不是"松手"
            control.dt7_forced_keys = None
            control.dt7_send_paused = True
            # 暂停必须带到期：finish() 万一没跑成（事件循环里抛异常、热重载、
            # 场景切换把回调链打断），C 路会从此一帧都不发，而界面看着一切正常。
            control.dt7_paused_until = (time.perf_counter()
                                        + (self.DT7_SELFTEST_HOLD_MS / 1000.0) * 3.0 + 5.0)
            state["phase"] = "hold"

        def finish() -> None:
            self._dt7_selftest_running = False
            control.dt7_send_paused = False
            control.dt7_forced_keys = None
            baseline = 0
            if base:
                counts: dict = {}
                for s in base:
                    counts[s] = counts.get(s, 0) + 1
                baseline = max(counts.items(), key=lambda kv: kv[1])[0]
            sent_now = int(getattr(control, "dt7_sent", 0))
            verdict, detail = evaluate_dt7_selftest(base, probe, baseline,
                                                    frames_sent=max(0, sent_now - sent0))
            hv, hd = evaluate_dt7_hold(tail, probe)
            self.toast(f"C 路自检 {verdict} · {detail}")
            self.toast(f"粘键测试 {hv} · {hd}")
            try:
                from rm_client.backend.dt7_link import load_profile
                report = build_dt7_selftest_report(
                    keys=["X"], forced_bits=probe, baseline=baseline,
                    verdict=verdict, detail=detail, hold_verdict=hv, hold_detail=hd,
                    samples=len(base), tail_samples=len(tail), link_profile=load_profile())
                root = self.backend.paths.evidence_root
                root.mkdir(parents=True, exist_ok=True)
                out = root / f"dt7-selftest-{int(time.time())}.json"
                out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
                self.toast(f"证据已写入 {out.name}")
            except Exception as exc:            # 写证据失败不许把结论一起吞掉
                self.toast(f"证据写入失败：{exc}")

        self.toast("C 路自检开始（探针=X 键，不会让车动）：观察车上 km_key")
        poll()
        QTimer.singleShot(self.DT7_SELFTEST_PRESS_MS, to_hold)
        QTimer.singleShot(self.DT7_SELFTEST_PRESS_MS + self.DT7_SELFTEST_HOLD_MS, finish)

    def start_kmc_qualification_test(self) -> None:
        """Schedule 750 neutral KMC frames without blocking the render thread."""

        if getattr(self, "_qualification_kmc_timer", None) is not None:
            self.toast("KMC qualification is already running")
            return
        # A mock bridge reports every frame as delivered, which would mint
        # fake heartbeat evidence. Qualification must run on the real link.
        if self.backend.mqtt.mock_output or not self.backend.mqtt.connected:
            self.toast("KMC qualification requires a live real MQTT connection")
            return
        token = self.backend.begin_qualification({"core_kmc"}, ttl_s=15.0)
        started = time.perf_counter()
        samples: list[float] = []
        sent = 0
        next_due = started
        timer = QTimer(self)
        timer.setTimerType(Qt.TimerType.PreciseTimer)
        # Poll at 2 ms but emit at most once every exact 1/75 second. A 13 ms
        # timer is 76.9 Hz and was correctly rejected by the official limiter.
        timer.setInterval(2)
        self._qualification_kmc_timer = timer

        def finish() -> None:
            nonlocal sent
            timer.stop()
            timer.deleteLater()
            self._qualification_kmc_timer = None
            elapsed = time.perf_counter() - started
            intervals = [
                (samples[index] - samples[index - 1]) * 1000.0
                for index in range(1, len(samples))
            ]
            ordered = sorted(intervals)
            p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))] if ordered else 9999.0
            maximum = max(intervals, default=9999.0)
            passed = sent == 750 and p95 < 20.0 and maximum < 100.0
            try:
                self.backend.qualification.record_automatic(
                    "control_heartbeat_test",
                    passed,
                    measured={
                        "sent": sent,
                        "seconds": elapsed,
                        "p95_interval_ms": p95,
                        "max_interval_ms": maximum,
                    },
                    threshold={"sent": 750, "p95_interval_ms": 20, "max_interval_ms": 100},
                )
            finally:
                self.backend.lock_control("qualification KMC test complete")
            self.toast(f"KMC {'PASS' if passed else 'FAIL'} · P95 {p95:.1f} ms · LOCKED")
            self.update_backend_readiness(force=True)

        def send_neutral() -> None:
            nonlocal sent, next_due
            now = time.perf_counter()
            if now < next_due:
                return
            ok, _ = self.backend.publish_keyboard_mouse(qualification_token=token.value)
            if ok:
                sent += 1
                samples.append(now)
                next_due = now + 1.0 / 75.0
            if len(samples) >= 750 or now - started > 12.0:
                finish()

        timer.timeout.connect(send_neutral)
        timer.start()
        self.toast("KMC neutral 75 Hz qualification started")

    # ------------------------------------------------------------------
    # 阶段 3d 大域 mixin 化：start_economy_qualification_test（D6 资格赛窗口）
    # 已机械迁至 EconomyMixin；_economy_qualification_token 由同迁的
    # send_economy_request 消费，一次性授权语义零修改随行搬运。
    # ------------------------------------------------------------------

    def restore_compact_hud(self) -> None:
        """Restore compact visuals without changing behavior or connection settings."""
        hud = self.registry.get("HUD")
        tactical_map = self.registry.get("TacticalMap")
        values = (
            (hud, "Density", "CombatCompact"),
            (hud, "Visual Tone", "LiquidClean"),
            (hud, "Target Style", "RoundCompact"),
            (tactical_map, "Map Size", "Compact"),
            (tactical_map, "Chrome", "Minimal"),
            (tactical_map, "Status Display", "LiquidAuto"),
        )
        for module, name, value in values:
            setting = module.get_setting(name) if module else None
            if setting is not None and (not setting.options or value in setting.options):
                setting.value = value
        self.invalidate_gui_cache()
        self.tactical_map_cached_rect = QRectF()
        self.toast("Compact HUD restored")
        self.auto_save_config()

    def on_module_toggled(self, module: Module, enabled: bool, source: str) -> None:
        jello_click = bool(
            source == "clickgui"
            and self.gui_visible
            and self.active_clickgui_mode() == PRIMARY_GUI_MODE
        )
        self.invalidate_gui_cache()
        # The ActiveMods fade starts on this event, but the row targets are
        # only updated during the next paint (after begin_frame). Seed the
        # static-HUD deferral window here so the toggle frame itself does not
        # repaint the whole snapshot mid-fade.
        self._last_module_toggle_at = time.perf_counter()
        self._hud_static_defer_since = self._last_module_toggle_at
        if module.name == "MinecraftCombatHUD":
            hud = self.registry.get("HUD")
            preset = hud.get_setting("Combat Preset") if hud else None
            if preset is not None:
                if enabled:
                    preset.value = "Minecraft 1.21.11"
                elif str(preset.value) == "Minecraft 1.21.11":
                    preset.value = "Polar"
            self.invalidate_transient_overlay_scene()
        elif module.name == "HeroLob":
            if enabled and not self.home_visible:
                self.open_hero_deploy_interface()
            elif not enabled:
                self.state.hero_lob_armed = False
                if int(self.state.deploy_mode) == 1:
                    # Deployment is an acknowledged referee state. Never hide
                    # its explicit EXIT control merely because the helper
                    # module was switched off.
                    self.hero_deploy_ui.open(time.perf_counter())
                    self.overlay_coordinator.request_modal(OverlayKind.HERO_DEPLOY)
                    self.toast("HeroLob disabled; explicitly EXIT deploy mode")
                else:
                    self.close_hero_deploy_interface(force=True)
        elif module.name == "SpinMode":
            if not str(source).startswith("auto_hit"):
                self.auto_spin.operator_override()
            self.publish_spin_control_state(enabled, source=source)
        audio = self.registry.get("AudioFeedback")
        active = bool(
            audio
            and (audio.enabled or module is audio)
            and self.setting_bool(audio, "Enabled", True)
            and self.setting_bool(audio, "Module Toggle Sounds", True)
        )
        if jello_click:
            hud = self.registry.get("HUD")
            self.ui_audio.jello_module_toggled(
                enabled,
                # Sigma routes module toggles through ActiveMods -> Sound.
                # Keep that independent switch while still respecting the
                # application's global audio/master-toggle controls.
                active=active and self.setting_bool(hud, "Jello List Sound", True),
                volume=self.get_setting_number(audio, "UI Volume", 45.0),
            )
            return
        self.ui_audio.module_toggled(
            enabled,
            source,
            active=active,
            volume=self.get_setting_number(audio, "UI Volume", 45.0),
            theme=self.setting_mode(audio, "Sound Theme", "Polar UI"),
            custom_sounds=self.custom_ui_sound_selection(audio),
        )

    def play_gui_transition_sound(self, kind: str) -> None:
        audio = self.registry.get("AudioFeedback")
        if not audio or not self.setting_bool(audio, "Enabled", True):
            return
        self.ui_audio.gui_feedback(
            kind,
            self.get_setting_number(audio, "UI Volume", 45.0),
            self.setting_mode(audio, "Sound Theme", "Polar UI"),
        )

    def preview_elimination_fx(self, *, single: bool = False) -> None:
        module = self.registry.get("EliminationFX")
        sequence = "Single" if single else self.setting_mode(module, "Preview Sequence", "Normal 1-6")
        if sequence == "All Kill Types":
            types = ["NORMAL", "HEADSHOT", "EXPLOSION", "CRIT", "ASSIST", "DESTROY_VEHICLE"]
        elif sequence == "Single":
            types = ["NORMAL"]
        else:
            types = ["NORMAL"] * 6
        for index, kill_type in enumerate(types):
            event = CombatEvent(
                "elimination", "preview", True, time.perf_counter(),
                victim_id=101 + index,
                detail="local_preview",
                kill_type=kill_type,
                combo=index + 1,
                victim_name=f"ROBOT {101 + index}",
                distance_m=8.0 + index,
                score_delta=100,
                tags=("ELIMINATION", "ARMOR HIT") if kill_type != "DESTROY_VEHICLE" else ("ROBOT DESTROYED",),
            )
            QTimer.singleShot(index * 650, lambda queued=event: self.accept_combat_event(queued))

    def handle_calibration_action(self, action_name: str) -> None:
        module = self.registry.get("CameraCalibration")
        name = self.setting_mode(module, "Profile", "polar_webcam")
        columns = int(self.get_setting_number(module, "Board Columns", 9))
        rows = int(self.get_setting_number(module, "Board Rows", 6))
        square_size = self.get_setting_number(module, "Square Size", 25.0)
        if action_name == "Capture Chessboard":
            frame = self.camera_worker.latest_frame()
            if frame is not None and self.calibration.capture(frame.bgr, columns, rows, square_size):
                self.toast(f"Calibration sample {self.calibration.sample_count}: corners locked")
            else:
                self.toast(self.calibration.last_error or "Chessboard capture failed", kind="warning")
            return
        if action_name == "Solve Calibration":
            profile = self.calibration.solve(name, columns, rows, square_size)
            if profile is None:
                self.toast(self.calibration.last_error or "Calibration solve failed", kind="warning")
            else:
                self.toast(f"Calibration solved: {profile.rms_error_px:.2f}px RMS")
            return
        bridge_module = self.registry.get("TongjiVisionBridge")
        device = self.setting_mode(bridge_module, "Inference Device", "AUTO")
        path = self.calibration.export_tongji_yaml(name, device)
        if path is None:
            self.toast(self.calibration.last_error or "Tongji YAML export failed", kind="warning")
        else:
            self.toast(f"Tongji YAML exported: {path.name}")


# ----------------------------------------------------------------------
# __qualname__ 钉回（api_freeze_test 对方法记录 __qualname__ 并参与比对，
# 见 tests/api_freeze_test.py _member_entry）：全部迁入方法钉回
# PolarRMWindow.<name>，冻结面签名不变。
# ----------------------------------------------------------------------

_QUALNAME_PINNED_MEMBERS = (
    ConfigActionsMixin.after_setting_changed,
    ConfigActionsMixin.handle_config_action,
    ConfigActionsMixin.handle_qualification_action,
    ConfigActionsMixin.start_kmc_qualification_test,
    ConfigActionsMixin.restore_compact_hud,
    ConfigActionsMixin.on_module_toggled,
    ConfigActionsMixin.play_gui_transition_sound,
    ConfigActionsMixin.preview_elimination_fx,
    ConfigActionsMixin.handle_calibration_action,
)

for _fn in _QUALNAME_PINNED_MEMBERS:
    _fn.__qualname__ = f"PolarRMWindow.{_fn.__name__}"
del _fn, _QUALNAME_PINNED_MEMBERS
