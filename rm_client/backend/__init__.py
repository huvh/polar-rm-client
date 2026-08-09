"""POLAR-RM 后端包：对齐 SharkClient 的后端能力（协议/通信/安全）。

对外只暴露 BackendManager，三种运行模式（LabDebug/CampusSimulation/OfficialEvent）
由 BackendManager.apply_scenario() 统一编排。
"""

from .manager import BackendManager
from .safety import OfficialSafety
from .mqtt_backend import RmMqttBackend
from .video_backend import RmVideoBackend
from .serial_backend import RmSerialBackend
from . import protocol

__all__ = [
    "BackendManager",
    "OfficialSafety",
    "RmMqttBackend",
    "RmVideoBackend",
    "RmSerialBackend",
    "protocol",
]
