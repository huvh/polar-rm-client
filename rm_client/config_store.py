from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any


CONFIG_VERSION = 1
DEFAULT_PROFILE = "default"


def validate_client_config(data: Any, registry: Any = None) -> None:
    """Preflight the entire candidate before replacing a file or live values.

    Unknown modules/settings remain forwards-compatible, but malformed JSON
    values must never be coerced into enabled safety switches or NaN geometry.
    """
    def require(ok: bool, path: str) -> None:
        if not ok:
            raise ValueError(f"Invalid configuration value: {path}")

    def number(value: Any) -> bool:
        try:
            return type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            return False

    require(isinstance(data, dict), "root")
    version = data.get("version", 0)
    require(type(version) is int and 0 <= version <= CONFIG_VERSION, "version")
    # Also reject non-finite values in unknown settings instead of carrying
    # them into a later version of the application.
    try:
        json.dumps(data, allow_nan=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Configuration must contain finite JSON values") from exc
    for key in ("profile", "gui_mode", "selected_category", "selected_module"):
        if key in data:
            require(isinstance(data[key], str), key)
    if "module_expanded" in data:
        require(isinstance(data["module_expanded"], list) and all(isinstance(v, str) for v in data["module_expanded"]), "module_expanded")
    modules = data.get("modules", {})
    require(isinstance(modules, dict), "modules")
    for name, item in modules.items():
        require(isinstance(item, dict), f"modules.{name}")
        if "enabled" in item:
            require(type(item["enabled"]) is bool, f"{name}.enabled")
        if "keybind" in item:
            require(isinstance(item["keybind"], str), f"{name}.keybind")
        settings = item.get("settings", {})
        require(isinstance(settings, dict), f"{name}.settings")
        module = registry.get(name) if registry is not None else None
        for key, value in settings.items():
            require(value is None or type(value) in (str, int, float, bool), f"{name}.{key}")
            setting = module.get_setting(key) if module else None
            if setting is None or setting.kind in ("action", "action_group"):
                continue
            if setting.kind == "bool":
                require(type(value) is bool, f"{name}.{key}")
            elif setting.kind == "number":
                require(number(value), f"{name}.{key}")
            elif setting.kind == "mode":
                require(isinstance(value, str), f"{name}.{key}")
    for key in ("old_panels", "new_panels", "dropdown_panels", "polar_windows", "vape_windows"):
        panels = data.get(key, {})
        require(isinstance(panels, dict), key)
        for name, panel in panels.items():
            require(isinstance(panel, dict), f"{key}.{name}")
            for field, value in panel.items():
                if field in ("expanded", "dragged"):
                    require(type(value) is bool, f"{key}.{name}.{field}")
                else:
                    require(number(value), f"{key}.{name}.{field}")
    wheel = data.get("quick_action_wheel", {})
    require(isinstance(wheel, dict), "quick_action_wheel")
    for key in ("sectors", "radius", "dead_zone"):
        if key in wheel:
            require(number(wheel[key]), f"quick_action_wheel.{key}")
    if "show_labels" in wheel:
        require(type(wheel["show_labels"]) is bool, "quick_action_wheel.show_labels")
    for key in ("label_style", "icon_style"):
        if key in wheel:
            require(isinstance(wheel[key], str), f"quick_action_wheel.{key}")
    for key in ("actions", "labels", "icons"):
        if key in wheel:
            require(isinstance(wheel[key], list) and all(isinstance(v, str) for v in wheel[key]), f"quick_action_wheel.{key}")


def _atomic_write(path: Path, serialized: str) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


class ClientConfigStore:
    def __init__(self, config_dir: Path) -> None:
        self.config_dir = config_dir
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def profile_names(self) -> list[str]:
        names = []
        for path in sorted(self.config_dir.glob("*.json")):
            if path.is_file() and not path.name.startswith("."):
                names.append(path.stem)
        return names or [DEFAULT_PROFILE]

    def profile_path(self, profile: str) -> Path:
        return self.config_dir / f"{self.clean_profile_name(profile)}.json"

    def load(self, profile: str) -> dict[str, Any] | None:
        path = self.profile_path(profile)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            validate_client_config(data)
        except (OSError, UnicodeError, ValueError, OverflowError):
            return None
        return data

    def save(self, profile: str, data: dict[str, Any]) -> Path:
        path = self.profile_path(profile)
        payload = dict(data)
        payload["version"] = CONFIG_VERSION
        payload["profile"] = self.clean_profile_name(profile)
        validate_client_config(payload)
        serialized = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
        # A power loss or process termination must leave either the old valid
        # profile or the new valid profile, never a half-written default.json.
        _atomic_write(path, serialized)
        return path

    def load_startup_preferences(self) -> dict[str, Any] | None:
        try:
            data = json.loads((self.config_dir / ".startup.json").read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("profile"), str) or type(data.get("load_on_start")) is not bool:
                return None
            return {"profile": self.clean_profile_name(data["profile"]), "load_on_start": data["load_on_start"]}
        except (OSError, UnicodeError, ValueError):
            return None

    def save_startup_preferences(self, profile: str, load_on_start: bool) -> None:
        if type(load_on_start) is not bool:
            raise ValueError("load_on_start must be a boolean")
        _atomic_write(self.config_dir / ".startup.json", json.dumps({"profile": self.clean_profile_name(profile), "load_on_start": load_on_start}))

    def ensure_default(self, data: dict[str, Any]) -> Path:
        path = self.profile_path(DEFAULT_PROFILE)
        if not path.exists():
            self.save(DEFAULT_PROFILE, data)
        return path

    def import_file(self, source: Path, *, registry: Any = None) -> str:
        source = Path(source)
        if source.suffix.lower() != ".json" or not source.exists():
            raise ValueError("只能导入已经存在的 .json 配置文件。")
        data = json.loads(source.read_text(encoding="utf-8"))
        validate_client_config(data, registry)
        name = self.clean_profile_name(source.stem)
        target = self.profile_path(name)
        if source.resolve() != target.resolve():
            if target.exists():
                # Keep the prior bytes recoverable even when the previous
                # profile itself was corrupt. A failed backup aborts import.
                _atomic_write(target.with_suffix(".json.bak"), target.read_text(encoding="utf-8"))
            self.save(name, data)
        return name

    def clean_profile_name(self, profile: str) -> str:
        safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in str(profile).strip())
        return safe or DEFAULT_PROFILE


