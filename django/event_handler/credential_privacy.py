"""Keep account secrets out of caches and Django exception reports."""
from django.views.debug import SafeExceptionReporterFilter


class CredentialExceptionFilter(SafeExceptionReporterFilter):
    def get_traceback_frame_variables(self, request, tb_frame):
        # DRF JSON lives in frame locals rather than request.POST. Suppress all
        # frame values for these requests, including serializer/request objects.
        return [('locals', '[redacted credential request]')]

    def get_post_parameters(self, request):
        return {key: '[redacted]' for key in request.POST}


class CredentialPrivacyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        sensitive = request.path.startswith(('/api/auth/', '/api/coaches/')) or (
            request.path.rstrip('/') == '/api/system/wifi-password')
        if sensitive:
            request.sensitive_post_parameters = '__ALL__'
            request.exception_reporter_filter = CredentialExceptionFilter()
        response = self.get_response(request)
        if sensitive:
            response['Cache-Control'] = 'private, no-store'
        return response
