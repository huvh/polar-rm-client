"""设置中心的本体列表式键位编辑，复用原 BindingSession 校验和草稿。"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from .scroll import EndfieldScrollArea
from ...emergency_shortcut import install_estop_shortcut
from .shell import EndfieldSettingsDialog, apply_settings_widgets
from .widgets import EndfieldComboBox, add_setting_row


def build_binding_manager(host, session, keys, target=None, parent=None):
    dialog = EndfieldSettingsDialog(parent or host)
    try:
        dialog.setObjectName("EndfieldBindingManager")
        dialog.setWindowTitle("POLAR · 键位设置")
        dialog.resize(max(720, host.width()), max(540, host.height()))
        dialog.session = session
        dialog.binding_controls = {}
        root = dialog.panel.layout()
        title = QLabel("//设置 / 键位")
        root.addWidget(title)
        search = QLineEdit()
        search.setPlaceholderText("搜索功能或按键…")
        root.addWidget(search)
        scroll = EndfieldScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        form.setSpacing(6)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)
        status = QLabel("编辑写入当前设置页草稿，应用当前页后生效。F12 急停始终有效。")
        status.setWordWrap(True)
        root.addWidget(status)
        rows = []
        for entry in dialog.session.entries:
            controls = QWidget()
            buttons = QHBoxLayout(controls)
            buttons.setContentsMargins(0,0,0,0)
            combo = EndfieldComboBox()
            combo.addItems(["None", *keys])
            value = dialog.session.values[entry.identity]
            if combo.findText(value) < 0:
                combo.addItem(value)
            combo.setCurrentText(value)
            combo.setEnabled(not entry.readonly)
            dialog.binding_controls[entry.identity] = combo
            clear = QPushButton("清除")
            clear.setEnabled(not entry.readonly)
            buttons.addWidget(combo, 1)
            buttons.addWidget(clear)
            row = add_setting_row(form, entry.title, controls)
            row.setToolTip(entry.category)
            rows.append((row, entry))

            def assign(text, binding=entry, field=combo):
                previous = dialog.session.values[binding.identity]
                try:
                    if text == "None":
                        dialog.session.clear(binding)
                    else:
                        dialog.session.assign(binding, text)
                    status.setText("已暂存："+binding.title+" → "+text)
                except ValueError as error:
                    field.blockSignals(True)
                    field.setCurrentText(previous)
                    field.blockSignals(False)
                    status.setText(str(error))
            combo.currentTextChanged.connect(assign)
            clear.clicked.connect(lambda checked=False, field=combo: field.setCurrentText("None"))
            if entry.identity == target:
                QTimer.singleShot(500, dialog, lambda item=row: scroll.ensureWidgetVisible(item))
        search.textChanged.connect(lambda text: [row.setVisible(text.casefold() in
            (entry.title+" "+entry.category+" "+dialog.session.values[entry.identity]).casefold()) for row,entry in rows])
        footer = QHBoxLayout()
        root.addLayout(footer)
        footer.addStretch()
        back = QPushButton("返回")
        done = QPushButton("确认键位")
        footer.addWidget(back)
        footer.addWidget(done)
        back.clicked.connect(dialog.reject)
        done.clicked.connect(dialog.accept)
        dialog.estop_shortcut = install_estop_shortcut(dialog, host)
        apply_settings_widgets(dialog)
        return dialog
    except Exception:
        dialog.deleteLater()
        raise
