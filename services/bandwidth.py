"""Bandwidth limiter for downloads."""

import time
from threading import Lock


class BandwidthLimiter:
    """Token bucket rate limiter for download speed control."""

    def __init__(self, max_bytes_per_second=0):
        """
        Args:
            max_bytes_per_second: 0 = unlimited, otherwise bytes/sec limit
        """
        self.max_bps = max_bytes_per_second
        self.tokens = max_bytes_per_second if max_bytes_per_second > 0 else float('inf')
        self.last_refill = time.time()
        self.lock = Lock()

    def set_limit(self, max_bytes_per_second):
        """Update the bandwidth limit."""
        with self.lock:
            self.max_bps = max_bytes_per_second
            self.tokens = max_bytes_per_second if max_bytes_per_second > 0 else float('inf')

    def consume(self, num_bytes):
        """Consume tokens for num_bytes. Blocks if necessary to stay under limit."""
        if self.max_bps <= 0:
            return  # Unlimited

        with self.lock:
            now = time.time()
            elapsed = now - self.last_refill
            self.tokens = min(self.max_bps, self.tokens + elapsed * self.max_bps)
            self.last_refill = now

            if self.tokens >= num_bytes:
                self.tokens -= num_bytes
                return

            # Need to wait
            wait_time = (num_bytes - self.tokens) / self.max_bps
            self.tokens = 0

        time.sleep(wait_time)

    @staticmethod
    def format_speed(bytes_per_sec):
        """Format bytes/sec to human-readable string."""
        if bytes_per_sec <= 0:
            return "Ilimitado"
        if bytes_per_sec >= 1024 * 1024:
            return f"{bytes_per_sec / (1024 * 1024):.1f} MB/s"
        return f"{bytes_per_sec / 1024:.0f} KB/s"


# Global limiter instance
bandwidth_limiter = BandwidthLimiter()
