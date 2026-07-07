"""Simple in-memory rate limiter for Flask routes."""

import time
from functools import wraps
from threading import Lock

from flask import request, jsonify


class RateLimiter:
    """Per-IP sliding window rate limiter."""

    def __init__(self, max_requests=60, window_seconds=60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits = {}  # ip -> [timestamps]
        self._lock = Lock()

    def _cleanup(self, ip):
        now = time.time()
        cutoff = now - self.window_seconds
        self._hits[ip] = [t for t in self._hits[ip] if t > cutoff]
        if not self._hits[ip]:
            del self._hits[ip]

    def is_allowed(self, ip):
        now = time.time()
        with self._lock:
            if ip not in self._hits:
                self._hits[ip] = []
            # Prune expired entries inline (no separate cleanup that deletes the key)
            cutoff = now - self.window_seconds
            self._hits[ip] = [t for t in self._hits[ip] if t > cutoff]
            if len(self._hits[ip]) >= self.max_requests:
                return False
            self._hits[ip].append(now)
            return True


# Global instance: 60 requests per minute per IP
default_limiter = RateLimiter(max_requests=60, window_seconds=60)

# Strict limiter for expensive endpoints (analyze, download): 10 requests per minute
strict_limiter = RateLimiter(max_requests=10, window_seconds=60)


def rate_limit(limiter=None):
    """Decorator to apply rate limiting to a Flask route."""
    if limiter is None:
        limiter = default_limiter

    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            client_ip = request.remote_addr or '127.0.0.1'
            if not limiter.is_allowed(client_ip):
                return jsonify({
                    "error": "Muitas requisições. Aguarde um momento e tente novamente."
                }), 429
            return f(*args, **kwargs)
        return wrapped
    return decorator
