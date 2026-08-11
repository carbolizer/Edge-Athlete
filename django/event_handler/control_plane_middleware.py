"""Apply the hosted Rack wire envelope before DRF dispatches route handlers."""
import json

from django.http import JsonResponse


CONTROL_PREFIXES = (
    "/api/rack/v1/",
    "/api/rack-helper/v1/",
    "/api/coach/v1/rack-endpoint-pairings/",
    "/api/coach/v1/rack-helper-pairings/",
)


class ControlPlaneWireMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        scoped = request.path.startswith(CONTROL_PREFIXES)
        if scoped and request.method == "POST":
            if request.content_type != "application/json" or not request.body:
                response = JsonResponse(
                    {"code": "invalid_request", "detail": "The request body is invalid."},
                    status=400,
                )
                response["Cache-Control"] = "no-store"
                return response
        response = self.get_response(request)
        if scoped:
            if response.status_code == 400 and not self._has_error_code(response):
                response = JsonResponse(
                    {"code": "invalid_json", "detail": "The JSON body is malformed."},
                    status=400,
                )
            response["Cache-Control"] = "no-store"
        return response

    @staticmethod
    def _has_error_code(response):
        try:
            body = json.loads(response.content)
        except (TypeError, ValueError, UnicodeDecodeError):
            return False
        return isinstance(body, dict) and isinstance(body.get("code"), str)
