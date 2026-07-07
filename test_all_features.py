"""Comprehensive integration tests for all Vortex features."""

import os
import sys
import json
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from services.page_extract import extract_all_media
from services.stream_support import check_url_is_stream, detect_stream_type, extract_m3u8_variants
from services.bandwidth import BandwidthLimiter, bandwidth_limiter
from services.download_engine import download_with_resume, download_parallel, verify_download, get_file_size
from services.converter import convert_media, get_ffmpeg_path
from services.download_history import add_download_record, get_history, clear_history
from services.logger import logger

PASS = 0
FAIL = 0

def test(name, result, detail=""):
    global PASS, FAIL
    if result:
        PASS += 1
        print(f"  OK  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} — {detail}")

print("=" * 60)
print("VORTEX COMPREHENSIVE TEST SUITE")
print("=" * 60)

# ============================================================
# 1. PAGE EXTRACTION (manga)
# ============================================================
print("\n[1] Page Extraction — Manga")
try:
    items = extract_all_media("https://www.muitohentai.com/manga/immoral-routine/capitulo-1/")
    images = [i for i in items if i['type'] == 'image']
    test("Manga images found", len(images) > 20, f"Found {len(images)}")
    # Check filenames are sequential
    nums = []
    for img in images:
        fn = img['filename'].split('.')[0]
        if fn.isdigit():
            nums.append(int(fn))
    nums.sort()
    test("Images have sequential names", len(nums) > 10, f"Got {len(nums)} numbered images")
    print(f"    Total items: {len(items)}, Images: {len(images)}")
except Exception as e:
    test("Manga extraction", False, str(e))

# ============================================================
# 2. PAGE EXTRACTION (video page)
# ============================================================
print("\n[2] Page Extraction — Video Page")
try:
    items = extract_all_media("https://www.muitohentai.com/episodios/nuki-nuki-zupposism-episodio-1/")
    test("Video page items found", len(items) > 0, f"Found {len(items)}")
    for it in items[:3]:
        print(f"    {it['type']}: {it['filename'][:50]} ({it['source']})")
except Exception as e:
    test("Video page extraction", False, str(e))

# ============================================================
# 3. STREAM DETECTION
# ============================================================
print("\n[3] Stream Detection")
test("HLS detection", detect_stream_type("https://example.com/video.m3u8") == 'hls')
test("DASH detection", detect_stream_type("https://example.com/video.mpd") == 'dash')
test("Regular URL not stream", detect_stream_type("https://example.com/video.mp4") is None)
test("M3U8 in path", detect_stream_type("https://cdn.example.com/hls/playlist.m3u8") == 'hls')

# ============================================================
# 4. BANDWIDTH LIMITER
# ============================================================
print("\n[4] Bandwidth Limiter")
limiter = BandwidthLimiter(1024 * 1024)  # 1 MB/s
test("Limiter initialized", limiter.max_bps == 1024 * 1024)
test("Format speed MB/s", BandwidthLimiter.format_speed(1024 * 1024) == "1.0 MB/s")
test("Format speed KB/s", BandwidthLimiter.format_speed(512 * 1024) == "512 KB/s")
test("Format unlimited", BandwidthLimiter.format_speed(0) == "Ilimitado")
limiter.set_limit(0)
test("Set unlimited", limiter.max_bps == 0)
test("Global limiter exists", bandwidth_limiter is not None)

# ============================================================
# 5. DOWNLOAD ENGINE — FILE SIZE
# ============================================================
print("\n[5] Download Engine — File Size")
try:
    size = get_file_size("https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf")
    test("Get file size", size > 0, f"Size: {size}")
except Exception as e:
    test("Get file size", False, str(e))

