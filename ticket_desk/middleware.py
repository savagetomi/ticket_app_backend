"""Django-wide baseline rate limiting for routes outside DRF."""

import hashlib

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse


class GlobalRateLimitMiddleware:
    """Limit all HTTP routes by a trusted server-observed caller identity.

    DRF throttles supply endpoint-specific limits for the API. This middleware
    is deliberately broader: it also handles admin, documentation, media, and
    malformed bearer-token requests that DRF rejects before its throttles run.
    A shared cache such as Redis makes the counter atomic across workers.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def _identity(request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            return f"user:{user.pk}", settings.GLOBAL_RATE_LIMIT_AUTHENTICATED_REQUESTS

        # Do not trust X-Forwarded-For here. A reverse proxy must overwrite
        # it before the application sees traffic if client IP preservation is
        # required in deployment.
        return f"ip:{request.META.get('REMOTE_ADDR', '')}", settings.GLOBAL_RATE_LIMIT_ANON_REQUESTS

    @staticmethod
    def _increment(key, timeout):
        """Increment a portable cache counter, recovering from expiry races."""
        if cache.add(key, 1, timeout=timeout):
            return 1
        try:
            return cache.incr(key)
        except ValueError:
            # A key can expire after add() fails and before incr(). Retry once.
            if cache.add(key, 1, timeout=timeout):
                return 1
            return cache.incr(key)

    def __call__(self, request):
        identity, limit = self._identity(request)
        window = settings.GLOBAL_RATE_LIMIT_WINDOW_SECONDS
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        count = self._increment(f"global-rate-limit:{digest}", window)

        if count > limit:
            response = JsonResponse(
                {"detail": "Request rate limit exceeded. Please try again later."},
                status=429,
            )
            response["Retry-After"] = str(window)
            return response

        return self.get_response(request)
