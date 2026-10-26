"""仅保留旧画布的手势回归夹具；生产快捷键入口已使用Endfield。"""
from rm_client.ui.jello_keybinds import BindingSession, KeyboardCanvas
from rm_client.ui.jello_widgets import JelloDialog, apply_jello_widgets
from rm_client.ui.emergency_shortcut import install_estop_shortcut


def legacy_keyboard_dialog(host):
    dialog = JelloDialog(host,keyboard=True)
    available = host.screen().availableGeometry()
    dialog.resize(min(1280,available.width()-30,max(600,host.width()-20)),
                  min(860,available.height()-40,max(430,host.height()-20)))
    dialog.setMinimumSize(600,430)
    dialog.session = BindingSession(host)
    dialog.canvas = KeyboardCanvas(dialog,dialog.session)
    dialog.focus_widget = dialog.canvas
    dialog.panel.layout().setContentsMargins(0,0,0,0)
    dialog.panel.layout().addWidget(dialog.canvas)
    dialog.estop_shortcut = install_estop_shortcut(dialog,host)
    apply_jello_widgets(dialog)
    return dialog
