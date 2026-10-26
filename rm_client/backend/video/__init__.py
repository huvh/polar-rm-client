"""图传公共入口；纯协议导入不加载设备传输或可选解码依赖。"""
from importlib import import_module

_EXPORTS = {
    "AnnexBRecoveryGate": ("annexb", "AnnexBRecoveryGate"),
    "ContinuousMjpegDecoder": ("decoder", "ContinuousMjpegDecoder"),
    "LegacyReceiverControl": ("receiver", "LegacyReceiverControl"),
    "RmVideoBackend": ("udp", "RmVideoBackend"),
    "resolve_ffmpeg_executable": ("codec", "resolve_ffmpeg_executable"),
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    try:
        module_name, symbol = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    result = getattr(import_module(f".{module_name}", __name__), symbol)
    globals()[name] = result
    return result


def __dir__():
    return sorted(set(globals()) | set(__all__))
