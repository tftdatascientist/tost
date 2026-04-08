"""OTLP HTTP receiver — lightweight aiohttp server accepting metric exports from Claude Code."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from aiohttp import web

from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
    ExportMetricsServiceResponse,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue

from tost.store import MetricSnapshot

if TYPE_CHECKING:
    from tost.store import Store

log = logging.getLogger("tost.collector")


def _attr_value(attr: KeyValue) -> str | int | float | bool:
    """Extract a scalar value from an OTLP KeyValue."""
    v: AnyValue = attr.value
    if v.HasField("string_value"):
        return v.string_value
    if v.HasField("int_value"):
        return v.int_value
    if v.HasField("double_value"):
        return v.double_value
    if v.HasField("bool_value"):
        return v.bool_value
    return ""


def _attrs_to_dict(attrs: list[KeyValue]) -> dict[str, str | int | float | bool]:
    return {a.key: _attr_value(a) for a in attrs}


def _parse_metrics(body: bytes, store: Store) -> int:
    """Parse ExportMetricsServiceRequest protobuf and write to store.

    Returns the number of data points processed.
    """
    req = ExportMetricsServiceRequest()
    req.ParseFromString(body)

    count = 0
    for rm in req.resource_metrics:
        # Extract session_id from resource attributes
        res_attrs = _attrs_to_dict(rm.resource.attributes)
        session_id = str(res_attrs.get("session.id", "unknown"))

        for sm in rm.scope_metrics:
            # Accumulate per-(session, model) totals from this batch
            # CC sends cumulative counters, so we take the latest value
            accum: dict[str, dict] = {}  # key = model

            for metric in sm.metrics:
                if metric.name == "claude_code.token.usage":
                    for dp in metric.sum.data_points:
                        dp_attrs = _attrs_to_dict(dp.attributes)
                        model = str(dp_attrs.get("model", "unknown"))
                        token_type = str(dp_attrs.get("type", ""))
                        value = int(dp.as_int) if dp.HasField("as_int") else int(dp.as_double)

                        if model not in accum:
                            accum[model] = {
                                "input": 0, "output": 0,
                                "cacheRead": 0, "cacheCreation": 0,
                                "cost": 0.0,
                            }
                        accum[model][token_type] = value

                elif metric.name == "claude_code.cost.usage":
                    for dp in metric.sum.data_points:
                        dp_attrs = _attrs_to_dict(dp.attributes)
                        model = str(dp_attrs.get("model", "unknown"))
                        value = dp.as_double if dp.HasField("as_double") else float(dp.as_int)

                        if model not in accum:
                            accum[model] = {
                                "input": 0, "output": 0,
                                "cacheRead": 0, "cacheCreation": 0,
                                "cost": 0.0,
                            }
                        accum[model]["cost"] = value

            # Write accumulated snapshots to store
            for model, vals in accum.items():
                snap = MetricSnapshot(
                    session_id=session_id,
                    model=model,
                    input_tokens=vals["input"],
                    output_tokens=vals["output"],
                    cache_read_tokens=vals["cacheRead"],
                    cache_creation_tokens=vals["cacheCreation"],
                    cost_usd=vals["cost"],
                )
                store.insert(snap)
                count += 1

    return count


async def handle_metrics(request: web.Request) -> web.Response:
    """Handle POST /v1/metrics."""
    store: Store = request.app["store"]
    body = await request.read()

    try:
        count = _parse_metrics(body, store)
        log.debug("Processed %d metric data points", count)
    except Exception:
        log.exception("Failed to parse OTLP metrics")
        return web.Response(status=400, text="Bad request")

    # Return empty ExportMetricsServiceResponse
    resp = ExportMetricsServiceResponse()
    return web.Response(
        body=resp.SerializeToString(),
        content_type="application/x-protobuf",
    )


def create_app(store: Store, on_data: Callable[[], None] | None = None) -> web.Application:
    """Create the aiohttp OTLP receiver app."""
    app = web.Application()
    app["store"] = store
    app["on_data"] = on_data
    app.router.add_post("/v1/metrics", handle_metrics)
    return app


async def run_collector(store: Store, host: str = "0.0.0.0", port: int = 4318) -> None:
    """Start the OTLP HTTP receiver."""
    app = create_app(store)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    log.info("OTLP collector listening on %s:%d", host, port)
