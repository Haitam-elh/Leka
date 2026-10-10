"""LEKA's metrics, as Prometheus reads them (LEKA-408).

Two kinds:
- what this API process served — requests by route and status class, how
  long they took — counted as they happen (`observe_request`), in memory;
- how the whole system stands — jobs, queues, connectors, processing, AI,
  actions, circuit breakers — read from the database and Redis when the
  metrics are asked for (repository.py).

The text format, written by hand: a dozen families do not need a client
library, and nothing here holds a lock a request would wait on.

A route is its template (`/api/v1/sources/{source_id}`), never the path
asked: one series per route, not one per id — and no id leaves here.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping

from leka.ops.repository import Snapshot

# Seconds: the buckets a request's duration falls in.
BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)

_requests: dict[tuple[str, str, str], int] = defaultdict(int)
_durations: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0] * (len(BUCKETS) + 1))
_duration_sums: dict[tuple[str, str], float] = defaultdict(float)


def observe_request(method: str, route: str, status: int, seconds: float) -> None:
    """One request served: counted, and how long it took."""
    _requests[(method, route, f"{status // 100}xx")] += 1
    counts = _durations[(method, route)]
    for i, bound in enumerate(BUCKETS):
        if seconds <= bound:
            counts[i] += 1
    counts[-1] += 1
    _duration_sums[(method, route)] += seconds


def reset() -> None:
    """For the tests."""
    _requests.clear()
    _durations.clear()
    _duration_sums.clear()


def _labels(**labels: object) -> str:
    said = ",".join(
        f'{k}="{str(v).replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"'
        for k, v in labels.items()
    )
    return f"{{{said}}}" if said else ""


def _family(
    name: str, kind: str, help_: str, samples: Iterable[tuple[Mapping[str, object], float]]
) -> list[str]:
    lines = [f"# HELP {name} {help_}", f"# TYPE {name} {kind}"]
    lines += [f"{name}{_labels(**labels)} {value:g}" for labels, value in samples]
    return lines


_UUID = re.compile(r":?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def circuits(snap: Snapshot) -> dict[str, int]:
    """Open breakers counted by kind — `model:google:leka`,
    `action_endpoint` — a workspace's or an endpoint's id left out."""
    counts: dict[str, int] = defaultdict(int)
    for name, state in snap.breakers.items():
        counts[_UUID.sub("", name)] += 1 if state == "open" else 0
    return dict(counts)


def render(snap: Snapshot) -> str:
    """Every metric, in the Prometheus text format."""
    lines: list[str] = []
    lines += _family("leka_up", "gauge", "The API answers.", [({}, 1)])
    lines += _family(
        "leka_http_requests_total",
        "counter",
        "Requests this API process served, by route template and status class.",
        [({"method": m, "route": r, "status": s}, n) for (m, r, s), n in sorted(_requests.items())],
    )
    histogram = [
        "# HELP leka_http_request_duration_seconds How long requests took.",
        "# TYPE leka_http_request_duration_seconds histogram",
    ]
    for (method, route), counts in sorted(_durations.items()):
        for bound, count in zip((*map(str, BUCKETS), "+Inf"), counts, strict=True):
            histogram.append(
                "leka_http_request_duration_seconds_bucket"
                f"{_labels(method=method, route=route, le=bound)} {count}"
            )
        histogram.append(
            f"leka_http_request_duration_seconds_sum{_labels(method=method, route=route)}"
            f" {_duration_sums[(method, route)]:g}"
        )
        histogram.append(
            f"leka_http_request_duration_seconds_count{_labels(method=method, route=route)}"
            f" {counts[-1]}"
        )
    lines += histogram
    lines += _family(
        "leka_jobs",
        "gauge",
        "Background jobs in a live state.",
        [({"status": s}, n) for s, n in sorted(snap.jobs.items())],
    )
    lines += _family(
        "leka_jobs_failed_1h", "gauge", "Jobs failed in the last hour.", [({}, snap.jobs_failed_1h)]
    )
    if snap.oldest_waiting_seconds is not None:
        lines += _family(
            "leka_job_oldest_waiting_seconds",
            "gauge",
            "How long the oldest queued job has waited.",
            [({}, snap.oldest_waiting_seconds)],
        )
    if snap.last_job_finished_seconds is not None:
        lines += _family(
            "leka_worker_last_finished_seconds",
            "gauge",
            "Since a worker last finished a job.",
            [({}, snap.last_job_finished_seconds)],
        )
    if snap.last_scheduled_seconds is not None:
        lines += _family(
            "leka_scheduler_last_scheduled_seconds",
            "gauge",
            "Since the scheduler last put a sweep on the queue.",
            [({}, snap.last_scheduled_seconds)],
        )
    lines += _family(
        "leka_queue_depth",
        "gauge",
        "Jobs waiting in each queue.",
        [({"queue": q}, n) for q, n in snap.queue_depth.items()],
    )
    lines += _family(
        "leka_sources",
        "gauge",
        "Sources by status and health.",
        [({"status": s, "health": h}, n) for (s, h), n in sorted(snap.sources.items())],
    )
    lines += _family(
        "leka_syncs_failing",
        "gauge",
        "Source capabilities failing to sync.",
        [({}, snap.syncs_failing)],
    )
    lines += _family(
        "leka_sync_runs_failed_1h",
        "gauge",
        "Sync passes failed or abandoned in the last hour.",
        [({}, snap.sync_runs_failed_1h)],
    )
    lines += _family(
        "leka_processing_runs_1h",
        "gauge",
        "Processing stage runs in the last hour, and those failed.",
        [
            ({"outcome": "all"}, snap.processing_runs_1h),
            ({"outcome": "failed"}, snap.processing_failed_1h),
        ],
    )
    lines += _family(
        "leka_model_calls_1h",
        "gauge",
        "Model calls in the last hour, by provider and outcome.",
        [({"provider": p, "outcome": o}, n) for (p, o), n in sorted(snap.model_calls_1h.items())],
    )
    lines += _family(
        "leka_model_latency_ms_1h",
        "gauge",
        "Mean latency of answered model calls in the last hour.",
        [({"provider": p}, v) for p, v in sorted(snap.model_latency_ms_1h.items())],
    )
    lines += _family(
        "leka_model_cost_usd_24h",
        "gauge",
        "What model calls cost in the last day.",
        [({}, snap.model_cost_usd_24h)],
    )
    lines += _family(
        "leka_agent_runs",
        "gauge",
        "Agent runs in a live state.",
        [({"status": s}, n) for s, n in sorted(snap.agent_runs.items())],
    )
    lines += _family(
        "leka_workflow_runs",
        "gauge",
        "Workflow runs in a live state.",
        [({"status": s}, n) for s, n in sorted(snap.workflow_runs.items())],
    )
    lines += _family(
        "leka_runs_failed_1h",
        "gauge",
        "Agent and workflow runs failed in the last hour.",
        [
            ({"kind": "agent"}, snap.agent_runs_failed_1h),
            ({"kind": "workflow"}, snap.workflow_runs_failed_1h),
        ],
    )
    lines += _family(
        "leka_action_steps_1h",
        "gauge",
        "Actions LEKA ran on customers' systems in the last hour, by outcome.",
        [({"outcome": o}, n) for o, n in sorted(snap.action_steps_1h.items())],
    )
    lines += _family(
        "leka_circuits_open",
        "gauge",
        "Circuit breakers open now, by kind of dependency.",
        [({"kind": k}, n) for k, n in sorted(circuits(snap).items())],
    )
    lines += _family(
        "leka_metrics_unreadable",
        "gauge",
        "Parts of the system the metrics could not read.",
        [({"part": p}, 1) for p in snap.unreadable],
    )
    return "\n".join(lines) + "\n"
