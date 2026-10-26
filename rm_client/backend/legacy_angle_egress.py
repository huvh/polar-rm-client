"""旧图传角度出口兼容入口；内部不再持有重复的协议实现。"""
from .video.angle_egress import LegacyAngleEgress
from .video.receiver_protocol import encode_receiver_angles

__all__ = ["LegacyAngleEgress", "encode_receiver_angles"]
