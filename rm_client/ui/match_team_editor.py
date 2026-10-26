"""Explicit, non-modal identity import/editing; never starts a link or controls."""
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                              QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout)

from .fonts import cjk_ui_font
from .jello_locale import chinese_enabled
from .match_teams import TeamIdentity, SIDES


class MatchTeamEditor(QDialog):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.store = host.top_match_bar.team_profiles
        self.draft = dict(self.store.teams)
        self.fields = {}
        zh = chinese_enabled(host.registry)
        self.tr_text = lambda cn,en: cn if zh else en
        self.setWindowTitle(self.tr_text('比赛队伍资料','Match team identities'))
        self.setWindowModality(Qt.NonModal)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.resize(700,390)
        self.setFont(cjk_ui_font(QFont('Arial',10)))
        outer = QVBoxLayout(self)
        notice = QLabel(self.tr_text(
            '只替换 CS 队徽与队名原位，不改变机器人 ID、红蓝敌我关系或裁判数据。',
            'Replaces CS team emblems/names in place. No robot, alliance or referee changes.'))
        notice.setWordWrap(True);outer.addWidget(notice)
        row = QHBoxLayout();outer.addLayout(row)
        for side in SIDES:
            group = QGroupBox(self.tr_text('红方','Red') if side=='Red' else self.tr_text('蓝方','Blue'))
            form = QFormLayout(group);row.addWidget(group)
            logo = QLabel();logo.setFixedSize(80,80);logo.setAlignment(Qt.AlignCenter)
            school = QLineEdit(); school.setMaxLength(80)
            team = QLineEdit(); team.setMaxLength(80)
            form.addRow(logo)
            form.addRow(self.tr_text('学校','University'),school)
            form.addRow(self.tr_text('战队名','Team name'),team)
            buttons = QHBoxLayout()
            pick = QPushButton(self.tr_text('导入校徽','Import logo'))
            clear = QPushButton(self.tr_text('清除校徽','Clear logo'))
            buttons.addWidget(pick);buttons.addWidget(clear);form.addRow(buttons)
            pick.clicked.connect(lambda _checked=False,s=side: self.pick_logo(s))
            clear.clicked.connect(lambda _checked=False,s=side: self.clear_logo(s))
            self.fields[side] = (school,team,logo)
        self.error = QLabel(self.store.error);self.error.setWordWrap(True)
        self.error.setStyleSheet('color: #ca6154;');outer.addWidget(self.error)
        import_button = QPushButton(self.tr_text('导入官方 match_info JSON + 同目录校徽',
                                                'Import official match_info JSON + adjacent logos'))
        import_button.clicked.connect(self.pick_official);outer.addWidget(import_button)
        outer.addWidget(QLabel(self.tr_text('仅导入本地文件，不联网下载 JSON 中的图片地址。',
                                           'Local files only; image URLs in JSON are not fetched.')))
        buttons = QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save);buttons.rejected.connect(self.reject);outer.addWidget(buttons)
        # Return inside an edit field must not accidentally commit the form.
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False);button.setDefault(False)
        self.populate()

    def populate(self):
        for side,(school,team,preview) in self.fields.items():
            identity = self.draft[side]
            school.setText(identity.school);team.setText(identity.team)
            self.populate_logo(side)

    def pick_logo(self, side):
        path,_ = QFileDialog.getOpenFileName(self,self.tr_text('导入校徽','Import team logo'),'',
                                            'Images (*.png *.jpg *.jpeg *.webp)')
        if not path:
            return
        try:
            self.draft[side] = replace(self.draft[side],logo=self.store.import_logo(Path(path)))
            self.populate_logo(side)
            self.error.clear()
        except (OSError,ValueError) as exc:
            self.error.setText(str(exc))

    def populate_logo(self, side):
        preview = self.fields[side][2]
        image = self.store._image(self.draft[side].logo)
        preview.clear()
        if not image.isNull():
            preview.setPixmap(QPixmap.fromImage(image).scaled(80,80,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        else:
            preview.setText(self.tr_text('未设置校徽','No logo'))

    def clear_logo(self,side):
        self.draft[side] = replace(self.draft[side],logo='')
        self.populate_logo(side)

    def pick_official(self):
        path,_ = QFileDialog.getOpenFileName(self,self.tr_text('导入官方比赛资料','Import official match info'),'',
                                            'Match JSON (*.json)')
        if not path:
            return
        try:
            self.draft = self.store.read_official(Path(path))
            self.populate();self.error.clear()
        except (OSError,ValueError,TypeError) as exc:
            self.error.setText(str(exc))

    def save(self):
        try:
            teams = {side: TeamIdentity(school.text(),team.text(),self.draft[side].logo)
                     for side,(school,team,_preview) in self.fields.items()}
            self.store.save(teams)
        except (OSError,ValueError,TypeError) as exc:
            self.error.setText(str(exc))
            return
        self.host.frame_scheduler.force()
        self.accept()


def open_match_team_editor(host):
    current = getattr(host,'_match_team_editor',None)
    if current is not None:
        current.raise_();current.activateWindow()
        return current
    editor = MatchTeamEditor(host)
    host._match_team_editor = editor
    def retire(_result):
        if getattr(host,'_match_team_editor',None) is editor:
            host._match_team_editor = None
    editor.finished.connect(retire)
    editor.show()
    return editor
