import os
import re
import time
import urllib.parse
import random
import socket
import secrets
from concurrent.futures import ThreadPoolExecutor
from threading import Lock, Thread
from flask import Flask, request, jsonify, render_template, Response
from extractors import extract_media, GenericExtractor
from services.proxy_safety import is_safe_url, is_safe_redirect, proxy_fetch, PROXY_MAX_RESPONSE_BYTES
from services.file_safety import is_safe_cookie_path, resolve_cookie_path, is_safe_path, COOKIES_DIR_NAME
from services.rate_limiter import rate_limit, default_limiter, strict_limiter
from services.logger import logger
import requests
from bs4 import BeautifulSoup

# Set default socket timeout to prevent hanging connections
socket.setdefaulttimeout(15.0)


app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
vortex_token = secrets.token_hex(16)


def is_extension_allowed(ext_id):
    """Checks if a given Chrome extension ID is permitted. Fail-closed by default."""
    # Dev bypass: only via explicit environment variable
    if os.environ.get('VORTEX_DEV_ALLOW_ANY_EXTENSION', '').lower() == 'true':
        print(f"[SECURITY DEV] Extension ID '{ext_id}' allowed via VORTEX_DEV_ALLOW_ANY_EXTENSION.")
        return True

    allowed_file = os.path.join(os.getcwd(), 'allowed_extensions.txt')
    if not os.path.exists(allowed_file):
        print(f"[SECURITY BLOCK] No allowed_extensions.txt found. Extension ID '{ext_id}' denied.")
        return False

    try:
        with open(allowed_file, 'r', encoding='utf-8') as f:
            lines = [line.split('#')[0].strip() for line in f.read().splitlines()]
            allowed_ids = {line for line in lines if line}
    except Exception as e:
        print(f"[SECURITY BLOCK] Error reading allowed_extensions.txt: {e}. Denying extension ID '{ext_id}'.")
        return False

    if not allowed_ids:
        print(f"[SECURITY BLOCK] allowed_extensions.txt is empty. Extension ID '{ext_id}' denied.")
        return False

    if ext_id in allowed_ids:
        return True

    logger.warning('AUTH', f"Blocked unauthorized extension ID: {ext_id}")
    return False

@app.before_request
def verify_vortex_token():
    if request.method == 'OPTIONS':
        return '', 200
        
    if request.path.startswith('/api/'):
        # Allow Chrome/Edge extensions to bypass token via Origin, verifying ID
        origin = request.headers.get('Origin', '')
        if origin.startswith('chrome-extension://'):
            ext_id = origin.replace('chrome-extension://', '').split('/')[0]
            if is_extension_allowed(ext_id):
                return
            else:
                return "Unauthorized Extension ID", 403
            
        token = request.headers.get('X-Vortex-Token')
        if request.path in ['/api/proxy-image', '/api/proxy', '/api/serve-file']:
            token = token or request.args.get('token')
        if not token or token != vortex_token:
            return "Forbidden", 403

# Global state for tracking downloads
download_lock = Lock()
download_state = {
    "status": "idle",  # idle, downloading, completed, error
    "album_title": "",
    "total_files": 0,
    "downloaded_files": 0,
    "active_downloads": {},  # filename -> {downloaded, total, percent, speed}
    "error_message": "",
    "download_dir": "",
    "cancelled_files": []
}

# Active sockets map for watchdog stall protection
ACTIVE_SOCKETS = {}
ACTIVE_SOCKETS_LOCK = Lock()

def download_watchdog():
    """Background thread that monitors active downloads and closes sockets that are stalled."""
    while True:
        time.sleep(2)
        now = time.time()
        stalled_filenames = []
        
        with ACTIVE_SOCKETS_LOCK:
            for filename, info in list(ACTIVE_SOCKETS.items()):
                # If no bytes downloaded for more than 20 seconds, mark as stalled
                if now - info["last_time"] > 20:
                    stalled_filenames.append((filename, info["socket"]))
                    
        for filename, sock in stalled_filenames:
            print(f"[WATCHDOG] Closing stalled socket for: {filename}", flush=True)
            try:
                sock.close()
            except Exception as e:
                print(f"[WATCHDOG] Error closing socket: {e}", flush=True)
                
            # Remove from ACTIVE_SOCKETS so we don't try to close it again
            with ACTIVE_SOCKETS_LOCK:
                if filename in ACTIVE_SOCKETS:
                    del ACTIVE_SOCKETS[filename]

# Start the watchdog thread immediately
watchdog_thread = Thread(target=download_watchdog, daemon=True)
watchdog_thread.start()

# Thread pool for downloading files

executor = ThreadPoolExecutor(max_workers=2)

# Browser headers to match real user requests
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9,pt-BR;q=0.8,pt;q=0.7',
    'Connection': 'keep-alive'
}

def sanitize_filename(name):
    """Sanitizes names for Windows file system directories and files."""
    # Remove chars not allowed on Windows
    sanitized = re.sub(r'[\\/*?:"<>|]', "", name)
    # Remove non-ascii or emojis to prevent shell encoding bugs in path names
    sanitized = re.sub(r'[^\x00-\x7F]+', '', sanitized)
    return sanitized.strip()[:100]

def get_default_download_dir(title):
    """Returns the default download directory in the user's Downloads folder."""
    home = os.path.expanduser('~')
    sanitized_title = sanitize_filename(title) or "VortexMedia"
    download_dir = os.path.join(home, 'Downloads', 'VortexMedia', sanitized_title)
    return download_dir

