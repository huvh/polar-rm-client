"""独立实体键盘与当前按键的绑定条；配置只由原BindingSession提交。"""
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QLineEdit, QPushButton, QDialog, QScrollArea

from ...emergency_shortcut import install_estop_shortcut
from ..settings.shell import EndfieldSettingsDialog, apply_settings_widgets
from ..settings.widgets import EndfieldComboBox
from ..settings.resources import ASSETS
from .capture import KeyCapturePopup
from .keyboard import KeyboardView


class KeybindDialog(EndfieldSettingsDialog):
    def current_entry(self):
        index = self.function_combo.currentData()
        return self.session.entries[index] if index is not None else None

    def capture(self, entry):
        popup = KeyCapturePopup(self,entry)
        try:
            if popup.exec() == QDialog.DialogCode.Accepted and popup.selected_key is not None:
                self.session.assign(entry,popup.selected_key)
                self.select_key(popup.selected_key)
                self.status.setText("已暂存："+entry.title+" → "+popup.selected_key)
        finally:
            popup.deleteLater()

    def clear(self, entry):
        try:
            self.session.clear(entry)
            self.select_key(self.keyboard.selected_key)
            self.status.setText("已暂存清除："+entry.title)
        except ValueError as error:
            self.status.setText(str(error))

    def select_key(self, key):
        if key not in self.keyboard.keys:
            return
        self.keyboard.selected_key = key
        bound = self.session.bound(key)
        self.selected_label.setText(self.keyboard.keys[key].label+f" · {len(bound)} 项绑定")
        layout = self.bound_content.layout()
        while layout.count():
            item = layout.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        self.bound_buttons = {}
        for entry in bound:
            button = QPushButton(entry.title+"  ×")
            button.setToolTip(entry.category+" · 点击清除草稿绑定")
            button.setEnabled(not entry.readonly)
            button.clicked.connect(lambda checked=False,binding=entry: self.clear(binding))
            layout.addWidget(button)
            self.bound_buttons[entry.identity] = button
        if not bound:
            layout.addWidget(QLabel("此键尚未绑定功能"))
        layout.addStretch()
        self.filter(self.search.text())

    def select_entry(self, entry):
        self.search.clear()
        index = self.function_combo.findData(self.session.entries.index(entry))
        self.function_combo.setCurrentIndex(index)
        key = self.session.values[entry.identity]
        if key in self.keyboard.keys:
            self.select_key(key)

    def update_actions(self):
        entry = self.current_entry()
        self.bind_button.setEnabled(entry is not None and not entry.readonly)
        self.change_button.setEnabled(entry is not None and not entry.readonly)
        if entry is not None:
            self.bind_button.setToolTip(self.session.reason(entry,self.keyboard.selected_key) or "写入当前窗口草稿")

    def bind_selected(self):
        entry = self.current_entry()
        if entry is None:
            return
        try:
            key = self.keyboard.selected_key
            self.session.assign(entry,key)
            self.select_key(key)
            self.status.setText("已暂存："+entry.title+" → "+key)
        except ValueError as error:
            self.status.setText(str(error))

    def filter(self, text):
        previous = self.function_combo.currentData()
        self.function_combo.blockSignals(True)
        self.function_combo.clear()
        query = text.casefold().strip()
        for index,entry in enumerate(self.session.entries):
            key = self.session.values[entry.identity]
            if query in (entry.title+" "+entry.category+" "+key).casefold():
                self.function_combo.addItem(entry.title+" · "+entry.category,index)
        index = self.function_combo.findData(previous)
        self.function_combo.setCurrentIndex(0 if index < 0 and self.function_combo.count() == 1 else index)
        self.function_combo.blockSignals(False)
        self.keyboard.set_query(text)
        self.update_actions()


