"""菜单模态路由：退出确认沿用 Jello，更新日志使用原版公告组件。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel, QPushButton, QHBoxLayout, QDialog, QScrollArea, QWidget, QVBoxLayout, QLayout,
)

from rm_client.ui.emergency_shortcut import install_estop_shortcut
from rm_client.ui.jello_widgets import JelloDialog, apply_jello_widgets
from rm_client.ui.jello_locale import chinese_enabled
from rm_client.ui.jello_scroll import JelloScrollArea


def _dialog(host, title, text, *, confirm=False, scroll=False, back_label=None):
    host.backend.lock_control("menu dialog opened")
    host._neutralize_modal_inputs()
    dialog = JelloDialog(host)
    try:
        if scroll:
            dialog.resize(min(680, max(360, host.width()-80)), min(560, max(240, host.height()-80)))
        else:
            dialog.resize(560, 260)
        dialog.setWindowTitle(title)
        dialog.panel.layout().addWidget(QLabel(title))
        label = QLabel(text)
        label.setWordWrap(True)
        if scroll:
            label.setAlignment(Qt.AlignmentFlag.AlignTop)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            area = JelloScrollArea()
            area.setObjectName("ChangelogBody")
            area.setWidgetResizable(True)
            area.setFrameShape(QScrollArea.Shape.NoFrame)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            content = QWidget()
            layout = QVBoxLayout(content)
            layout.setContentsMargins(0, 0, 8, 0)
            layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
            layout.addWidget(label)
            area.setWidget(content)
            dialog.panel.layout().addWidget(area, 1)
        else:
            dialog.panel.layout().addWidget(label)
        row = QHBoxLayout()
        cancel = QPushButton(back_label or ("取消" if confirm else "返回"))
        cancel.clicked.connect(dialog.reject)
        row.addWidget(cancel)
        if confirm:
            accept = QPushButton("确认退出")
            accept.clicked.connect(dialog.accept)
            row.addWidget(accept)
        dialog.panel.layout().addLayout(row)
        apply_jello_widgets(dialog)
        dialog.estop_shortcut = install_estop_shortcut(dialog, host)
        return dialog.exec() == QDialog.DialogCode.Accepted
    finally:
        dialog.deleteLater()
        host._neutralize_modal_inputs()
        host.frame_scheduler.force()


def confirm_exit(host):
    return _dialog(host, "退出 POLAR-RM？", "退出前将清空本地输入、锁定操控并清理连接。", confirm=True)


def changelog_text(chinese):
    if chinese:
        return (
            "2026.10.21 · 本地更新\n\n"
            "新增\n"
            "• 终末地式 Esc 菜单，接入设置、显示、键位与返回战斗等入口。\n"
            "• 2027 官方场地模型预览，支持 7v7、3v3、1v1 赛制切换。\n\n"
            "优化\n"
            "• 菜单背景使用 GPU 高斯模糊与压暗，暂时隐藏战斗 HUD，退出后恢复。\n"
            "• 保留 Jello 设置与键盘绑定界面，以及原有液态玻璃材质。\n\n"
            "修复\n"
            "• 按钮悬停闪烁、鼠标移出后的高亮残留。\n"
            "• 背景 HUD 重复叠加，以及模糊背景尚未就绪就显示菜单的问题。\n"
            "• GPU 绘制清理返回值被误判，导致意外回退普通绘制的问题。\n\n"
            "说明：这是本地界面更新记录，不代表已发布新版本或通过实战资格验证。"
        )
    return (
        "2026.10.21 · Local changes\n\n"
        "Added\n"
        "• Endfield-style Esc menu with settings, display, key bindings and return-to-combat actions.\n"
        "• Official 2027 field previews for 7v7, 3v3 and 1v1.\n\n"
        "Improved\n"
        "• GPU Gaussian blur and dimmed menu backdrop; combat HUD hides temporarily and restores on exit.\n"
        "• Existing Jello settings, keyboard binding screen and liquid-glass materials retained.\n\n"
        "Fixed\n"
        "• Flickering hover states and highlights left behind after pointer exit.\n"
        "• Duplicate background HUD and premature menu reveal before the backdrop is ready.\n"
        "• Incorrect GPU painter cleanup rejection that caused unintended compatibility rendering.\n\n"
        "Note: local UI changes only, not a new release or real-match qualification."
    )


def show_changelog(host):
    from .changelog.dialog import show_changelog as show_original_changelog
    return show_original_changelog(host)


# Compatibility for older internal callers; the menu now presents a changelog.
show_help = show_changelog
