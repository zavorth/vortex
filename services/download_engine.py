"""Smart download engine with retry, resume, integrity check, and parallel download."""

import os
import re
import time
import hashlib
import urllib.parse
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from services.logger import logger

# Maximum parallel chunks for a single file
MAX_CHUNKS = 4
CHUNK_SIZE = 1024 * 1024  # 1MB chunks
MAX_RETRIES = 3
STALL_TIMEOUT = 30  # seconds before considering a download stalled


def calculate_file_hash(filepath, algorithm='md5'):
    """Calculate hash of a file for integrity verification."""
    h = hashlib.new(algorithm)
    try:
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def verify_download(filepath, expected_size=None):
    """Verify downloaded file integrity."""
    if not os.path.exists(filepath):
        return False, "File does not exist"

    size = os.path.getsize(filepath)
    if size == 0:
        return False, "File is empty"

    if expected_size and size != expected_size:
        return False, f"Size mismatch: expected {expected_size}, got {size}"

    # Check for common corrupt file signatures
    try:
        with open(filepath, 'rb') as f:
            header = f.read(16)
            # Empty or all-zero file
            if header == b'\x00' * len(header):
                return False, "File appears to be all zeros"
    except Exception:
        pass

    return True, "OK"


def get_file_size(url, headers=None, timeout=10):
    """Get file size via HEAD request without downloading."""
    try:
        h = headers or {}
        r = requests.head(url, headers=h, timeout=timeout, allow_redirects=True)
        return int(r.headers.get('content-length', 0))
    except Exception:
        return 0


def download_with_resume(url, filepath, headers=None, progress_callback=None,
                         max_retries=MAX_RETRIES, cookies=None):
    """
    Download a file with resume support and retry logic.
    Returns (success, bytes_downloaded, error_message).
    """
    os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)

    downloaded = 0
    if os.path.exists(filepath):
        downloaded = os.path.getsize(filepath)

    total_size = get_file_size(url, headers)

    for attempt in range(max_retries):
        try:
            req_headers = (headers or {}).copy()
            if downloaded > 0:
                req_headers['Range'] = f'bytes={downloaded}-'

            session = requests.Session()
            if cookies:
                session.cookies = cookies

            r = session.get(url, headers=req_headers, stream=True, timeout=30, allow_redirects=True)

            if r.status_code == 416:
                # Range not satisfiable — file already complete
                if total_size > 0 and downloaded >= total_size:
                    return True, downloaded, "Already complete"
                # Reset and retry without range
                downloaded = 0
                r = session.get(url, headers=headers or {}, stream=True, timeout=30, allow_redirects=True)

            if r.status_code not in (200, 206):
                logger.warning('DOWNLOAD', f"HTTP {r.status_code} for {url[:80]}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return False, downloaded, f"HTTP {r.status_code}"

            # Check for safe redirect to private IP
            from services.proxy_safety import is_safe_url
            if hasattr(r, 'url') and r.url != url:
                if not is_safe_url(r.url):
                    return False, 0, "Redirected to unsafe URL"

            content_len = int(r.headers.get('content-length', 0))
            if response_status := r.status_code:
                if response_status == 200 and downloaded > 0:
                    downloaded = 0

            mode = 'ab' if downloaded > 0 and r.status_code == 206 else 'wb'
            bytes_downloaded = downloaded

            with open(filepath, mode) as f:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
                        bytes_downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(bytes_downloaded, total_size)

            return True, bytes_downloaded, "OK"

        except requests.exceptions.ConnectionError as e:
            logger.warning('DOWNLOAD', f"Connection error (attempt {attempt+1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return False, downloaded, f"Connection error: {str(e)[:100]}"
        except Exception as e:
            logger.warning('DOWNLOAD', f"Error (attempt {attempt+1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return False, downloaded, f"Error: {str(e)[:100]}"

    return False, downloaded, "Max retries exceeded"


def download_parallel(url, filepath, headers=None, progress_callback=None,
                      num_chunks=MAX_CHUNKS, cookies=None):
    """
    Download a file using parallel chunks for faster speed.
    Falls back to sequential if server doesn't support Range requests.
    """
    total_size = get_file_size(url, headers)

    if total_size <= 0 or total_size < CHUNK_SIZE * 2:
        # Too small for parallel or unknown size — use sequential
        return download_with_resume(url, filepath, headers, progress_callback, cookies=cookies)

    # Check if server supports Range requests
    try:
        test_headers = (headers or {}).copy()
        test_headers['Range'] = 'bytes=0-1'
        r = requests.head(url, headers=test_headers, timeout=10, allow_redirects=True)
        if r.status_code not in (200, 206):
            return download_with_resume(url, filepath, headers, progress_callback, cookies=cookies)
    except Exception:
        return download_with_resume(url, filepath, headers, progress_callback, cookies=cookies)

    os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)

    chunk_size = total_size // num_chunks
    chunks = []
    for i in range(num_chunks):
        start = i * chunk_size
        end = start + chunk_size - 1 if i < num_chunks - 1 else total_size - 1
        chunks.append((start, end, i))

    downloaded_bytes = [0] * num_chunks
    lock = Lock()

    def download_chunk(start, end, chunk_idx):
        chunk_file = f"{filepath}.chunk{chunk_idx}"
        try:
            req_headers = (headers or {}).copy()
            req_headers['Range'] = f'bytes={start}-{end}'

            session = requests.Session()
            if cookies:
                session.cookies = cookies

            r = session.get(url, headers=req_headers, stream=True, timeout=30)
            if r.status_code not in (200, 206):
                return False

            with open(chunk_file, 'wb') as f:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
                        with lock:
                            downloaded_bytes[chunk_idx] += len(chunk)
                            if progress_callback:
                                progress_callback(sum(downloaded_bytes), total_size)
            return True
        except Exception as e:
            logger.warning('DOWNLOAD', f"Chunk {chunk_idx} error: {e}")
            return False

    with ThreadPoolExecutor(max_workers=num_chunks) as pool:
        futures = {pool.submit(download_chunk, s, e, i): i for s, e, i in chunks}
        all_ok = True
        for future in as_completed(futures):
            if not future.result():
                all_ok = False

    if not all_ok:
        # Clean up chunk files
        for i in range(num_chunks):
            chunk_file = f"{filepath}.chunk{i}"
            if os.path.exists(chunk_file):
                os.remove(chunk_file)
        # Fallback to sequential
        return download_with_resume(url, filepath, headers, progress_callback, cookies=cookies)

    # Merge chunks
    try:
        with open(filepath, 'wb') as out:
            for i in range(num_chunks):
                chunk_file = f"{filepath}.chunk{i}"
                with open(chunk_file, 'rb') as cf:
                    while True:
                        data = cf.read(1024 * 1024)
                        if not data:
                            break
                        out.write(data)
                os.remove(chunk_file)
        return True, total_size, "OK"
    except Exception as e:
        return False, 0, f"Merge error: {str(e)[:100]}"
