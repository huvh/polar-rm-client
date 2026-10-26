"""旧接收端兼容入口；协议和串口所有权实现位于 backend.video。"""
from .video.receiver import LegacyReceiverControl, discover_receiver_port
from .video.receiver_protocol import (
    CHANNEL_FREQUENCIES, HOST_ADDRESS, RECEIVER_ADDRESS, QUERY_STATUS, PUSH_STATUS,
    SET_CONFIG, ReceiverFrame, ReceiverFrameParser, channel_payload,
    encode_receiver_command, status_parameters,
)

__all__ = [
    "LegacyReceiverControl", "discover_receiver_port", "CHANNEL_FREQUENCIES",
    "HOST_ADDRESS", "RECEIVER_ADDRESS", "QUERY_STATUS", "PUSH_STATUS", "SET_CONFIG",
    "ReceiverFrame", "ReceiverFrameParser", "channel_payload", "encode_receiver_command",
    "status_parameters",
]
