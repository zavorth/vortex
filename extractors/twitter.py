import re
import math
import requests
import urllib.parse
from .base import BaseExtractor

class TwitterExtractor(BaseExtractor):
    """Extractor for Twitter/X URLs using direct API fetches."""
    
    def can_handle(self, url: str) -> bool:
        return any(domain in url.lower() for domain in ['x.com', 'twitter.com'])
        
    def extract(self, url: str, cookies_path: str = None) -> tuple[list[dict], str]:
        tweet_id = self._extract_tweet_id(url)
        if not tweet_id:
            return [], "Twitter"
            
        print(f"[TwitterExtractor] Attempting direct API extraction for Tweet ID: {tweet_id}")
        
        # Method 1: Syndication API
        media_items, title = self._extract_syndication(tweet_id)
        if media_items:
            return media_items, title
            
        # Method 2: FxTwitter API Fallback
        media_items, title = self._extract_fxtwitter(tweet_id)
        if media_items:
            return media_items, title
            
        return [], "Twitter"
        
    def _extract_tweet_id(self, url: str) -> str:
        match = re.search(r'/status(?:es)?/(\d+)', url)
        if match:
            return match.group(1)
        if url.strip().isdigit():
            return url.strip()
        return None

    def _calc_syndication_token(self, tweet_id: str) -> str:
        try:
            num = int(tweet_id)
            raw = (num / 1e15) * math.pi
            chars = '0123456789abcdefghijklmnopqrstuvwxyz'
            int_part = int(raw)
            frac = raw - int_part
            result = ''
            if int_part == 0:
                result = '0'
            else:
                n = int_part
                while n > 0:
                    result = chars[n % 36] + result
                    n //= 36
            if frac > 0:
                result += '.'
                for _ in range(15):
                    frac *= 36
                    d = int(frac)
                    result += chars[d]
                    frac -= d
                    if frac < 1e-10:
                        break
            result = result.replace('.', '')
            result = re.sub(r'^0+', '', result)
            result = re.sub(r'0+$', '', result)
            return result
        except Exception:
            return ""

    def _extract_syndication(self, tweet_id: str) -> tuple[list[dict], str]:
        token = self._calc_syndication_token(tweet_id)
        url = f'https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&lang=en&token={token}'
        try:
            r = requests.get(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': '*/*',
            }, timeout=8)
            if r.status_code == 200:
                data = r.json()
                items = []
                text = data.get("text", "")
                title = text[:50].strip() or f"Twitter_{tweet_id}"
                
                media_details = data.get('mediaDetails', [])
                for idx, media in enumerate(media_details):
                    m_type = media.get('type')
                    thumbnail = media.get('media_url_https', '/static/video-placeholder.png')
                    
                    if m_type == 'video' or m_type == 'animated_gif':
                        video_info = media.get('video_info', {})
                        variants = video_info.get('variants', [])
                        best_url = None
                        best_bitrate = -1
                        for variant in variants:
                            if variant.get('content_type') == 'video/mp4':
                                bitrate = variant.get('bitrate', 0)
                                if bitrate > best_bitrate:
                                    best_bitrate = bitrate
                                    best_url = variant.get('url')
                        
                        if best_url:
                            clean_url = best_url.split('?')[0] if '?' in best_url else best_url
                            ext = clean_url.split('.')[-1].lower() if '.' in clean_url else 'mp4'
                            filename = f"twitter_{tweet_id}_{idx}.{ext}"
                            items.append({
                                "type": "video",
                                "url": best_url,
                                "thumbnail": thumbnail,
                                "filename": filename,
                                "source": "Twitter API (Syndication)"
                            })
                    elif m_type == 'photo':
                        photo_url = media.get('media_url_https')
                        if photo_url:
                            clean_url = photo_url.split('?')[0] if '?' in photo_url else photo_url
                            ext = clean_url.split('.')[-1].lower() if '.' in clean_url else 'jpg'
                            filename = f"twitter_{tweet_id}_{idx}.{ext}"
                            items.append({
                                "type": "image",
                                "url": photo_url,
                                "thumbnail": photo_url,
                                "filename": filename,
                                "source": "Twitter API (Image)"
                            })
                return items, title
        except Exception as e:
            print(f"[TwitterExtractor] Error fetching from Twitter Syndication: {e}")
        return None, None

    def _extract_fxtwitter(self, tweet_id: str) -> tuple[list[dict], str]:
        url = f'https://api.fxtwitter.com/status/{tweet_id}'
        try:
            r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=8)
            if r.status_code == 200:
                data = r.json()
                tweet = data.get('tweet', {})
                text = tweet.get('text', '')
                title = text[:50].strip() or f"Twitter_{tweet_id}"
                media = tweet.get('media', {})
                items = []
                
                for idx, video in enumerate(media.get('videos', [])):
                    video_url = video.get('url')
                    if video_url:
                        thumbnail = video.get('thumbnail_url', '/static/video-placeholder.png')
                        clean_url = video_url.split('?')[0] if '?' in video_url else video_url
                        ext = clean_url.split('.')[-1].lower() if '.' in clean_url else 'mp4'
                        filename = f"twitter_{tweet_id}_video_{idx}.{ext}"
                        items.append({
                            "type": "video",
                            "url": video_url,
                            "thumbnail": thumbnail,
                            "filename": filename,
                            "source": "FxTwitter API"
                        })
                
                for idx, photo in enumerate(media.get('photos', [])):
                    photo_url = photo.get('url')
                    if photo_url:
                        clean_url = photo_url.split('?')[0] if '?' in photo_url else photo_url
                        ext = clean_url.split('.')[-1].lower() if '.' in clean_url else 'jpg'
                        filename = f"twitter_{tweet_id}_photo_{idx}.{ext}"
                        items.append({
                            "type": "image",
                            "url": photo_url,
                            "thumbnail": photo_url,
                            "filename": filename,
                            "source": "FxTwitter API (Image)"
                        })
                return items, title
        except Exception as e:
            print(f"[TwitterExtractor] Error fetching from FxTwitter: {e}")
        return None, None
