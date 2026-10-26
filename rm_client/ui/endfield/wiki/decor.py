"""Wiki 本体背景层级与首页悬停轨道的二维呈现；不持有模块或输入状态。"""
from __future__ import annotations

import math
from PySide6.QtGui import QColor


def _rotate(x, y, angle):
    angle = math.radians(angle)
    return x * math.cos(angle) - y * math.sin(angle), x * math.sin(angle) + y * math.cos(angle)


def draw_background(renderer):
    root = renderer.pack.get("background_nodes")
    if root:
        cx,cy,scale,opacity = renderer.background_projection
        _background_node(renderer, root, cx,cy,scale,0,opacity)


def _background_node(r, node, cx, cy, scale, angle, opacity):
    """合成原 prefab 的父子变换；旋转来自原循环片段的逐帧四元数。"""
    transform, motion = node["transform"], r.motion
    path = node["path"]
    loop_path = path.removeprefix("BgDecoLayout/")
    at = r.state.session_time
    loop_at = at % motion.durations["wiki_uideco_loop"]
    def sample(attribute, default, axis=None):
        return r.background.sample(motion,"HudNode/"+path,attribute,r.now,default,axis)

    pos, size, pivot = (transform[n] for n in ("m_AnchoredPosition", "m_SizeDelta", "m_Pivot"))
    x = sample("m_AnchoredPosition.x", pos["x"])
    y = -sample("m_AnchoredPosition.y", pos["y"])
    x, y = _rotate(x * scale, y * scale, angle)
    cx, cy = cx + x, cy + y
    q = transform["m_LocalRotation"]
    static_angle = -math.degrees(2 * math.atan2(q["z"], q["w"]))
    angle += motion.rotation("wiki_uideco_loop", loop_path, loop_at, static_angle)
    scale *= abs(sample("m_ScaleCurves", transform["m_LocalScale"]["x"], "x"))
    opacity *= sample("m_Alpha", node["alpha"])
    if node.get("image"):
        color = node["color"]
        tint = QColor.fromRgbF(*(max(0, min(1, sample("m_Color." + channel, color[channel]))) for channel in "rgb"))
        alpha = sample("m_Color.a", color["a"]) * opacity
        width, height = size["x"] * scale, size["y"] * scale
        px, py = _rotate((.5 - pivot["x"]) * width, (pivot["y"] - .5) * height, angle)
        r._image(node["image"], cx + px - width / 2, cy + py - height / 2,
                 width, height, alpha, tint=tint, rotation=angle)
    for child in node["children"]:
        _background_node(r, child, cx, cy, scale, angle, opacity)


def draw_home_selection(r, category, x, icon_y, reveal, pose):
    """同一个悬停时钟驱动软遮罩、明暗闪变、定位方块及错峰三角。"""
    if not pose.played:
        return
    if not pose.hovered and r.now - pose.changed_at >= r.motion.durations["wiki_btnoption_select_out"]:
        return
    layout = r.pack["home_layout"]
    # 同一个水平单元比例同时换算锚点、位移和宽度，不能把 160 px 轨道叠到另一套栏宽上。
    scale = 257 / (layout["cell_width"] + layout["spacing"])
    cx, cy = x + 103, 584 + icon_y - 461
    parent_width = (layout["cell_width"] + layout["select_transform"]["m_SizeDelta"]["x"]) * scale
    left, top, parent_height = cx - parent_width / 2, cy - 496, 992
    column = r._r(left, top, parent_width, parent_height)
    nodes = r.pack["home_select_nodes"]

    def track(path, attribute, default=0, axis=None):
        return pose.track(r.motion, path, attribute, r.now, default, axis)

    def color(path, default=1):
        return QColor.fromRgbF(*(max(0, min(1, track(path, "m_Color." + channel, default))) for channel in "rgb"))

    def geometry(path):
        t = nodes[path]["transform"]
        pos, size, pivot = (t[n] for n in ("m_AnchoredPosition", "m_SizeDelta", "m_Pivot"))
        amin, amax = t["m_AnchorMin"], t["m_AnchorMax"]
        width = parent_width * (amax["x"] - amin["x"]) + track(path, "m_SizeDelta.x", size["x"]) * scale
        height = parent_height * (amax["y"] - amin["y"]) + size["y"] * scale
        ax = left + parent_width * (amin["x"] + (amax["x"] - amin["x"]) * pivot["x"])
        ay = top + parent_height * (1 - amin["y"] - (amax["y"] - amin["y"]) * pivot["y"])
        px = ax + track(path, "m_AnchoredPosition.x", pos["x"]) * scale - width * pivot["x"]
        py = ay - track(path, "m_AnchoredPosition.y", pos["y"]) * scale - height * (1 - pivot["y"])
        return px, py, width, height

    base = track("ImgBg", "m_Color.a") * reveal
    mask = track("ImgBgBlackmask", "m_Alpha") * reveal
    if mask > .001:
        softness = track("ImgBgBlackmask", "m_Softness.y", 1000) * scale
        r._image("home_blackmask", *geometry("ImgBgBlackmask"), mask, tint="#121212", softness_y=softness)
    if base > .001:
        # 保留本体斜纹的明暗；不能再被纯色软遮罩整层盖住。
        r._image("select_background", *geometry("ImgBg"), base)
    disc_scale = track("ImgDeco3", "m_ScaleCurves", 1, "x")
    width, height = 440 * scale * disc_scale, 447 * scale * disc_scale
    r._image("selected_disc", cx - width / 2, cy - 80 * scale - height / 2, width, height,
             track("ImgDeco3", "m_Color.a", .502) * reveal, clip=column, tint=color("ImgDeco3"))
    selected_rect = (cx - 225 * scale, cy - 280 * scale, 450 * scale, 400 * scale)
    r._image(category + "Selected", *selected_rect,
             track("Mask/ImgIcon", "m_Color.a") * reveal, clip=column, tint=color("Mask/ImgIcon"))
    flash_color = QColor.fromRgbF(*(max(0, min(1, track("Mask/ImgIconVFX", "_propertiesColor2." + channel, .449)))
                                   for channel in "rgb"))
    r._image(category + "Flash", *selected_rect,
             track("Mask/ImgIconVFX", "m_Color.a") * reveal, clip=column, tint=flash_color)
    # 详细图已有原色/闪现两层，不再把普通灰图标叠到选中层中拖到583 ms才消失。
    for path in ("ImgDeco1", "ImgDeco2"):
        alpha = track(path, "m_Color.a") * reveal
        r._box(*geometry(path), color(path, .447), alpha=alpha, clip=column)
    for path in ("LeftPointImage", "RightPointImage"):
        r._box(*geometry(path), "#060606",
               alpha=track(path, "m_Color.a") * reveal)
    for path in ("ImgTriangle1", "ImgTriangle2"):
        r._image("triangle", *geometry(path), track(path, "m_Color.a") * reveal,
                 clip=column, tint="#fdfd18")
    for index in range(6, 14):
        path = "ImgDeco" + str(index)
        symbol = (index - 6) % 4 + 1
        r._image("selected_symbol" + str(symbol), *geometry(path),
                 track(path, "m_Color.a") * reveal, clip=column, tint="#b4b4b4")
