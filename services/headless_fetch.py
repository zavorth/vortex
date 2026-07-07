"""Headless browser fetching for pages that require JavaScript execution."""

import re
import urllib.parse


def headless_fetch_video_url(url, timeout_ms=15000):
    """
    Use Playwright to load a page and extract video URLs that are
    created dynamically by JavaScript.

    Returns a list of dicts: [{"url": "...", "type": "video"}]
    Returns empty list if Playwright is not installed or fails.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return []

    video_urls = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = context.new_page()

            # Collect network requests that look like media
            captured_media = []

            def on_response(response):
                resp_url = response.url
                ct = response.headers.get('content-type', '').lower()
                # Detect video responses
                if any(t in ct for t in ['video/', 'application/x-mpegurl', 'application/vnd.apple.mpegurl']):
                    captured_media.append({"url": resp_url, "type": "video"})
                # Also capture googlevideo URLs from the page
                if 'googlevideo.com' in resp_url and 'videoplayback' in resp_url:
                    captured_media.append({"url": resp_url, "type": "video"})

            page.on('response', on_response)

            page.goto(url, timeout=timeout_ms, wait_until='networkidle')

            # Also look for <video> and <source> elements created by JS
            video_elements = page.query_selector_all('video, source')
            for el in video_elements:
                src = el.get_attribute('src')
                if src and src.startswith('http'):
                    video_urls.append({"url": src, "type": "video"})

            # Check for video elements with blob URLs ( HLS/DASH players )
            blob_videos = page.query_selector_all('video[src^="blob:"]')
            # Blob URLs can't be downloaded directly, skip them

            # Merge captured network media
            video_urls.extend(captured_media)

            # Deduplicate
            seen = set()
            unique = []
            for item in video_urls:
                if item["url"] not in seen:
                    seen.add(item["url"])
                    unique.append(item)

            browser.close()
            return unique

    except Exception as e:
        print(f"[HeadlessFetcher] Error: {e}")
        return []


def headless_fetch_iframe_video(iframe_url, timeout_ms=15000):
    """
    Load an iframe URL in a headless browser and extract video URLs.
    Intercepts API responses (batchexecute) to capture googlevideo URLs
    from services like Blogger that load video data dynamically.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return []

    video_urls = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = context.new_page()

            # Capture API responses that contain video URLs
            api_bodies = []

            def on_response(response):
                resp_url = response.url
                ct = response.headers.get('content-type', '').lower()
                # Capture batchexecute/datalib API responses (Blogger pattern)
                if 'batchexecute' in resp_url or 'datalib' in resp_url:
                    try:
                        api_bodies.append(response.text())
                    except Exception:
                        pass
                # Direct video content-type
                if any(t in ct for t in ['video/', 'application/x-mpegurl']):
                    api_bodies.append(f'__DIRECT__{resp_url}')

            page.on('response', on_response)
            page.goto(iframe_url, timeout=timeout_ms, wait_until='networkidle')

            # Look for <video> and <source> elements created by JS
            for el in page.query_selector_all('video, source'):
                src = el.get_attribute('src')
                if src and src.startswith('http'):
                    video_urls.append({"url": src, "type": "video"})

            # Parse captured API responses for video URLs
            for body in api_bodies:
                if body.startswith('__DIRECT__'):
                    video_urls.append({"url": body[len('__DIRECT__'):], "type": "video"})
                else:
                    # Extract googlevideo.com/videoplayback URLs
                    found = re.findall(
                        r'https?://[^"\\]+googlevideo\.com/videoplayback[^"\\]*',
                        body
                    )
                    for u in found:
                        u = u.replace('\\u003d', '=').replace('\\u0026', '&')
                        video_urls.append({"url": u, "type": "video"})

            browser.close()

            # Deduplicate
            seen = set()
            unique = []
            for item in video_urls:
                if item["url"] not in seen:
                    seen.add(item["url"])
                    unique.append(item)
            return unique

    except Exception as e:
        print(f"[HeadlessFetcher] iframe error: {e}")
        return []
