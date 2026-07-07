"""Page-wide media extraction — finds ALL media on a page."""

import os
import re
import urllib.parse
import requests
from bs4 import BeautifulSoup
from services.logger import logger


def extract_all_media(url, cookies_path=None, timeout=15):
    """
    Extract ALL media (images, videos, audio) from a page.
    Returns a list of media items with metadata.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
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

    try:
        r = session.get(url, headers=headers, timeout=timeout)
        if r.status_code != 200:
            return []
    except Exception as e:
        logger.error('PAGE_EXTRACT', f"Failed to fetch page: {e}")
        return []

    soup = BeautifulSoup(r.text, 'html.parser')
    base_url = url
    media_items = []
    seen_urls = set()

    # 1. Extract from <video> and <source> tags
    for video in soup.find_all('video'):
        poster = video.get('poster', '')
        for source in video.find_all('source'):
            src = source.get('src')
            if src:
                full_url = urllib.parse.urljoin(base_url, src)
                if full_url not in seen_urls:
                    seen_urls.add(full_url)
                    ext = os.path.splitext(urllib.parse.urlparse(full_url).path)[1] or '.mp4'
                    media_items.append({
                        'url': full_url,
                        'type': 'video',
                        'filename': os.path.basename(urllib.parse.urlparse(full_url).path) or f'video_{len(media_items)}{ext}',
                        'thumbnail': urllib.parse.urljoin(base_url, poster) if poster else '',
                        'source': 'HTML5 Video'
                    })
        # Also check video src directly
        src = video.get('src')
        if src and src.startswith('http'):
            if src not in seen_urls:
                seen_urls.add(src)
                media_items.append({
                    'url': src,
                    'type': 'video',
                    'filename': os.path.basename(urllib.parse.urlparse(src).path) or f'video_{len(media_items)}.mp4',
                    'thumbnail': urllib.parse.urljoin(base_url, poster) if poster else '',
                    'source': 'HTML5 Video'
                })

    # 2. Extract from <audio> and <source> tags
    for audio in soup.find_all('audio'):
        for source in audio.find_all('source'):
            src = source.get('src')
            if src:
                full_url = urllib.parse.urljoin(base_url, src)
                if full_url not in seen_urls:
                    seen_urls.add(full_url)
                    ext = os.path.splitext(urllib.parse.urlparse(full_url).path)[1] or '.mp3'
                    media_items.append({
                        'url': full_url,
                        'type': 'audio',
                        'filename': os.path.basename(urllib.parse.urlparse(full_url).path) or f'audio_{len(media_items)}{ext}',
                        'thumbnail': '',
                        'source': 'HTML5 Audio'
                    })

    # 3. Extract from <img> tags
    for img in soup.find_all('img'):
        src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
        if not src or src.startswith('data:'):
            continue
        full_url = urllib.parse.urljoin(base_url, src)
        if full_url not in seen_urls:
            # Filter out tiny tracking pixels and icons
            width = img.get('width', '')
            height = img.get('height', '')
            if width and width.isdigit() and int(width) < 50:
                continue
            if height and height.isdigit() and int(height) < 50:
                continue

            ext = os.path.splitext(urllib.parse.urlparse(full_url).path)[1] or '.jpg'
            if ext.lower() in ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.avif', '.svg'):
                seen_urls.add(full_url)
                media_items.append({
                    'url': full_url,
                    'type': 'image',
                    'filename': os.path.basename(urllib.parse.urlparse(full_url).path) or f'image_{len(media_items)}{ext}',
                    'thumbnail': full_url,
                    'source': 'HTML Image'
                })

    # 4. Extract from <a> tags (direct file links)
    file_extensions = {
        '.mp4', '.webm', '.mkv', '.avi', '.mov', '.flv',  # video
        '.mp3', '.wav', '.flac', '.ogg', '.aac',  # audio
        '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.avif',  # image
        '.pdf', '.zip', '.rar', '.7z',  # documents
    }
    for a in soup.find_all('a'):
        href = a.get('href')
        if not href or href.startswith('#') or href.startswith('javascript:'):
            continue
        full_url = urllib.parse.urljoin(base_url, href)
        path = urllib.parse.urlparse(full_url).path.lower()
        ext = os.path.splitext(path)[1]
        if ext in file_extensions and full_url not in seen_urls:
            seen_urls.add(full_url)
            filename = os.path.basename(urllib.parse.urlparse(full_url).path)
            if ext in ('.mp4', '.webm', '.mkv', '.avi', '.mov', '.flv'):
                mtype = 'video'
            elif ext in ('.mp3', '.wav', '.flac', '.ogg', '.aac'):
                mtype = 'audio'
            elif ext in ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.avif'):
                mtype = 'image'
            else:
                mtype = 'document'
            media_items.append({
                'url': full_url,
                'type': mtype,
                'filename': filename,
                'thumbnail': '',
                'source': 'Direct Link'
            })

    # 5. Extract from <meta> tags
    for meta in soup.find_all('meta'):
        prop = meta.get('property', '').lower()
        content = meta.get('content', '')
        if not content or not content.startswith('http'):
            continue
        if prop in ('og:video', 'og:video:url') and content not in seen_urls:
            seen_urls.add(content)
            media_items.append({
                'url': content,
                'type': 'video',
                'filename': os.path.basename(urllib.parse.urlparse(content).path) or f'video_{len(media_items)}.mp4',
                'thumbnail': '',
                'source': 'og:video'
            })
        elif prop in ('og:image', 'og:image:url') and content not in seen_urls:
            seen_urls.add(content)
            media_items.append({
                'url': content,
                'type': 'image',
                'filename': os.path.basename(urllib.parse.urlparse(content).path) or f'image_{len(media_items)}.jpg',
                'thumbnail': content,
                'source': 'og:image'
            })

    # 6. Extract from JavaScript arrays (manga-style pages)
    for script in soup.find_all('script'):
        if not script.string:
            continue
        array_matches = re.findall(r'(?:var|let|const)\s+\w+\s*=\s*\[(.*?)\]', script.string, re.DOTALL)
        for match in array_matches:
            urls = re.findall(r'["\']([^"\']+)["\']', match)
            for u in urls:
                u = u.strip()
                if not u or not u.startswith('http'):
                    continue
                u_lower = u.lower().split('?')[0]
                ext = u_lower.rsplit('.', 1)[-1] if '.' in u_lower else ''
                if ext in ('jpg', 'jpeg', 'png', 'gif', 'webp'):
                    mtype = 'image'
                elif ext in ('mp4', 'm3u8', 'webm'):
                    mtype = 'video'
                else:
                    continue
                if u not in seen_urls:
                    seen_urls.add(u)
                    filename = os.path.basename(urllib.parse.urlparse(u).path).split('?')[0]
                    media_items.append({
                        'url': u,
                        'type': mtype,
                        'filename': filename or f'{mtype}_{len(media_items)}.{ext}',
                        'thumbnail': u if mtype == 'image' else '',
                        'source': 'JavaScript Array'
                    })

    logger.info('PAGE_EXTRACT', f"Found {len(media_items)} media items on {url[:60]}...")
    return media_items