def export_client_config(
    registry: Any,
    *,
    gui_mode: str,
    selected_category: str,
    selected_module: str,
    module_expanded: set[str],
    old_panels: dict[str, Any],
    new_panels: dict[str, Any],
    dropdown_panels: dict[str, Any],
    polar_windows: dict[str, Any] | None = None,
    quick_action_wheel: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "version": CONFIG_VERSION,
        # Legacy ClickGUI renderers are transient previews. Never serialize
        # one as the profile's startup surface, even when an older caller
        # passes a historical mode name.
        "gui_mode": "JelloSigma",
        "startup_wallpaper_revision": 1,
        "selected_category": selected_category,
        "selected_module": selected_module,
        "module_expanded": sorted(module_expanded),
        "old_panels": old_panels,
        "new_panels": new_panels,
        "dropdown_panels": dropdown_panels,
        "polar_windows": polar_windows or {},
        "quick_action_wheel": quick_action_wheel or {},
        "modules": {
            module.name: {
                "enabled": module.enabled,
                "keybind": module.keybind,
                "settings": {
                    setting.name: setting.value
                    for setting in module.settings
                    if setting.kind != "action_group" and not (module.name == "ConfigManager" and setting.name == "Profile")
                },
            }
            for module in registry.modules
        },
    }