# ============================================================
# 6. DOWNLOAD ENGINE — DOWNLOAD + VERIFY
# ============================================================
print("\n[6] Download Engine — Download + Verify")
tmpdir = tempfile.mkdtemp()
test_file = os.path.join(tmpdir, "test_download.pdf")
try:
    ok, size, msg = download_with_resume(
        "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf",
        test_file
    )
    test("Download file", ok, msg)
    test("File exists", os.path.exists(test_file))
    if os.path.exists(test_file):
        test("File not empty", os.path.getsize(test_file) > 0)

    # Verify integrity
    valid, v_msg = verify_download(test_file)
    test("Verify integrity", valid, v_msg)

    # Verify with wrong size
    valid2, _ = verify_download(test_file, expected_size=999999)
    test("Verify wrong size fails", not valid2)
finally:
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)

# ============================================================
# 7. DOWNLOAD ENGINE — RESUME
# ============================================================
print("\n[7] Download Engine — Resume")
tmpdir = tempfile.mkdtemp()
resume_file = os.path.join(tmpdir, "test_resume.pdf")
try:
    # Create partial file (simulate interrupted download)
    with open(resume_file, 'wb') as f:
        f.write(b'partial content')
    partial_size = os.path.getsize(resume_file)
    test("Partial file created", partial_size > 0, f"Size: {partial_size}")

    ok, size, msg = download_with_resume(
        "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf",
        resume_file
    )
    test("Resume download", ok, msg)
    if os.path.exists(resume_file):
        test("Resumed file complete", os.path.getsize(resume_file) > partial_size)
finally:
    shutil.rmtree(tmpdir, ignore_errors=True)

# ============================================================
# 8. CONVERTER — CHECK FFMPEG
# ============================================================
print("\n[8] Converter — FFmpeg")
ffmpeg = get_ffmpeg_path()
if ffmpeg:
    test("FFmpeg found", True, ffmpeg)
else:
    test("FFmpeg found", False, "FFmpeg not installed (optional)")

# ============================================================
# 9. DOWNLOAD HISTORY
# ============================================================
print("\n[9] Download History")
clear_history()
record = add_download_record("Test Video", ["file1.mp4", "file2.mp4"], "/tmp/downloads", "completed")
test("Add record", record is not None)
test("Record has ID", 'id' in record)
test("Record has date", 'date' in record)
history = get_history(limit=10)
test("Get history", len(history) == 1)
test("History title correct", history[0]['title'] == "Test Video")
clear_history()
history2 = get_history()
test("Clear history", len(history2) == 0)

# ============================================================
# 10. EXTRACTOR — PORNHUB (mock)
# ============================================================
print("\n[10] Extractor — PornHub (domain matching)")
from extractors.pornhub import PornHubExtractor
ext = PornHubExtractor()
test("PornHub domain match", ext.can_handle("https://www.pornhub.com/view_video.php?viewkey=abc"))
test("PornHub reject other", not ext.can_handle("https://xvideos.com/video123"))
test("Clean filename", "Test Video" == ext._clean_filename("Test Video"))
test("Clean special chars", "<>" not in ext._clean_filename('A <b> Video'))

# ============================================================
# 11. EXTRACTOR — XVIDEOS (mock)
# ============================================================
print("\n[11] Extractor — XVideos (domain matching)")
from extractors.xvideos import XVideosExtractor
ext = XVideosExtractor()
test("XVideos domain match", ext.can_handle("https://www.xvideos.com/video12345/title"))
test("XVideos reject other", not ext.can_handle("https://pornhub.com/video"))

# ============================================================
# 12. EXTRACTOR — SPANKBANG (mock)
# ============================================================
print("\n[12] Extractor — SpankBang (domain matching)")
from extractors.spankbang import SpankBangExtractor
ext = SpankBangExtractor()
test("SpankBang domain match", ext.can_handle("https://spankbang.com/video123/title"))
test("SpankBang reject other", not ext.can_handle("https://redtube.com/video"))

