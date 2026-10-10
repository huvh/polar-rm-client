"""Ammo detail extension shared by the existing GPU/compat economy sheets."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFont, QPainter

from ..student_ui import presentation_data, value_text
from .clickgui_gpu import ClickGuiDrawList
from .paint import rounded_rect
from .theme import color


def reload_detail_height(host) -> float:
    if host.economy_category != "ammo":
        return 0.0
    return 290.0 if host.student_reload_expanded else 38.0


def append_reload_details(host, commands: ClickGuiDrawList, rect: QRectF,
                          clip: QRectF, alpha: float, scale: float = 1.0,
                          interactive: bool = True) -> None:
    if host.economy_category != "ammo":
        return
    s = scale
    def r(x, y, w, h):
        return QRectF(rect.left()+x*s, rect.top()+y*s, w*s, h*s)
    width = rect.width()/s
    def text(box, label, tint="#d5e2ee", size=8.8, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter):
        font = QFont("Microsoft YaHei UI")
        font.setStyleName("Regular"); font.setPointSizeF(size*s)
        commands.text(box, label, font, color(tint, alpha), alignment, clip=clip, preserve_weight=True)
    def button(box, label, action, payload=None, active=False):
        commands.rect(box, box.height()/2, color("#39aaff" if active else "#ffffff", (0.27 if active else 0.08)*alpha), clip=clip)
        text(box, label, alignment=Qt.AlignmentFlag.AlignCenter)
        visible=box.intersected(clip)
        if interactive and alpha >= 0.65 and not visible.isEmpty():
            host.add_hotspot(visible, action, payload, tooltip=label)
    button(r(0,0,width,30), "补弹 / 换弹  " + ("▾" if host.student_reload_expanded else "▸"), "student_reload_toggle")
    if not host.student_reload_expanded:
        return
    data=presentation_data(host.state).get("reloading", {})
    data=data if isinstance(data,dict) else {}
    zone=data.get("in_supplier_zone")
    zone_text="未在补弹区" if zone is False else "已在补弹区" if zone is True else "补弹区位置：等待官方状态"
    rows=(
        ("已有允许发弹量", f"17mm {value_text(host.state.projectile_allowance_17mm)} / 42mm {value_text(host.state.projectile_allowance_42mm)}"),
        ("可兑换允许发弹量", value_text(data.get("virtual_reserve"))),
        ("补给站实体储备", value_text(data.get("physical_reserve"))),
        ("补给位置",zone_text),
    )
    for i,(label,value) in enumerate(rows):
        text(r(6,36+i*26,width-12,24), f"{label}  ·  {value}", "#aebfd0", 8.1)
    half=(width-8)/2
    for i,(key,label) in enumerate((("Left","左闸"),("Right","右闸"))):
        button(r(i*(half+8),145,half,30),label+"（草稿）","student_gate",key,host.student_ui.gate==key)
    text(r(6,181,width-12,24),f"加弹数量（草稿）  {host.student_ui.quantity}")
    button(r(0,210,half,28),"− 10","student_quantity",-10)
    button(r(half+8,210,half,28),"+ 10","student_quantity",10)
    text(r(6,244,width-12,35),"闸口/实体补弹仅前端草稿；买弹沿用原确认入口", "#ffd187",7.7)


def paint_reload_commands(host, p: QPainter, commands: ClickGuiDrawList) -> None:
    # Identical extension geometry in the compatibility path. Never touches
    # economy lens materials, refraction parameters or transaction semantics.
    for command in commands.commands:
        item=command.payload
        p.save()
        if item.clip is not None:
            p.setClipRect(item.clip, Qt.ClipOperation.IntersectClip)
        if hasattr(item,"fill"):
            rounded_rect(p,item.rect,item.radius,item.fill)
        else:
            host.draw_text(p,item.rect,item.text,item.font,item.color,item.alignment)
        p.restore()
