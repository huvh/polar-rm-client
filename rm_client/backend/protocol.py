"""Compatibility facade. New integrations must select a referee profile explicitly.

RM2026 codec and year-neutral PRM1 team payloads live in separate modules.
Existing imports (including wire helpers used by integrations) remain valid.
"""
from .referee.rm2026 import codec as _codec
from .referee import wire as _wire
from . import team_control as _team
from .referee.rm2026.codec import *  # noqa: F401,F403
from .referee.wire import *  # noqa: F401,F403
from .team_control import *  # noqa: F401,F403


def __getattr__(name):
    for module in (_codec, _wire, _team):
        if hasattr(module, name):
            return getattr(module, name)
    raise AttributeError(name)
