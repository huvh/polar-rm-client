"""实际D3D验证新增UI切换条目的可见性、按钮反馈和零语义动作。"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from rm_client.ui.endfield.menu.native import EndfieldNativeMenu
from tools.endfield.pack import validate
from tools.endfield.verify_hover import hover_reader


def check_window_placeholder(window, wait, until, out):
    """经真实Qt事件点击新增条目，Esc保持打开且不分发任何客户端动作。"""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtGui import QImage
    from unittest.mock import patch
    menu,dpr = window._endfield_menu,window.devicePixelRatioF()
    rect = (ctypes.c_double*4)()
    def point(code):
        until(lambda:bool(menu.api.button(menu.handle,code,rect)))
        return rect[0]+rect[2]/2,rect[1]+rect[3]/2
    x,y = point(9);menu.pointer(1,x,y);wait(.65)
    x,y = point(9);menu.pointer(4,x,y,-30);wait(1.1)
    x,y = point(21);menu.pointer(1,x,y);wait(.65)
    x,y = point(21)
    with patch.object(window,"dispatch_endfield_action",wraps=window.dispatch_endfield_action) as dispatch:
        QTest.mouseClick(window,Qt.MouseButton.LeftButton,pos=QPoint(round(x/dpr),round(y/dpr)))
        wait(.45)
        assert window.escape_menu_visible and not window.gui_visible
        dispatch.assert_not_called()
    raw = out/"ui_switch_placeholder.bgra"
    menu.api.capture(menu.handle,os.fsencode(raw));until(lambda:menu.api.captured(menu.handle)!=0)
    assert menu.api.captured(menu.handle)==1
    width,height = round(window.width()*dpr),round(window.height()*dpr)
    assert QImage(raw.read_bytes(),width,height,width*4,QImage.Format.Format_ARGB32).save(str(raw.with_suffix(".png")))
    return {"code":21,"dpr":dpr,"escape_still_open":True,"client_actions":0,"status":"PASS"}


def run(pack: Path, out: Path):
    from PySide6.QtGui import QImage
    validate(pack)
    out.mkdir(parents=True,exist_ok=False)
    report = {"scope":"owned native D3D; placeholder never activates a client action","cases":[]}
    for width,height,chinese in ((1280,720,True),(1920,1080,False)):
        menu = EndfieldNativeMenu(pack)
        def until(test,timeout=15):
            deadline = time.perf_counter()+timeout
            while not test():
                if menu.handle and menu.api.status(menu.handle)==-1:
                    raise RuntimeError(menu.api.error(menu.handle))
                if time.perf_counter()>deadline:raise TimeoutError("UI switch source card")
                time.sleep(.005)
        def point(code):
            rect = (ctypes.c_double*4)()
            until(lambda:bool(menu.api.button(menu.handle,code,rect)))
            return rect[0]+rect[2]/2,rect[1]+rect[3]/2
        def capture(name):
            raw = out/f"{width}_{name}.bgra"
            menu.api.capture(menu.handle,os.fsencode(raw))
            until(lambda:menu.api.captured(menu.handle)!=0)
            assert menu.api.captured(menu.handle)==1
            data = raw.read_bytes()
            assert QImage(data,width,height,width*4,QImage.Format.Format_ARGB32).save(str(raw.with_suffix(".png")))
        try:
            menu.prepare(0,width,height,offscreen=True);until(lambda:menu.ready)
            menu.tick(width=width,height=height,chinese=chinese,mode="RMUL3v3",paused=False)
            menu.request(True);time.sleep(1.1)
            x,y = point(9);menu.pointer(1,x,y);time.sleep(.65)
            x,y = point(9);menu.pointer(4,x,y,-30);time.sleep(1.1)
            x,y = point(21);menu.pointer(1,x,y);time.sleep(.65)
            x,y = point(21);menu.pointer(1,x,y);time.sleep(.3)
            read_hover = hover_reader(menu)
            assert read_hover()["code"]==21
            capture("ui_switch_hover")
            for _ in range(2):
                menu.pointer(2,x,y);time.sleep(.04);menu.pointer(3,x,y);time.sleep(.3)
                assert menu.api.action(menu.handle)==0
                assert menu.phase==1
            capture("ui_switch_after_click")
            report["cases"].append({"physical_size":[width,height],"chinese":chinese,
                "hover":read_hover(),"clicks":2,"action":0,"phase":menu.phase,"stats":menu.stats()})
            print(f"PASS UI switch {width}x{height}",flush=True)
        finally:
            menu.close();menu.wait_closed();assert menu.handle==0
    report["status"] = "PASS"
    (out/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf8")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack",type=Path,required=True);parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args();run(args.pack.resolve(),args.out.resolve())
