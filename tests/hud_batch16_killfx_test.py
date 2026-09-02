"""第 16 批验收：`EliminationFX / Lock Target Bonus` 接通。

上一轮我把这项归为"需要绘制层动手术"，**判错了**（第四次同源错误：
用猜的方向找东西）。实际情况是消费端**整套早就写好**：

  * `kill_fx.py` 有 `LockedTargetTracker`、`LOCKED_TARGET_TAG`、专门的
    提示音 `addscore_df.ogg`，`trigger()` 明确读
    `element_toggles.get("locked_target_bonus", True)`；
  * 但 `video_backend_mixin.elimination_element_toggles()` 构造那个字典时
    **从来没提供 `locked_target_bonus` 这个键**，于是它永远取默认 True。

后果：ClickGUI 上"锁定目标加分"这个开关**关不掉任何东西**——标签、
提示音都照旧。差的就是一行供值。

本文件做真正的端到端：从 ClickGUI 的开关读起，经过 mixin 构造的字典，
喂进真实的 `KillFxRenderer.trigger()`，最后检查击杀上下文里到底有没有
`locked_target` 标签、播放的是哪个音效。不靠截图、不 mock 判据。

    python tests/hud_batch16_killfx_test.py
"""

from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["POLAR_USER_DATA_ROOT"] = tempfile.mkdtemp(prefix="polar_b16_")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from rm_client.combat_events import CombatEvent  # noqa: E402
from rm_client.kill_fx import (  # noqa: E402
    LOCKED_TARGET_TAG,
    CompanionHud,
    KillFxRenderer,
    LockedTargetTracker,
)
from rm_client.model import build_default_registry  # noqa: E402
from rm_client.ui.polar.mixins.video_backend_mixin import VideoBackendMixin  # noqa: E402

FAILED: list[str] = []

# 关掉全部“视觉元素”开关，让 effective_elements 为空，这样 trigger() 不会
# 去碰需要纹理资产的子渲染器；同时把这条测试钉在“标签与音效”这一件事上。
ELEMENT_SWITCHES = (
    "Kill Feed", "Score Popup", "Bonus Tags", "Combo Subtitle",
    "Scrolling Icons", "Combo Icons", "Card Icons", "Battlefield Icons",
    "Valorant Icons", "Honor Badges", "Hit Info", "Match Progress",
)


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILED.append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


class _NullFx:
    """吃掉 trigger 调用，不记录任何东西。"""

    def trigger(self, *_args, **_kwargs) -> None:
        return None


class RecordingSounds:
    """记录播放请求；不碰音频设备。"""

    def __init__(self) -> None:
        self.played: list[tuple[str, float]] = []

    def play(self, name: str, volume: float) -> None:
        self.played.append((str(name), float(volume)))


def bare_renderer() -> KillFxRenderer:
    """只装配 `trigger()` 实际会碰到的字段。

    真实构造函数会建 AssetBank/SoundPool（纹理缓存 + 音频设备），测试里
    不需要，也不该依赖。图标类子渲染器换成空壳：它们跟“锁定目标加分”
    无关，本文件只关心标签与音效。
    """
    renderer = object.__new__(KillFxRenderer)
    renderer.locked_targets = LockedTargetTracker()
    renderer.combo_count = 0
    renderer.last_kill_at = 0.0
    renderer.last_context = None
    renderer.companion = CompanionHud()
    renderer.sounds = RecordingSounds()
    for name in ("honor", "scrolling", "combo", "card", "card_bar", "battlefield", "valorant"):
        setattr(renderer, name, _NullFx())
    return renderer


class Host(VideoBackendMixin):
    """只提供 `elimination_element_toggles()` 需要的三件东西。"""

    def __init__(self) -> None:
        self.registry = build_default_registry()

    def setting_bool(self, module, setting_name: str, default: bool = False) -> bool:
        # 与 polar_app.py:4316 同一实现：查不到就回落默认（fail-open）。
        setting = module.get_setting(setting_name) if module else None
        return bool(setting.value) if setting else default

    def toggles(self, *_args, **_kwargs) -> dict[str, bool]:
        effect = self.registry.get("EliminationFX")
        assert effect is not None
        effect.enabled = True
        return self.elimination_element_toggles(effect)

    def set_lock_bonus(self, value) -> None:
        effect = self.registry.get("EliminationFX")
        assert effect is not None
        setting = effect.get_setting("Lock Target Bonus")
        assert setting is not None
        setting.value = value


