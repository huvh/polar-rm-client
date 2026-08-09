"""MQTT 后端（对齐 SharkClient Rust mqtt_client 的能力，纯 Python 实现）。

- 真实连接/自动重连（paho reconnect_delay_set）
- 收发统计、最后消息时间、重连次数
- 订阅全量 topic（#），在回调线程解码后放入队列，UI 主线程安全消费
- 发布走 OfficialMqttBridge 边界：mock 记录 或 真实发布 + 10Hz 限频 + 安全门控
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable

from ..transports import MqttPublishRecord, OfficialMqttBridge
from .protocol import decode_message, encode_custom_control, topic_message_name
from .safety import OfficialSafety


class RmMqttBackend(OfficialMqttBridge):
    """SharkClient 风格 MQTT 后端，兼容本地 OfficialMqttBridge 全部接口。"""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 3333,
        client_id: str = "3",
        mock_output: bool = True,
        safety: OfficialSafety | None = None,
    ) -> None:
        super().__init__(host=host, port=port, client_id=client_id)
        self.mock_output = bool(mock_output)
        self.safety = safety or OfficialSafety()
        self.messages_received = 0
        self.messages_sent = 0
        self.bytes_received = 0
        self.reconnect_count = 0
        self.last_message_at = 0.0
        self.connected_at = 0.0
        self._decoded: deque[tuple[str, str, dict[str, Any], float]] = deque(maxlen=512)
        self._decoded_lock = threading.Lock()
        self._started = False
        self._on_connect_hook: Callable[[], None] | None = None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._started:
            return
        try:
            import paho.mqtt.client as mqtt  # type: ignore
            self._mqtt = mqtt
            try:
                self.client = mqtt.Client(
                    mqtt.CallbackAPIVersion.VERSION2,
                    client_id=self.client_id or None,
                    clean_session=True,
                )
            except Exception:
                self.client = mqtt.Client(client_id=self.client_id or None)
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_message = self._on_message
            self.client.reconnect_delay_set(min_delay=1, max_delay=30)
            try:
                self.client.will_set(
                    "ClientStatus", b'{"online":false}', qos=1, retain=True
                )
            except Exception:
                pass
            self.client.connect_async(self.host, self.port, keepalive=30)
            self.client.loop_start()
            self._started = True
        except Exception as exc:  # pragma: no cover - depends on paho availability
            self.last_error = str(exc)
            self.connected = False
            self._started = False

    def stop(self) -> None:
        self._started = False
        client = self.client
        self.client = None
        if client is not None:
            try:
                client.publish("ClientStatus", b'{"online":false}', qos=1, retain=True)
            except Exception:
                pass
            try:
                client.disconnect()
            except Exception:
                pass
            try:
                client.loop_stop(force=True)
            except Exception:
                pass
        self.connected = False

    # ------------------------------------------------------------------
    # paho 回调
    # ------------------------------------------------------------------
    def _on_connect(self, client, _userdata, _flags, reason_code, _properties=None) -> None:
        ok = int(reason_code) == 0 if not isinstance(reason_code, str) else reason_code == "Success"
        self.connected = ok
        if ok:
            self.connected_at = time.time()
            try:
                client.publish("ClientStatus", b'{"online":true}', qos=1, retain=True)
            except Exception:
                pass
            client.subscribe("#", qos=1)
            if self._on_connect_hook:
                try:
                    self._on_connect_hook()
                except Exception:
                    pass

    def _on_disconnect(self, _client, _userdata, _flags=None, _reason_code=None, _properties=None) -> None:
        if self.connected:
            self.reconnect_count += 1
        self.connected = False

    def _on_message(self, client, userdata, msg) -> None:
        super()._on_message(client, userdata, msg)
        payload = bytes(msg.payload)
        self.messages_received += 1
        self.bytes_received += len(payload)
        self.last_message_at = time.time()
        topic = str(msg.topic)
        name = topic_message_name(topic)
        if name in {"GameStatus"}:
            # 比赛阶段同步给安全策略
            data = decode_message(name, payload)
            if data:
                self.safety.update_stage(data.get("current_stage", "0"))
                with self._decoded_lock:
                    self._decoded.append((topic, name, data, time.perf_counter()))
                return
        data = decode_message(name, payload)
        if not data:
            return
        with self._decoded_lock:
            self._decoded.append((topic, name, data, time.perf_counter()))

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
                      now: float | None = None) -> tuple[bool, str]:
        # 急停在任何模式（含 mock）都立即生效
        if self.safety.estop_active:
            self.last_error = "急停激活，禁止发布"
            return False, self.last_error
        allowed, reason = self.safety.can_publish(topic, now=now)
        if not allowed and not self.mock_output:
            self.last_error = reason
            return False, reason
        record = self._publish_record(topic, payload, qos)
        if self.mock_output:
            return True, "mock"
        if self.client is None or not self.connected:
            self.last_error = "未连接 MQTT 客户端"
            return False, self.last_error
        try:
            info = self.client.publish(topic, payload, qos=qos)
            rc = getattr(info, "rc", 0)
            mqtt = getattr(self, "_mqtt", None)
            success = rc == 0 or (mqtt is not None and rc == mqtt.MQTT_ERR_SUCCESS)
            if not success:
                self.last_error = f"MQTT 发布未进入网络（rc={rc}）"
                return False, self.last_error
            self.messages_sent += 1
            self.safety.mark_published(topic, now=now)
            return True, "ok"
        except Exception as exc:  # pragma: no cover
            self.last_error = str(exc)
            return False, str(exc)

    def _publish_record(self, topic: str, payload: bytes, qos: int) -> MqttPublishRecord:
        record = MqttPublishRecord(
            topic=topic, payload=payload, qos=qos,
            timestamp=time.time(), mock_output=self.mock_output,
        )
        self.publish_records.append(record)
        return record

    def publish_named(self, name: str, payload: bytes, *, qos: int = 1,
                      now: float | None = None) -> tuple[bool, str]:
        return self.publish_topic(name, payload, qos=qos, now=now)

    # 兼容经济链路（透传 now，保持旧语义）
    def publish_common_command(self, payload: bytes, *, now: float | None = None) -> bool:
        ok, _ = self.publish_topic("CommonCommand", payload, qos=1, now=now)
        return ok

    def publish_air_support_command(self, payload: bytes, *, now: float | None = None) -> bool:
        ok, _ = self.publish_topic("AirSupportCommand", payload, qos=1, now=now)
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

    def publish_custom_control(self, data: bytes) -> bool:
        if len(data) > 30:
            self.last_error = "CustomControl 载荷最多 30 字节"
            return False
        ok, _ = self.publish_topic("CustomControl", encode_custom_control(data), qos=1)
        return ok

    def stats(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
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
            "last_error": self.last_error,
        }
