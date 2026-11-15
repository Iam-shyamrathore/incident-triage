"""Turn manually supplied sandbox telemetry into a request-scoped incident."""

import re
import time
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .catalog import SERVICES, label

CUSTOM_TOOLS = {
    "trace": "trace_failures",
    "error_counter": "inspect_errors",
    "latency": "inspect_latency",
    "health": "dependency_health",
}

SYMPTOMS = {
    "trace": "errors",
    "error_counter": "errors",
    "latency": "latency",
    "health": "connections",
}

PROVIDED_SOURCE = "Your submitted telemetry"
Nonblank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class SignalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str = Field(max_length=60)
    kind: Literal["trace", "error_counter", "latency", "health"]
    value: Nonblank = Field(max_length=300)
    age: int = Field(default=0, ge=0, le=240)

    @model_validator(mode="after")
    def validate_sample(self):
        if self.service not in SERVICES:
            raise ValueError("Select an evidence service from the sandbox catalog.")
        self.sample()
        return self

    def sample(self):
        if self.kind == "trace":
            return {"trace": self.value}
        if self.kind == "health":
            if self.value not in {"healthy", "degraded", "unavailable"}:
                raise ValueError("Choose healthy, degraded, or unavailable.")
            return {"connection_status": self.value}
        if self.kind == "latency":
            if not re.fullmatch(r"[0-9]{1,7}", self.value):
                raise ValueError("Enter a latency in milliseconds as a whole number.")
            return {"p95_ms": int(self.value)}
        match = re.fullmatch(r"([0-9]{1,7})\s*/\s*([0-9]{1,7})", self.value)
        if not match:
            raise ValueError("Enter failed and total requests, such as 12/100.")
        failed, total = map(int, match.groups())
        if not 0 < total or failed > total:
            raise ValueError("Failed requests cannot exceed the positive total.")
        return {"failed_requests": failed, "sampled_requests": total}

    def summary(self, sample):
        if self.kind == "trace":
            return self.value
        if self.kind == "health":
            return f"Connections are {sample['connection_status']}."
        if self.kind == "latency":
            return f"Observed p95 latency: {sample['p95_ms']} ms."
        return f"{sample['failed_requests']} of {sample['sampled_requests']} requests failed."


class CustomIncident(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alert: Nonblank = Field(max_length=500)
    service: str = Field(max_length=60)
    hop_limit: int = Field(default=3, ge=0, le=3)
    mode: Literal["learned", "graph"] = "learned"
    signals: list[SignalInput] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def validate_services_and_evidence(self):
        if self.service not in SERVICES:
            raise ValueError("Select an alerted service from the sandbox catalog.")
        unique = {(entry.service, entry.kind) for entry in self.signals}
        if len(unique) != len(self.signals):
            raise ValueError("Enter only one measurement of each kind per service.")
        return self

    def as_case(self):
        at = int(time.time()) // 60
        signals, telemetry = [], {}
        for entry in self.signals:
            sample = entry.sample()
            signals.append(
                {
                    "service": entry.service,
                    "kind": entry.kind,
                    "severity": 10,
                    "observed": at - entry.age,
                    "environment": "sandbox",
                    "text": f"{label(entry.service)}: {entry.summary(sample)}",
                }
            )
            if entry.age <= 30:
                telemetry.setdefault(entry.service, {}).update(sample)
        fresh_signals = [signal for signal in signals if at - signal["observed"] <= 30]
        primary = fresh_signals[0]["kind"] if fresh_signals else ""
        return {
            "id": f"custom-{uuid4().hex}",
            "alert": self.alert,
            "service": self.service,
            "at": at,
            "environment": "sandbox",
            "symptom": SYMPTOMS.get(primary, ""),
            "signals": signals,
            "telemetry": telemetry,
            "deployments": [],
            "custom": True,
        }
