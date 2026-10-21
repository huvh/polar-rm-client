"""MQTT 后端（对齐 SharkClient Rust mqtt_client 的能力，纯 Python 实现）。

- 真实连接/退避重建连接（丢弃旧客户端未确认的运动指令）
- 收发统计、最后消息时间、重连次数
- 按年度 profile 订阅下行 topic，在回调线程解码后放入有界队列
- 发布走 OfficialMqttBridge 边界：mock 记录 或年度限频 + 安全门控
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable

from ..transports import MqttPublishRecord, OfficialMqttBridge
from .referee.registry import DEFAULT_PROFILE, get_profile
from .referee.validation import InvalidRefereePayload, validate_message
from .referee.wire import decode_fields, _u
from .referee.rm2026_v2 import codec as v2_codec
from .referee.rm2026_v2.economy_rules import request_decision
from .referee.rm2026_v2.observations import WireSnapshot, observe
from .referee.rm2026_v2.uplink_validation import validate_uplink, is_sentry_map
from .safety import OfficialSafety, ControlState, CONTROL_TOPICS
from .mqtt_cleanup import MqttClientResources


class RmMqttBackend(OfficialMqttBridge):
    """SharkClient 风格 MQTT 后端，兼容本地 OfficialMqttBridge 全部接口。"""

    SUBACK_TIMEOUT_S = 5.0  # Local admission policy, not a vendor protocol limit.

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 3333,
        client_id: str = "3",
        mock_output: bool = True,
        safety: OfficialSafety | None = None,
        referee_profile: str = DEFAULT_PROFILE,
    ) -> None:
        self.referee = get_profile(referee_profile)
        super().__init__(host=host, port=port, client_id=self.referee.validate_client_id(client_id))
        self.mock_output = bool(mock_output)
        self.safety = safety or OfficialSafety()
        self.safety.configure_referee_limits(self.referee.uplink_hz)
        self.messages_received = 0
        self.messages_sent = 0
        self.bytes_received = 0
        self.reconnect_count = 0
        self.last_message_at = 0.0
        self.connected_at = 0.0
        self._decoded: deque[tuple[str, str, dict[str, Any], float]] = deque(maxlen=512)
        self._decoded_lock = threading.Lock()
        self._v2_wire_snapshot: WireSnapshot | None = None
        self._v2_wire_context: tuple[Any, Any, str] | None = None
        self._economy_state_owner: Any = None
        self._economy_qualification_owner: Any = None
        self._started = False
        self._on_connect_hook: Callable[[], None] | None = None
        self.event_hook: Callable[[str, dict[str, Any]], None] | None = None
        self.disconnected_at = time.perf_counter()
        self.receive_generation = 0
        self.invalid_messages = 0
        self.ignored_topics = 0
        self.queue_overflows = 0
        self.retained_messages_ignored = 0
        # CONNACK proves the broker connection, not acceptance of downlinks.
        # Keep SUBACK evidence attached to its exact client/request epoch.
        self._subscription_request: tuple[Any, int, int, int] | None = None
        self._subscriptions_ready = False
        self._subscription_error = ""
        self._subscription_started_at = 0.0
        self._receive_blocked = False
        self._reconnect_required = False
        self._next_reconnect_at = 0.0
        self._reconnect_backoff_s = 0.5
        self._zero_after_reconnect = False
        # Only lifecycle bookkeeping is protected here. Paho loop_stop() joins
        # its network thread without a timeout and must never hold this lock.
        self._lifecycle_lock = threading.RLock()
        self._lifecycle_generation = 0
        self._cleanup_thread: threading.Thread | None = None
        self._cleanup_client: Any = None
        self._client_resources: MqttClientResources | None = None
        self._pending_start = False
        self._cleanup_error = ""
        self._pending_input_clear: str | None = None
        self._owner_thread = threading.get_ident()

    @property
    def subscriptions_ready(self) -> bool:
        """Current session has a complete successful downlink SUBACK."""
        with self._lifecycle_lock:
            return bool(self.client is not None and self.connected and self._subscriptions_ready)

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def start(self) -> None:
        with self._lifecycle_lock:
            self._request_start_locked()
        self._flush_input_clear()

    def _request_start_locked(self) -> None:
        if self._started and (self.client is not None or self._pending_start):
            return
        if self._cleanup_error:
            self.last_error = self._cleanup_error
            return
        self._started = True
        if self._cleanup_client is not None:
            # The old client still owns the network loop. Coalesce starts
            # and endpoint changes rather than accumulating cleanup jobs.
            self._pending_start = True
            return
        self._start_client_locked()

    def _start_client_locked(self) -> None:
        """Start Paho's asynchronous connection after previous ownership ends."""
        try:
            import paho.mqtt.client as mqtt  # type: ignore
            self.client_id = self.referee.validate_client_id(self.client_id)
            self._mqtt = mqtt
            try:
                self.client = mqtt.Client(
                    mqtt.CallbackAPIVersion.VERSION2,
                    client_id=self.client_id or None,
                    clean_session=True,
                    protocol=mqtt.MQTTv311,
                    reconnect_on_failure=False,
                )
            except Exception:
                self.client = mqtt.Client(client_id=self.client_id or None,
                                          protocol=mqtt.MQTTv311,
                                          reconnect_on_failure=False)
            self._client_resources = MqttClientResources(self.client)
            self._client_resources.attach_socket_observers()
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_connect_fail = self._on_connect_fail
            self.client.on_message = self._on_message
            self.client.on_subscribe = self._on_subscribe
            self.client.reconnect_delay_set(min_delay=1, max_delay=30)
            self.client.connect_async(self.host, self.port, keepalive=30)
            self._started = True
            result = self._client_resources.start_network_loop()
            if result is not None and result != 0:
                raise RuntimeError(f"MQTT network loop failed to start (rc={result})")
        except Exception as exc:  # pragma: no cover - depends on paho availability
            # A partly constructed client is still an owner until cleaned up.
            # Never leave it available for publication or a later restart.
            self._stop_client_locked()
            self.last_error = str(exc)

    def stop(self, *, publish_status: bool = True, wait: bool = True) -> None:
        """Invalidate immediately; optionally wait for ordered final cleanup.

        Interactive restarts use wait=False. One cleanup owner holds the old
        client until loop_stop completes; no replacement can replay its QoS1
        queue or receive its callbacks. Final shutdown retains explicit waiting.
        """
        with self._lifecycle_lock:
            client = self.client if self.client is not None else self._cleanup_client
            network_thread = getattr(client, "_thread", None)
            worker = self._stop_client_locked()
        self._flush_input_clear()
        # publish_status remains a compatibility argument. There is no
        # ClientStatus JSON / retained will on the official wire.
        self._emit_event("mqtt_disconnect", reason="stop")
        # A callback cannot join a cleanup worker that must join that callback's
        # own Paho thread. Its invalidation is immediate and cleanup stays owned.
        if (wait and worker is not None
                and threading.current_thread() not in (worker, network_thread)):
            worker.join()

    def wait_stopped(self, timeout: float | None = None) -> bool:
        """Wait/observe only; never invoke safety hooks from a cleanup worker.

        Call stop(wait=False) on the owner thread first. The retained cleanup
        owner is not replaced when a driver stalls or reports a close error.
        """
        with self._lifecycle_lock:
            worker = self._cleanup_thread
            client = self._cleanup_client
            network_thread = getattr(client, "_thread", None)
        if worker is not None and threading.current_thread() not in (worker, network_thread):
            worker.join(timeout)
        with self._lifecycle_lock:
            return (not self._started and self.client is None
                    and self._cleanup_client is None and not self._cleanup_error)

    def _stop_client_locked(self) -> threading.Thread | None:
        self._lifecycle_generation += 1
        self._started = False
        self._pending_start = False
        self._reconnect_required = False
        self._zero_after_reconnect = False
        self.connected = False
        self._subscription_request = None
        self._subscriptions_ready = False
        self._receive_blocked = True
        # Transfer ownership before fallible epoch/safety notification work.
        # A preparation error must never detach a client without scheduling
        # its cleanup or retaining it for an explicit retry.
        if self.client is not None:
            if self._cleanup_client is not None and self._cleanup_client is not self.client:
                raise RuntimeError("MQTT already retains a different cleanup owner")
            if self._client_resources is None or self._client_resources.client is not self.client:
                self._client_resources = MqttClientResources(self.client)
            self._cleanup_client, self.client = self.client, None
        failure = None
        try:
            self.disconnected_at = time.perf_counter()
            try:
                self.clear_received_epoch()
            except Exception as exc:
                failure = exc
            try:
                if not self.safety.estop_active:
                    self._lock_safety_locked("MQTT stopped; explicit re-arm required")
            except Exception as exc:
                if failure is None:
                    failure = exc
            self.safety.clear_stage_evidence()
        finally:
            self._begin_client_cleanup_locked()
        if failure is not None:
            raise failure
        return self._cleanup_thread

    def _begin_client_cleanup_locked(self) -> None:
        # An explicit stop may retry a previously failed cleanup. A normal
        # poll/start never retries a broken owner or spawns more workers.
        if self._cleanup_client is not None and self._cleanup_thread is None:
            self._cleanup_error = ""
            worker = threading.Thread(target=self._finish_client_cleanup,
                                      name="mqtt-close", daemon=True)
            self._cleanup_thread = worker
            try:
                worker.start()
            except Exception as exc:
                if worker.ident is None:
                    self._cleanup_thread = None
                self._cleanup_error = self.last_error = f"MQTT cleanup failed: {exc}"

    def _finish_client_cleanup(self) -> None:
        with self._lifecycle_lock:
            resources = self._client_resources
        error = ""
        try:
            if resources is None:
                raise RuntimeError("MQTT cleanup has no retained resource owner")
            resources.close()
        except Exception as exc:
            error = f"MQTT cleanup failed: {exc}"
        with self._lifecycle_lock:
            self._cleanup_thread = None
            if error:
                self._cleanup_error = self.last_error = error
                self._pending_start = self._started = False
            else:
                self._cleanup_error = ""
                self._cleanup_client = None
                self._client_resources = None
            if not error and self._pending_start and self._started:
                self._pending_start = False
                # Start uses the latest endpoint/profile/identity, not values
                # captured by a stale restart request. All actual socket/DNS
                # work remains in Paho's newly created network thread.
                self._start_client_locked()
        self._flush_input_clear()

    def _lock_safety_locked(self, reason: str) -> None:
        # Admission precedes the fallible observer boundary; delivery remains
        # owner-only even when Paho invokes this method from a callback.
        self._pending_input_clear = reason
        self.safety.lock_control(reason, notify=False)

    def _flush_input_clear(self) -> None:
        if threading.get_ident() != self._owner_thread:
            return
        with self._lifecycle_lock:
            reason, self._pending_input_clear = self._pending_input_clear, None
        if reason is not None:
            self.safety._notify_input_clear(reason)

    def poll_connection(self) -> None:
        """Recreate the client outside its callback thread after a disconnect.

        Paho may replay unacknowledged QoS1 commands on reconnect even with
        clean_session=True. A fresh Client discards that motion queue instead.
        Deliberate stop/profile failures never schedule an automatic restart.
        """
        # Serialize expiry with receipt evidence; never call UI observers
        # while holding lifecycle/decoded locks or from the Paho callback.
        with self._lifecycle_lock:
            with self._decoded_lock:
                if self.safety.expire_stage(now=time.perf_counter(), notify=False):
                    self._pending_input_clear = self.safety.last_reason
        # Observer delivery cannot wait for reconnect backoff to expire.
        self._flush_input_clear()
        with self._lifecycle_lock:
            request = self._subscription_request
            expired = request if (request is not None
                and time.perf_counter() - self._subscription_started_at >= self.SUBACK_TIMEOUT_S) else None
        if expired is not None:
            self._subscription_failed(expired[0], expired[1],
                f"MQTT SUBACK timeout after {self.SUBACK_TIMEOUT_S:g} seconds",
                expected_request=expired)
            return
        with self._lifecycle_lock:
            if not self._reconnect_required or time.perf_counter() < self._next_reconnect_at:
                return
            self._stop_client_locked()
            self._zero_after_reconnect = True
            self._request_start_locked()
        self._flush_input_clear()
        self._emit_event("mqtt_disconnect", reason="stop")

    def clear_received_epoch(self) -> None:
        with self._decoded_lock:
            self.receive_generation += 1
            self._decoded.clear()
            self._v2_wire_snapshot = None
            self._v2_wire_context = None
        with self._received_lock:
            self._received_messages.clear()

    def bind_economy_context(self, state: Any, qualification: Any) -> None:
        """Bind live owners, never a cached/default competition-mode string."""
        with self._lifecycle_lock:
            if (state is self._economy_state_owner
                    and qualification is self._economy_qualification_owner):
                return
            self._economy_state_owner = state
            self._economy_qualification_owner = qualification
            self.clear_received_epoch()

    def _economy_scope_locked(self) -> tuple:
        state, qualification = self._economy_state_owner, self._economy_qualification_owner
        session = getattr(qualification, "session", None)
        state_mode = getattr(state, "match_mode", None)
        session_mode = getattr(session, "match_mode", None)
        if state is None or session is None or state_mode != "RMUC7v7" or session_mode != "RMUC7v7":
            raise InvalidRefereePayload("V2 economic rules require explicit current RMUC7v7 state and qualification session")
        if (getattr(session, "referee_profile", None) != self.referee.profile_id
                or str(getattr(session, "robot_id", "")) != str(self.client_id)):
            raise InvalidRefereePayload("economic qualification session profile/robot does not match MQTT")
        return state, qualification, session, state_mode, session_mode

    def _check_economy_scope_locked(self, expected: tuple) -> None:
        current = self._economy_scope_locked()
        if (any(a is not b for a, b in zip(current[:3], expected[:3]))
                or current[3:] != expected[3:]):
            raise InvalidRefereePayload("economic context/session changed after confirmation")

    def v2_wire_snapshot(self) -> WireSnapshot | None:
        """Return immutable receipt evidence, never projected state/permission.

        Match the existing lifecycle -> decoded order. The callback reducer
        takes decoded only and cannot call back into lifecycle/GUI owners.
        A held older snapshot is not a reusable action-admission witness.
        """
        with self._lifecycle_lock:
            with self._decoded_lock:
                return self._v2_wire_snapshot_locked()

    def _v2_wire_snapshot_locked(self) -> WireSnapshot | None:
        """Caller holds lifecycle then decoded; never reacquire either lock."""
        context = self._v2_wire_context
        snapshot = self._v2_wire_snapshot
        if (context is None or snapshot is None
                or context[0] is not self.referee
                or context[1] is not self.client
                or context[2] != str(self.client_id)
                or snapshot.receive_generation != self.receive_generation):
            return None
        return snapshot

    def set_referee_profile(self, profile_id: str) -> None:
        try:
            profile = get_profile(profile_id)
        except ValueError:
            self.publish_estop_zero()
            self.stop(publish_status=False, wait=False)
            self.safety.lock_control("unsupported referee profile")
            self.safety.clear_stage_evidence()
            raise
        with self._lifecycle_lock:
            if profile.profile_id == self.referee.profile_id:
                return
            started = self._started
            self._stop_client_locked()
            self.referee = profile
            self.safety.configure_referee_limits(profile.uplink_hz)
            self._lock_safety_locked("referee profile changed")
            self.safety.clear_stage_evidence()
            if started:
                self._request_start_locked()
        self._flush_input_clear()
        self._emit_event("mqtt_disconnect", reason="stop")

    def set_address(self, host: str, port: int) -> bool:
        """改 broker 地址。已经连着就断开重连，返回是否真的换了。

        以前 host/port 只在场景切换时被**赋值**（``manager._apply_config``），
        赋值不会重连：进程已经连着 127.0.0.1 时把字段改成 192.168.12.1，
        实际还在往老地址发 —— 检录当天这就会把"键鼠出口开着但赛事引擎收不到"
        演成一条查不出原因的故障。
        """
        host = str(host).strip()
        port = int(port)
        with self._lifecycle_lock:
            if (host, port) == (str(self.host), int(self.port)):
                return False
            self.host = host
            self.port = port
            self.clear_received_epoch()
            self._lock_safety_locked("MQTT endpoint changed")
            self.safety.clear_stage_evidence()
            started = self._started
            if started:
                self._stop_client_locked()
                self._request_start_locked()
        self._flush_input_clear()
        if started:
            self._emit_event("mqtt_disconnect", reason="stop")
        return True

    # ------------------------------------------------------------------
    # paho 回调
    # ------------------------------------------------------------------
    def _on_connect(self, client, _userdata, _flags, reason_code, _properties=None) -> None:
        # ReasonCode conversion and optional observers run outside the short
        # lifecycle section. Neither may make a GUI restart wait for a callback.
        value = getattr(reason_code, "value", reason_code)
        ok = value == 0 or str(value) == "Success"
        with self._lifecycle_lock:
            if client is not self.client:
                return
            self.connected = ok
            self._receive_blocked = not ok
            self._subscription_request = None
            self._subscriptions_ready = False
            if ok:
                self.connected_at = time.time()
                self.disconnected_at = 0.0
                self._reconnect_required = False
                self._reconnect_backoff_s = 0.5
                profile = self.referee
                generation = self._lifecycle_generation
        if not ok:
            self._schedule_reconnect(f"connect rejected: {reason_code}", client=client)
            return
        self._emit_event("mqtt_connect", host=self.host, port=self.port)
        downlinks = (v2_codec.DECODABLE_MESSAGES if profile.codec is v2_codec
                     else profile.codec.DOWNLINK_MESSAGES)
        with self._lifecycle_lock:
            if client is not self.client or generation != self._lifecycle_generation:
                return
        try:
            result = client.subscribe([(name, profile.max_qos) for name in sorted(downlinks)])
            if (not isinstance(result, tuple) or len(result) != 2
                    or result[0] != 0 or type(result[1]) is not int
                    or not 1 <= result[1] <= 65535):
                raise RuntimeError(f"subscribe request not queued (result={result!r})")
        except Exception as exc:
            self._subscription_failed(client, generation,
                f"MQTT subscription failed: {type(exc).__name__}: {exc}")
            return
        with self._lifecycle_lock:
            if client is not self.client or generation != self._lifecycle_generation:
                return
            self._subscription_request = (client, generation, result[1], len(downlinks))
            self._subscription_started_at = time.perf_counter()
            self._subscription_error = ""
            zero = self._zero_after_reconnect and not self.referee.read_only
            if zero:
                self._zero_after_reconnect = False
            hook = self._on_connect_hook
        if zero:
            self.publish_estop_zero(_expected_session=(client, generation))
        if hook:
            try:
                hook()
            except Exception:
                pass

    def _subscription_failed(self, client: Any, generation: int, reason: str, *,
                             expected_request: tuple | None = None) -> None:
        with self._lifecycle_lock:
            if (client is not self.client or generation != self._lifecycle_generation
                    or (expected_request is not None and self._subscription_request is not expected_request)):
                return
            self.connected = False
            self._receive_blocked = True
            self._subscription_request = None
            self._subscriptions_ready = False
            self._subscription_error = self.last_error = reason
        # Reuse the existing asynchronous reconnect and owner-only input-clear
        # path. A Paho callback must never synchronously stop its own loop.
        self._schedule_reconnect(reason, client=client)

    def _on_subscribe(self, client, _userdata, mid, reason_codes, _properties=None) -> None:
        """Accept only a complete successful SUBACK for our current request."""
        with self._lifecycle_lock:
            request = self._subscription_request
            if (request is None or client is not self.client or request[0] is not client
                    or request[1] != self._lifecycle_generation or request[2] != mid):
                return
            generation, count = request[1], request[3]
            try:
                grants = tuple(getattr(code, "value", code) for code in reason_codes)
                accepted = (len(grants) == count and all(
                    type(code) is int and 0 <= code <= self.referee.max_qos for code in grants))
            except (TypeError, ValueError):
                grants, accepted = (), False
            if accepted:
                self._subscription_request = None
                self._subscriptions_ready = True
                self._subscription_error = ""
                return
        self._subscription_failed(client, generation,
            f"MQTT SUBACK rejected or incomplete: expected {count} grants, got {grants!r}",
            expected_request=request)

    def _on_connect_fail(self, client, _userdata) -> None:
        self._schedule_reconnect("connect failed", client=client)

    def _schedule_reconnect(self, reason: str, *, client: Any = None) -> None:
        with self._lifecycle_lock:
            if client is not None and client is not self.client:
                return
            self.connected = False
            self._subscription_request = None
            self._subscriptions_ready = False
            self._receive_blocked = True
            self.disconnected_at = time.perf_counter()
            self.clear_received_epoch()
            self._lock_safety_locked(reason)
            self.safety.clear_stage_evidence()
            self._reconnect_required = self._started
            self._next_reconnect_at = time.perf_counter() + self._reconnect_backoff_s
            self._reconnect_backoff_s = min(5.0, self._reconnect_backoff_s * 2.0)
        self._flush_input_clear()
        self._emit_event("mqtt_disconnect", reason=reason)

    def _on_disconnect(self, _client, _userdata, _flags=None, _reason_code=None, _properties=None) -> None:
        with self._lifecycle_lock:
            if _client is not self.client:
                return
            if self.connected:
                self.reconnect_count += 1
        self._schedule_reconnect(f"MQTT disconnected: {_reason_code}", client=_client)

    def _on_message(self, client, userdata, msg) -> None:
        if client is not self.client or self._receive_blocked:
            return
        received_at = time.perf_counter()
        generation = self.receive_generation
        profile = self.referee
        is_v2 = profile.codec is v2_codec and profile.protocol_version == v2_codec.PROTOCOL_VERSION
        client_id = str(self.client_id) if is_v2 else ""
        payload = bytes(msg.payload)
        self.messages_received += 1
        self.bytes_received += len(payload)
        self.last_message_at = time.time()
        topic = str(msg.topic)
        self._emit_event("referee_rx", topic=topic, payload=payload)
        if getattr(msg, "retain", False):
            # A broker can replay a retained snapshot from a previous match or
            # receiver session. It carries no trustworthy production timestamp:
            # receipt now cannot establish current phase, HUD events or V2
            # action evidence. Keep traffic diagnostics, but no live queues.
            self.retained_messages_ignored += 1
            self._emit_event("referee_retained_ignored", topic=topic, profile=profile.profile_id)
            return
        # Official topics are exact instruction names, not arbitrary prefixes
        # or a topic echoed from our own uplink.
        name = topic
        if name not in profile.codec.DOWNLINK_MESSAGES:
            self.ignored_topics += 1
            return
        if not self._subscriptions_ready:
            # Traffic may arrive before SUBACK. It must not later become stage
            # authority through the UI adapter or immutable economic receipts.
            self.ignored_topics += 1
            return
        try:
            data = profile.codec.decode_message(name, payload)
        except Exception as exc:
            self.last_error = f"{name} decode failed: {type(exc).__name__}: {exc}"
            data = {}
        if not data:
            self.invalid_messages += 1
            self._emit_event("referee_decode_error", topic=topic, profile=profile.profile_id)
            return
        with self._decoded_lock:
            if (generation != self.receive_generation or profile is not self.referee
                    or client is not self.client or self._receive_blocked
                    or not self._subscriptions_ready):
                return
            if is_v2:
                if client_id != str(self.client_id):
                    return
                context = self._v2_wire_context
                previous = self._v2_wire_snapshot if (context is not None
                    and context[0] is profile and context[1] is client
                    and context[2] == client_id) else None
                snapshot = observe(previous, profile_id=profile.profile_id,
                                   receive_generation=generation, client_id=client_id,
                                   message=name, data=data, received_at=received_at)
                self._v2_wire_snapshot = snapshot
                self._v2_wire_context = (profile, client, client_id)
            super()._on_message(client, userdata, msg, received_at=received_at)
            if (name == "GameStatus" and self._subscriptions_ready
                    and 5 in data.get("__present__", ())):
                if self.safety.observe_stage_receipt(data["current_stage"], received_at=received_at):
                    self._pending_input_clear = self.safety.last_reason
            if len(self._decoded) == self._decoded.maxlen:
                self.queue_overflows += 1
            self._decoded.append((topic, name, data, received_at))

    # ------------------------------------------------------------------
    # 解码结果消费（UI 主线程）
    # ------------------------------------------------------------------
    def drain_decoded(self) -> list[tuple[str, str, dict[str, Any], float]]:
        with self._decoded_lock:
            messages = list(self._decoded)
            self._decoded.clear()
        return messages

    # ------------------------------------------------------------------
    # 发布（带安全门控 + 10Hz 限频）
    # ------------------------------------------------------------------
    def publish_topic(self, topic: str, payload: bytes, *, qos: int = 1,
                      now: float | None = None, intent: str = "control",
                      qualification_token: str | None = None,
                      expected_economy_snapshot: WireSnapshot | None = None) -> tuple[bool, str]:
        try:
            if self.referee.codec is v2_codec:
                payload = bytes(payload)  # Freeze V2 before classification/admission.
            if (self.referee.codec is v2_codec and topic == "MapClickCmd"
                    and is_sentry_map(payload) and intent != "economy"):
                raise InvalidRefereePayload("sentry map destination requires explicit economic confirmation intent")
        except (ValueError, TypeError, OverflowError) as exc:
            self.last_error = str(exc)
            return False, self.last_error
        if self._uses_v2_request_guard(self.referee, topic, payload):
            return self._publish_v2_request(topic, payload, qos=qos,
                qualification_token=qualification_token,
                expected_economy_snapshot=expected_economy_snapshot)
        with self._lifecycle_lock:
            client, generation = self.client, self._lifecycle_generation
            authority_generation = self.safety.control_generation
            uplink_context = (self.referee, self.safety, str(self.client_id), intent,
                              qualification_token) if self.referee.codec is v2_codec else None
        valid, reason = self.referee.validate_publish(topic, qos)
        if not valid:
            self.last_error = reason
            return False, reason
        try:
            validate_message(topic, payload, self.referee.codec.FIELDS)
            if self.referee.codec is v2_codec:
                validate_uplink(topic, payload)
            if topic == "CustomControl" and len(self.referee.codec._b(self.referee.codec.decode_fields(payload), 1)) > 30:
                raise InvalidRefereePayload("CustomControl payload exceeds 30 bytes")
        except (ValueError, TypeError, OverflowError) as exc:
            self.last_error = f"invalid {topic}: {exc}"
            return False, self.last_error
        # 急停在任何模式（含 mock）都立即生效
        if self.safety.estop_active:
            self.last_error = "急停激活，禁止发布"
            return False, self.last_error
        allowed, reason = self.safety.can_publish(
            topic,
            now=now,
            intent=intent,
            qualification_token=qualification_token,
        )
        if not allowed and not self.mock_output:
            self.last_error = reason
            self._emit_event("publish_result", topic=topic, ok=False, reason=reason, intent=intent)
            return False, reason
        record = self._publish_record(topic, payload, qos)
        if self.mock_output:
            self._emit_event("publish_result", topic=topic, ok=True, reason="mock", intent=intent)
            return True, "mock"
        if self.client is None or not self.connected:
            self.last_error = (
                "未连接裁判 MQTT：检查官方自定义客户端服务、网卡及机器人 ClientId；"
                f"当前 {self.host}:{self.port} / ClientId={self.client_id}。"
                "引擎内部 TCP 登录端口不是该 MQTT 接口。"
            )
            self._emit_event("publish_result", topic=topic, ok=False, reason=self.last_error, intent=intent)
            return False, self.last_error
        try:
            info = self._publish_current(client, generation, topic, payload, qos,
                                         authority_generation=authority_generation,
                                         uplink_context=uplink_context)
            rc = getattr(info, "rc", 0)
            mqtt = getattr(self, "_mqtt", None)
            success = rc == 0 or (mqtt is not None and rc == mqtt.MQTT_ERR_SUCCESS)
            if not success:
                self.last_error = f"MQTT 发布未进入网络（rc={rc}）"
                self._emit_event("publish_result", topic=topic, ok=False, reason=self.last_error, intent=intent)
                return False, self.last_error
            self.messages_sent += 1
            self.safety.mark_published(topic, now=now)
            self._emit_event("publish_result", topic=topic, ok=True, reason="ok", intent=intent)
            return True, "ok"
        except Exception as exc:  # pragma: no cover
            self.last_error = str(exc)
            self._emit_event("publish_result", topic=topic, ok=False, reason=self.last_error, intent=intent)
            return False, str(exc)

    @staticmethod
    def _uses_v2_request_guard(profile: Any, topic: str, payload: bytes | None = None) -> bool:
        return (profile.codec is v2_codec
                and profile.protocol_version == v2_codec.PROTOCOL_VERSION
                and (topic in ("AirSupportCommand", "SentryCtrlCommand", "CommonCommand")
                     or (topic == "MapClickCmd" and payload is not None and is_sentry_map(payload))))

    def _publish_v2_request(self, topic: str, payload: bytes, *, qos: int,
                            qualification_token: str | None,
                            expected_economy_snapshot: WireSnapshot | None = None) -> tuple[bool, str]:
        """One immutable payload and one policy for every V2 economy entry."""
        try:
            with self._lifecycle_lock:
                profile, safety = self.referee, self.safety
                client, generation = self.client, self._lifecycle_generation
                authority_generation = safety.control_generation
                mock_output = self.mock_output
                scope = self._economy_scope_locked()
                with self._decoded_lock:
                    snapshot = self._v2_wire_snapshot_locked()
                    if (topic != "AirSupportCommand" or expected_economy_snapshot is not None):
                        if expected_economy_snapshot is None or expected_economy_snapshot is not snapshot:
                            raise InvalidRefereePayload("the exact current economic snapshot must be confirmed")
            payload = bytes(payload)
            if not self._uses_v2_request_guard(profile, topic, payload):
                raise RuntimeError("V2 request profile changed; command discarded")
            valid, reason = profile.validate_publish(topic, qos)
            if not valid:
                raise InvalidRefereePayload(reason)
            current = time.perf_counter()
            validate_uplink(topic, payload, snapshot=snapshot, now=current,
                            client_id=str(self.client_id), require_identity=True)
            fields = decode_fields(payload)
            command_id = 0 if topic == "MapClickCmd" else _u(fields, 1)
            param = _u(fields, 2) if topic == "CommonCommand" else 0
            allowed, reason, _estimate = request_decision(topic, command_id, snapshot, now=current, param=param)
            if not allowed:
                raise ValueError(reason)
            allowed, reason = safety.can_publish(topic, now=current, intent="economy",
                                                 qualification_token=qualification_token)
            if not allowed:
                raise ValueError(reason)
            self._publish_record(topic, payload, qos)
            info = self._publish_current(
                client, generation, topic, payload, qos,
                authority_generation=authority_generation,
                v2_context=(profile, safety, snapshot, qualification_token, mock_output, scope),
            )
            if mock_output:
                reason = "mock"
            else:
                rc = getattr(info, "rc", 0)
                mqtt = getattr(self, "_mqtt", None)
                if rc != 0 and (mqtt is None or rc != mqtt.MQTT_ERR_SUCCESS):
                    raise RuntimeError(f"MQTT publish not queued (rc={rc})")
                self.messages_sent += 1
                reason = "ok"
        except Exception as exc:
            reason = self.last_error = str(exc)
            self._emit_event("publish_result", topic=topic, ok=False, reason=reason, intent="economy")
            return False, reason
        self._emit_event("publish_result", topic=topic, ok=True, reason=reason, intent="economy")
        return True, reason

    def _publish_record(self, topic: str, payload: bytes, qos: int) -> MqttPublishRecord:
        record = MqttPublishRecord(
            topic=topic, payload=payload, qos=qos,
            timestamp=time.time(), mock_output=self.mock_output,
        )
        self.publish_records.append(record)
        return record

    def publish_named(self, name: str, payload: bytes, *, qos: int = 1,
                      now: float | None = None, intent: str = "control",
                      qualification_token: str | None = None,
                      expected_economy_snapshot: WireSnapshot | None = None) -> tuple[bool, str]:
        return self.publish_topic(
            name,
            payload,
            qos=qos,
            now=now,
            intent=intent,
            qualification_token=qualification_token,
            expected_economy_snapshot=expected_economy_snapshot,
        )

    # 兼容经济链路（透传 now，保持旧语义）
    def publish_common_command(
        self,
        payload: bytes,
        *,
        now: float | None = None,
        qualification_token: str | None = None,
        expected_economy_snapshot: WireSnapshot | None = None,
    ) -> bool:
        ok, _ = self.publish_topic(
            "CommonCommand",
            payload,
            qos=1,
            now=now,
            intent="economy",
            qualification_token=qualification_token,
            expected_economy_snapshot=expected_economy_snapshot,
        )
        return ok

    def publish_air_support_command(
        self,
        payload: bytes,
        *,
        now: float | None = None,
        qualification_token: str | None = None,
        expected_economy_snapshot: WireSnapshot | None = None,
    ) -> bool:
        ok, _ = self.publish_topic(
            "AirSupportCommand",
            payload,
            qos=1,
            now=now,
            intent="economy",
            qualification_token=qualification_token,
            expected_economy_snapshot=expected_economy_snapshot,
        )
        return ok

    # 堵住继承入口的安全后门：所有发布统一走 publish_topic（门控 + 10Hz + 急停）
    def publish_binary(self, topic: str, payload: bytes, qos: int = 1) -> bool:
        ok, _ = self.publish_topic(topic, payload, qos=qos)
        return ok

    def publish_match_command(self, topic: str, payload: bytes, *, qos: int = 1,
                              now: float | None = None) -> bool:
        ok, _ = self.publish_topic(topic, payload, qos=qos, now=now)
        return ok

    def publish_keyboard_mouse(self, payload: bytes) -> bool:
        ok, _ = self.publish_topic("KeyboardMouseControl", payload, qos=1)
        return ok

    def _publish_current(self, client: Any, generation: int, topic: str,
                         payload: bytes, qos: int, *,
                         authority_generation: int | None = None,
                         v2_context: tuple | None = None,
                         uplink_context: tuple | None = None) -> Any:
        # Admission may precede a stop/restart. Never redirect an old command
        # into a replacement session, even if its new connection is already up.
        # Paho publish enqueues on nonblocking sockets; no observers run here.
        with self._lifecycle_lock:
            if (client is None or client is not self.client or not self.connected
                    or generation != self._lifecycle_generation):
                raise RuntimeError("MQTT session changed; command discarded")
            if authority_generation is not None and not self._subscriptions_ready:
                raise RuntimeError("MQTT downlink subscriptions pending SUBACK; command discarded")
            # A command can pause after admission while the same session is
            # locked, E-stopped, or re-armed. Never carry that old command into
            # new authority. The dedicated fixed-zero path deliberately omits
            # this guard. This recheck does not recall an already queued write.
            if authority_generation is not None and (
                    self.safety.estop_active
                    or authority_generation != self.safety.control_generation):
                raise RuntimeError("MQTT control authority changed; command discarded")
            if self._uses_v2_request_guard(self.referee, topic, payload) or v2_context is not None:
                if v2_context is None or authority_generation is None:
                    raise RuntimeError("V2 request context required; command discarded")
                profile, safety, snapshot, token, mock_output, scope = v2_context
                with self._decoded_lock:
                    if (self.safety.estop_active
                            or authority_generation != self.safety.control_generation):
                        raise RuntimeError("MQTT control authority changed; command discarded")
                    if (profile is not self.referee or safety is not self.safety
                            or mock_output != self.mock_output or snapshot is None
                            or not self._uses_v2_request_guard(profile, topic, payload)
                            or snapshot is not self._v2_wire_snapshot_locked()):
                        raise RuntimeError("V2 request evidence changed; command discarded")
                    if type(payload) is not bytes:
                        raise InvalidRefereePayload("V2 final payload must be frozen bytes")
                    self._check_economy_scope_locked(scope)
                    current = time.perf_counter()
                    validate_uplink(topic, payload, snapshot=snapshot, now=current,
                                    client_id=str(self.client_id), require_identity=True)
                    fields = decode_fields(payload)
                    command_id = 0 if topic == "MapClickCmd" else _u(fields, 1)
                    param = _u(fields, 2) if topic == "CommonCommand" else 0
                    allowed, reason = safety.can_publish_v2_economy_current(
                        topic, now=current, qualification_token=token)
                    if not allowed:
                        raise RuntimeError(reason)
                    allowed, reason, _estimate = request_decision(
                        topic, command_id, snapshot, now=current, param=param)
                    if not allowed:
                        raise RuntimeError(reason)
                    if mock_output:
                        return None
                    info = client.publish(topic, payload, qos=qos)
                    rc = getattr(info, "rc", 0)
                    mqtt = getattr(self, "_mqtt", None)
                    if rc == 0 or (mqtt is not None and rc == mqtt.MQTT_ERR_SUCCESS):
                        safety.mark_published(topic, now=current)
                    return info
            with self._decoded_lock:
                # Receipt-side expiry can revoke authority while we wait for
                # decoded. Recheck inside that same lock before the wire write.
                if authority_generation is not None and (
                        self.safety.estop_active
                        or authority_generation != self.safety.control_generation):
                    raise RuntimeError("MQTT control authority changed; command discarded")
                # A command may wait after initial admission while stage
                # evidence expires or a non-fighting phase arrives. Check the
                # actual wire clock, never the caller's optional test clock.
                # The fixed-zero path has no authority_generation and remains
                # available independently of phase; supervised qualification
                # keeps its existing stage exemption.
                if (authority_generation is not None and topic in CONTROL_TOPICS
                        and self.safety.enforce_official_limits
                        and self.safety.control_state == ControlState.MATCH_ARMED
                        and not self.safety.is_fighting(now=time.perf_counter())):
                    raise RuntimeError("referee stage not fresh/fighting; command discarded")
                if authority_generation is not None and self.referee.codec is v2_codec:
                    if uplink_context is None:
                        raise RuntimeError("V2 uplink context required; command discarded")
                    profile, safety, client_id, intent, token = uplink_context
                    if (profile is not self.referee or safety is not self.safety
                            or client_id != str(self.client_id)):
                        raise RuntimeError("V2 uplink context changed; command discarded")
                    validate_uplink(topic, payload, snapshot=self._v2_wire_snapshot_locked(),
                                    now=time.perf_counter(), client_id=client_id, require_identity=True)
                    allowed, reason = safety.can_publish_current(
                        topic, now=time.perf_counter(), intent=intent, qualification_token=token)
                    if not allowed:
                        raise RuntimeError(reason)
                elif uplink_context is not None:
                    raise RuntimeError("V2 uplink profile changed; command discarded")
                return client.publish(topic, payload, qos=qos)

    def publish_estop_zero(self, *, _expected_session: tuple[Any, int] | None = None) -> tuple[bool, str]:
        """仅发布固定全零 KMC，绕过普通限频以避免按键释放被 75Hz 门控吞掉。"""
        with self._lifecycle_lock:
            client, generation = (_expected_session if _expected_session is not None else
                                  (self.client, self._lifecycle_generation))
        if self.referee.read_only:
            return False, "Student preview is READ ONLY; use the physical E-stop"
        payload = self.referee.codec.encode_keyboard_mouse_control()
        if self.mock_output:
            self._publish_record("KeyboardMouseControl", payload, 1)
            self._emit_event("publish_result", topic="KeyboardMouseControl", ok=True, reason="estop mock", intent="estop_zero")
            return True, "mock"
        if self.client is None or not self.connected:
            self.last_error = "未连接 MQTT 客户端，急停零帧未上网"
            self._emit_event("publish_result", topic="KeyboardMouseControl", ok=False, reason=self.last_error, intent="estop_zero")
            return False, self.last_error
        try:
            info = self._publish_current(client, generation, "KeyboardMouseControl", payload, 1)
            rc = getattr(info, "rc", 0)
            mqtt = getattr(self, "_mqtt", None)
            success = rc == 0 or (mqtt is not None and rc == mqtt.MQTT_ERR_SUCCESS)
            if not success:
                self.last_error = f"急停零帧未进入网络（rc={rc}）"
                self._emit_event("publish_result", topic="KeyboardMouseControl", ok=False, reason=self.last_error, intent="estop_zero")
                return False, self.last_error
            self._publish_record("KeyboardMouseControl", payload, 1)
            self.messages_sent += 1
            self.safety.mark_published("KeyboardMouseControl")
            self._emit_event("publish_result", topic="KeyboardMouseControl", ok=True, reason="ok", intent="estop_zero")
            return True, "ok"
        except Exception as exc:
            self.last_error = str(exc)
            self._emit_event("publish_result", topic="KeyboardMouseControl", ok=False, reason=self.last_error, intent="estop_zero")
            return False, self.last_error

    def publish_custom_control(self, data: bytes) -> bool:
        if len(data) > 30:
            self.last_error = "CustomControl 载荷最多 30 字节"
            return False
        ok, _ = self.publish_topic("CustomControl", self.referee.codec.encode_custom_control(data), qos=1)
        return ok

    def stats(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "referee_profile": self.referee.profile_id,
            "protocol_version": self.referee.protocol_version,
            "read_only": self.referee.read_only,
            "receive_generation": self.receive_generation,
            "lifecycle_generation": self._lifecycle_generation,
            "cleanup_pending": self._cleanup_client is not None,
            "restart_pending": self._pending_start,
            "cleanup_error": self._cleanup_error,
            "invalid_messages": self.invalid_messages,
            "ignored_topics": self.ignored_topics,
            "queue_overflows": self.queue_overflows,
            "retained_messages_ignored": self.retained_messages_ignored,
            "subscriptions_ready": self.subscriptions_ready,
            "subscription_pending": self._subscription_request is not None,
            "subscription_error": self._subscription_error,
            "host": self.host,
            "port": self.port,
            "client_id": self.client_id,
            "mock_output": self.mock_output,
            "messages_received": self.messages_received,
            "messages_sent": self.messages_sent,
            "bytes_received": self.bytes_received,
            "reconnect_count": self.reconnect_count,
            "last_message_at": self.last_message_at,
            "connected_at": self.connected_at,
            "disconnected_at": self.disconnected_at,
            "last_error": self.last_error,
        }

    def _emit_event(self, event: str, **payload: Any) -> None:
        hook = self.event_hook
        if hook is None:
            return
        try:
            hook(event, **payload)
        except Exception:
            pass
