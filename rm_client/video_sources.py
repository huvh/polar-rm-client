"""视频来源选择的纯数据；代际选项与其他来源共用一个配置值。"""

LEGACY_VIDEO_SOURCE = "Legacy VT02 UDP"
NEW_VIDEO_SOURCE = "New Video Link"
VIDEO_SOURCE_CHOICES = (
    "Webcam", "Shark UDP", "UDP HEVC", LEGACY_VIDEO_SOURCE, NEW_VIDEO_SOURCE,
    "Legacy Official Bridge", "Native 0x0310", "Synthetic",
)


def video_source_notice(source: str, *, chinese: bool = True) -> str:
    """返回占位来源的明确状态；实现过的来源仍由原有连接状态负责显示。"""
    if str(source).strip().lower() == NEW_VIDEO_SOURCE.lower():
        return "新图传：暂未实现" if chinese else "New video link: not implemented"
    return ""
