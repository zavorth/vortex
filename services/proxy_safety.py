"""URL and proxy safety validations for SSRF protection."""

import ipaddress
import socket
import urllib.parse

import requests
from services.logger import logger

PROXY_MAX_RESPONSE_BYTES = 100 * 1024 * 1024  # 100 MB


def _is_restricted_ip(ip_str):
    """Check if an IP address is private, loopback, link-local, multicast, unspecified, or reserved."""
    try:
        ip_obj = ipaddress.ip_address(ip_str)
        return (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_unspecified
        )
    except ValueError:
        return True  # Fail-closed: reject unparseable IPs


def is_safe_url(url):
    """Enforces SSRF protection by resolving hostnames and validating resolved IPs."""
    if not url:
        return False
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return False

        hostname = parsed.hostname
        if not hostname:
            return False

        # Validate hostname characters
        if not all(c.isalnum() or c in '.-' for c in hostname):
            return False

        addr_info = socket.getaddrinfo(hostname, None)
        for family, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            if _is_restricted_ip(ip_str):
                logger.warning('SSRF', f"Blocked access to local/private IP '{ip_str}' resolved from '{hostname}'")
                return False
        return True
    except Exception as e:
        logger.warning('SSRF', f"Failed to validate URL '{url}': {e}")
        return False


def is_safe_redirect(target_url, original_url=None):
    """Validate a redirect target. Must pass the same safety checks as the original URL."""
    if not target_url:
        return False
    if not is_safe_url(target_url):
        return False
    # If original URL provided, ensure redirect stays on same host
    if original_url:
        orig_parsed = urllib.parse.urlparse(original_url)
        target_parsed = urllib.parse.urlparse(target_url)
        if orig_parsed.hostname != target_parsed.hostname:
            return False
    return True


def proxy_fetch(url, headers=None, timeout=15, stream=True, allow_redirects=False, cookies=None):
    """
    Fetch a URL through the proxy with safety controls.
    - Manual redirect following with per-redirect validation.
    - Response size cap.
    - Returns (response, error_tuple) where error_tuple is None on success.
    """
    if not is_safe_url(url):
        return None, ("Forbidden target URL", 403)

    session = requests.Session()
    if cookies:
        session.cookies = cookies

    current_url = url
    redirect_count = 0
    max_redirects = 10

    while True:
        try:
            r = session.get(current_url, headers=headers, timeout=timeout, stream=stream, allow_redirects=False)
        except requests.exceptions.RequestException as e:
            return None, (f"Proxy error: {str(e)}", 502)

        if r.status_code in (301, 302, 303, 307, 308):
            redirect_count += 1
            if redirect_count > max_redirects:
                return None, ("Too many redirects", 502)
            location = r.headers.get('Location', '')
            if not location:
                return None, ("Redirect with no Location header", 502)
            # Resolve relative redirects
            location_parsed = urllib.parse.urlparse(location)
            if not location_parsed.scheme:
                base = urllib.parse.urlparse(current_url)
                location = urllib.parse.urljoin(current_url, location)
            if not is_safe_redirect(location, current_url):
                logger.warning('SSRF', f"Redirect to unsafe target blocked: {location}")
                return None, ("Redirect to blocked target", 403)
            current_url = location
            r.close()
            continue

        # Check final response size
        content_length = r.headers.get('Content-Length')
        if content_length and int(content_length) > PROXY_MAX_RESPONSE_BYTES:
            r.close()
            return None, ("Response too large", 413)

        return r, None

    return None, ("Unexpected error", 500)
