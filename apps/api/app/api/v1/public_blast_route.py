"""Keep capability-bearing BLAST responses (including failures) out of caches."""

from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from ...core.exceptions import (
    SoyMutDBError,
    http_exception_handler,
    soy_mut_db_exception_handler,
    validation_exception_handler,
)


class PublicBlastRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def private_handler(request: Request):
            try:
                response = await handler(request)
            except SoyMutDBError as exc:
                response = await soy_mut_db_exception_handler(request, exc)
            except RequestValidationError as exc:
                response = await validation_exception_handler(request, exc)
            except HTTPException as exc:
                response = await http_exception_handler(request, exc)
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["Vary"] = "X-Blast-Token"
            return response

        return private_handler
