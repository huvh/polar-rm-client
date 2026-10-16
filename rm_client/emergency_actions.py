"""Operator stop sequencing with independent, observable cleanup failures.

Backend authority is revoked before fallible UI input cleanup. These interfaces
cannot arm, release E-stop, replace a scenario, or start a transport.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol


class ControlLock(Protocol):
    def lock_control(self, reason: str) -> None: ...


class EmergencyBackend(ControlLock, Protocol):
    def trigger_estop(self) -> tuple[bool, str]: ...


class PendingInputs(Protocol):
    def reset_inputs(self) -> None: ...
    def clear_pending(self) -> None: ...


@dataclass(frozen=True)
class StopFailure:
    operation: str
    error_type: str
    message: str

    @property
    def summary(self) -> str:
        return f"{self.operation}: {self.error_type}: {self.message}"


@dataclass(frozen=True)
class StopResult:
    status: str
    failures: tuple[StopFailure, ...]

    @property
    def message(self) -> str:
        if self.failures:
            return self.status + "; incomplete: " + "; ".join(failure.summary for failure in self.failures)
        return self.status


def _attempt(operation: str, action: Callable[[], object], failures: list[StopFailure]) -> bool:
    try:
        action()
        return True
    except Exception as error:
        failures.append(StopFailure(operation, type(error).__name__, str(error)))
        return False


def _clear_inputs(inputs: PendingInputs, failures: list[StopFailure]) -> None:
    _attempt("input reset", inputs.reset_inputs, failures)
    _attempt("pending input clear", inputs.clear_pending, failures)


def request_emergency_stop(backend: EmergencyBackend, inputs: PendingInputs) -> StopResult:
    failures = []
    try:
        ok, reason = backend.trigger_estop()
        status = "E-STOP ACTIVE" if ok else f"E-STOP ACTIVE ({reason})"
    except Exception as error:
        failures.append(StopFailure("backend E-stop", type(error).__name__, str(error)))
        # A driver may fail before the backend reaches its local E-stop latch.
        # Revoke authority independently before touching fallible UI state.
        _attempt("fallback control lock", lambda: backend.lock_control("E-stop request failed"), failures)
        status = "E-STOP REQUEST INCOMPLETE"
    _clear_inputs(inputs, failures)
    return StopResult(status, tuple(failures))


def request_control_lock(backend: ControlLock, inputs: PendingInputs,
                         publish_zero: Callable[[], tuple[bool, str]]) -> StopResult:
    failures = []
    locked = _attempt("control lock", lambda: backend.lock_control("operator lock"), failures)
    try:
        ok, reason = publish_zero()
        if not ok:
            failures.append(StopFailure("neutral publication", "Rejected", reason))
    except Exception as error:
        failures.append(StopFailure("neutral publication", type(error).__name__, str(error)))
    _clear_inputs(inputs, failures)
    return StopResult("Match control LOCKED" if locked else "Control lock INCOMPLETE", tuple(failures))
