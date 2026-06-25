"""
Prometheus metrics for the Lot Tracking service.

We define three metrics here, covering the standard "RED" pattern
used for monitoring web services (Rate, Errors, Duration):
  - REQUEST_COUNT (a Counter): total requests, broken down by path
    and status code - lets us compute request RATE and error RATE
  - REQUEST_LATENCY (a Histogram): how long requests take - lets us
    compute DURATION percentiles (e.g. "95% of requests finish under
    200ms")
  - HOLD_EVENTS (a Counter): a domain-specific metric, not a generic
    web-server one - counts how many times a lot has gone on HOLD,
    broken down by reason. This ties directly back to the
    "busy ratio / transaction time" style monitoring.

Counter vs Histogram: a Counter only ever increases (think of it as
an odometer) - Prometheus computes rate-of-change for you on the
query side, you just increment it. A Histogram tracks how many
observations fall into predefined buckets (e.g. how many requests
took 0-50ms, how many took 50-100ms, etc.) - this is what lets
Grafana later draw percentile lines, which a single average number
could never show (an average hides whether most requests are fast
with a few very slow outliers, vs all requests being moderately slow).
"""

import time

from fastapi import FastAPI, Request
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status_code"],
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
)

HOLD_EVENTS = Counter(
    "lot_hold_events_total",
    "Total number of times a lot has entered HOLD state, by reason",
    ["reason"],
)


def setup_metrics(app: FastAPI) -> None:
    """
    Wire up metrics middleware and the /metrics endpoint on the given
    FastAPI app. Called once from main.py at startup.
    """

    @app.middleware("http")
    async def track_requests(request: Request, call_next):
        """
        Middleware runs around EVERY request, regardless of which
        route handles it - this is why we don't need to repeat
        metric-tracking code in each route function individually.
        call_next(request) actually runs the matched route; we just
        wrap it with timing and counting.
        """
        start_time = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start_time

        # request.url.path gives the raw path (e.g. "/lots/LOT-0042"),
        # which would create a separate time series PER LOT ID if used
        # directly - not what we want for aggregate dashboards. Using
        # the route's PATTERN ("/lots/{lot_id}") instead keeps all
        # lots grouped under one series. FastAPI exposes the matched
        # route on request.scope once routing has happened.
        route = request.scope.get("route")
        path_label = route.path if route is not None else request.url.path

        REQUEST_COUNT.labels(
            method=request.method,
            path=path_label,
            status_code=response.status_code,
        ).inc()
        REQUEST_LATENCY.labels(method=request.method, path=path_label).observe(duration)

        return response

    @app.get("/metrics")
    def metrics():
        """
        Prometheus scrapes this endpoint. generate_latest() formats
        all registered metrics (REQUEST_COUNT, REQUEST_LATENCY,
        HOLD_EVENTS, plus some default Python process metrics
        prometheus_client adds automatically) into the plain-text
        format Prometheus expects.
        """
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
