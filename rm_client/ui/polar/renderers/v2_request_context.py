"""Actual owner/context capture shared by supervised V2 dialogs; no UI imports."""
from typing import Any
from ....referee_profiles import V2_PROFILE
from ....qualification_observations import same_v2_air_owners
from ....backend.referee.rm2026_v2.observations import WireSnapshot

def _v2_air_context(host: Any) -> tuple:
    """Capture actual owners; equality of dataclass profile values is insufficient."""
    backend = host.backend
    mqtt = backend.mqtt
    session = backend.qualification.session
    owners = (backend, mqtt, backend.referee, mqtt.referee, mqtt.client, session)
    snapshot = mqtt.v2_wire_snapshot()
    scope = tuple(snapshot.get(message, field).value
                  if snapshot is not None and snapshot.get(message, field) is not None else None
                  for message, field in (("GameStatus", "current_round"),
                                         ("RobotStaticStatus", "robot_id"),
                                         ("RobotStaticStatus", "robot_type")))
    values = (backend.referee.profile_id, mqtt.referee.profile_id,
              mqtt.receive_generation, str(mqtt.client_id), bool(mqtt.mock_output),
              bool(mqtt.connected), host.scenario_manager.current.key,
              getattr(session, "session_id", ""), getattr(session, "operator", ""),
              getattr(session, "referee_profile", ""), getattr(session, "robot_id", ""),
              (getattr(getattr(getattr(host, "match_mode_manager", None), "current", None), "key", None),
               getattr(host.state, "match_mode", None), getattr(session, "match_mode", None)), scope)
    scope_revision = snapshot.scope_revision if snapshot is not None else None
    return owners, values, snapshot, getattr(host, "_economy_qualification_token", None), scope_revision


def _same_v2_air_context(before: tuple, after: tuple, *, token: bool = True) -> bool:
    return (same_v2_air_owners(before[0], after[0]) and before[1] == after[1]
            and before[4] == after[4]
            and (not token or before[3] == after[3]))


def _v2_air_snapshot_current(context: tuple) -> bool:
    owners, values, snapshot, _token, _scope_revision = context
    return (values[0] == values[1] == V2_PROFILE and values[5]
            and values[6] == "OfficialEvent" and values[-2] == ("RMUC7v7",) * 3
            and type(snapshot) is WireSnapshot
            and (snapshot.profile_id, snapshot.receive_generation, snapshot.client_id)
                == (V2_PROFILE, values[2], values[3]))
