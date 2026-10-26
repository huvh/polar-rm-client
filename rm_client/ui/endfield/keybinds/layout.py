"""客户端84键物理位置；键帽和表现参数来自游戏，键盘排列为标准QWERTY适配。"""
from dataclasses import dataclass

from PySide6.QtCore import QRectF

UNIT = 72
WIDTH, HEIGHT = 1368, 440


@dataclass(frozen=True)
class KeyCap:
    name: str
    label: str
    x: float
    y: float
    width: float
    height: float = 65

    def rect(self):
        return QRectF(self.x,self.y,self.width,self.height)


def _row(y, entries):
    x = 0
    result = []
    for name,label,units in entries:
        result.append(KeyCap(name,label,x,y,units*UNIT-7))
        x += units*UNIT
    return result


def keyboard_layout():
    keys = [KeyCap("Escape","Esc",0,0,65,52)]
    for number in range(1,13):
        x = (2+(number-1)+(number-1)//4*.5)*UNIT
        keys.append(KeyCap(f"F{number}",f"F{number}",x,0,65,52))
    keys += _row(82,[(name,name,1) for name in "`1234567890-="]+[("Backspace","Backspace",2)])
    keys += _row(154,[("Tab","Tab",1.5)]+[(name,name,1) for name in "QWERTYUIOP[]"]+[("\\","\\",1.5)])
    keys += _row(226,[("CapsLock","Caps Lock",1.75)]+[(name,name,1) for name in "ASDFGHJKL;'"]+[("Enter","Enter",2.25)])
    keys += _row(298,[("Shift","Shift",2.25)]+[(name,name,1) for name in "ZXCVBNM,./"]+[("RightShift","Shift",2.75)])
    keys += _row(370,[("Ctrl","Ctrl",1.25),("MetaLeft","Win",1.25),("Alt","Alt",1.25),
                       ("Space","Space",6.25),("AltRight","Alt Gr",1.25),("MetaRight","Win",1.25),
                       ("Menu","Menu",1.25),("CtrlRight","Ctrl",1.25)])
    for row,names in enumerate((("Insert","Home","PageUp"),("Delete","End","PageDown"))):
        for column,name in enumerate(names):
            label = {"Insert":"Ins","Delete":"Del","PageUp":"PgUp","PageDown":"PgDn"}.get(name,name)
            keys.append(KeyCap(name,label,(16+column)*UNIT,82+row*UNIT,65))
    keys.append(KeyCap("Up","↑",17*UNIT,298,65))
    for column,(name,label) in enumerate((("Left","←"),("Down","↓"),("Right","→"))):
        keys.append(KeyCap(name,label,(16+column)*UNIT,370,65))
    return tuple(keys)


KEYS = keyboard_layout()
