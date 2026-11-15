from mcp.server.fastmcp import FastMCP
from typing_extensions import TypedDict

from .catalog import REPLAYS, SERVICES

server = FastMCP("Online Boutique incident replay")


class Observation(TypedDict):
    service: str
    environment: str
    observed_at: int
    source: str
    status: str
    evidence: dict[str, object]


def response(
    case_id: str, service: str, observed_at: int, fields: tuple[str, ...]
) -> Observation:
    replay = REPLAYS.get(case_id)
    if replay is None or replay["at"] != observed_at or service not in SERVICES:
        raise ValueError("Unknown replay, service or observation time")
    telemetry = replay["telemetry"].get(service, {})
    evidence = {field: telemetry[field] for field in fields if field in telemetry}
    return {
        "service": service,
        "environment": replay["environment"],
        "observed_at": observed_at,
        "source": "Synthetic replay telemetry",
        "status": "observed" if evidence else "no data",
        "evidence": evidence,
    }


@server.tool()
def inspect_errors(case_id: str, service: str, observed_at: int) -> Observation:
    """Read failed and sampled request counts for the resolved service at alert time."""
    return response(
        case_id, service, observed_at, ("failed_requests", "sampled_requests")
    )


@server.tool()
def trace_failures(case_id: str, service: str, observed_at: int) -> Observation:
    """Read a sampled failed upstream trace for the resolved service at alert time."""
    return response(case_id, service, observed_at, ("trace",))


@server.tool()
def list_deployments(case_id: str, service: str, observed_at: int) -> Observation:
    """Read the latest visible release record for a service before the alert."""
    result = response(case_id, service, observed_at, ())
    replay = REPLAYS[case_id]
    releases = [
        record
        for record in replay["deployments"]
        if record["service"] == service
        and record["environment"] == replay["environment"]
        and record["at"] <= observed_at
    ]
    if releases:
        result["status"] = "observed"
        result["evidence"] = {
            "deployment": max(releases, key=lambda record: record["at"])
        }
    return result


@server.tool()
def inspect_latency(case_id: str, service: str, observed_at: int) -> Observation:
    """Read p95 latency for the resolved service at alert time."""
    return response(case_id, service, observed_at, ("p95_ms",))


@server.tool()
def dependency_health(case_id: str, service: str, observed_at: int) -> Observation:
    """Read the connection health of the resolved dependency at alert time."""
    return response(case_id, service, observed_at, ("connection_status",))


@server.tool()
def sample_logs(case_id: str, service: str, observed_at: int) -> Observation:
    """Read an available sampled error log for the resolved service."""
    return response(case_id, service, observed_at, ("log",))


if __name__ == "__main__":
    server.run(transport="stdio")
