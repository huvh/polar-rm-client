"""兼容旧图传后端导入路径；实现见 :mod:`rm_client.backend.video`。"""
from .video.annexb import (
    AnnexBRecoveryGate, has_complete_annexb_recovery, iter_annexb_nal_units,
)
from .video.codec import (
    _decode_jpeg_bgr, consume_mjpeg_stream, detect_frame_codec, resolve_ffmpeg_executable,
)
from .video.decoder import ContinuousMjpegDecoder, _DecoderSession, _TimedDecoderInput
from .video.udp import RmVideoBackend

__all__ = [
    "AnnexBRecoveryGate", "ContinuousMjpegDecoder", "RmVideoBackend",
    "consume_mjpeg_stream", "detect_frame_codec", "has_complete_annexb_recovery",
    "iter_annexb_nal_units", "resolve_ffmpeg_executable",
]
