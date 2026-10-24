"""Serverless entry point (AWS Lambda / API Gateway proxy style).

``handler(event, context)`` accepts either a direct event ``{"csv": ..., "mapping": ...}`` or an
API Gateway proxy event whose ``body`` is that JSON (optionally base64 encoded). It returns a
proxy-style response with ``statusCode``, ``headers`` and a JSON ``body``.
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any

from . import api
from .errors import DatamoldError, RowError


def _response(status: int, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload),
    }


def _payload(event: Any) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise DatamoldError("event must be a JSON object")
    if "body" not in event:
        return event
    body = event["body"]
    if body is None:
        raise DatamoldError("request body is empty")
    if isinstance(body, str):
        if event.get("isBase64Encoded"):
            try:
                body = base64.b64decode(body, validate=True).decode("utf-8")
            except (binascii.Error, UnicodeDecodeError):
                raise DatamoldError("body is flagged base64 but could not be decoded") from None
        try:
            body = json.loads(body)
        except json.JSONDecodeError as exc:
            raise DatamoldError(f"body is not valid JSON: {exc.msg}") from None
    if not isinstance(body, dict):
        raise DatamoldError("body must be a JSON object")
    return body


def handler(event: Any, context: Any = None) -> dict[str, Any]:
    try:
        args = _payload(event)
        action = args.get("action", "convert")
        if action == "convert":
            return _response(200, api.convert(args))
        if action == "validate":
            return _response(200, api.validate(args))
        if action == "infer":
            return _response(200, api.infer(args))
        raise DatamoldError(f"unknown action {action!r} (use convert, validate or infer)")
    except RowError as exc:
        return _response(422, {"error": str(exc)})
    except DatamoldError as exc:
        return _response(400, {"error": str(exc)})


lambda_handler = handler