def kill_pair(toggles: dict[str, bool]):
    """对同一目标连打两下：第二次构成“持续交战”，是触发加分的那一刀。

    返回 (是否带标签, 播放的音效名列表)。
    """
    renderer = bare_renderer()
    first = CombatEvent("elimination", "referee", True, 0.0, victim_id=101, killer_id=31)
    second = CombatEvent("elimination", "referee", True, 0.0, victim_id=101, killer_id=31, score_delta=150)
    renderer.trigger(
        first, combo_window=5.0, sound_enabled=True, volume=50.0,
        preset="Default Scrolling", visibility="Preset",
        now_override=100.0, element_toggles=toggles,
    )
    renderer.trigger(
        second, combo_window=5.0, sound_enabled=True, volume=50.0,
        preset="Default Scrolling", visibility="Preset",
        now_override=101.0, element_toggles=toggles,
    )
    context = renderer.last_context
    tagged = any(str(tag).lower() == LOCKED_TARGET_TAG for tag in (context.tags if context else ()))
    sounds = [name for name, _ in renderer.sounds.played]
    return tagged, sounds


def test_switch_reaches_the_renderer() -> None:
    """开关经 mixin 一路走到 trigger()，改标签与音效。"""
    host = Host()
    host.set_lock_bonus(True)
    on_tagged, on_sounds = kill_pair(host.toggles())
    check("开关注入后键存在于字典", "locked_target_bonus" in host.toggles(), str(sorted(host.toggles())))
    check("开着时：持续交战的那一刀带“锁定目标”标签", on_tagged, str(on_sounds))
    check("开着时：播放的是加分音效 addscore_df.ogg", "addscore_df.ogg" in on_sounds, str(on_sounds))

    host.set_lock_bonus(False)
    off_tagged, off_sounds = kill_pair(host.toggles())
    check("关掉后：同一刀不再有“锁定目标”标签", not off_tagged, str(off_sounds))
    check("关掉后：不再播放加分音效", "addscore_df.ogg" not in off_sounds, str(off_sounds))
    check("关掉后：普通击杀音效仍然播", len(off_sounds) == 2, str(off_sounds))


def test_default_matches_pre_wiring_behaviour() -> None:
    """接线不能改变默认行为：默认值与 element_toggles=None 都要有标签。"""
    host = Host()
    effect = host.registry.get("EliminationFX")
    default_value = effect.get_setting("Lock Target Bonus").value
    check("设置项默认仍为 True（与接线前的硬编行为一致）", default_value is True, repr(default_value))

    tagged, _ = kill_pair(host.toggles())
    check("默认配置下标签照旧出现", tagged)

    none_tagged, _ = kill_pair(None)  # 接线前 mixin 根本没给这个键 == 取默认 True
    check("字典缺该键时按开处理（不改历史行为）", none_tagged)


def test_switch_does_not_step_on_others() -> None:
    """只动自己那一格：Bonus Tags 与其它元素开关不受牵连。"""
    host = Host()
    effect = host.registry.get("EliminationFX")
    for name in ELEMENT_SWITCHES:
        effect.get_setting(name).value = True
    host.set_lock_bonus(False)
    toggles = host.toggles()
    check("关 Lock Target Bonus 不影响 bonus 元素开关", toggles["bonus"] is True, str(toggles["bonus"]))
    check("关 Lock Target Bonus 不影响 kill_feed 开关", toggles["kill_feed"] is True, str(toggles["kill_feed"]))
    check("字典键数量等于全部元素开关 + 本项", len(toggles) == 16, str(len(toggles)))

    effect.get_setting("Bonus Tags").value = False
    toggles = host.toggles()
    check("Bonus Tags 仍能独立关掉整行标签", toggles["bonus"] is False, str(toggles["bonus"]))
    check("Bonus Tags 关闭不牵连 locked_target_bonus", toggles["locked_target_bonus"] is False, str(toggles["locked_target_bonus"]))


def test_missing_setting_fails_open() -> None:
    """查不到设置项时按“开”处理，别因为配置缺项静默关掉加分提示。"""
    class EmptyModule:
        name = "EliminationFX"

        def get_setting(self, _name: str):
            return None

    host = Host()
    toggles = host.elimination_element_toggles(EmptyModule())  # type: ignore[arg-type]
    check("缺项时 locked_target_bonus 回落 True", toggles.get("locked_target_bonus") is True, str(toggles.get("locked_target_bonus")))
    tagged, sounds = kill_pair(toggles)
    check("缺项时加分标签与音效都照旧", tagged and "addscore_df.ogg" in sounds, str(sounds))


def main() -> int:
    for fn in (
        test_switch_reaches_the_renderer,
        test_default_matches_pre_wiring_behaviour,
        test_switch_does_not_step_on_others,
        test_missing_setting_fails_open,
    ):
        fn()
    print(f"\n合计 {len(FAILED)} 项失败")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
