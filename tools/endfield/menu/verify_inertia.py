"""在自有D3D离屏菜单上验证拖动惯性、终止与生命周期，不启动游戏或设备。"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from rm_client.ui.endfield.menu.native import EndfieldNativeMenu
from tools.endfield.pack import validate


def scroll_reader(menu):
    function = menu.api.lib.pe_scroll
    function.argtypes = [ctypes.c_uint64, ctypes.POINTER(ctypes.c_double)]
    function.restype = None

    def read():
        values = (ctypes.c_double * 6)()
        function(menu.handle, values)
        return dict(zip(("position", "velocity", "hidden_length", "dragging", "coasting", "rate"), values))
    return read


def check_window_drag(window, wait, until):
    """使用生产Qt鼠标适配器验证逻辑坐标到原生物理坐标的拖动和松手。"""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest
    menu, dpr = window._endfield_menu,window.devicePixelRatioF()
    read = scroll_reader(menu)
    rect = (ctypes.c_double*4)()
    def point():
        until(lambda:bool(menu.api.button(menu.handle,9,rect)))
        return QPointF((rect[0]+rect[2]/2)/dpr,(rect[1]+rect[3]/2)/dpr)
    def move(p,buttons=Qt.MouseButton.NoButton):
        window.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove,p,
            QPointF(window.mapToGlobal(p.toPoint())),Qt.MouseButton.NoButton,buttons,Qt.KeyboardModifier.NoModifier))
    move(point());wait(.65)
    start = point()
    QTest.mousePress(window,Qt.MouseButton.LeftButton,pos=start.toPoint());wait(.025)
    for index in range(1,9):
        move(start-QPointF(0,index*5),Qt.MouseButton.LeftButton);wait(.016)
    dragged = read()
    assert dragged["dragging"]
    QTest.mouseRelease(window,Qt.MouseButton.LeftButton,pos=(start-QPointF(0,40)).toPoint())
    wait(.04);released = read();wait(.15);coasting = read()
    assert released["coasting"] and coasting["position"]<released["position"]-.01
    assert 0<abs(coasting["velocity"])<abs(released["velocity"])
    assert window.escape_menu_visible and not window.gui_visible
    assert not getattr(window,"_endfield_pending_action",None)
    return {"dpr":dpr,"dragged":dragged,"released":released,"coasting":coasting,"status":"PASS"}


def run(pack: Path, out: Path) -> dict:
    from PySide6.QtGui import QImage
    checked = validate(pack)
    out.mkdir(parents=True, exist_ok=False)
    report = {"scope": "actual owned D3D menu; no game/device I/O", "pack": checked, "cases": []}
    scenarios = (("coast",1280,720), ("regrab",1280,720), ("hold",1280,720),
                 ("pause",1920,1080), ("boundary",1920,1080), ("close",1280,720))
    for name,width,height in scenarios:
        menu = EndfieldNativeMenu(pack)
        def until(predicate, timeout=15):
            deadline = time.perf_counter()+timeout
            while not predicate():
                if menu.handle and menu.api.status(menu.handle)==-1:
                    raise RuntimeError(menu.api.error(menu.handle).decode("utf8","replace"))
                if menu.error:
                    raise RuntimeError(menu.error)
                if time.perf_counter()>deadline:
                    raise TimeoutError("Native menu inertia check: "+name)
                time.sleep(.005)

        def capture(suffix):
            raw = out/(name+"_"+suffix+".bgra")
            menu.api.capture(menu.handle,os.fsencode(raw))
            until(lambda:menu.api.captured(menu.handle)!=0)
            assert menu.api.captured(menu.handle)==1
            pixels = raw.read_bytes()
            assert len(pixels)==width*height*4
            assert QImage(pixels,width,height,width*4,QImage.Format.Format_ARGB32).save(str(raw.with_suffix(".png")))

        try:
            menu.prepare(0,width,height,offscreen=True)
            until(lambda:menu.ready)
            menu.tick(width=width,height=height,chinese=True,mode="RMUL3v3",paused=False)
            menu.request(True)
            time.sleep(1.1)
            read = scroll_reader(menu)
            initial = read()
            assert abs(initial["rate"]-.135)<.000001
            assert initial["hidden_length"]>0
            rect = (ctypes.c_double*4)()
            until(lambda:bool(menu.api.button(menu.handle,9,rect)))
            x,y = rect[0]+rect[2]/2,rect[1]+rect[3]/2
            menu.pointer(1,x,y)
            time.sleep(.6)
            until(lambda:bool(menu.api.button(menu.handle,9,rect)))
            x,y = rect[0]+rect[2]/2,rect[1]+rect[3]/2
            menu.pointer(2,x,y)
            time.sleep(.025)
            distance = (240 if name=="boundary" else 40)*width/1280
            for index in range(1,9):
                menu.pointer(1,x,y-distance*index/8)
                time.sleep(.016)
            dragged = read()
            assert dragged["dragging"] and dragged["position"]<initial["position"]
            if name=="hold":
                time.sleep(.9)
            menu.pointer(3,x,y-distance)
            time.sleep(.035)
            released = read()
            assert not released["dragging"]
            row = {"scenario":name,"physical_size":[width,height],"initial":initial,
                   "dragged":dragged,"released":released}
            if name in ("coast","pause","regrab","close"):
                assert released["coasting"] and released["velocity"]<0
            if name=="coast":
                capture("release")
                first_time,first = time.perf_counter(),read()
                time.sleep(.15)
                second_time,second = time.perf_counter(),read()
                assert second["position"]<first["position"]-.02
                assert 0<abs(second["velocity"])<abs(first["velocity"])
                expected = first["velocity"]*first["rate"]**(second_time-first_time)
                assert abs(second["velocity"]-expected)<abs(expected)*.08
                capture("coasting")
                row.update(first=first,second=second,elapsed=second_time-first_time,expected_velocity=expected)
                until(lambda:not read()["coasting"],7)
            elif name=="regrab":
                menu.pointer(2,x,y)
                time.sleep(.05)
                held = read()
                time.sleep(.2)
                assert not held["coasting"] and held["velocity"]==0
                assert abs(read()["position"]-held["position"])<.000001
                # 松到列表外取消本次单击，不触发任何功能。
                menu.pointer(3,-30,-30)
                time.sleep(.05)
                row["held"] = held
            elif name=="hold":
                assert not released["coasting"]
                time.sleep(.15)
                assert abs(read()["position"]-released["position"])<.000001
            elif name=="pause":
                menu.tick(width=width,height=height,chinese=True,mode="RMUL3v3",paused=True)
                time.sleep(.08)
                stopped = read()
                assert not stopped["coasting"] and stopped["velocity"]==0
                menu.tick(width=width,height=height,chinese=True,mode="RMUL3v3",paused=False)
                time.sleep(.15)
                assert abs(read()["position"]-stopped["position"])<.000001
                row["paused"] = stopped
            elif name=="boundary":
                until(lambda:not read()["coasting"])
                time.sleep(1.1)
                assert -.0001<=read()["position"]<=1.0001
                row["settled"] = read()
            elif name=="close":
                menu.request(False)
                until(lambda:menu.phase==0)
                menu.request(True)
                time.sleep(1.1)
                assert not read()["coasting"] and read()["velocity"]==0
                row["reopened"] = read()
            assert menu.api.action(menu.handle)==0,"Drag must not activate a feature"
            row.update(final=read(),stats=menu.stats(),result="PASS")
            report["cases"].append(row)
            print("PASS "+name,flush=True)
        finally:
            menu.close()
            menu.wait_closed()
            assert menu.handle==0
    report["status"] = "PASS"
    (out/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    args = parser.parse_args()
    run(args.pack.resolve(),args.out.resolve())
