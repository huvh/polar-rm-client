"""从 EndfieldStudio original --full 导出生成终端 Wiki 的小型离线资源包。

只读原始导出，不扫描/修改游戏安装目录；UnityPy/Pillow 仅为离线工具依赖。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil

import sys

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.endfield.prepare_boot import decode
from tools.endfield.wiki.check_assets import write_manifest
from tools.endfield.wiki.breadcrumb_assets import prepare_breadcrumbs
from tools.endfield.wiki.layer_assets import prepare_layers


ASSETS = ROOT / "rm_client/ui/endfield/wiki/assets"


CATEGORY_ICONS = {
    "Combat": 3, "Movement": 6, "Vision": 1,
    "Strategy": 2, "System": 4, "Render": 5,
}
# 终端模块名称保留；用本体 groupicon 中语义相近的图标替换显示。
MODULE_ICON_GROUPS = {
    "guide_adventure": "SpinMode AutoSpinOnHit MapMarker TacticalMap LiquidTacticalMap CameraCalibration Crosshair",
    "item_portable_device": "ChassisAssist FireControlStub ConfigManager ClickGui CameraFeed TongjiVisionBridge SerialBridge ControllerAngles RobotLink",
    "building_electric": "PowerGuard ThermalPowerPanel GimbalPower PowerLimit Capacitor WirelessCharging",
    "guide_battle": "ArmorAutoAim ArmorLock Armor3DESP CombatTargetHUD HUD MinecraftCombatHUD MatchMode",
    "item_special": "EnergyAutoAim LockState ArmorStatus EmergencyStop MatchReadiness",
    "weapon_lance": "HeroLob DartPanel ProjectileAllowance",
    "building_assemble": "FrictionWheel ChassisGimbalIndicator RobotProfile RobotOverlay",
    "building_logistic": "SpeedLimit UWBStatus MQTTLink UDPVideo",
    "building_battle": "SentinelCommand AirSupport BaseOutpostStatus VictoryPointStatus",
    "item_nature": "EconomyPanel ResourceIsland GainZone",
    "item_material": "ProjectileShop ReloadingPanel",
    "item_usable": "BuffStatus BuffTimeline MinecraftBuffs SkillConfiguration",
    "guide_all": "RadarOverlay TopMatchBar UIScale MinecraftInventory",
    "guide_system": "Scenario StartupVisual AllianceProfile AudioFeedback QuickActionWheel JumpPTEWheelLES MatchTimer MatchChat InjuryStatistics MatchSettlement EliminationFX RuneRingStatus",
}
CLIPS = (
    "wiki_in", "wiki_out", "wiki_btnoption_in", "wiki_btnoption_select",
    "wiki_btnoption_select_out", "wiki_group_in", "wiki_group_out",
    "wiki_weapon_in", "wiki_weapon_out", "wiki_search_in", "wiki_search_content_in",
    "wiki_search_out", "wiki_uideco_in", "wiki_uideco_loop", "wiki_topwidget_loop",
    "wiki_group_leftcell_in", "wiki_group_leftcellselect", "wiki_group_leftcellselect_out",
    "wiki_groupitemlist_in", "wiki_groupitemlist_out", "wiki_search_history_in",
    "wiki_search_content_out", "wiki_search_history_out",
    "itembigleft_in",
    "wiki_uideco_star_loop", "wiki_search_historycell_in",
    "wiki_uideco_grouppanel_in", "wiki_uideco_grouppanel_out", "wiki_uideco_out",
)


def json_numbers(value):
    """Unity 阶跃切线的 Infinity 用字符串保存，保持资源清单为标准 JSON。"""
    if isinstance(value, dict):
        return {key: json_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_numbers(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return "Infinity" if value > 0 else "-Infinity"
    return value


def verify_game_bundles(provenance, bundle_index: Path, game_vfs: Path):
    """直接读取本体分包，核验导出来源对应的 Bundle，留下可追溯摘要。"""
    wanted = {row["bundle"] for row in provenance}
    index = json.loads(bundle_index.read_text(encoding="utf-8"))
    checked = []
    for block in index["blocks"]:
        for chunk in block["chunks"]:
            for entry in chunk["files"]:
                if entry["name"] not in wanted:
                    continue
                source = game_vfs / chunk["name"]
                with source.open("rb") as stream:
                    stream.seek(entry["offset"])
                    data = stream.read(entry["length"])
                digest = hashlib.md5(data).hexdigest()
                # VFS 将 MD5 保存为小端 UInt128，索引 JSON 的十六进制需要反转字节序。
                expected = bytes.fromhex(entry["file_data_md5"])[::-1].hex()
                if len(data) != entry["length"] or digest != expected:
                    raise ValueError("Game Bundle verification failed: " + entry["name"])
                checked.append({"bundle": entry["name"], "chunk": str(source),
                                "offset": entry["offset"], "length": len(data), "md5": digest,
                                "sha256": hashlib.sha256(data).hexdigest()})
    missing = wanted - {row["bundle"] for row in checked}
    if missing:
        raise ValueError("Bundle index missing sources: " + str(sorted(missing)))
    return checked


def rotation_samples(clip):
    """将本体逐帧平面四元数转为连续角度，保留60 Hz采样，避免漏掉背景旋转。"""
    result = {}
    for track in clip.get("m_RotationCurves", ()):
        samples, previous, angle = [], None, 0.0
        for key in track["curve"]["m_Curve"]:
            value = key["value"]
            raw = -math.degrees(2 * math.atan2(value["z"], value["w"]))
            angle = (raw + 180) % 360 - 180 if previous is None else angle + (raw - previous + 180) % 360 - 180
            samples.append([round(key["time"], 6), round(angle, 6)])
            previous = raw
        result[track["path"]] = samples
    return result


def source_decorations(root, rows, image, images, output, provenance):
    """读取本体背景层级及首页装饰的几何/材质颜色，不由截图猜测位置。"""
    from PIL import Image, ImageChops, ImageDraw
    objects = {}
    for row in rows:
        if (row.get("parent_asset_path") or "").endswith(("wiki_uideco.prefab", "wikibtnoptionwidget.prefab", "/wikipanel.prefab")) \
                and row.get("type") in ("GameObject", "RectTransform", "MonoBehaviour"):
            try:
                objects[row["path_id"]] = decode(root, row)
            except (ValueError, KeyError):
                continue
    transforms = {key: value for key, value in objects.items() if "m_AnchoredPosition" in value}
    sprites = {row["path_id"]: row for row in rows if row.get("type") == "Sprite"}

    def node(key, path=""):
        transform = transforms[key]
        go = objects[transform["m_GameObject"]["m_PathID"]]
        path = path + "/" + go["m_Name"] if path else go["m_Name"]
        components = [objects.get(ref["component"]["m_PathID"], {}) for ref in go["m_Component"]]
        graphic = next((c for c in components if "m_Sprite" in c), {})
        source = sprites.get(graphic.get("m_Sprite", {}).get("m_PathID"), {})
        result = {"path": path, "transform": {k: transform[k] for k in (
            "m_AnchorMin", "m_AnchorMax", "m_AnchoredPosition", "m_SizeDelta", "m_Pivot", "m_LocalScale", "m_LocalRotation")},
            "color": graphic.get("m_Color", dict(r=1, g=1, b=1, a=1)),
            "alpha": next((c["m_Alpha"] for c in components if "m_Alpha" in c), 1),
            "children": [node(ref["m_PathID"], path) for ref in transform["m_Children"]
                         if ref["m_PathID"] in transforms]}
        if source and "BgDecoLayout/" in path:
            name = Path(source.get("parent_asset_path") or source["original_path"]).stem
            image_key = "scene_" + go["m_Name"].replace(" ", "_").replace("(", "").replace(")", "")
            image(image_key, name)
            result["image"] = image_key
            if graphic.get("m_Type") == 3 and graphic.get("m_FillMethod") == 4:
                # UIImage.Radial360从下方起、顺时针填充；只保留原圆环的弧段。
                amount = graphic["m_FillAmount"]
                origin, clockwise = graphic["m_FillOrigin"],bool(graphic["m_FillClockwise"])
                target = output/images[image_key]
                raster = Image.open(target).convert("RGBA")
                mask = Image.new("L",(raster.width*4,raster.height*4))
                start = 90+origin*90
                end = start+(360*amount if clockwise else -360*amount)
                ImageDraw.Draw(mask).pieslice((0,0,mask.width,mask.height),min(start,end),max(start,end),fill=255)
                mask = mask.resize(raster.size,Image.Resampling.LANCZOS)
                raster.putalpha(ImageChops.multiply(raster.getchannel("A"),mask))
                raster.save(target)
                result["radial_fill"] = {"amount":amount,"origin":origin,"clockwise":clockwise}
                provenance[-1].update(adaptation="source UIImage Radial360 fill geometry",
                                     sha256=hashlib.sha256(target.read_bytes()).hexdigest())
            if graphic.get("m_Type") == 2:
                target = output / images[image_key]
                tile = Image.open(target).convert("RGBA")
                size = transform["m_SizeDelta"]
                canvas = Image.new("RGBA", (round(size["x"]), round(size["y"])))
                multiplier = graphic.get("m_PixelsPerUnitMultiplier", 1)
                tile = tile.resize((max(1, round(tile.width / multiplier)), max(1, round(tile.height / multiplier))))
                for y in range(0, canvas.height, tile.height):
                    for x in range(0, canvas.width, tile.width):
                        canvas.paste(tile, (x, y))
                canvas.save(target)
                provenance[-1].update(adaptation="source UIImage tiled at prefab size and pixel multiplier",
                                     sha256=hashlib.sha256(target.read_bytes()).hexdigest())
        return result

    bg_key = next(key for key, t in transforms.items()
                  if objects[t["m_GameObject"]["m_PathID"]].get("m_Name") == "BgDecoLayout")
    select_key = next(key for key, t in transforms.items()
                     if objects[t["m_GameObject"]["m_PathID"]].get("m_Name") == "SelectNode")
    background = node(bg_key)
    selected = node(select_key)
    cell = next(t for t in transforms.values()
                if objects[t["m_GameObject"]["m_PathID"]].get("m_Name") == "WikiBtnOptionWidget")
    total = next(t for t in transforms.values()
                 if objects[t["m_GameObject"]["m_PathID"]].get("m_Name") == "TotalNode")
    components = objects[total["m_GameObject"]["m_PathID"]]["m_Component"]
    spacing = next(objects[ref["component"]["m_PathID"]]["m_Spacing"] for ref in components
                   if "m_Spacing" in objects.get(ref["component"]["m_PathID"], {}))
    layout = {"cell_width": cell["m_SizeDelta"]["x"], "spacing": spacing,
              "select_transform": selected["transform"]}
    return background, {n["path"].removeprefix("SelectNode/"): n for n in selected["children"]}, layout


def prepare(root: Path, output: Path, *, bundle_index: Path | None = None,
            game_vfs: Path | None = None, cell_export_root: Path | None = None,
            extra_export_root: Path | None = None) -> None:
    from PIL import Image
    rows = [json.loads(line) for line in (root / "_index.jsonl").open(encoding="utf-8")]
    if extra_export_root:
        for line in (extra_export_root / "_index.jsonl").open(encoding="utf-8"):
            row = json.loads(line)
            for key in ("metadata_path", "raw_path", "output_path"):
                if row.get(key):
                    row[key] = str((extra_export_root / row[key]).resolve())
            rows.append(row)
    output.mkdir(parents=True, exist_ok=True)
    textures = {row["name"]: row for row in rows if row.get("type") == "Texture2D"}
    clips = {row["name"]: row for row in rows if row.get("type") == "AnimationClip"}
    cell_clips = {row["name"]: row for row in
                  (json.loads(line) for line in (cell_export_root / "_index.jsonl").open(encoding="utf-8"))
                  if row.get("type") == "AnimationClip"} if cell_export_root else {}
    clips.update(cell_clips)
    images, provenance = {}, []

    def image(key, name, tint=False):
        row = textures[name]
        source = root / row["output_path"]
        target = output / (key + ".png")
        if tint:
            # UIImage 的白色遮罩按终端灰色材质烘焙，GPU/Qt 兼容路径使用同一成品。
            rgba = Image.open(source).convert("RGBA")
            color = tint if isinstance(tint, tuple) else (121, 122, 120, 255)
            result = Image.new("RGBA", rgba.size, color)
            result.putalpha(rgba.getchannel("A"))
            result.save(target)
        else:
            shutil.copyfile(source, target)
        images[key] = target.name
        provenance.append({"output": target.name, "source": row.get("original_path") or row.get("parent_asset_path"),
                           "texture_name": row["name"],
                           "bundle": row["source_path"], "object": row["path_id"],
                           "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                           "adaptation": ("UIImage tint " + str(color)) if tint else "decoded source texture"})

    for category, index in CATEGORY_ICONS.items():
        image(category, f"deco_wiki_icon_{index}", True)
        image(category + "Selected", f"deco_wiki_select_icon_{index}")
        image(category + "Flash", f"deco_wiki_select_icon_{index}", (255, 255, 255, 255))
        image(category + "Grid", f"deco_wiki_icon_{index}_{index}", True)
        image(category + "Deco", f"deco_wiki_bg_{index}", True)
    for index in range(1, 7):
        image("number" + str(index), f"deco_wiki_icon_0{index}")
    module_icons = {}
    for name, modules in MODULE_ICON_GROUPS.items():
        for selected, tint in ((False, (44, 44, 44, 255)), (True, (253, 253, 24, 255))):
            image("module_" + name + ("_selected" if selected else ""),
                  "icon_wiki_group_" + name, tint)
        module_icons.update({module: "module_" + name for module in modules.split()})
    for key, name, tint in (
        ("folder", "wiki_folder", (57, 57, 57, 255)),
        ("path_arrow", "wiki_arrows", (57, 57, 57, 255)),
        ("path_parent", "deco_wiki_top_bg", (57, 57, 57, 255)),
        ("module_selected_bg", "bg_wiki_equip_btn_select", False),
        ("module_deco", "deco_wiki_group_17", False),
        ("back", "btn_common_return_shadeless", (68, 68, 68, 255)),
        ("close", "close_btn_bg_shadeless", (68, 68, 68, 255)),
        ("search", "wiki_magnifying_glass", (57, 57, 57, 255)),
    ):
        image(key, name, tint)
    for key, name in {
        "background": "deco_wiki_bg09_map", "logo": "deco_wiki_bg07_logo",
        "ring": "deco_wiki_bg04_ring", "line": "deco_wiki_bgbuttomline",
        "triangle": "deco_wiki_triangle", "topdeco": "deco_wiki_17",
        "select_background": "deco_wiki_select_bg",
        "selected_disc": "deco_wiki_1",
        "selected_symbol1": "deco_wiki_symbol_1",
        "selected_symbol2": "deco_wiki_symbol_2",
        "selected_symbol3": "deco_wiki_symbol_3",
        "selected_symbol4": "deco_wiki_symbol_4",
    }.items():
        image(key, name, key in ("background", "folder", "line"))
    background_nodes, home_nodes, home_layout = source_decorations(root, rows, image, images, output, provenance)
    breadcrumbs = prepare_breadcrumbs(root, rows, output, images, provenance)
    layers = prepare_layers(root, rows, output, images, provenance)
    # 这些矢量是项目维护的源资源，新输出目录也必须得到完整运行包。
    for name in ("settings", "chevron", "topgrid", "home_blackmask"):
        filename = name + ".svg"
        source = ASSETS / filename
        target = output / filename
        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)
        images[name] = filename
    # 字体与许可随功能包分发，离线输出不能借用其他资源目录。
    (output / "fonts").mkdir(exist_ok=True)
    for filename in ("NotoSansSC.ttf", "NotoSansSC-OFL.txt", "manifest.json"):
        source = ASSETS / "fonts" / filename
        target = output / "fonts" / filename
        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)
    animations = {}
    for name in CLIPS:
        clip = decode(cell_export_root if name in cell_clips else root, clips[name])
        animations[name] = {k: clip[k] for k in (
            "m_FloatCurves", "m_PositionCurves", "m_ScaleCurves", "m_SampleRate")}
        if name == "wiki_uideco_loop":
            animations[name]["rotation_samples"] = rotation_samples(clip)
    controller_row = next(row for row in rows if row.get("type") == "AnimatorController"
                          and row.get("name") == "wiki_group_leftcellselect_btn")
    controller = decode(root, controller_row)
    button_states = {}
    for pointer in controller["m_AnimationClips"]:
        row = next(row for row in rows if row.get("path_id") == pointer["m_PathID"])
        clip = decode(root, row)
        values = clip["m_MuscleClip"]["m_Clip"]["data"]["m_ConstantClip"]["data"]
        # CRC32 路径/属性由 TabCell 层级和 m_Color.r/g/b/a 核对。
        button_states[row["name"]] = {"normal_bg": values[:4], "selected_bg": values[4:8],
                                      "selected_deco": values[8:11]}
    layout = {"schema": 1, "canvas": [1920, 1080], "images": images,
              "font": "fonts/NotoSansSC.ttf",
              "category_icons": CATEGORY_ICONS, "module_icons": module_icons, "clips": animations,
              "tab_button": {"states": button_states, "hover_in": 0.0, "hover_out": .1,
                             "source": controller_row["parent_asset_path"]},
              "background_nodes": background_nodes, "home_select_nodes": home_nodes, "home_layout": home_layout,
              "breadcrumbs": breadcrumbs,
              "layers": layers,
              "adaptation": "six original RM categories; live Module/Setting identity and command owners retained"}
    (output / "layout.json").write_text(json.dumps(json_numbers(layout), ensure_ascii=False,
                                                  allow_nan=False, separators=(",", ":")), encoding="utf-8")
    prefabs = ("wikipanel.prefab", "wikigrouppanel.prefab", "wikisearchpanel.prefab", "widgets/wikitopwidget.prefab",
               "widgets/wikibtnoptionwidget.prefab")
    documents = [{"source": "assets/beyond/dynamicassets/gameplay/ui/prefabs/wiki/" + name,
                  "bundle": next(row["source_path"] for row in rows
                      if (row.get("parent_asset_path") or "").endswith("/" + name))}
                 for name in prefabs]
    documents.extend({"source": clips[name].get("original_path") or clips[name].get("parent_asset_path"),
                      "clip": name, "object": clips[name]["path_id"],
                      "serialized_file": clips[name]["serialized_file"],
                      "bundle": clips[name]["source_path"]} for name in CLIPS)
    documents.append({"source": controller_row["parent_asset_path"], "bundle": controller_row["source_path"]})
    deco = next(row for row in rows if (row.get("parent_asset_path") or "").endswith("wiki_uideco.prefab"))
    documents.append({"source": deco["parent_asset_path"], "bundle": deco["source_path"]})
    documents.extend(dependency for entry in provenance for dependency in entry.get("dependencies", ()))
    checked = verify_game_bundles([*provenance, *documents], bundle_index, game_vfs) if bundle_index and game_vfs else []
    (output / "PROVENANCE.json").write_text(json.dumps({"origin": "local Endfield Wiki original export",
        "files": provenance, "clips": CLIPS, "source_documents": documents, "verified_game_bundles": checked},
        ensure_ascii=False, indent=2), encoding="utf-8")
    write_manifest(output)
    print(f"Prepared {len(images)} textures and {len(animations)} authored Wiki clips")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--bundle-index", type=Path)
    parser.add_argument("--game-vfs", type=Path)
    parser.add_argument("--cell-export-root", type=Path,
                        help="WikiGroup ItemBig 所引用的 common/itembigleft_in.anim 原始导出")
    parser.add_argument("--extra-export-root", type=Path, help="搜索卡片等共享纹理的补充分包原始导出")
    args = parser.parse_args()
    if bool(args.bundle_index) != bool(args.game_vfs):
        parser.error("--bundle-index and --game-vfs must be supplied together")
    prepare(args.export_root.resolve(), args.out.resolve(),
            bundle_index=args.bundle_index, game_vfs=args.game_vfs,
            cell_export_root=args.cell_export_root, extra_export_root=args.extra_export_root)
