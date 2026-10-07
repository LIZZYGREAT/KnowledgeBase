"""Small HTTP middleware shared by the API application."""

import logging
from time import perf_counter

from fastapi import FastAPI, Request


_API_PREFIX = "/api/"
_SLOW_REQUEST_MS = 100.0
_logger = logging.getLogger("knowledgebase.request_timing")


def install_api_timing(application: FastAPI) -> None:
    """Expose API processing time and log requests that take at least 100 ms."""

    @application.middleware("http")
    async def api_timing(request: Request, call_next):
        started = perf_counter()
        response = await call_next(request)
        duration_ms = (perf_counter() - started) * 1000
        if request.url.path.startswith(_API_PREFIX):
            response.headers["Server-Timing"] = "app;dur={:.1f}".format(duration_ms)
            if duration_ms >= _SLOW_REQUEST_MS:
                route = request.scope.get("route")
                route_path = getattr(route, "path", request.url.path)
                _logger.info(
                    "Slow API request method=%s route=%s status=%s duration_ms=%.1f",
                    request.method,
                    route_path,
                    response.status_code,
                    duration_ms,
                )
        return response
