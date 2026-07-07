import os
import re
import urllib.parse
import requests
from bs4 import BeautifulSoup
import yt_dlp
from .base import BaseExtractor
from services.headless_fetch import headless_fetch_video_url, headless_fetch_iframe_video

class GenericExtractor(BaseExtractor):
    """Fallback extractor using yt-dlp and general HTML parsing."""
    
    def can_handle(self, url: str) -> bool:
        # Fallback can handle anything
        return True
        
    def extract(self, url: str, cookies_path: str = None) -> tuple[list[dict], str]:
        media_items = []
        seen_filenames = set()
        media_counter = 0
        
        # 1. Run yt-dlp
        ytdl_media, ytdl_title = self._extract_yt_dlp_media(url, cookies_path)
        for item in ytdl_media:
            item["id"] = f"media_{media_counter}"
            seen_filenames.add(item["filename"])
            media_items.append(item)
            media_counter += 1
            
        # If yt-dlp successfully extracted media for a known video or social platform,
        # return early to prevent BeautifulSoup from scraping hundreds of recommended videos/ads thumbnails.
        is_video_social = any(domain in url.lower() for domain in [
            'pornhub.com', 'youtube.com', 'youtu.be', 'xvideos.com', 'xnxx.com',
            'twitter.com', 'x.com', 'instagram.com', 'tiktok.com', 'threads.net',
            'spankbang.com', 'redtube.com', 'youporn.com', 'xhamster.com',
            'erome.com', 'vimeo.com', 'dailymotion.com'
        ])
        if is_video_social and media_items:
            clean_title = ytdl_title or "Mídias de Streaming"
            return media_items, clean_title
            
        # 2. General HTML Parsing fallback
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,pt-BR;q=0.8,pt;q=0.7',
            'Connection': 'keep-alive'
        }
        
        try:
            r = requests.get(url, headers=headers, timeout=12)
            if r.status_code != 200:
                if media_items:
                    return media_items, "Mídias de Streaming"
                return [], "Generic Webpage"
                
            soup = BeautifulSoup(r.text, 'html.parser')
            return self._extract_from_soup(soup, url, media_counter, seen_filenames, media_items)
            
        except Exception as e:
            print(f"[GenericExtractor] General parsing failed: {e}")
            if media_items:
                return media_items, "Mídias de Streaming"
                
        return [], "Generic Webpage"
        
    def extract_html(self, html: str, base_url: str = "") -> tuple[list[dict], str]:
        soup = BeautifulSoup(html, 'html.parser')
        media_items = []
        seen_filenames = set()
        media_counter = 0
        try:
            return self._extract_from_soup(soup, base_url, media_counter, seen_filenames, media_items)
        except Exception as e:
            print(f"[GenericExtractor] HTML parsing failed: {e}")
            return [], "Local HTML"

    def _extract_from_soup(self, soup, url, media_counter, seen_filenames, media_items):
        # Fetch page title
        album_title = None
        title_meta = soup.find('meta', property='og:title')
        if title_meta:
            album_title = title_meta['content']
        if not album_title:
            album_title = soup.title.text.strip() if soup.title else "VortexMedia"

        album_title = re.sub(r'[\\/*?:"<>|]', "", album_title).strip()[:100]

        # 2.1. Extract HTML5 video tags
        videos = soup.find_all('video')
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

                if filename not in seen_filenames:
                    seen_filenames.add(filename)
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

        # 2.2. Extract HTML5 audio tags
        audios = soup.find_all('audio')
        for audio in audios:
            sources = audio.find_all('source')
            audio_url = None
            if sources:
                for s in sources:
                    if s.get('src'):
                        audio_url = s.get('src')
                        break
            elif audio.get('src'):
                audio_url = audio.get('src')

            if audio_url:
                audio_url = urllib.parse.urljoin(url, audio_url)
                filename = os.path.basename(urllib.parse.urlparse(audio_url).path) or f"audio_{media_counter}.mp3"
                filename = re.sub(r'[\\/*?:"<>|]', "", filename).strip()[:100]

                if filename not in seen_filenames:
                    seen_filenames.add(filename)
                    media_items.append({
                        "id": f"media_{media_counter}",
                        "type": "audio",
                        "url": audio_url,
                        "thumbnail": "/static/video-placeholder.png",
                        "filename": filename,
                        "source": "HTML5 Audio"
                    })
                    media_counter += 1

        # 2.3. Extract Image tags
        images = soup.find_all('img')
        for img in images:
            # Try to extract from srcset first to get the highest resolution
            srcset = img.get('data-srcset') or img.get('srcset')
            best_src = None
            if srcset:
                parts = [p.strip().split() for p in srcset.split(',') if p.strip()]
                max_w = -1
                for p in parts:
                    if len(p) >= 1:
                        curr_url = p[0]
                        curr_w = 0
                        if len(p) >= 2:
                            w_str = p[1].lower()
                            if w_str.endswith('w'):
                                try:
                                    curr_w = int(w_str[:-1])
                                except ValueError:
                                    pass
                            elif w_str.endswith('x'):
                                try:
                                    curr_w = int(float(w_str[:-1]) * 1000)
                                except ValueError:
                                    pass
                        if curr_w > max_w:
                            max_w = curr_w
                            best_src = curr_url

            src = best_src or img.get('data-src') or img.get('src')
            if not src:
                continue

            # Generic filter for generic layout elements
            if not any(kw in src.lower() for kw in ['avatar', 'logo', 'icon', 'button', 'sprite', 'banner', 'ad-', 'header', 'footer', 'nav', 'menu', 'favicon', 'user']):
                img_url = urllib.parse.urljoin(url, src)

                # Clean WordPress/CMS image resize suffixes (e.g., -300x200.jpg -> .jpg) to download original sizes
                img_url = re.sub(r'-\d+x\d+(\.[a-zA-Z0-9]+)$', r'\1', img_url)

                filename = os.path.basename(urllib.parse.urlparse(img_url).path) or f"image_{media_counter}.jpg"

                ext = filename.split('.')[-1].lower() if '.' in filename else ""
                if ext not in ['jpg', 'jpeg', 'png', 'webp', 'gif', 'avif', 'svg']:
                    filename += ".jpg"

                filename = re.sub(r'[\\/*?:"<>|]', "", filename).strip()[:100]

                if filename not in seen_filenames:
                    seen_filenames.add(filename)
                    media_items.append({
                        "id": f"media_{media_counter}",
                        "type": "image",
                        "url": img_url,
                        "thumbnail": img_url,
                        "filename": filename,
                        "source": "Web Image"
                    })
                    media_counter += 1

        # 2.4. Extract Document/Compressed files from anchor tags
        anchors = soup.find_all('a')
        file_extensions = {
            'pdf', 'zip', 'rar', '7z', 'tar', 'gz', 'bz2', 'xz',
            'exe', 'msi', 'dmg', 'pkg', 'apk', 'iso',
            'docx', 'xlsx', 'pptx', 'epub', 'pub', 'mobi', 'azw3', 'txt', 'csv'
        }
        for a in anchors:
            href = a.get('href')
            if not href:
                continue

            file_url = urllib.parse.urljoin(url, href)
            parsed_path = urllib.parse.urlparse(file_url).path
            filename = os.path.basename(parsed_path)

            if '.' in filename:
                ext = filename.split('.')[-1].lower()
                if ext in file_extensions:
                    filename = re.sub(r'[\\/*?:"<>|]', "", filename).strip()[:100]
                    if filename not in seen_filenames:
                        seen_filenames.add(filename)
                        media_items.append({
                            "id": f"media_{media_counter}",
                            "type": "document",
                            "url": file_url,
                            "thumbnail": "",
                            "filename": filename,
                            "source": f"Link ({ext.upper()})"
                        })
                        media_counter += 1

        # 2.5. Extract media URLs from JavaScript arrays in <script> tags
        # Pattern: var arr = ["url1.jpg", "url2.jpg", ...];
        scripts = soup.find_all('script')
        for script in scripts:
            if not script.string:
                continue
            # Find arrays containing image/video URLs in JavaScript
            # Matches any array assignment with quoted URLs ending in media extensions
            array_matches = re.findall(
                r'(?:var|let|const)\s+\w+\s*=\s*\[(.*?)\]',
                script.string, re.DOTALL
            )
            for match in array_matches:
                urls = re.findall(r'["\']([^"\']+)["\']', match)
                # Determine the common domain/path pattern from the first media URLs
                domain_pattern = None
                media_urls = []
                for u in urls:
                    u = u.strip()
                    if not u:
                        continue
                    url_low = u.lower().split('?')[0]
                    ext = url_low.rsplit('.', 1)[-1] if '.' in url_low else ''
                    if ext in ('jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'avif', 'mp4', 'm3u8', 'webm'):
                        media_urls.append(u)
                        if domain_pattern is None:
                            parsed_u = urllib.parse.urlparse(u if u.startswith('http') else urllib.parse.urljoin(url, u))
                            domain_pattern = parsed_u.netloc

                for media_url in media_urls:
                    media_url = media_url.strip()
                    if not media_url:
                        continue

                    # Check if URL points to a media file
                    url_lower = media_url.lower().split('?')[0]
                    ext = url_lower.rsplit('.', 1)[-1] if '.' in url_lower else ''

                    if ext in ('jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'avif'):
                        media_type = 'image'
                    elif ext in ('mp4', 'm3u8', 'webm'):
                        media_type = 'video'
                    else:
                        continue

                    if not media_url.startswith('http'):
                        media_url = urllib.parse.urljoin(url, media_url)

                    # Filter out ad/tracking images that don't match the domain pattern
                    if media_type == 'image' and domain_pattern:
                        parsed_check = urllib.parse.urlparse(media_url)
                        if parsed_check.netloc != domain_pattern:
                            continue

                    parsed = urllib.parse.urlparse(media_url)
                    filename = os.path.basename(parsed.path) or f"{media_type}_{media_counter}.{ext or 'jpg'}"
                    # Strip query params from filename
                    filename = filename.split('?')[0]
                    filename = re.sub(r'[\\/*?:"<>|]', "", filename).strip()[:100]

                    if filename not in seen_filenames:
                        seen_filenames.add(filename)
                        media_items.append({
                            "id": f"media_{media_counter}",
                            "type": media_type,
                            "url": media_url,
                            "thumbnail": media_url if media_type == 'image' else "/static/video-placeholder.png",
                            "filename": filename,
                            "source": "JavaScript Array"
                        })
                        media_counter += 1

        # 2.6. Extract video/audio from iframes (follow up to 3 levels deep)
        iframes = soup.find_all('iframe')
        iframe_depth = getattr(self, '_iframe_depth', 0)
        if iframe_depth < 3:
            for iframe in iframes:
                iframe_src = iframe.get('src') or iframe.get('data-src') or ''
                if not iframe_src or iframe_src.startswith('about:'):
                    continue
                iframe_url = urllib.parse.urljoin(url, iframe_src)

                # Special handling for Blogger video player — try yt-dlp then headless
                if 'blogger.com/video.g' in iframe_url:
                    try:
                        ydl_items, ydl_title = self._extract_yt_dlp_media(iframe_url)
                        for item in ydl_items:
                            if item.get('url') and item['url'] not in seen_filenames:
                                seen_filenames.add(item['url'])
                                item["source"] = "Blogger Video (yt-dlp)"
                                media_items.append(item)
                                media_counter += 1
                    except Exception:
                        pass

                    # Fallback: try headless browser if yt-dlp found nothing
                    if not any(it.get('type') == 'video' for it in media_items[-3:]):
                        try:
                            hl_videos = headless_fetch_iframe_video(iframe_url)
                            for item in hl_videos:
                                vid_url = item["url"]
                                if vid_url and vid_url not in seen_filenames:
                                    seen_filenames.add(vid_url)
                                    parsed_v = urllib.parse.urlparse(vid_url)
                                    fname = os.path.basename(parsed_v.path) or "blogger_video.mp4"
                                    fname = fname.split('?')[0]
                                    fname = re.sub(r'[\\/*?:"<>|]', "", fname).strip()[:100]
                                    media_items.append({
                                        "id": f"media_{media_counter}",
                                        "type": "video",
                                        "url": vid_url,
                                        "thumbnail": "/static/video-placeholder.png",
                                        "filename": fname,
                                        "source": "Blogger Video (headless)"
                                    })
                                    media_counter += 1
                        except Exception:
                            pass
                    continue

                try:
                    iframe_html = self._fetch_iframe_content(iframe_url)
                    if not iframe_html:
                        continue
                    iframe_soup = BeautifulSoup(iframe_html, 'html.parser')
                    # Recursively extract from iframe content
                    sub = GenericExtractor()
                    sub._iframe_depth = iframe_depth + 1
                    sub_items, _ = sub._extract_from_soup(
                        iframe_soup, iframe_url, media_counter, seen_filenames, []
                    )
                    for item in sub_items:
                        item["source"] = f"iframe ({urllib.parse.urlparse(iframe_url).netloc})"
                        media_items.append(item)
                        media_counter += 1
                except Exception:
                    pass

        return media_items, album_title

    def _fetch_iframe_content(self, iframe_url, timeout=8):
        """Fetch iframe page content for nested video extraction."""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }
        r = requests.get(iframe_url, headers=headers, timeout=timeout, allow_redirects=True)
        if r.status_code == 200:
            return r.text
        return None

    def _extract_yt_dlp_media(self, url: str, cookies_path: str = None) -> tuple[list[dict], str]:
        ydl_opts = {
            'skip_download': True,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': 'in_playlist'
        }
        
        local_bin = os.path.join(os.getcwd(), 'bin')
        if os.path.exists(os.path.join(local_bin, 'ffmpeg.exe')):
            ydl_opts['ffmpeg_location'] = local_bin
        
        if cookies_path and os.path.exists(cookies_path):
            ydl_opts['cookiefile'] = cookies_path
        else:
            # Fallback to Firefox cookies if available
            try:
                with yt_dlp.YoutubeDL({'cookiesfrombrowser': ('firefox', None, None, None), 'quiet': True}) as ydl:
                    pass
                ydl_opts['cookiesfrombrowser'] = ('firefox', None, None, None)
            except Exception:
                pass
                
        items = []
        video_title = None
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    return items, None
                
                video_title = info.get('title') or info.get('playlist_title')
                    
                if 'entries' in info:
                    for entry in info['entries']:
                        if not entry:
                            continue
                        entry_title = entry.get('title') or 'Video'
                        entry_url = entry.get('url') or entry.get('webpage_url')
                        thumbnail = entry.get('thumbnail') or "/static/video-placeholder.png"
                        
                        if entry_url:
                            # Clean title for filename
                            clean_title = re.sub(r'[\\/*?:"<>|]', "", entry_title).strip()[:100]
                            items.append({
                                "type": "video",
                                "url": entry_url,
                                "original_url": entry_url,
                                "thumbnail": thumbnail,
                                "filename": f"{clean_title}.mp4",
                                "source": info.get('extractor_key', 'yt-dlp'),
                                "download_via_ytdl": True
                            })
                else:
                    title = info.get('title') or 'Video'
                    thumbnail = info.get('thumbnail') or "/static/video-placeholder.png"
                    formats = info.get('formats', [])
                    
                    # Direct MP4 links
                    direct_formats = []
                    hls_formats = []
                    
                    for f in formats:
                        url_val = f.get('url', '')
                        if not url_val:
                            continue
                        ext = f.get('ext', 'mp4')
                        if ext == 'mp4' and url_val.startswith('http') and '.m3u8' not in url_val and '.mpd' not in url_val:
                            direct_formats.append(f)
                        elif '.m3u8' in url_val or f.get('protocol', '').startswith('m3u8'):
                            hls_formats.append(f)
                            
                    # Clean main title for filename
                    clean_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()[:100]
                    
                    if direct_formats:
                        direct_formats.sort(key=lambda x: x.get('height') or 0, reverse=True)
                        seen_labels = set()
                        for f in direct_formats:
                            height = f.get('height')
                            url_val = f['url']
                            format_id = f.get('format_id') or ''
                            
                            height_label = None
                            if height:
                                height_label = f"{height}p"
                            else:
                                for q in ['240p', '360p', '480p', '720p', '1080p', '1440p', '2160p']:
                                    if q in url_val.lower():
                                        height_label = q
                                        break
                                if not height_label and format_id:
                                    if format_id == 'mp4-low':
                                        height_label = "240p"
                                    elif format_id == 'mp4-high':
                                        height_label = "360p"
                                    else:
                                        height_label = format_id.replace('mp4-', '').capitalize()
                                if not height_label:
                                    height_label = "Link Direto"
                                    
                            if height_label in seen_labels:
                                continue
                            seen_labels.add(height_label)
                            
                            items.append({
                                "type": "video",
                                "url": url_val,
                                "original_url": url,
                                "format_id": format_id,
                                "thumbnail": thumbnail,
                                "filename": f"{clean_title}_{height_label}.mp4",
                                "source": f"MP4 Direct ({height_label})",
                                "download_via_ytdl": True
                            })
                    elif hls_formats:
                        hls_formats.sort(key=lambda x: x.get('height') or 0, reverse=True)
                        seen_labels = set()
                        for f in hls_formats:
                            height = f.get('height')
                            url_val = f['url']
                            format_id = f.get('format_id') or ''
                            
                            height_label = None
                            if height:
                                height_label = f"{height}p"
                            else:
                                for q in ['240p', '360p', '480p', '720p', '1080p', '1440p', '2160p']:
                                    if q in url_val.lower():
                                        height_label = q
                                        break
                                if not height_label and format_id:
                                    height_label = format_id.replace('hls-', '').capitalize()
                                if not height_label:
                                    height_label = "Streaming"
                                    
                            if height_label in seen_labels:
                                continue
                            seen_labels.add(height_label)
                            
                            items.append({
                                "type": "video",
                                "url": url_val,
                                "original_url": url,
                                "format_id": format_id,
                                "thumbnail": thumbnail,
                                "filename": f"{clean_title}_{height_label}.mp4",
                                "source": f"Streaming HLS ({height_label})",
                                "download_via_ytdl": True
                            })
                            
                    # Audio format
                    best_audio = None
                    best_abr = 0
                    for f in formats:
                        if f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                            abr = f.get('abr') or 0
                            if abr > best_abr:
                                best_abr = abr
                                best_audio = f
                                
                    if best_audio and best_audio.get('url'):
                        ext = best_audio.get('ext') or 'mp3'
                        items.append({
                            "type": "audio",
                            "url": best_audio['url'],
                            "original_url": url,
                            "format_id": best_audio.get('format_id'),
                            "thumbnail": "/static/video-placeholder.png",
                            "filename": f"{clean_title} [Audio].{ext}",
                            "source": "Streaming (Audio)",
                            "download_via_ytdl": True
                        })
                        
                    # Thumbnail
                    if thumbnail and thumbnail.startswith('http'):
                        thumb_ext = 'jpg'
                        parsed_thumb = urllib.parse.urlparse(thumbnail)
                        thumb_basename = os.path.basename(parsed_thumb.path)
                        if '.' in thumb_basename:
                            thumb_ext = thumb_basename.split('.')[-1].lower()
                            if thumb_ext not in ['jpg', 'jpeg', 'png', 'webp', 'avif']:
                                thumb_ext = 'jpg'
                        items.append({
                            "type": "image",
                            "url": thumbnail,
                            "thumbnail": thumbnail,
                            "filename": f"{clean_title} [Thumbnail].{thumb_ext}",
                            "source": "Thumbnail"
                        })
        except Exception as e:
            print(f"[GenericExtractor] yt-dlp failed: {e}")
            
        return items, video_title