def is_media_ad_or_generic(url, filename, page_url=None):
    """Filters out advertisement media, widgets, user avatars, icons, and generic cards."""
    if not url:
        return True
        
    url_lower = url.lower()
    filename_lower = filename.lower()
    
    # Common advertisement and promotional keywords in URL or filename
    ad_patterns = [
        'adsystem', 'exoclick', 'juicyads', 'trafficjunky', 'adprovider', 'popads', 'onclick',
        'streampass', 'premium-pass', 'join-now', 'signup', 'register', 'promo', 'banner',
        'advertisement', 'affiliate', 'sp-card', 'billing', 'clickunder', 'popunder',
        'cams', 'livesex', 'chaturbate', 'stripchat', 'bongacams', 'imlive', 'flirt4free',
        'cam-show', 'adultfriendfinder', 'faphouse', 'dirtydating', 'sex-cam', 'webcam',
        'ads.', '/ads/', 'google-analytics', 'doubleclick', 'ad-services', 'adform',
        'adnxs', 'rubiconproject', 'pubmatic', 'openx', 'appnexus', 'smartadserver'
    ]
    
    for pattern in ad_patterns:
        if pattern in url_lower or pattern in filename_lower:
            return True
            
    # Generic UI components we typically want to ignore
    ui_patterns = [
        'logo', 'favicon', 'avatar', 'user-profile', 'profile-pic', 'icon-', '-icon',
        'sprite', 'button', 'header-bg', 'footer-bg', 'menu-bg', 'nav-bg', 'spacer',
        'loader', 'loading', 'default-user', 'anonymous'
    ]
    for pattern in ui_patterns:
        if pattern in url_lower or pattern in filename_lower:
            return True
            
    # Platform-specific rules
    if page_url:
        page_url_lower = page_url.lower()
        if 'erome.com' in page_url_lower:
            # For Erome, actual media is hosted on erome CDN servers (*.erome.com) or erome.com
            parsed_url = urllib.parse.urlparse(url)
            domain = parsed_url.netloc.lower()
            if not (domain == 'erome.com' or domain.endswith('.erome.com')):
                return True
                
    return False

# Simple in-memory cache for analyzed URLs
# Key: url, Value: {"media": media_items, "title": title, "timestamp": float}
ANALYZE_CACHE = {}
CACHE_TTL = 600  # 10 minutes in seconds

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1'
]

def get_random_headers(referer=None):
    headers = {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9,pt-BR;q=0.8,pt;q=0.7',
        'Connection': 'keep-alive'
    }
    if referer:
        headers['Referer'] = referer
    return headers

def check_item_size(item):
    """Worker to check media item file size concurrently using HEAD requests."""
    try:
        url = item.get('url', '')
        if not url:
            item['size_str'] = 'Tamanho desc.'
            return
            
        # Ignore m3u8 playlists
        if '.m3u8' in url or 'manifest' in url:
            item['size_str'] = 'Streaming'
            return
            
        # Build standard referer
        parsed = urllib.parse.urlparse(url)
        if 'erome.com' in parsed.netloc:
            referer = 'https://www.erome.com/'
        elif 'phncdn.com' in parsed.netloc or 'pornhub.com' in parsed.netloc:
            referer = 'https://www.pornhub.com/'
        else:
            referer = f"{parsed.scheme}://{parsed.netloc}/"
            
        r = requests.head(url, headers=get_random_headers(referer), timeout=4, allow_redirects=True)
        size = int(r.headers.get('content-length', 0))
        if size > 0:
            item['size_bytes'] = size
            item['size_str'] = f"{size / (1024 * 1024):.2f} MB"
        else:
            item['size_bytes'] = 0
            item['size_str'] = 'Tamanho desc.'
    except Exception:
        item['size_bytes'] = 0
        item['size_str'] = 'Tamanho desc.'

@app.route('/')
def index():
    return render_template('index.html', token=vortex_token)

@app.after_request
def add_header(r):
    """Security headers, CORS for Extension, and cache control."""
    r.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    r.headers["Pragma"] = "no-cache"
    r.headers["Expires"] = "0"
    r.headers['Cache-Control'] = 'public, max-age=0'

    # Security headers
    r.headers['X-Content-Type-Options'] = 'nosniff'
    r.headers['X-Frame-Options'] = 'SAMEORIGIN'
    r.headers['X-XSS-Protection'] = '1; mode=block'
    r.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'

    # CORS for Chrome/Edge extension
    origin = request.headers.get('Origin')
    if origin and origin.startswith('chrome-extension://'):
        r.headers['Access-Control-Allow-Origin'] = origin
        r.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization,X-Vortex-Token'
        r.headers['Access-Control-Allow-Methods'] = 'GET,PUT,POST,DELETE,OPTIONS'

    return r

@app.route('/api/analyze-html', methods=['POST'])
@rate_limit(strict_limiter)
def analyze_html():
    if 'html_file' not in request.files:
        return jsonify({"error": "Nenhum arquivo HTML enviado."}), 400
        
    html_file = request.files['html_file']
    base_url = request.form.get('url', '').strip()
    
    if html_file.filename == '':
        return jsonify({"error": "Nenhum arquivo selecionado."}), 400
        
    try:
        html_content = html_file.read().decode('utf-8', errors='ignore')
        
        extractor = GenericExtractor()
        media_list, title = extractor.extract_html(html_content, base_url)
        
        default_dir = get_default_download_dir("Local_HTML")
        
        return jsonify({
            "title": title or "Arquivo HTML Local",
            "media": media_list,
            "default_dir": default_dir
        })
    except Exception as e:
        print(f"[ERROR] Falha ao analisar HTML: {e}")
        return jsonify({"error": f"Erro interno ao analisar o arquivo HTML."}), 500

