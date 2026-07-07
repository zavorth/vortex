"""Simple in-memory rate limiter with JSON persistence."""

import json
import os
import time
from functools import wraps
from threading import Lock

from flask import request, jsonify

_STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'rate_limiter_state.json')
_SYNC_INTERVAL = 30  # seconds between disk syncs


class RateLimiter:
    """Per-IP sliding window rate limiter."""

    def __init__(self, max_requests=60, window_seconds=60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits = {}  # ip -> [timestamps]
        self._lock = Lock()
        self._last_sync = 0.0
        self._load_state()

    def _load_state(self):
        """Load persisted hits from JSON file on startup."""
        try:
            if os.path.exists(_STATE_FILE):
                with open(_STATE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                now = time.time()
                cutoff = now - self.window_seconds
                for ip, timestamps in data.items():
                    valid = [t for t in timestamps if t > cutoff]
                    if valid:
                        self._hits[ip] = valid
        except Exception:
            pass

    def _save_state(self):
        """Persist current hits to JSON file."""
        now = time.time()
        if now - self._last_sync < _SYNC_INTERVAL:
            return
        self._last_sync = now
        try:
            snapshot = {ip: list(ts) for ip, ts in self._hits.items()}
            tmp = _STATE_FILE + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(snapshot, f)
            os.replace(tmp, _STATE_FILE)
        except Exception:
            pass

    def is_allowed(self, ip):
        now = time.time()
        with self._lock:
            if ip not in self._hits:
                self._hits[ip] = []
            cutoff = now - self.window_seconds
            self._hits[ip] = [t for t in self._hits[ip] if t > cutoff]
            if len(self._hits[ip]) >= self.max_requests:
                return False
            self._hits[ip].append(now)
            self._save_state()
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
