"""用 Qt 自己的接口抓真实 OpenGL 表面，区分"应用没画"与"我抓不到"。

Win32 PrintWindow 对 QOpenGLWidget 这类硬件加速表面经常拿到空白，所以之前
"窗口 96% 纯白"不能证明应用没渲染。这里改用 widget.grabFramebuffer()，
由 Qt 从 GL 上下文里取，是权威路径。

跑法：
    python tools/capture_live_window.py [输出png路径]
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "field_evidence" / "live-window.png"
    out.parent.mkdir(parents=True, exist_ok=True)

    # 关键：不能用 offscreen，否则测的不是真实窗口的渲染路径
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv[:1])

    from rm_client.ui.polar_app import PolarRMWindow

    window = PolarRMWindow()
    audio = window.registry.get("AudioFeedback")
    if audio is not None:
        audio.enabled = False
    window.ui_audio_enabled = False
    window.resize(1280, 720)
    window.show()

    # 让启动页动画跑完（stagger 动画未结算时画面本来就接近空）
    import time

    deadline = time.time() + 8.0
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)

    image = window.grabFramebuffer()
    if image.isNull():
        print("[FAIL] grabFramebuffer 返回空图像")
        return 1

    image.save(str(out), "PNG")
    print(f"[info] 抓取尺寸 {image.width()}x{image.height()}  格式 {image.format()}")

    # 统计非背景像素（Qt 侧直接读，不依赖 PIL）
    from PySide6.QtGui import QImage

    gray = image.convertToFormat(QImage.Format.Format_Grayscale8)
    w, h = gray.width(), gray.height()
    ptr = gray.constBits()
    try:
        buf = bytes(memoryview(ptr)[: gray.sizeInBytes()])
    except Exception:
        buf = bytes(ptr)
    stride = gray.bytesPerLine()

    non_white = 0
    total = 0
    distinct = set()
    for y in range(0, h, 3):
        row = y * stride
        for x in range(0, w, 3):
            v = buf[row + x]
            total += 1
            if v <= 245:
                non_white += 1
            distinct.add(v)
    ratio = 100.0 * non_white / max(1, total)
    print(f"[info] 非白像素占比 = {ratio:.1f}%   灰阶取值数 = {len(distinct)}")

    try:
        window.backend.shutdown()
    except Exception:
        pass

    if ratio < 5.0:
        print("[FAIL] Qt 自身抓取也几乎是空白 -> 应用确实没画出内容")
        return 1
    print("[PASS] Qt 抓取到真实内容 -> 之前的空白是 Win32 PrintWindow 抓不到 GL 表面")
    print(f"已保存 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