@app.route('/api/analyze', methods=['POST'])
@rate_limit(strict_limiter)
def analyze():
    data = request.json
    url = data.get('url', '').strip()
    cookies_path = data.get('cookies_path', '').strip()

    # Resolve cookie_id to actual path server-side
    resolved_cookies = resolve_cookie_path(cookies_path)
    if cookies_path and not resolved_cookies:
        return jsonify({"error": "Caminho de cookies inválido."}), 400
        
    print(f"\n[ANALYZE] URL solicitada: {url}", flush=True)
    
    if not url:
        return jsonify({"error": "Por favor, insira uma URL válida."}), 400
        
    if not url.startswith('http://') and not url.startswith('https://'):
        url = 'https://' + url

    # 1. Check Cache
    current_time = time.time()
    if url in ANALYZE_CACHE:
        cached = ANALYZE_CACHE[url]
        if current_time - cached["timestamp"] < CACHE_TTL:
            print(f"[ANALYZE] Retornando dados do Cache para a URL: {url}", flush=True)
            return jsonify({
                "title": cached["title"],
                "media": cached["media"],
                "default_dir": get_default_download_dir(cached["title"])
            })

    try:
        # 2. Check if link is a direct file download (ZIP, PDF, MP4, etc.)
        try:
            headers = get_random_headers()
            head_res = requests.head(url, headers=headers, timeout=6, allow_redirects=True)
            content_type = head_res.headers.get('content-type', '').lower()
            content_length = int(head_res.headers.get('content-length', 0))
            
            if content_type and 'text/html' not in content_type:
                filename = os.path.basename(urllib.parse.urlparse(url).path) or "arquivo_baixado"
                item_type = "document"
                if "video" in content_type:
                    item_type = "video"
                elif "audio" in content_type:
                    item_type = "audio"
                elif "image" in content_type:
                    item_type = "image"
                    
                size_str = f"{content_length / (1024 * 1024):.2f} MB" if content_length > 0 else "Tamanho desc."
                
                media_item = {
                    "id": "media_0",
                    "type": item_type,
                    "url": url,
                    "thumbnail": "/static/video-placeholder.png" if item_type == "video" else url if item_type == "image" else "",
                    "filename": filename,
                    "source": f"Link Direto ({size_str})"
                }
                
                home = os.path.expanduser('~')
                base_dir = os.path.join(home, 'Downloads', 'VortexMedia')
                default_dir = get_default_download_dir("Downloads_Diretos")
                
                path1 = os.path.join(default_dir, filename)
                path2 = os.path.join(base_dir, filename)
                media_item['exists_locally'] = os.path.exists(path1) or os.path.exists(path2)
                
                # Cache and return
                ANALYZE_CACHE[url] = {
                    "title": filename,
                    "media": [media_item],
                    "timestamp": current_time
                }
                
                return jsonify({
                    "title": filename,
                    "media": [media_item],
                    "default_dir": default_dir,
                    "base_dir": base_dir
                })
        except Exception as e:
            print("HEAD check failed, fallback to scrapers:", str(e))

        # 3. Use modular extractors
        media_items, album_title = extract_media(url, resolved_cookies)
        if not media_items:
            # Check if social media domain to provide helpful message
            is_social = any(domain in url.lower() for domain in ['x.com', 'twitter.com', 'instagram.com', 'tiktok.com', 'threads.net'])
            if is_social:
                return jsonify({"error": "Não foi possível extrair nenhuma mídia deste link de rede social. Verifique se o link está correto, público e se não exige login."}), 400
            return jsonify({"error": "Nenhuma mídia compatível foi encontrada nesta página."}), 400

        # 4. Clean up, proxy Erome thumbnails, and de-duplicate by URL
        filtered_media = []
        seen_urls = set()
        for item in media_items:
            item_url = item.get('url', '')
            item_filename = item.get('filename', '')
            
            if item_url in seen_urls:
                continue
                
            if not is_media_ad_or_generic(item_url, item_filename, url):
                seen_urls.add(item_url)
                
                # Proxy Erome thumbnails to bypass hotlink protection
                thumbnail = item.get('thumbnail', '')
                if thumbnail and 'erome.com' in thumbnail:
                    item['thumbnail'] = f"/api/proxy-image?url={urllib.parse.quote(thumbnail)}"
                
                filtered_media.append(item)
        media_items = filtered_media

        # 5. Check size of all media items concurrently
        with ThreadPoolExecutor(max_workers=5) as pool:
            pool.map(check_item_size, media_items)

        # 6. Re-assign sequential IDs and append size string to sources
        for idx, item in enumerate(media_items):
            item["id"] = f"media_{idx}"
            sz_str = item.get('size_str', 'Tamanho desc.')
            original_source = item.get('source', 'Web')
            item['source'] = f"{original_source} ({sz_str})"

        print(f"[ANALYZE] Retornando {len(media_items)} midias filtradas e com tamanho checado:", flush=True)
        for m in media_items:
            print(f"  - ID={m['id']}, Type={m['type']}, Source={m['source']}, Filename={m['filename']}", flush=True)

        album_title = album_title or "Mídias da Página"
        default_dir = get_default_download_dir(album_title)
        home = os.path.expanduser('~')
        base_dir = os.path.join(home, 'Downloads', 'VortexMedia')
        
        for item in media_items:
            path1 = os.path.join(default_dir, item['filename'])
            path2 = os.path.join(base_dir, item['filename'])
            item['exists_locally'] = os.path.exists(path1) or os.path.exists(path2)
            
        # Save to Cache
        ANALYZE_CACHE[url] = {
            "title": album_title,
            "media": media_items,
            "timestamp": current_time
        }

        return jsonify({
            "title": album_title,
            "media": media_items,
            "default_dir": default_dir,
            "base_dir": base_dir
        })

    except Exception as e:
        return jsonify({"error": f"Erro interno ao analisar a página: {str(e)}"}), 500

@app.route('/api/proxy-image')
def proxy_image():
    image_url = request.args.get('url')
    if not image_url:
        return "Missing url parameter", 400

    parsed = urllib.parse.urlparse(image_url)
    domain = parsed.netloc.lower()

    if 'erome.com' in domain:
        referer = 'https://www.erome.com/'
    else:
        referer = f"{parsed.scheme}://{parsed.netloc}/"

    headers = {
        'User-Agent': HEADERS['User-Agent'],
        'Referer': referer
    }

    r, error = proxy_fetch(image_url, headers=headers, timeout=8)
    if error:
        return error[0], error[1]

    try:
        if r.status_code == 200:
            content_type = r.headers.get('content-type', 'image/jpeg')
            IMAGE_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
            data = r.raw.read(IMAGE_MAX_BYTES + 1)
            r.close()
            if len(data) > IMAGE_MAX_BYTES:
                return "Image exceeds 10 MB limit", 413
            return Response(data, mimetype=content_type)
        else:
            r.close()
            return f"Error fetching image: {r.status_code}", r.status_code
    except Exception as e:
        r.close()
        return f"Proxy error: {str(e)}", 500

