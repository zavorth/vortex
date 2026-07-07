"""Extractor for XVideos videos."""

import os
import re
import urllib.parse
import requests
from bs4 import BeautifulSoup
from .base import BaseExtractor


class XVideosExtractor(BaseExtractor):
    """Extracts video from XVideos pages."""

    DOMAINS = ['xvideos.com', 'www.xvideos.com', 'xvideos2.com', 'xvideos3.com', 'xvideos4.com']

    def can_handle(self, url: str) -> bool:
        parsed = urllib.parse.urlparse(url)
        return any(d in parsed.netloc.lower() for d in self.DOMAINS)

    def extract(self, url: str, cookies_path: str = None) -> tuple[list[dict], str]:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        session = requests.Session()
        if cookies_path and os.path.exists(cookies_path):
            try:
                import http.cookiejar
                cj = http.cookiejar.MozillaCookieJar(cookies_path)
                cj.load(ignore_discard=True, ignore_expires=True)
                session.cookies = cj
            except Exception:
                pass

        r = session.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            return [], "XVideos"

        soup = BeautifulSoup(r.text, 'html.parser')
        media_items = []

        # Extract title
        title = None
        h1 = soup.find('h1')
        if h1:
            title = h1.get_text(strip=True)
        if not title:
            og_title = soup.find('meta', property='og:title')
            title = og_title['content'] if og_title else None
        title = title or "XVideos Video"

        # Method 1: XVideos embeds video URL in flashvars within script tags
        scripts = soup.find_all('script')
        for script in scripts:
            if not script.string:
                continue

            # Look for HTML5 video URL
            url_matches = re.findall(r'html5player\.setVideoUrl\([\'"]([^\'"]+)[\'"]\)', script.string)
            for m in url_matches:
                video_url = m.replace('\\u0026', '&').replace('\\/', '/')
                if video_url.startswith('http'):
                    media_items.append({
                        "type": "video",
                        "url": video_url,
                        "thumbnail": "",
                        "filename": self._clean_filename(title) + ".mp4",
                        "source": "XVideos (html5player)"
                    })

            # Also look for video_url in flashvars
            flash_matches = re.findall(r'flashvars\.[a-zA-Z_]+\s*=\s*["\']([^"\']+\.mp4[^"\']*)', script.string)
            for m in flash_matches:
                video_url = m.replace('\\u0026', '&').replace('\\/', '/')
                if video_url.startswith('http') and not any(it['url'] == video_url for it in media_items):
                    media_items.append({
                        "type": "video",
                        "url": video_url,
                        "thumbnail": "",
                        "filename": self._clean_filename(title) + ".mp4",
                        "source": "XVideos (flashvars)"
                    })

        # Method 2: og:video
        if not media_items:
            og_video = soup.find('meta', property='og:video')
            if og_video and og_video.get('content'):
                media_items.append({
                    "type": "video",
                    "url": og_video['content'],
                    "thumbnail": "",
                    "filename": self._clean_filename(title) + ".mp4",
                    "source": "XVideos (og:video)"
                })

        # Method 3: video/source tags
        if not media_items:
            for video in soup.find_all('video'):
                src = video.get('src') or ''
                if not src:
                    source_tag = video.find('source')
                    if source_tag:
                        src = source_tag.get('src', '')
                if src and src.startswith('http'):
                    media_items.append({
                        "type": "video",
                        "url": src,
                        "thumbnail": video.get('poster', ''),
                        "filename": self._clean_filename(title) + ".mp4",
                        "source": "XVideos (HTML5)"
                    })

        # Get thumbnail
        thumb = ""
        og_image = soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            thumb = og_image['content']

        for item in media_items:
            if not item.get('thumbnail'):
                item['thumbnail'] = thumb

        return media_items, title

    def _clean_filename(self, name):
        clean = re.sub(r'[\\/*?:"<>|]', "", name or "video")
        clean = re.sub(r'[^\x00-\x7F]+', '', clean)
        return clean.strip()[:100]
