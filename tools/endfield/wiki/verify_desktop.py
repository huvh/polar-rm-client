"""使用真实 Windows Qt/OpenGL 表面验收 Wiki；配置隔离，设备启动使用惰性替身。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]


def run(out: Path) -> None:
    os.environ.update(QT_QPA_PLATFORM="windows", POLAR_AUTOSTART="0", CI="true",
                      POLAR_DISABLE_LOCAL_CAPTURE="1", POLAR_DISABLE_MEDIA_PRELOAD="1")
    from PySide6 import __version__ as qt_version
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QImage, QInputMethodEvent, QMouseEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from rm_client.backend.mqtt_backend import RmMqttBackend
    from rm_client.backend.serial_backend import RmSerialBackend
    from rm_client.backend.video_backend import RmVideoBackend
    from rm_client.ui.polar_app import PolarRMWindow
    from window_lifecycle_helpers import close_window_safely, settle_window_lifecycle

    app = QApplication.instance() or QApplication([])
    out.mkdir(parents=True, exist_ok=False)
    report = {"python": sys.version, "PySide6": qt_version,
              "scope": "real Windows/OpenGL, temporary profile, inert transport starts"}

    def wait(seconds):
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            app.processEvents()
            time.sleep(.003)

    with tempfile.TemporaryDirectory() as profile, patch.dict(os.environ, POLAR_USER_DATA_ROOT=profile), \
         patch.object(RmMqttBackend, "start"), patch.object(RmSerialBackend, "start"), \
         patch.object(RmVideoBackend, "start"):
        window = PolarRMWindow()
        try:
            window.resize(1280, 720)
            window.show()
            window.raise_()
            window.activateWindow()
            assert QTest.qWaitForWindowExposed(window, 5000)
            settle_window_lifecycle(window, app)
            window.home_visible = False
            window.ui_audio_enabled = False
            window.set_clickgui_visible(True, announce=False)
            wait(1.2)
            assert window.clickgui_gpu.available, window.clickgui_gpu.last_error

            def capture(name):
                wait(.6)
                image = window.grabFramebuffer()
                assert not image.isNull()
                assert image.save(str(out / (name + ".png")))
                assert not window.clickgui_gpu.last_error, window.clickgui_gpu.last_error
                assert not window.gpu_compositor.last_error, window.gpu_compositor.last_error

            def click(action, payload=None):
                wait(.12)
                target = next(h for h in window.hotspots if h.action == action
                              and (payload is None or h.payload == payload))
                QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=target.rect.center().toPoint())
                wait(.6)

            def breadcrumb_snapshot(name, expected):
                patches = [i for i in window.jello_clickgui.commands.images if Path(i.source).name.startswith("path_bg_")]
                assert len(patches) == expected * 9
                dark = len([i for i in patches if i.tint.name() == "#393939"]) // 9
                assert dark == (0 if "home" in name else 1)
                report.setdefault("breadcrumbs", []).append({"page": name, "black_backgrounds": dark,
                    "highlight_overlays": expected - dark})
                if name == "movement":
                    frame = window.grabFramebuffer()
                    scale, dpr = window.jello_clickgui.s, window.devicePixelRatioF()
                    corner = patches[0].rect.topLeft()
                    outer = frame.pixelColor(round((corner.x() + .5 * scale) * dpr),
                                             round((corner.y() + .5 * scale) * dpr)).red()
                    right = patches[8].rect.right()
                    inner = frame.pixelColor(round((right - 12 * scale) * dpr),
                                             round((corner.y() + 19 * scale) * dpr)).red()
                    assert outer > inner + 100, "source corner must remain rounded/translucent"
                    report["breadcrumb_corner_inner_red"] = [outer, inner]

            def motion_samples(action, payload, prefix, times):
                """冻结呈现时钟，抓取真实 GL 中间帧，避免读回耗时跳过短退场。"""
                wait(.2)
                target = next(h for h in window.hotspots if h.action == action
                              and (payload is None or h.payload == payload))
                state_clock, renderer_clock = window.jello_state.clock, window.jello_clickgui.clock
                frozen = [time.perf_counter()]
                start = frozen[0]
                window.jello_state.clock = window.jello_clickgui.clock = lambda: frozen[0]
                try:
                    QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=target.rect.center().toPoint())
                    for at in times:
                        frozen[0] = start + at
                        window.invalidate_gui_cache()
                        window.frame_scheduler.force()
                        window.update()
                        capture(prefix + "_" + str(round(at * 1000)) + "ms")
                        report.setdefault("motion_frames", []).append({"event": prefix, "at_ms": at * 1000})
                        bg = window.jello_clickgui.background
                        projection = window.jello_clickgui.background_projection
                        report.setdefault("background_frames",[]).append({"event":prefix,"at_ms":at*1000,
                            "clip":bg.clip,"projection":list(projection),
                            "deco_alpha":bg.sample(window.jello_clickgui.motion,"HudNode/BgDecoLayout","m_Alpha",frozen[0]),
                            "bottom_alpha":bg.sample(window.jello_clickgui.motion,"HudNode/ButtomDecoLayout ","m_Alpha",frozen[0])})
                        if prefix=="switch_module":
                            assert abs(projection[2]-5/6)<.0001,"same-page module selection must not replay background"
                        if prefix=="search_switch":
                            titles = [{"text":t.text,"x":(t.rect.left()-window.jello_clickgui.ox)/window.jello_clickgui.s,
                                       "alpha":t.color.alphaF()} for t in window.jello_clickgui.commands.texts
                                      if abs(t.font.pointSizeF()-28.5)<.01 and
                                      t.rect.left()>window.jello_clickgui.ox+700*window.jello_clickgui.s]
                            targets = [h.payload for h in window.hotspots if h.action=="jello_open_settings"]
                            report.setdefault("search_switch_frames",[]).append({"at_ms":at*1000,
                                "titles":titles,"detail_targets":targets})
                            if at==.08:
                                assert len(titles)==2 and all(0<t["alpha"]<1 for t in titles)
                                assert 1090<titles[-1]["x"]<1110
                                assert targets==[payload]
                finally:
                    window.jello_state.clock, window.jello_clickgui.clock = state_clock, renderer_clock
                    window.invalidate_gui_cache()
                    window.frame_scheduler.force()
                    window.update()
                wait(.6)

            capture("home_1280x720")
            breadcrumb_snapshot("home", 0)
            # 对自有窗口投递真实 Qt 移动事件，避免桌面上同时移动的鼠标污染逐项抓帧。
            window.setMouseTracking(False)
            def hover_at(point):
                local = QPointF(point)
                window.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove, local,
                              QPointF(window.mapToGlobal(point)), Qt.MouseButton.NoButton,
                              Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
            report["hover_input"] = "production Qt mouse adapter on owned native OpenGL window"
            # 原软遮罩先让中心变黑，不能再用整列上缘像素当作100 ms响应条件。
            hover_at(QPoint(4, 4))
            wait(.1)
            target = next(h for h in window.hotspots if h.action == "wiki_category")
            started = time.perf_counter()
            hover_at(target.rect.center().toPoint())
            # 等待首帧接收悬停，再验证 83 ms 遮罩轨道；冷启动绘制耗时单独记录。
            deadline = started + 3
            while not window.jello_state.home_hovers[target.payload].hovered:
                assert time.perf_counter() < deadline, "hover frame was not rendered"
                wait(.01)
            report["hover_first_frame_ms"] = (time.perf_counter() - started) * 1000
            wait(.12)
            image = window.grabFramebuffer()
            dpr = window.devicePixelRatioF()
            color = image.pixelColor(round((target.rect.left()+12)*dpr),
                                     round((target.rect.top()+600*window.jello_clickgui.s)*dpr))
            report["hover_sample_elapsed_ms"] = (time.perf_counter()-started)*1000
            report["hover_background_rgb"] = [color.red(), color.green(), color.blue()]
            report["hover_pointer"] = [window.hover_point.x(), window.hover_point.y()]
            report["hover_target"] = list(target.rect.getRect())
            report["hover_mask_progress"] = window.jello_state.home_hovers[target.payload].values(
                time.perf_counter())[1]
            image.save(str(out / "home_hover_fast.png"))
            assert max(report["hover_background_rgb"]) < 65, report
            hover_at(QPoint(4, 4))
            wait(.3)
            state_clock, renderer_clock = window.jello_state.clock, window.jello_clickgui.clock
            frozen = [time.perf_counter()]
            start = frozen[0]
            window.jello_state.clock = window.jello_clickgui.clock = lambda: frozen[0]
            try:
                window.jello_state.home_hovers.clear()
                hover_at(target.rect.center().toPoint())
                window.invalidate_gui_cache()
                window.update()
                wait(.1)
                for at in (.05, .1, .2, .24, 1 / 3, .4, .45, .55, .65, .733333333, .75, .85):
                    frozen[0] = start + at
                    window.invalidate_gui_cache()
                    window.frame_scheduler.force()
                    window.update()
                    capture("home_select_" + str(round(at * 1000)) + "ms")
                    report.setdefault("motion_frames", []).append({"event": "home_select", "at_ms": at * 1000})
                    markers = [v for v in window.jello_clickgui.commands.rects
                               if v.fill.name() in ("#060606", "#4a4a4a", "#727272")]
                    report.setdefault("block_frames", []).append({"at_ms": at * 1000,
                        "markers": [{"rect": list(v.rect.getRect()), "color": v.fill.name(),
                                     "alpha": v.fill.alpha()} for v in markers]})
                    assert len(markers) == 4
                    plain_source = str(window.jello_clickgui.wiki_images[target.payload])
                    plain = [i for i in window.jello_clickgui.commands.images if i.source == plain_source]
                    assert len(plain) == 1 and plain[0].tint.alpha() == 0, "plain gray icon must retire on hover"
                    report.setdefault("plain_icon_alpha", []).append({"at_ms": at * 1000, "alpha": plain[0].tint.alpha()})
                    if at == .75:
                        frame = window.grabFramebuffer()
                        pixels = []
                        for marker in markers:
                            center = marker.rect.center()
                            rgb = frame.pixelColor(round(center.x() * dpr), round(center.y() * dpr)).red()
                            pixels.append(rgb)
                            assert (80 < rgb < 145) if marker.fill.name() == "#727272" else rgb < 40
                        report["block_final_pixel_red"] = pixels
                    if at == .05:
                        frame = window.grabFramebuffer()
                        x = round((target.rect.left() + 12) * dpr)
                        edge = frame.pixelColor(x, round(103 * window.jello_clickgui.s * dpr)).red()
                        center = frame.pixelColor(x, round(736 * window.jello_clickgui.s * dpr)).red()
                        report["soft_mask_50ms_edge_center_rgb"] = [edge, center]
                        assert edge > center + 40, "soft mask must darken its center before its edges"
            finally:
                window.jello_state.clock, window.jello_clickgui.clock = state_clock, renderer_clock
            # 保持不移动鼠标，记录原背景持续旋转；独立于悬停的时钟。
            capture("background_loop_a")
            wait(1)
            capture("background_loop_b")
            wait(1)
            capture("home_hover")
            targets = [h for h in window.hotspots if h.action == "wiki_category"]
            for target in targets:
                hover_at(target.rect.center().toPoint())
                wait(.25)
                capture("hover_" + target.payload)
            hover_at(QPoint(4, 4))
            window.setMouseTracking(True)
            wait(.3)
            for size in ((1000, 620), (1920, 1080), (2560, 1440)):
                window.resize(*size)
                capture("home_" + "x".join(map(str, size)))
                assert len([h for h in window.hotspots if h.action == "wiki_category"]) == 6
                expected = min(window.width()/1920,window.height()/1080)
                assert abs(window.jello_clickgui.s-expected)<.0001
                report.setdefault("canvas_scaling",[]).append({"size":[window.width(),window.height()],
                    "device_pixel_ratio":window.devicePixelRatioF(),"scale":window.jello_clickgui.s})
            window.showFullScreen()
            capture("home_fullscreen")
            assert window.isFullScreen()
            assert abs(window.jello_clickgui.s-min(window.width()/1920,window.height()/1080))<.0001
            report["fullscreen"] = {"size":[window.width(),window.height()],"scale":window.jello_clickgui.s,
                                    "device_pixel_ratio":window.devicePixelRatioF()}
            window.showNormal()
            window.resize(1280, 720)
            wait(.3)
            motion_samples("wiki_category", "Movement", "enter_movement", (.08, .25, .45, .8))
            assert window.jello_state.settings_module == "SpinMode"
            capture("movement_spin")
            text_node = next(n for n in window.jello_clickgui.pack["layers"]["frame"]["children"] if n.get("uv_scroll"))
            text_source = str(window.jello_clickgui.wiki_images[text_node["image"]])
            assert not any(i.source==text_source for i in window.jello_clickgui.commands.images)
            report["group_page_has_no_home_text_stream"] = True
            window.showFullScreen()
            capture("movement_fullscreen")
            assert abs(window.jello_clickgui.s-min(window.width()/1920,window.height()/1080))<.0001
            report["group_fullscreen"] = {"size":[window.width(),window.height()],"scale":window.jello_clickgui.s}
            window.showNormal()
            window.resize(1280,720)
            wait(.3)
            breadcrumb_snapshot("movement", 1)
            parent = next(t for t in window.jello_clickgui.commands.texts if t.text == "POLAR 终端")
            hover_at(parent.rect.center().toPoint())
            capture("breadcrumb_parent_hover")
            breadcrumb_snapshot("movement_parent_hover", 2)
            hover_at(QPoint(4, 4))
            wait(.2)
            motion_samples("jello_open_settings", "AutoSpinOnHit", "switch_module", (.05, .12, .22, .34))
            assert window.jello_state.settings_module == "AutoSpinOnHit"
            capture("movement_hit_spin")
            breadcrumb_snapshot("movement_switched_module", 1)
            motion_samples("wiki_search", None, "search_over_module", (.08, .25, .5))
            assert window.jello_state.settings_module == "AutoSpinOnHit"
            assert not any(h.action in ("setting_toggle", "setting_slider", "module_bind") for h in window.hotspots)
            assert window.clickgui_gpu._frost is not None and window.clickgui_gpu._frost.passes > 0
            report["gpu_frost_passes"] = window.clickgui_gpu._frost.passes
            motion_samples("wiki_back", None, "search_return", (.08, .24))
            assert not window.jello_state.search_open
            assert window.jello_state.settings_module == "AutoSpinOnHit"
            click("jello_open_settings", "ChassisAssist")
            assert window.jello_state.settings_module == "ChassisAssist"
            for size in ((1000, 620), (1280, 720), (1920, 1080), (2560, 1440)):
                window.resize(*size)
                capture("movement_chassis_" + "x".join(map(str, size)))
                sidebar = next(v for v in window.gui_scroll_viewports if v["key"] == "wiki:Movement")
                settings = next(v for v in window.gui_scroll_viewports if v["mode"] == "jello_settings")
                assert settings["key"] == "ChassisAssist"
                assert sidebar["rect"].right() < settings["rect"].left()
            window.resize(1280, 720)
            wait(.3)
            click("jello_toggle_language")
            click("jello_open_settings", "AutoSpinOnHit")
            capture("movement_english_breadcrumb")
            # 长路径的文字和点击范围必须始终留在左侧地址栏中。
            path_targets = [h for h in window.hotspots if h.action in ("wiki_home", "wiki_category")]
            search_target = next(h for h in window.hotspots if h.action == "wiki_search")
            assert all(h.rect.right() < search_target.rect.left() for h in path_targets)
            click("jello_toggle_language")
            click("wiki_home")
            click("wiki_category", "Combat")
            click("jello_open_settings", "ArmorAutoAim")
            assert window.jello_state.settings_module == "ArmorAutoAim"
            capture("armor_settings")
            motion_samples("wiki_back", None, "category_return", (.08, .24, .9))
            assert window.jello_state.category is None and window.gui_visible
            breadcrumb_snapshot("returned_home", 0)
            click("wiki_search")
            event = QInputMethodEvent()
            event.setCommitString("装甲自瞄")
            app.sendEvent(window, event)
            wait(.4)
            capture("chinese_search")
            QTest.keyClick(window, Qt.Key.Key_Return)
            wait(.6)
            assert window.jello_state.settings_module == "ArmorAutoAim"
            click("wiki_home")
            click("wiki_search")
            event = QInputMethodEvent();event.setCommitString("小陀螺")
            app.sendEvent(window,event)
            capture("search_result_selected")
            rows = [h for h in window.hotspots if h.action=="wiki_search_select"]
            assert len(rows)>=2
            def row_surface(target):
                return next(r for r in window.jello_clickgui.commands.rects
                            if r.rect==target.rect and r.radius>0 and r.fill.alphaF()>.001)
            chosen,normal = row_surface(rows[0]),row_surface(rows[1])
            assert chosen.fill.red()<80 and normal.fill.red()>150
            hover_at(rows[1].rect.center().toPoint())
            capture("search_result_hover")
            hovered = row_surface(rows[1])
            assert hovered.fill.red()<normal.fill.red()
            assert chosen.radius==hovered.radius==4*window.jello_clickgui.s
            report["search_row_style"] = {"selected_rgb":chosen.fill.name(),"normal_rgb":normal.fill.name(),
                "hover_rgb":hovered.fill.name(),"radius":chosen.radius}
            click("wiki_search_select",rows[1].payload)
            capture("search_result_switched")
            assert window.jello_state.search_selection==rows[1].payload
            assert not window.pointer_interaction.background_release_owned
            hover_at(rows[0].rect.center().toPoint())
            capture("search_hover_after_selection")
            assert (window.hover_point-rows[0].rect.center()).manhattanLength()<1
            assert row_surface(rows[0]).fill.red()<170
            report["search_hover_after_click_without_scroll"] = True
            motion_samples("wiki_search_select",rows[0].payload,"search_switch",(.05,.08,.16,.26,.38))
            assert window.jello_state.search_selection==rows[0].payload
            assert not window.pointer_interaction.background_release_owned
            click("wiki_search_select",rows[1].payload)
            QTest.keyClick(window,Qt.Key.Key_Return)
            wait(.6)
            assert window.jello_state.settings_module==rows[1].payload
            click("wiki_home")
            click("wiki_category", "System")
            capture("system")
            # 使用实际鼠标适配器拖动目录，不得在press时或drag后选择新模块。
            selected = window.jello_state.settings_module
            item = next(h for h in window.hotspots if h.action == "jello_open_settings" and h.payload != selected)
            start = item.rect.center().toPoint()
            QTest.mousePress(window,Qt.MouseButton.LeftButton,pos=start)
            assert window.jello_state.settings_module == selected
            destination = QPointF(start.x(),start.y()-100)
            window.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove,destination,
                QPointF(window.mapToGlobal(destination.toPoint())),Qt.MouseButton.NoButton,
                Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier))
            QTest.mouseRelease(window,Qt.MouseButton.LeftButton,pos=destination.toPoint())
            assert window.jello_state.settings_module == selected
            assert window.jello_state.panel_scroll["wiki:System"] > 0
            report["vertical_drag"] = {"selected_unchanged":True,"scroll":window.jello_state.panel_scroll["wiki:System"]}
            capture("system_dragged")
            from rm_client.ui.endfield.wiki.scroll import edge_offset
            viewport = next(v for v in window.gui_scroll_viewports if v["key"]=="wiki:System")
            old_clock,old_renderer_clock = window.jello_state.clock,window.jello_clickgui.clock
            frozen = [time.perf_counter()]
            window.jello_state.clock = window.jello_clickgui.clock = lambda:frozen[0]
            try:
                for name,boundary,direction in (("top",0,1),("bottom",viewport["maximum"],-1)):
                    window.jello_state.list_fling = None
                    window.jello_state.list_edges.clear()
                    window.jello_state.panel_scroll["wiki:System"] = boundary
                    window.invalidate_gui_cache();window.frame_scheduler.force();window.update();wait(.08)
                    start = viewport["rect"].center().toPoint()
                    end = QPointF(start.x(),start.y()+150*direction)
                    QTest.mousePress(window,Qt.MouseButton.LeftButton,pos=start)
                    frozen[0] += .05
                    window.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove,end,QPointF(window.mapToGlobal(end.toPoint())),
                        Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier))
                    pull = edge_offset(window.jello_state,"wiki:System")
                    assert 0<abs(pull)<150 and pull*direction<0
                    capture("overscroll_"+name+"_pull")
                    QTest.mouseRelease(window,Qt.MouseButton.LeftButton,pos=end.toPoint())
                    frozen[0] += .1
                    capture("overscroll_"+name+"_return100ms")
                    middle = edge_offset(window.jello_state,"wiki:System")
                    assert 0<abs(middle)<abs(pull)
                    frozen[0] += .7
                    capture("overscroll_"+name+"_settled")
                    assert edge_offset(window.jello_state,"wiki:System")==0
                    assert window.jello_state.settings_module==selected
                    report.setdefault("overscroll",[]).append({"edge":name,"pull":pull,"after_100ms":middle,"settled":0})
            finally:
                window.jello_state.clock,window.jello_clickgui.clock = old_clock,old_renderer_clock
            click("wiki_home")
            window.jello_state.search_history[:] = ["小陀螺"]
            click("wiki_search")
            capture("recent_search")
            assert any(t.text == "最近搜索" for t in window.jello_clickgui.commands.texts)
            assert window.jello_clickgui.commands.frost_radius >= 40
            report["search_frost_radius"] = window.jello_clickgui.commands.frost_radius
            click("wiki_back")
            click("wiki_category","System")
            click("jello_open_settings", "Scenario")
            capture("scenario_settings")
            target = next(h for h in window.hotspots if h.action == "jello_mode_dropdown")
            QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=target.rect.center().toPoint())
            wait(.4)
            assert window.jello_state.dropdown_key
            capture("mode_dropdown")
            QTest.keyClick(window, Qt.Key.Key_Escape)
            wait(.2)
            assert window.jello_state.dropdown_key is None
            with patch.object(window.backend, "trigger_estop", return_value=(True, "test-only")) as stop:
                QTest.keyClick(window, Qt.Key.Key_F12)
                assert stop.call_count == 1
            QTest.keyClick(window, Qt.Key.Key_F8)
            wait(.4)
            assert not window.gui_visible
            assert not window.hotspots or not any(h.action.startswith("wiki_") for h in window.hotspots)
            # 直接入口必须与首页分类入口建立相同导航；退出目标为原生Esc模态。
            for action, name in ((9, "TacticalMap"), (12, "MatchReadiness"), (20, "Scenario")):
                window.dispatch_endfield_action(action)
                capture("direct_entry_" + name)
                assert window.jello_state.settings_module == name
                assert window.jello_state.category == window.registry.get(name).category
                assert any(h.action == "wiki_back" for h in window.hotspots)
                assert not any(h.action == "wiki_close" for h in window.hotspots)
                report.setdefault("direct_entries", []).append({"module": name, "category": window.jello_state.category})
                click("wiki_back")
                assert window.jello_state.category is None
            click("wiki_close")
            assert not window.gui_visible and window.escape_menu_visible
            assert not window.home_visible
            capture("terminal_exit_to_escape")
            report["terminal_exit_target"] = "escape_menu"
            # Qt读回只包含磨砂底层；Esc文字/按钮由同一客户端的D3D表面绘制，必须另取自有帧。
            menu = window._endfield_menu
            deadline = time.perf_counter() + 10
            while not (menu.ready and menu.phase == 1):
                assert not menu.error, menu.error
                assert time.perf_counter() < deadline, "native Esc did not become visible"
                wait(.02)
            raw = out / "terminal_exit_native.bgra"
            menu.api.capture(menu.handle, os.fsencode(raw))
            while menu.api.captured(menu.handle) == 0:
                assert time.perf_counter() < deadline, "native Esc capture timed out"
                wait(.02)
            assert menu.api.captured(menu.handle) == 1
            pixels = raw.read_bytes()
            dpr = window.devicePixelRatioF()
            width, height = round(window.width() * dpr), round(window.height() * dpr)
            assert len(pixels) == width * height * 4
            assert sum(v > 0 for v in pixels[3::4]) > width * height // 100
            native_image = QImage(pixels, width, height, width * 4, QImage.Format.Format_ARGB32)
            assert native_image.save(str(out / "terminal_exit_native.png"))
            report["escape_native"] = {"ready": menu.ready, "phase": menu.phase, "error": menu.error,
                                        "stats": menu.stats(), "capture": "terminal_exit_native.png"}
            report.update(modules=len(window.registry.modules),
                          category_layout="left: category modules; right: selected module settings",
                          source_game_bundles=len(json.loads((ROOT / "rm_client/ui/endfield/wiki/assets/PROVENANCE.json")
                              .read_text(encoding="utf-8"))["verified_game_bundles"]),
                          settings=sum(len(m.settings) for m in window.registry.modules),
                          dpr=window.devicePixelRatioF(), gl=window.context().format().majorVersion(),
                          gui_gpu_error=window.clickgui_gpu.last_error,
                          compositor_error=window.gpu_compositor.last_error,
                          layout_ms=window.clickgui_gpu_layout_ms,
                          status="PASS")
        finally:
            close_window_safely(window, app)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    run(parser.parse_args().out.resolve())