def download_ytdl_worker(item, download_dir, cookies_path=None):
    filename = item.get('filename')
    url = item.get('original_url') or item.get('url')
    format_id = item.get('format_id')
    
    with download_lock:
        if download_state["status"] == "idle" or filename in download_state.get("cancelled_files", []):
            return
        download_state["active_downloads"][filename] = {
            "progress": 0,
            "percent": 0,
            "downloaded": 0,
            "total": 0,
            "speed": "0 KB/s",
            "speed_bytes": 0
        }
        
    import yt_dlp
    
    ydl_opts = {
        'outtmpl': os.path.join(download_dir, filename),
        'quiet': True,
        'no_warnings': True,
    }
    
    if format_id:
        if item.get('type') == 'video' and not format_id.startswith('hls'):
            ydl_opts['format'] = f"{format_id}+bestaudio/best"
        else:
            ydl_opts['format'] = format_id
    else:
        if item.get('type') == 'video':
            ydl_opts['format'] = 'bestvideo+bestaudio/best'
        elif item.get('type') == 'audio':
            ydl_opts['format'] = 'bestaudio/best'
            
    local_bin = os.path.join(os.getcwd(), 'bin')
    if os.path.exists(os.path.join(local_bin, 'ffmpeg.exe')):
        ydl_opts['ffmpeg_location'] = local_bin
        
    if cookies_path and os.path.exists(cookies_path):
        ydl_opts['cookiefile'] = cookies_path
        
    def progress_hook(d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes', 0)
            percent = int((downloaded / total) * 100) if total > 0 else 0
            
            speed_val = d.get('speed', 0)
            if speed_val:
                if speed_val > 1024 * 1024:
                    speed_str = f"{speed_val / (1024 * 1024):.2f} MB/s"
                else:
                    speed_str = f"{speed_val / 1024:.2f} KB/s"
            else:
                speed_str = "Baixando..."
                
            with download_lock:
                if download_state["status"] == "idle" or filename in download_state.get("cancelled_files", []):
                    raise Exception("Cancelado pelo usuário")
                if filename in download_state["active_downloads"]:
                    download_state["active_downloads"][filename].update({
                        "progress": percent,
                        "percent": percent,
                        "downloaded": downloaded,
                        "total": total,
                        "speed": speed_str,
                        "speed_bytes": speed_val or 0
                    })
        elif d['status'] == 'finished':
            with download_lock:
                if filename in download_state["active_downloads"]:
                    download_state["active_downloads"][filename]["progress"] = 100
                    download_state["active_downloads"][filename]["percent"] = 100
                    
    ydl_opts['progress_hooks'] = [progress_hook]
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with download_lock:
                if download_state["status"] == "idle" or filename in download_state.get("cancelled_files", []):
                    raise Exception("Cancelado pelo usuário")
                    
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            break
        except Exception as e:
            if "Cancelado pelo usuário" in str(e):
                raise e
            if attempt == max_retries - 1:
                raise e
            else:
                print(f"[RETRY] yt-dlp attempt {attempt+1} failed for {filename}: {e}. Retrying in 2s...")
                time.sleep(2)


def download_file_worker(item, download_dir, album_url, cookies_path=None):
    filename = item.get('filename')
    file_url = item.get('url')
    
    if not file_url:
        raise Exception("URL inválido")
        
    parsed = urllib.parse.urlparse(file_url)
    if 'erome.com' in parsed.netloc:
        referer = 'https://www.erome.com/'
    elif 'xvideos' in parsed.netloc:
        referer = 'https://www.xvideos.com/'
    elif 'phncdn.com' in parsed.netloc or 'pornhub.com' in parsed.netloc:
        referer = 'https://www.pornhub.com/'
    else:
        referer = album_url
        
    headers = {
        'User-Agent': HEADERS['User-Agent'],
        'Referer': referer
    }
    
    filepath = os.path.join(download_dir, filename)
    
    session = requests.Session()
    if cookies_path and os.path.exists(cookies_path):
        try:
            import http.cookiejar
            cj = http.cookiejar.MozillaCookieJar(cookies_path)
            cj.load(ignore_discard=True, ignore_expires=True)
            session.cookies = cj
        except Exception as e:
            print("Failed to load cookies:", str(e))
            
    if os.path.exists(filepath):
        try:
            head_res = session.head(file_url, headers=headers, timeout=10, allow_redirects=True)
            server_size = int(head_res.headers.get('content-length', 0))
            if os.path.getsize(filepath) == server_size and server_size > 0:
                return
        except Exception:
            pass

    with download_lock:
        if download_state["status"] == "idle" or filename in download_state.get("cancelled_files", []):
            return
        download_state["active_downloads"][filename] = {
            "progress": 0,
            "percent": 0,
            "downloaded": 0,
            "total": 0,
            "speed": "0 KB/s",
            "speed_bytes": 0
        }

    os.makedirs(download_dir, exist_ok=True)
    
    max_retries = 3
    bytes_downloaded = 0
    total_size = 0
    
    for attempt in range(max_retries):
        try:
            with download_lock:
                if download_state["status"] == "idle" or filename in download_state.get("cancelled_files", []):
                    raise Exception("Download cancelado pelo usuário")
            
            attempt_headers = headers.copy()
            if bytes_downloaded > 0:
                attempt_headers['Range'] = f"bytes={bytes_downloaded}-"
                mode = 'ab'
            else:
                if os.path.exists(filepath):
                    bytes_downloaded = os.path.getsize(filepath)
                    attempt_headers['Range'] = f"bytes={bytes_downloaded}-"
                    mode = 'ab'
                else:
                    bytes_downloaded = 0
                    mode = 'wb'
                    
            response = session.get(file_url, headers=attempt_headers, stream=True, timeout=25, allow_redirects=True)
            
            if response.status_code not in [200, 206]:
                if response.status_code == 416:
                    bytes_downloaded = 0
                    mode = 'wb'
                    response = session.get(file_url, headers=headers, stream=True, timeout=25, allow_redirects=True)
                    if response.status_code != 200:
                        raise Exception(f"HTTP Status {response.status_code}")
                else:
                    raise Exception(f"HTTP Status {response.status_code}")
            
            if response.status_code == 200 and bytes_downloaded > 0:
                bytes_downloaded = 0
                mode = 'wb'
                
            content_len = int(response.headers.get('content-length', 0))
            if response.status_code == 206:
                total_size = content_len + bytes_downloaded
            else:
                total_size = content_len
                
            with download_lock:
                download_state["active_downloads"][filename]["total"] = total_size
                
            sock = None
            try:
                if hasattr(response.raw, 'connection') and response.raw.connection:
                    sock = getattr(response.raw.connection, 'sock', None)
                    if sock:
                        sock.settimeout(15.0)
            except Exception:
                pass
                
            if sock:
                with ACTIVE_SOCKETS_LOCK:
                    ACTIVE_SOCKETS[filename] = {
                        "socket": sock,
                        "last_bytes": bytes_downloaded,
                        "last_time": time.time()
                    }
                    
            start_time = time.time()
            
            with open(filepath, mode) as f:
                for chunk in response.iter_content(chunk_size=1024 * 64):
                    with download_lock:
                        if download_state["status"] == "idle" or filename in download_state.get("cancelled_files", []):
                            raise Exception("Download cancelado pelo usuário")
                            
                    if chunk:
                        f.write(chunk)
                        bytes_downloaded += len(chunk)
                        
                        with ACTIVE_SOCKETS_LOCK:
                            if filename in ACTIVE_SOCKETS:
                                ACTIVE_SOCKETS[filename]["last_bytes"] = bytes_downloaded
                                ACTIVE_SOCKETS[filename]["last_time"] = time.time()
                                
                        elapsed_time = time.time() - start_time
                        if elapsed_time > 0:
                            speed_val = bytes_downloaded / elapsed_time
                            if speed_val > 1024 * 1024:
                                speed_str = f"{speed_val / (1024 * 1024):.2f} MB/s"
                            else:
                                speed_str = f"{speed_val / 1024:.2f} KB/s"
                        else:
                            speed_str = "0 KB/s"
                            speed_val = 0
                            
                        percent = int((bytes_downloaded / total_size) * 100) if total_size > 0 else 0
                        
                        with download_lock:
                            if filename in download_state["active_downloads"]:
                                download_state["active_downloads"][filename].update({
                                    "progress": percent,
                                    "percent": percent,
                                    "downloaded": bytes_downloaded,
                                    "speed": speed_str,
                                    "speed_bytes": int(speed_val)
                                })
            break
        except Exception as e:
            if "Download cancelado pelo usuário" in str(e):
                raise e
            if attempt == max_retries - 1:
                raise e
            else:
                print(f"[RETRY] Attempt {attempt+1} failed for {filename}: {e}. Retrying in 2s...")
                time.sleep(2)


def download_item_wrapper(item, download_dir, album_url, cookies_path=None):
    filename = item.get('filename')
    filepath = os.path.join(download_dir, filename)
    
    home = os.path.expanduser('~')
    allowed_dirs = [
        os.path.join(home, 'Downloads')
    ]
    
    try:
        # Enforce that download_dir itself is in allowed directories
        if not is_safe_path(download_dir, allowed_dirs):
            raise Exception("Diretório de download não permitido por segurança.")
            
        # Enforce that the output file path is strictly inside the download_dir (to prevent traversal name exploits)
        if not is_safe_path(filepath, [download_dir]):
            raise Exception("Caminho de arquivo de download inválido.")

        if item.get("download_via_ytdl"):
            download_ytdl_worker(item, download_dir, cookies_path)
        else:
            download_file_worker(item, download_dir, album_url, cookies_path)
            
        with download_lock:
            if download_state["status"] != "idle" and filename not in download_state.get("cancelled_files", []):
                download_state["downloaded_files"] += 1
            if filename in download_state["active_downloads"]:
                del download_state["active_downloads"][filename]
    except Exception as e:
        print(f"Error downloading {filename}: {str(e)}")
        with ACTIVE_SOCKETS_LOCK:
            if filename in ACTIVE_SOCKETS:
                del ACTIVE_SOCKETS[filename]
                
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception:
            pass
            
        try:
            part_file = filepath + ".part"
            if os.path.exists(part_file):
                os.remove(part_file)
            ytdl_file = filepath + ".ytdl"
            if os.path.exists(ytdl_file):
                os.remove(ytdl_file)
        except Exception:
            pass
            
        with download_lock:
            if filename in download_state["active_downloads"]:
                del download_state["active_downloads"][filename]
            if download_state["status"] != "idle":
                download_state["downloaded_files"] += 1


def download_manager_thread(items, download_dir, album_url, cookies_path=None, concurrency=4):
    """Manager thread that controls the thread pool and updates overall status."""
    global download_state
    
    with download_lock:
        download_state.update({
            "status": "downloading",
            "total_files": len(items),
            "downloaded_files": 0,
            "active_downloads": {},
            "error_message": "",
            "download_dir": download_dir,
            "cancelled_files": []
        })
    
    print(f"[DOWNLOAD] Iniciando com concorrência de {concurrency} downloads simultâneos.", flush=True)
    with ThreadPoolExecutor(max_workers=concurrency) as local_pool:
        futures = [local_pool.submit(download_item_wrapper, item, download_dir, album_url, cookies_path) for item in items]
        for future in futures:
            try:
                future.result()
            except Exception as e:
                print(f"Future error: {str(e)}")
            
    with download_lock:
        if download_state["status"] != "idle":
            download_state["status"] = "completed"
            try:
                if os.path.exists(download_dir):
                    os.startfile(download_dir)
            except Exception:
                pass

@app.route('/api/browse-folder', methods=['POST'])
def browse_folder():
    """Opens a native Windows directory selector dialog and returns the selected folder."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        
        # Initialize hidden tkinter window
        root = tk.Tk()
        root.withdraw()
        # Ensure dialog opens in front
        root.attributes('-topmost', True)
        
        selected_dir = filedialog.askdirectory(title="Selecione a pasta de download")
        root.destroy()
        
        if selected_dir:
            return jsonify({"directory": os.path.normpath(selected_dir)})
    except Exception as e:
        print("Folder browser error:", str(e))
        
    return jsonify({"directory": ""})

@app.route('/api/browse-file', methods=['POST'])
def browse_file():
    """Opens a native Windows file selector dialog and copies the selected cookies file to saved_cookies/."""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)

        selected_file = filedialog.askopenfilename(
            title="Selecione o arquivo de cookies",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        root.destroy()

        if selected_file:
            # Validate the selected file
            if not selected_file.endswith('.txt'):
                return jsonify({"error": "Apenas arquivos .txt são permitidos."}), 400

            import shutil
            cookies_dir = os.path.join(os.getcwd(), COOKIES_DIR_NAME)
            os.makedirs(cookies_dir, exist_ok=True)

            # Generate a safe cookie_id from the original filename
            basename = os.path.basename(selected_file)
            safe_name = re.sub(r'[^a-zA-Z0-9._-]', '_', basename)
            cookie_id = f"browse_{safe_name}"
            dest_path = os.path.join(cookies_dir, cookie_id)

            shutil.copy2(selected_file, dest_path)

            return jsonify({"cookie_id": cookie_id})
    except Exception as e:
        print("File browser error:", str(e))

    return jsonify({"cookie_id": ""})

@app.route('/api/upload-cookies', methods=['POST'])
@rate_limit(default_limiter)
def upload_cookies():
    """Receives a cookies.txt file uploaded from the client and saves it locally."""
    if 'file' not in request.files:
        return jsonify({"error": "Nenhum arquivo enviado."}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Nome de arquivo inválido."}), 400
        
    if not file.filename.endswith('.txt'):
        return jsonify({"error": "Apenas arquivos .txt de cookies são permitidos."}), 400
        
    # Limit size to 5MB (5 * 1024 * 1024 bytes)
    try:
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        if file_size > 5 * 1024 * 1024:
            return jsonify({"error": "O arquivo de cookies excede o limite de 5MB."}), 400
    except Exception as e:
        return jsonify({"error": f"Erro ao validar tamanho do arquivo: {str(e)}"}), 400
        
    if file:
        try:
            client_ip = request.remote_addr
            sanitized_ip = re.sub(r'[^a-zA-Z0-9]', '_', client_ip)
            cookie_id = f"cookies_{sanitized_ip}.txt"

            cookies_dir = os.path.join(os.getcwd(), COOKIES_DIR_NAME)
            os.makedirs(cookies_dir, exist_ok=True)
            filepath = os.path.join(cookies_dir, cookie_id)

            file.save(filepath)

            return jsonify({
                "success": True,
                "cookie_id": cookie_id,
                "message": "Cookies carregados com sucesso!"
            })
        except Exception as e:
            return jsonify({"error": f"Erro ao salvar arquivo de cookies: {str(e)}"}), 500

@app.route('/api/log-error', methods=['POST'])
def log_error():
    """Telemetry endpoint that prints browser JavaScript errors to Flask console logs."""
    data = request.json
    print(f"\n[BROWSER JS ERROR] {data.get('error')}", flush=True)
    print(f"  File: {data.get('filename')} : {data.get('lineno')}:{data.get('colno')}", flush=True)
    if data.get('stack'):
        print(f"  Stack: {data.get('stack')}", flush=True)
    return jsonify({"success": True})

@app.route('/api/proxy')
@rate_limit(default_limiter)
def proxy_media():
    """Proxy route to stream media files (avoiding browser Referer-related CORS/403 errors)."""
    url_val = request.args.get('url')
    download = request.args.get('download') == 'true'
    filename_val = request.args.get('filename')

    if not url_val:
        return "Missing URL", 400

    parsed = urllib.parse.urlparse(url_val)
    if 'erome.com' in parsed.netloc:
        referer = 'https://www.erome.com/'
    elif 'xvideos' in parsed.netloc:
        referer = 'https://www.xvideos.com/'
    elif 'phncdn.com' in parsed.netloc or 'pornhub.com' in parsed.netloc:
        referer = 'https://www.pornhub.com/'
    else:
        referer = f"https://{parsed.netloc}/"

    headers = {
        'User-Agent': HEADERS['User-Agent'],
        'Referer': referer
    }

    # Forward the Range header from the browser to support seeking and progressive loading
    range_header = request.headers.get('Range')
    if range_header:
        headers['Range'] = range_header

    r, error = proxy_fetch(url_val, headers=headers, timeout=15)
    if error:
        return error[0], error[1]

    try:
        # Strip encoding and connection headers to avoid transfer conflicts
        excluded_headers = ['content-encoding', 'transfer-encoding', 'connection']
        resp_headers = [(name, value) for name, value in r.raw.headers.items()
                        if name.lower() not in excluded_headers]
        resp_headers.append(('Access-Control-Allow-Origin', '*'))

        # Explicitly ensure Accept-Ranges is returned
        if not any(h[0].lower() == 'accept-ranges' for h in resp_headers):
            resp_headers.append(('Accept-Ranges', 'bytes'))

        # If download is true, append Content-Disposition attachment header
        if download and filename_val:
            quoted_filename = urllib.parse.quote(filename_val)
            resp_headers.append(('Content-Disposition', f'attachment; filename="{quoted_filename}"; filename*=UTF-8\'\'{quoted_filename}'))

        def generate():
            bytes_sent = 0
            try:
                for chunk in r.iter_content(chunk_size=1024 * 64):
                    bytes_sent += len(chunk)
                    if bytes_sent > PROXY_MAX_RESPONSE_BYTES:
                        break
                    yield chunk
            finally:
                r.close()

        return Response(generate(), status=r.status_code, headers=resp_headers)
    except Exception as e:
        r.close()
        return str(e), 500

@app.route('/api/download', methods=['POST'])
@rate_limit(strict_limiter)
def download():
    global download_state
    
    with download_lock:
        if download_state["status"] == "downloading":
            return jsonify({"error": "Já existe um download em andamento."}), 400
            
    data = request.json
    items = data.get('items', [])
    download_dir = data.get('download_dir', '').strip()
    album_url = data.get('album_url', '').strip()
    cookies_path = data.get('cookies_path', '').strip()

    # Resolve cookie_id to actual path server-side
    resolved_cookies = resolve_cookie_path(cookies_path)
    if cookies_path and not resolved_cookies:
        return jsonify({"error": "Caminho de cookies inválido."}), 400

    concurrency = int(data.get('concurrency', 4))
    # Clamp to safe limits
    concurrency = max(1, min(concurrency, 12))

    if not items:
        return jsonify({"error": "Nenhum arquivo selecionado para download."}), 400

    if not download_dir:
        return jsonify({"error": "Caminho de download inválido."}), 400

    thread = Thread(target=download_manager_thread, args=(items, download_dir, album_url, resolved_cookies, concurrency))
    thread.daemon = True
    thread.start()
    
    return jsonify({"success": True, "message": "Download iniciado em segundo plano."})

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def get_ffmpeg_path():
    # Check local bin directory first
    local_bin = os.path.join(os.getcwd(), 'bin')
    local_ffmpeg = os.path.join(local_bin, 'ffmpeg.exe')
    if os.path.exists(local_ffmpeg):
        return local_ffmpeg
        
    # Check PATH
    import shutil
    system_ffmpeg = shutil.which('ffmpeg')
    if system_ffmpeg:
        return system_ffmpeg
        
    return None

ffmpeg_install_state = {"status": "idle", "progress": 0, "error": ""}
ffmpeg_install_lock = Lock()

def install_ffmpeg_worker():
    global ffmpeg_install_state
    url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    bin_dir = os.path.join(os.getcwd(), 'bin')
    zip_path = os.path.join(bin_dir, 'ffmpeg_temp.zip')
    
    try:
        os.makedirs(bin_dir, exist_ok=True)
        
        with ffmpeg_install_lock:
            ffmpeg_install_state.update({"status": "downloading", "progress": 0, "error": ""})
            
        response = requests.get(url, stream=True, timeout=30)
        if response.status_code != 200:
            raise Exception(f"HTTP Status {response.status_code}")
            
        total_size = int(response.headers.get('content-length', 0))
        bytes_downloaded = 0
        
        with open(zip_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=1024 * 128):
                if chunk:
                    f.write(chunk)
                    bytes_downloaded += len(chunk)
                    if total_size > 0:
                        pct = int((bytes_downloaded / total_size) * 100)
                        with ffmpeg_install_lock:
                            ffmpeg_install_state["progress"] = pct
                            
        with ffmpeg_install_lock:
            ffmpeg_install_state["status"] = "extracting"
            
        import zipfile
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for file_info in zip_ref.infolist():
                filename = file_info.filename
                if filename.endswith('/ffmpeg.exe') or filename.endswith('/ffprobe.exe'):
                    base_name = os.path.basename(filename)
                    target_path = os.path.join(bin_dir, base_name)
                    with zip_ref.open(file_info) as source, open(target_path, 'wb') as target:
                        target.write(source.read())
                        
        if os.path.exists(zip_path):
            os.remove(zip_path)
            
        with ffmpeg_install_lock:
            ffmpeg_install_state["status"] = "completed"
            
    except Exception as e:
        print("FFmpeg installation failed:", str(e))
        if os.path.exists(zip_path):
            try:
                os.remove(zip_path)
            except Exception:
                pass
        with ffmpeg_install_lock:
            ffmpeg_install_state.update({"status": "error", "error": str(e)})

conversion_state = {"status": "idle", "progress": 0, "error": "", "output_path": "", "filename": ""}
conversion_lock = Lock()

def convert_to_mp3_worker(input_path):
    global conversion_state
    ffmpeg_path = get_ffmpeg_path()
    filename = os.path.basename(input_path)
    
    if not ffmpeg_path:
        with conversion_lock:
            conversion_state.update({"status": "error", "error": "FFmpeg não encontrado.", "filename": filename})
        return
        
    dir_name = os.path.dirname(input_path)
    file_name = os.path.basename(input_path)
    base_name = os.path.splitext(file_name)[0]
    output_path = os.path.join(dir_name, f"{base_name}.mp3")
    
    try:
        with conversion_lock:
            conversion_state.update({
                "status": "converting",
                "progress": 0,
                "error": "",
                "output_path": output_path,
                "filename": filename
            })
            
        import subprocess
        result = subprocess.run([
            ffmpeg_path,
            '-y',
            '-i', input_path,
            '-vn',
            '-acodec', 'libmp3lame',
            '-q:a', '2',
            output_path
        ], capture_output=True, text=True, timeout=120)
        
        if result.returncode == 0:
            with conversion_lock:
                conversion_state.update({
                    "status": "completed",
                    "progress": 100,
                    "filename": filename
                })
            try:
                os.startfile(dir_name)
            except Exception:
                pass
        else:
            raise Exception(result.stderr or "Erro desconhecido no ffmpeg")
    except Exception as e:
        print("MP3 conversion failed:", str(e))
        with conversion_lock:
            conversion_state.update({"status": "error", "error": str(e), "filename": filename})

@app.route('/api/status', methods=['GET'])
def get_status():
    with download_lock:
        total = download_state["total_files"]
        downloaded = download_state["downloaded_files"]
        
        overall_progress = 0
        if total > 0:
            base_percent = (downloaded / total) * 100
            active_contrib = 0
            for file_info in download_state["active_downloads"].values():
                active_contrib += (file_info["progress"] / 100) * (100 / total)
            overall_progress = min(100, int(base_percent + active_contrib))
            
        return jsonify({
            "status": download_state["status"],
            "total_files": total,
            "downloaded_files": downloaded,
            "active_downloads": download_state["active_downloads"],
            "overall_progress": overall_progress,
            "download_dir": download_state["download_dir"],
            "error_message": download_state["error_message"],
            "local_ip": get_local_ip()
        })

@app.route('/api/ffmpeg/status', methods=['GET'])
def ffmpeg_status():
    path = get_ffmpeg_path()
    return jsonify({
        "installed": path is not None,
        "path": path or ""
    })

@app.route('/api/ffmpeg/install', methods=['POST'])
def ffmpeg_install():
    global ffmpeg_install_state
    with ffmpeg_install_lock:
        if ffmpeg_install_state["status"] in ["downloading", "extracting"]:
            return jsonify({"error": "Instalação do FFmpeg já está em andamento."}), 400
            
    thread = Thread(target=install_ffmpeg_worker)
    thread.daemon = True
    thread.start()
    return jsonify({"success": True, "message": "Instalação do FFmpeg iniciada em segundo plano."})

@app.route('/api/ffmpeg/install-status', methods=['GET'])
def ffmpeg_install_status():
    with ffmpeg_install_lock:
        return jsonify(ffmpeg_install_state)

@app.route('/api/open-file', methods=['POST'])
def open_file():
    data = request.json
    filepath = data.get('filepath', '').strip()
    
    if not filepath or not os.path.exists(filepath):
        return jsonify({"error": "Arquivo não encontrado."}), 400
        
    _, ext = os.path.splitext(filepath)
    safe_extensions = {'.mp4', '.mp3', '.jpg', '.jpeg', '.png', '.gif', '.txt', '.pdf'}
    if ext.lower() not in safe_extensions:
        return jsonify({"error": "Extensão de arquivo não permitida por segurança."}), 400
        
    home = os.path.expanduser('~')
    allowed_dirs = [
        os.path.join(home, 'Downloads')
    ]
    
    if not is_safe_path(filepath, allowed_dirs):
        return jsonify({"error": "Acesso negado para abrir este arquivo."}), 403
        
    try:
        os.startfile(filepath)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": f"Erro ao abrir arquivo: {str(e)}"}), 500

@app.route('/api/convert-to-mp3', methods=['POST'])
def convert_to_mp3():
    global conversion_state
    data = request.json
    filepath = data.get('filepath', '').strip()
    
    if not filepath or not os.path.exists(filepath):
        return jsonify({"error": "Arquivo de origem não encontrado."}), 400
        
    home = os.path.expanduser('~')
    allowed_dirs = [
        os.path.join(home, 'Downloads')
    ]
    
    if not is_safe_path(filepath, allowed_dirs):
        return jsonify({"error": "Acesso negado para converter este arquivo."}), 403
        
    with conversion_lock:
        if conversion_state["status"] == "converting":
            return jsonify({"error": "Já existe uma conversão em andamento."}), 400
            
    thread = Thread(target=convert_to_mp3_worker, args=(filepath,))
    thread.daemon = True
    thread.start()
    return jsonify({"success": True, "message": "Conversão para MP3 iniciada."})

@app.route('/api/convert-status', methods=['GET'])
def convert_status():
    with conversion_lock:
        return jsonify(conversion_state)

@app.route('/api/serve-file', methods=['GET'])
def serve_file():
    filepath = request.args.get('path', '').strip()
    if not filepath or not os.path.exists(filepath):
        return "Arquivo não encontrado", 404
        
    home = os.path.expanduser('~')
    allowed_dirs = [
        os.path.join(home, 'Downloads')
    ]
    
    if not is_safe_path(filepath, allowed_dirs):
        return "Acesso negado", 403
        
    try:
        from flask import send_file
        return send_file(os.path.normpath(filepath), as_attachment=True)
    except Exception as e:
        return str(e), 500

@app.route('/api/cancel', methods=['POST'])
def cancel_downloads():
    global download_state
    data = request.json or {}
    filename = data.get('filename')
    
    with download_lock:
        if filename:
            if "cancelled_files" not in download_state:
                download_state["cancelled_files"] = []
            if filename not in download_state["cancelled_files"]:
                download_state["cancelled_files"].append(filename)
            if filename in download_state["active_downloads"]:
                del download_state["active_downloads"][filename]
        else:
            download_state["status"] = "idle"
            download_state["active_downloads"] = {}
            download_state["cancelled_files"] = []
            
    # Trigger watchdog socket closing if cancel is called on filename
    if filename:
        with ACTIVE_SOCKETS_LOCK:
            if filename in ACTIVE_SOCKETS:
                try:
                    ACTIVE_SOCKETS[filename]["socket"].close()
                except Exception:
                    pass
                del ACTIVE_SOCKETS[filename]
                
    return jsonify({"success": True})

@app.route('/api/update-ytdl', methods=['POST'])
@rate_limit(strict_limiter)
def update_ytdl():
    """Endpoint to update the yt-dlp package in the virtual environment."""
    import subprocess
    import sys
    
    try:
        # Run pip install --upgrade yt-dlp using the current python executable
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"],
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode == 0:
            print("yt-dlp updated successfully:", result.stdout)
            return jsonify({"success": True, "message": "yt-dlp atualizado com sucesso!"})
        else:
            print("yt-dlp update failed:", result.stderr)
            return jsonify({"success": False, "error": result.stderr or "Erro desconhecido ao rodar o pip."}), 500
    except Exception as e:
        print("yt-dlp update exception:", str(e))
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    import webbrowser
    from threading import Timer
    import socket
    
    local_ip = get_local_ip()
    
    def open_browser():
        webbrowser.open_new("http://127.0.0.1:8080")
        
    Timer(1.5, open_browser).start()
    print("\n" + "="*60)
    print("Vortex iniciado com sucesso!")
    print("Acesse no PC: http://127.0.0.1:8080")
    print(f"Acesse no Celular (na mesma rede Wi-Fi): http://{local_ip}:8080")
    print("="*60 + "\n")
    
    app.run(host='127.0.0.1', port=8080, debug=False)
