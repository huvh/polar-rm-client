"""更新日志内容；不承载游戏公告、远程接口或设备动作。"""
from __future__ import annotations

from datetime import datetime
from html import escape


def _html(sections: tuple[tuple[str, tuple[str, ...]], ...]) -> str:
    return "".join('<p><strong>▼//' + escape(title) + '</strong></p>'
                   + "".join('<p>・' + escape(line) + '</p>' for line in lines)
                   for title, lines in sections)


def changelog_entries(chinese: bool) -> list[dict]:
    """映射到原公告页的列表与详情格式，所有内容均来自本地终端。"""
    rows = (
        ("2026-10-25", "events", "菜单精简\\n部署移除", "2026.10.25 · Esc 菜单精简", (
            ("界面调整", ("Esc 菜单只保留一个声音设置入口。", "保留左侧更新日志，删除右侧重复入口。")),
            ("功能移除", ("英雄部署控制台、特殊快捷键、部署指令与自动图传切换已移除。",
                         "独立 HeroLob 吊射标定、弹道预览继续可用。")),
            ("本地记录", ("这些是本地客户端改动，不代表已发布新版本或通过实战资格验证。",)),
        )),
        ("2026-10-21", "events", "Esc 菜单\\n场地预览", "2026.10.21 · 本地更新", (
            ("新增", ("终末地式 Esc 菜单，接入设置、显示、键位与返回战斗入口。",
                     "2027 官方场地模型预览，支持 7v7、3v3、1v1 赛制切换。")),
            ("优化", ("菜单背景使用 GPU 高斯模糊与压暗，暂时隐藏战斗 HUD，退出后恢复。",
                     "保留原有设置、键盘绑定界面与液态玻璃材质。")),
            ("修复", ("按钮悬停闪烁、鼠标移出后的高亮残留。", "背景 HUD 重复叠加及菜单过早展开。",
                     "GPU 绘制清理返回值被误判而触发兼容绘制的问题。")),
            ("说明", ("这是本地界面更新记录，不代表已发布新版本或通过实战资格验证。",)),
        )),
        ("2026-10-25", "updates", "公告界面\\n原版样式", "更新日志 · 原版公告界面", (
            ("界面来源", ("采用游戏公告页的三页签、日期列表、正文容器、纹理与交互组件。",
                         "中文和英文均使用游戏 SDK 随附的 HarmonyOS Sans 字体。",
                         "保留原页面的淡入、切页、选中展开、悬停与滚动反馈。")),
            ("本地运行", ("页面资源、字体和更新内容随终端提供，运行时不访问游戏或网络。",)),
        )),
        ("2026-10-25", "news", "阅读操作\\n安全说明", "终端更新日志 · 使用说明", (
            ("阅读", ("点击顶部页签切换分类，点击左侧日期条目查看正文。",
                     "左侧目录与右侧正文可独立滚动。", "右上角关闭按钮或 Esc 返回终端。")),
            ("输入与设备", ("打开日志时锁定操控并清空输入；关闭不会自动恢复操控授权。",
                          "日志显示期间，F12 急停和后台遥测监控继续工作。")),
        )),
    )
    english = (
        ("Menu cleanup\\nDeploy removed", "2026.10.25 · Esc menu cleanup", (
            ("Menu", ("Keep one audio settings entry and the left-side changelog.",)),
            ("Removed", ("Hero deployment UI, special key routing, commands and automatic video switching.",
                         "Independent HeroLob calibration and ballistic preview remain available.")),
            ("Local changes", ("Local changes only, not a new release or real-match qualification.",)),)),
        ("Esc menu\\nField previews", "2026.10.21 · Local changes", (
            ("Added", ("Endfield Esc menu with settings, display and key bindings.",
                       "Official 2027 field previews for 7v7, 3v3 and 1v1.")),
            ("Improved", ("GPU menu backdrop; combat HUD restores after exit.",
                          "Existing Jello settings, bindings and liquid-glass materials retained.")),
            ("Fixed", ("Hover flicker, stale highlights and duplicate background HUD.",
                      "Premature reveal and incorrect GPU painter cleanup rejection.")),
            ("Note", ("Local UI changes only, not a new release or real-match qualification.",)),)),
        ("Bulletin UI\\nOriginal style", "Changelog · Original bulletin UI", (
            ("Source", ("Original game bulletin tabs, date list, content, textures and CSS motion.",
                        "Original HarmonyOS Sans fonts from the game SDK.")),
            ("Offline", ("All UI resources, fonts and changelog content are local.",)),)),
        ("Reading\\nClient controls", "Changelog · Client controls", (
            ("Navigation", ("Select a tab and dated entry; scroll each column independently.",
                            "Use the upper-right close button or Escape to return.")),
            ("Control", ("Opening locks control and clears held input. Closing never arms control.",
                         "F12 emergency stop and telemetry remain available.")),)),
    )
    entries = []
    for index, (date, tab, title, header, sections) in enumerate(rows):
        if not chinese:
            title, header, sections = english[index]
        entries.append({"cid": "polar-" + str(index), "type": 0, "tab": tab,
                        "displayType": "rich_text", "orderType": 0, "orderWeight": 0,
                        "startAt": int(datetime.fromisoformat(date + "T12:00:00+08:00").timestamp()),
                        "version": 1, "title": title, "header": header,
                        "data": {"html": _html(sections)}, "extraData": {}, "jumpButton": None})
    return entries