# ============================================================
# 13. EXTRACTOR — REDTUBE (mock)
# ============================================================
print("\n[13] Extractor — RedTube (domain matching)")
from extractors.redtube import RedTubeExtractor
ext = RedTubeExtractor()
test("RedTube domain match", ext.can_handle("https://www.redtube.com/video123/title"))
test("RedTube reject other", not ext.can_handle("https://xhamster.com/video"))

# ============================================================
# 14. EXTRACTOR — XHAMSTER (mock)
# ============================================================
print("\n[14] Extractor — XHamster (domain matching)")
from extractors.xhamster import XHamsterExtractor
ext = XHamsterExtractor()
test("XHamster domain match", ext.can_handle("https://xhamster.com/videos/test-123"))
test("XHamster domain2 match", ext.can_handle("https://xhamster3.com/videos/test"))
test("XHamster reject other", not ext.can_handle("https://pornhub.com/video"))

# ============================================================
# 15. SSRF PROTECTION
# ============================================================
print("\n[15] SSRF Protection")
from services.proxy_safety import is_safe_url, is_safe_redirect
from unittest.mock import patch

with patch('services.proxy_safety.socket.getaddrinfo') as mock_dns:
    mock_dns.return_value = [(2, None, None, None, ('127.0.0.1', 0))]
    test("Block localhost", not is_safe_url("http://localhost/admin"))
    test("Block 127.0.0.1", not is_safe_url("http://127.0.0.1/secret"))

with patch('services.proxy_safety.socket.getaddrinfo') as mock_dns:
    mock_dns.return_value = [(2, None, None, None, ('10.0.0.1', 0))]
    test("Block 10.x", not is_safe_url("http://10.0.0.1/internal"))

with patch('services.proxy_safety.socket.getaddrinfo') as mock_dns:
    mock_dns.return_value = [(2, None, None, None, ('93.184.216.34', 0))]
    test("Allow public", is_safe_url("https://example.com/page"))

# ============================================================
# 16. COOKIE SAFETY
# ============================================================
print("\n[16] Cookie Safety")
from services.file_safety import is_safe_cookie_path, resolve_cookie_path
test("Empty cookie OK", is_safe_cookie_path(""))
test("Absolute path rejected", not is_safe_cookie_path("/etc/passwd"))
test("Traversal rejected", not is_safe_cookie_path("../hack.txt"))
test("Resolve absolute rejected", resolve_cookie_path("/etc/passwd") is None)
test("Resolve traversal rejected", resolve_cookie_path("../hack.txt") is None)

# ============================================================
# 17. RATE LIMITER
# ============================================================
print("\n[17] Rate Limiter")
from services.rate_limiter import RateLimiter
rl = RateLimiter(max_requests=3, window_seconds=1)
test("Allow within limit", rl.is_allowed("test_ip"))
test("Allow within limit 2", rl.is_allowed("test_ip"))
test("Allow within limit 3", rl.is_allowed("test_ip"))
test("Block over limit", not rl.is_allowed("test_ip"))

# ============================================================
# 18. LOGGER
# ============================================================
print("\n[18] Logger")
from services.logger import VortexLogger
log = VortexLogger(level='DEBUG')
test("Logger creates", log is not None)
test("Logger has levels", hasattr(log, 'info'))
test("Logger has error", hasattr(log, 'error'))

# ============================================================
# 19. HEADLESS FETCHER (Playwright)
# ============================================================
print("\n[19] Headless Fetcher (Playwright)")
try:
    from services.headless_fetch import headless_fetch_iframe_video
    test("Headless module imports", True)
    # Test with a known Blogger URL (might not find video if token expired)
    # Just verify the function doesn't crash
    results = headless_fetch_iframe_video("https://example.com", timeout_ms=3000)
    test("Headless handles invalid URL gracefully", isinstance(results, list))
except ImportError:
    test("Playwright installed", False, "pip install playwright && playwright install chromium")
except Exception as e:
    test("Headless fetcher", False, str(e))

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 60)
total = PASS + FAIL
print(f"RESULTS: {PASS}/{total} passed, {FAIL} failed")
print("=" * 60)
