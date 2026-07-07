import re
import os
import requests
import urllib.parse
from bs4 import BeautifulSoup
from .base import BaseExtractor

class EromeExtractor(BaseExtractor):
    """Scraper for Erome albums."""
    
    def can_handle(self, url: str) -> bool:
        return 'erome.com' in url.lower()
        
    def extract(self, url: str, cookies_path: str = None) -> tuple[list[dict], str]:
        # Browser headers matching app.py global headers
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,pt-BR;q=0.8,pt;q=0.7',
            'Connection': 'keep-alive'
        }
        
        try:
            r = requests.get(url, headers=headers, timeout=12)
            if r.status_code != 200:
                print(f"[EromeExtractor] Error fetching page. HTTP {r.status_code}")
                return [], "Erome"
                
            soup = BeautifulSoup(r.text, 'html.parser')
            
            # Fetch album title
            album_title = None
            title_meta = soup.find('meta', property='og:title')
            if title_meta:
                album_title = title_meta['content']
            if not album_title:
                album_title = soup.title.text.strip() if soup.title else "VortexMedia"
                
            album_title = album_title.replace(" - Erome", "").strip()
            # Clean filename-unsafe characters
            album_title = re.sub(r'[\\/*?:"<>|]', "", album_title).strip()[:100]
            
            # Enforce search inside the album container only
            search_root = soup
            album_container = soup.find(id=lambda x: x and x.startswith('album_'))
            if album_container:
                search_root = album_container
                
            media_items = []
            media_counter = 0
            
            # 1. Extract HTML5 video tags
            videos = search_root.find_all('video')
            for video in videos:
                sources = video.find_all('source')
                video_url = None
                if sources:
                    for s in sources:
                        if s.get('src'):
                            video_url = s.get('src')
                            break
                elif video.get('src'):
                    video_url = video.get('src')
                    
                if video_url:
                    video_url = urllib.parse.urljoin(url, video_url)
                    filename = os.path.basename(urllib.parse.urlparse(video_url).path) or f"video_{media_counter}.mp4"
                    filename = re.sub(r'[\\/*?:"<>|]', "", filename).strip()[:100]
                    
                    poster = video.get('poster')
                    if poster:
                        poster = urllib.parse.urljoin(url, poster)
                    else:
                        poster = "/static/video-placeholder.png"
                        
                    media_items.append({
                        "id": f"media_{media_counter}",
                        "type": "video",
                        "url": video_url,
                        "thumbnail": poster,
                        "filename": filename,
                        "source": "HTML5 Video"
                    })
                    media_counter += 1
                    
            # 2. Extract Images (enforcing high-res album checks)
            images = search_root.find_all('img')
            for img in images:
                src = img.get('data-src') or img.get('src')
                if not src:
                    continue
                    
                img_classes = img.get('class', [])
                parent_classes = img.parent.get('class', []) if img.parent else []
                
                is_album_media = 'img-back' in img_classes or 'img-back' in parent_classes
                if is_album_media:
                    img_url = urllib.parse.urljoin(url, src)
                    filename = os.path.basename(urllib.parse.urlparse(img_url).path) or f"image_{media_counter}.jpg"
                    
                    ext = filename.split('.')[-1].lower() if '.' in filename else ""
                    if ext not in ['jpg', 'jpeg', 'png', 'webp', 'gif', 'avif', 'svg']:
                        filename += ".jpg"
                        
                    filename = re.sub(r'[\\/*?:"<>|]', "", filename).strip()[:100]
                    
                    media_items.append({
                        "id": f"media_{media_counter}",
                        "type": "image",
                        "url": img_url,
                        "thumbnail": img_url,
                        "filename": filename,
                        "source": "Web Image"
                    })
                    media_counter += 1
                    
            return media_items, album_title
            
        except Exception as e:
            print(f"[EromeExtractor] Scraper failed: {e}")
            
        return [], "Erome"