def build_keybind_dialog(host, session, keys, target=None, parent=None):
    dialog = KeybindDialog(parent or host)
    try:
        dialog.setObjectName("EndfieldKeybindManager")
        dialog.setWindowTitle("POLAR · 快捷键")
        dialog.resize(max(720,host.width()),max(540,host.height()))
        dialog.setMinimumSize(720,540)
        dialog.session, dialog.keys = session, keys
        for shortcut in dialog._keys:
            shortcut.setEnabled(False)
        root = dialog.panel.layout()
        header = QHBoxLayout()
        title = QLabel("//快捷键")
        header.addWidget(title)
        header.addStretch()
        dialog.search = QLineEdit()
        dialog.search.setPlaceholderText("搜索功能或按键，在键盘上定位…")
        dialog.search.setMaximumWidth(370)
        header.addWidget(dialog.search)
        dialog.close_button = QPushButton()
        dialog.close_button.setObjectName("EndfieldSettingsClose")
        dialog.close_button.setIcon(QIcon(str(ASSETS/"close.png")))
        dialog.close_button.setIconSize(QSize(36,36))
        dialog.close_button.setFixedSize(40,40)
        dialog.close_button.setAccessibleName("关闭快捷键，返回上一级")
        dialog.close_button.clicked.connect(dialog.reject)
        header.addWidget(dialog.close_button)
        root.addLayout(header)
        legend = QLabel("点击键帽查看绑定 · 黄色为当前按键 · 底部短线表示已有绑定")
        legend.setProperty("hint",True)
        root.addWidget(legend)
        dialog.keyboard = KeyboardView(dialog)
        dialog.keyboard.selected.connect(dialog.select_key)
        root.addWidget(dialog.keyboard,1)
        selected = QHBoxLayout()
        dialog.selected_label = QLabel()
        dialog.selected_label.setMinimumWidth(110)
        selected.addWidget(dialog.selected_label)
        bound_scroll = QScrollArea()
        bound_scroll.setWidgetResizable(True)
        bound_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        bound_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        bound_scroll.setFixedHeight(58)
        dialog.bound_content = QWidget()
        chips = QHBoxLayout(dialog.bound_content)
        chips.setContentsMargins(0,0,0,0)
        bound_scroll.setWidget(dialog.bound_content)
        selected.addWidget(bound_scroll,1)
        root.addLayout(selected)
        actions = QHBoxLayout()
        dialog.function_combo = EndfieldComboBox()
        dialog.function_combo.setPlaceholderText("选择要绑定的功能…")
        dialog.function_combo.setAccessibleName("要添加或改绑的功能")
        actions.addWidget(dialog.function_combo,1)
        dialog.bind_button = QPushButton("绑定到此键")
        dialog.change_button = QPushButton("按键输入…")
        actions.addWidget(dialog.bind_button)
        actions.addWidget(dialog.change_button)
        root.addLayout(actions)
        dialog.function_combo.currentIndexChanged.connect(dialog.update_actions)
        dialog.bind_button.clicked.connect(dialog.bind_selected)
        dialog.change_button.clicked.connect(lambda: dialog.capture(dialog.current_entry()))
        dialog.status = QLabel("仅编辑草稿，确认快捷键后应用。F11 全屏 / F12 急停始终有效。")
        dialog.status.setWordWrap(True)
        dialog.status.setProperty("hint",True)
        root.addWidget(dialog.status)
        footer = QHBoxLayout()
        footer.addStretch()
        dialog.back_button = QPushButton("返回")
        dialog.confirm_button = QPushButton("确认快捷键")
        dialog.back_button.clicked.connect(dialog.reject)
        dialog.confirm_button.clicked.connect(dialog.accept)
        footer.addWidget(dialog.back_button)
        footer.addWidget(dialog.confirm_button)
        root.addLayout(footer)
        dialog.search.textChanged.connect(dialog.filter)
        dialog.filter("")
        dialog.select_key("W")
        if target is not None:
            entry = next((entry for entry in session.entries if entry.identity == target),None)
            if entry is not None:
                dialog.select_entry(entry)
        dialog.estop_shortcut = install_estop_shortcut(dialog,host)
        apply_settings_widgets(dialog)
        dialog.apply_layout_scale()
        return dialog
    except Exception as error:
        try:
            dialog.deleteLater()
        finally:
            raise error