def apply_registry_config(registry: Any, data: dict[str, Any]) -> None:
    validate_client_config(data, registry)
    modules = data.get("modules")
    if not isinstance(modules, dict):
        return
    modules = dict(modules)
    # One-time migration of shipped defaults. Imported wallpapers and generated
    # modes are left alone; the revision makes later explicit choices persistent.
    startup = modules.get("StartupVisual")
    if data.get("startup_wallpaper_revision") != 1 and isinstance(startup, dict):
        settings = startup.get("settings")
        if isinstance(settings, dict) and settings.get("Wallpaper Profile") in {"TexasMP4", "VendingMachine4K"}:
            if settings.get("Background Mode", "VideoParallax") not in {"ParticleGrid", "PkgScene"}:
                startup = dict(startup)
                startup["settings"] = {**settings, "Wallpaper Profile": "BlackHole"}
                modules["StartupVisual"] = startup
    click_gui = modules.get("ClickGui")
    if isinstance(click_gui, dict) and isinstance(click_gui.get("settings"), dict):
        settings = dict(click_gui["settings"])
        settings["Mode"] = {
            "VapeUnified": "PolarUnified",
            "VapeMulti": "PolarMulti",
        }.get(str(settings.get("Mode", "")), settings.get("Mode"))
        click_gui = dict(click_gui)
        click_gui["settings"] = settings
        modules["ClickGui"] = click_gui
    audio = modules.get("AudioFeedback")
    if isinstance(audio, dict) and isinstance(audio.get("settings"), dict):
        settings = dict(audio["settings"])
        if settings.get("Sound Theme") == "Vape":
            settings["Sound Theme"] = "Polar UI"
        audio = dict(audio)
        audio["settings"] = settings
        modules["AudioFeedback"] = audio
    # 旧配置把阵营挂在 MatchMode；新模块独立管理，但仍能无感加载历史档案。
    alliance_profile = modules.get("AllianceProfile")
    legacy_match = modules.get("MatchMode")
    has_explicit_side = isinstance(alliance_profile, dict) and isinstance(alliance_profile.get("settings"), dict) and "Side" in alliance_profile["settings"]
    if not has_explicit_side and isinstance(legacy_match, dict):
        legacy_settings = legacy_match.get("settings")
        if isinstance(legacy_settings, dict) and legacy_settings.get("Alliance") in ("Red", "Blue"):
            modules = dict(modules)
            modules["AllianceProfile"] = {"settings": {"Side": legacy_settings["Alliance"]}}
    legacy_fx = modules.get("EliminationFX")
    if isinstance(legacy_fx, dict) and isinstance(legacy_fx.get("settings"), dict):
        fx_settings = dict(legacy_fx["settings"])
        if "Preset" not in fx_settings and "Style" in fx_settings:
            old_style = str(fx_settings.get("Style", "Scrolling"))
            old_variant = str(fx_settings.get("Variant", "Prime"))
            fx_settings["Preset"] = {
                "Scrolling": "Default Scrolling", "Combo": "Combo", "Card": "Card",
                "CardBar": "Card", "Battlefield 1": "Battlefield 1", "Battlefield 5": "Battlefield 5",
                "Valorant": f"Valorant {old_variant if old_variant != 'Default' else 'Prime'}",
            }.get(old_style, "Default Scrolling")
        if "Sound Volume" not in fx_settings and "Volume" in fx_settings:
            fx_settings["Sound Volume"] = fx_settings["Volume"]
        old_anchor = str(fx_settings.get("Anchor Policy", ""))
        if old_anchor == "Safe Area":
            fx_settings["Anchor Policy"] = "Combat Focus"
            fx_settings["X Offset"] = 0
            fx_settings["Y Offset"] = 0
        elif old_anchor == "Original Position":
            fx_settings["Anchor Policy"] = "Original Bottom"
        fx_settings.setdefault("Responsive Scale", "Auto")
        legacy_fx = dict(legacy_fx)
        legacy_fx["settings"] = fx_settings
        modules = dict(modules)
        modules["EliminationFX"] = legacy_fx
    for name, module_data in modules.items():
        module = registry.get(str(name))
        if module is None or not isinstance(module_data, dict):
            continue
        if "enabled" in module_data:
            module.set_enabled(bool(module_data["enabled"]))
        keybind = module_data.get("keybind")
        if isinstance(keybind, str):
            # HeroLob previously had no entry key and could remain enabled in
            # a profile without any way to reopen its new dedicated console.
            module.keybind = (
                "K"
                if module.name == "HeroLob" and keybind in {"", "None"}
                else (keybind or "None")
            )
        settings = module_data.get("settings")
        if not isinstance(settings, dict):
            continue
        for setting_name, value in settings.items():
            if module.name == "ConfigManager" and setting_name == "Profile":
                # The opened file owns its identity, never its embedded data.
                continue
            setting = module.get_setting(str(setting_name))
            if setting is None:
                continue
            if setting.kind == "bool":
                setting.value = bool(value)
            elif setting.kind == "number":
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    continue
                if setting.min_value is not None:
                    number = max(setting.min_value, number)
                if setting.max_value is not None:
                    number = min(setting.max_value, number)
                setting.value = number
            elif setting.kind == "mode":
                text_value = str(value)
                if module.name == "MQTTLink" and setting.name == "Referee Profile":
                    # Unknown annual schemas must reach the backend's explicit
                    # fail-closed validator, not silently become this year's
                    # default through the ordinary enum migration path.
                    setting.value = text_value
                    continue
                if setting.name == "Status Display":
                    text_value = {
                        "Auto": "LiquidAuto",
                        "Rings": "LegacyOrbit",
                        "Bars": "LegacyBars",
                        "ReGlassAuto": "LiquidAuto",
                        "ReGlassBars": "LiquidBars",
                        "ReGlassCards": "LiquidCards",
                    }.get(text_value, text_value)
                elif setting.name == "Glass Style":
                    text_value = {"ReGlass": "LiquidGlass"}.get(text_value, text_value)
                elif setting.name == "ModuleList Surface":
                    text_value = {"ReGlass": "LiquidGlass"}.get(text_value, text_value)
                elif setting.name == "ModuleList Style":
                    text_value = {
                        "PolarLegacy": "PolarTextList",
                        "RainbowRight": "PolarRainbowRight",
                        "DebugWhiteList": "JelloActiveMods",
                    }.get(text_value, text_value)
                elif setting.name == "Render Backend":
                    # 旧版的 GPU Cached 只是缓存合成，升级后统一迁移到真正的 Direct GPU。
                    text_value = {"GPU Cached": "Unified GPU", "Direct GPU": "Unified GPU"}.get(text_value, text_value)
                elif module.name == "Armor3DESP" and setting.name == "Style":
                    # The old fluorescent-white default is superseded by the
                    # Sigma Shadow implementation. Other explicitly selected
                    # ESP styles remain available unchanged.
                    text_value = {"PolarMechanicalWire": "JelloShadow"}.get(text_value, text_value)
                if not setting.options or text_value in setting.options:
                    setting.value = text_value
            elif setting.kind == "action_group":
                # Expansion and selected action belong to the live ClickGUI
                # session and are intentionally never restored from a profile.
                continue
            else:
                setting.value = value
    side_module = registry.get("AllianceProfile")
    side = side_module.get_setting("Side") if side_module else None
    match_module = registry.get("MatchMode")
    legacy_side = match_module.get_setting("Alliance") if match_module else None
    if side is not None and legacy_side is not None:
        legacy_side.value = side.value
