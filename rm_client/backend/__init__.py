"""POLAR-RM 后端包：对齐 SharkClient 的后端能力（协议/通信/安全）。

对外只暴露 BackendManager，三种运行模式（LabDebug/CampusSimulation/OfficialEvent）
由 BackendManager.apply_scenario() 统一编排。
"""

from .manager import BackendManager
from .safety import ControlState, OfficialSafety, QualificationToken
from .mqtt_backend import RmMqttBackend
from .video_backend import RmVideoBackend
from .serial_backend import RmSerialBackend
from .readiness import BackendReadinessReport, ReadinessGate, audit_backend
from .qualification import (
    Capability,
    CapabilityAuthorization,
    QualificationEvidenceStore,
    QualificationManager,
    QualificationSession,
    TestResult,
    TestStatus,
)
from . import protocol

__all__ = [
    "BackendManager",
    "OfficialSafety",
    "ControlState",
    "QualificationToken",
    "RmMqttBackend",
    "RmVideoBackend",
    "RmSerialBackend",
    "BackendReadinessReport",
    "ReadinessGate",
    "audit_backend",
    "Capability",
    "CapabilityAuthorization",
    "QualificationEvidenceStore",
    "QualificationManager",
    "QualificationSession",
    "TestResult",
    "TestStatus",
    "protocol",
]
