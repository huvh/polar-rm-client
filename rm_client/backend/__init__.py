"""Backend public facade. Pure schema imports never load Qt or transports."""
from importlib import import_module

_EXPORTS = {
    "BackendManager": ("manager", "BackendManager"),
    "OfficialSafety": ("safety", "OfficialSafety"),
    "ControlState": ("safety", "ControlState"),
    "QualificationToken": ("safety", "QualificationToken"),
    "RmMqttBackend": ("mqtt_backend", "RmMqttBackend"),
    "RmVideoBackend": ("video", "RmVideoBackend"),
    "RmSerialBackend": ("serial_backend", "RmSerialBackend"),
    "BackendReadinessReport": ("readiness", "BackendReadinessReport"),
    "ReadinessGate": ("readiness", "ReadinessGate"),
    "audit_backend": ("readiness", "audit_backend"),
    **{name: ("qualification", name) for name in (
        "Capability", "CapabilityAuthorization", "QualificationEvidenceStore",
        "QualificationManager", "QualificationSession", "TestResult", "TestStatus",
    )},
    "protocol": ("protocol", None),
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    try:
        module_name, symbol = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    module = import_module(f".{module_name}", __name__)
    result = module if symbol is None else getattr(module, symbol)
    globals()[name] = result
    return result


def __dir__():
    return sorted(set(globals()) | set(__all__))
