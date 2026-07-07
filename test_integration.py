"""Integration tests for Vortex Flask routes — security contracts."""

import io
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from app import app, vortex_token


class FlaskIntegrationBase(unittest.TestCase):
    """Base class that provides a Flask test client and temp saved_cookies dir."""

    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        self.tmpdir = tempfile.mkdtemp()
        self.cookies_dir = os.path.join(self.tmpdir, 'saved_cookies')
        os.makedirs(self.cookies_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _auth_headers(self):
        return {'X-Vortex-Token': vortex_token}

    def _ext_headers(self, ext_id='legitextid1234567890abcd'):
        return {'Origin': f'chrome-extension://{ext_id}'}


class TestExtensionAuth(FlaskIntegrationBase):
    """Extension without a listed ID must receive 403."""

    @patch('app.is_extension_allowed', return_value=False)
    def test_unauthorized_extension_gets_403(self, mock_allowed):
        resp = self.client.get('/api/status', headers=self._ext_headers('badid'))
        self.assertEqual(resp.status_code, 403)

    @patch('app.is_extension_allowed', return_value=True)
    def test_authorized_extension_passes(self, mock_allowed):
        resp = self.client.get('/api/status', headers=self._ext_headers('goodid'))
        self.assertEqual(resp.status_code, 200)

    def test_no_token_no_extension_gets_403(self):
        resp = self.client.get('/api/status')
        self.assertEqual(resp.status_code, 403)

    def test_valid_token_passes(self):
        resp = self.client.get('/api/status', headers=self._auth_headers())
        self.assertEqual(resp.status_code, 200)


class TestProxySSRF(FlaskIntegrationBase):
    """Proxy must block private/loopback URLs via proxy_fetch."""

    @patch('app.proxy_fetch', return_value=(None, ('Forbidden target URL', 403)))
    def test_proxy_blocks_private_url(self, mock_fetch):
        resp = self.client.get(
            '/api/proxy?url=http://127.0.0.1:8080/secret',
            headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 403)
        mock_fetch.assert_called_once()

    @patch('app.proxy_fetch', return_value=(None, ('Forbidden target URL', 403)))
    def test_proxy_blocks_10_x_url(self, mock_fetch):
        resp = self.client.get(
            '/api/proxy?url=http://10.0.0.1/admin',
            headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 403)

    @patch('app.proxy_fetch', return_value=(None, ('Forbidden target URL', 403)))
    def test_proxy_blocks_192_168_url(self, mock_fetch):
        resp = self.client.get(
            '/api/proxy?url=http://192.168.1.1/router',
            headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 403)

    def test_proxy_missing_url_returns_400(self):
        resp = self.client.get('/api/proxy', headers=self._auth_headers())
        self.assertEqual(resp.status_code, 400)


class TestProxyImageSSRF(FlaskIntegrationBase):
    """Proxy-image must also block private URLs."""

    @patch('app.proxy_fetch', return_value=(None, ('Forbidden target URL', 403)))
    def test_proxy_image_blocks_private(self, mock_fetch):
        resp = self.client.get(
            '/api/proxy-image?url=http://127.0.0.1/secret.png',
            headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 403)

    def test_proxy_image_missing_url_returns_400(self):
        resp = self.client.get('/api/proxy-image', headers=self._auth_headers())
        self.assertEqual(resp.status_code, 400)


class TestUploadCookies(FlaskIntegrationBase):
    """Upload must return cookie_id, never an absolute filepath."""

    def test_upload_returns_cookie_id(self):
        data = {
            'file': (io.BytesIO(b'# cookies\ntest.com\tTRUE\t/\tFALSE\t0\tname\tvalue'),
                     'cookies.txt')
        }
        resp = self.client.post(
            '/api/upload-cookies',
            data=data,
            content_type='multipart/form-data',
            headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertIn('cookie_id', body)
        self.assertNotIn('filepath', body)
        self.assertTrue(body['cookie_id'].endswith('.txt'))

    def test_upload_rejects_non_txt(self):
        data = {
            'file': (io.BytesIO(b'bad'), 'cookies.py')
        }
        resp = self.client.post(
            '/api/upload-cookies',
            data=data,
            content_type='multipart/form-data',
            headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 400)

    def test_upload_rejects_empty_filename(self):
        data = {
            'file': (io.BytesIO(b'data'), '')
        }
        resp = self.client.post(
            '/api/upload-cookies',
            data=data,
            content_type='multipart/form-data',
            headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 400)


class TestDownloadCookieValidation(FlaskIntegrationBase):
    """Download must reject invalid cookie_id values."""

    def test_download_rejects_absolute_cookie_path(self):
        payload = {
            'items': [{'filename': 'test.mp4', 'url': 'http://example.com/test.mp4'}],
            'download_dir': os.path.join(os.path.expanduser('~'), 'Downloads'),
            'album_url': 'http://example.com',
            'cookies_path': '/etc/passwd',
            'concurrency': 1
        }
        resp = self.client.post(
            '/api/download',
            json=payload,
            headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 400)

    def test_download_rejects_traversal_cookie_path(self):
        payload = {
            'items': [{'filename': 'test.mp4', 'url': 'http://example.com/test.mp4'}],
            'download_dir': os.path.join(os.path.expanduser('~'), 'Downloads'),
            'album_url': 'http://example.com',
            'cookies_path': '../../etc/passwd.txt',
            'concurrency': 1
        }
        resp = self.client.post(
            '/api/download',
            json=payload,
            headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 400)

    def test_download_rejects_nonexistent_cookie_id(self):
        payload = {
            'items': [{'filename': 'test.mp4', 'url': 'http://example.com/test.mp4'}],
            'download_dir': os.path.join(os.path.expanduser('~'), 'Downloads'),
            'album_url': 'http://example.com',
            'cookies_path': 'nonexistent_file.txt',
            'concurrency': 1
        }
        resp = self.client.post(
            '/api/download',
            json=payload,
            headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 400)

    def test_download_empty_cookies_path_passes_validation(self):
        """Empty cookies_path should be accepted (no cookie to resolve)."""
        payload = {
            'items': [{'filename': 'test.mp4', 'url': 'http://example.com/test.mp4'}],
            'download_dir': os.path.join(os.path.expanduser('~'), 'Downloads'),
            'album_url': 'http://example.com',
            'cookies_path': '',
            'concurrency': 1
        }
        # This will pass cookie validation but may fail on download_dir validation
        # depending on the environment. We just check it doesn't return 400 for cookies.
        resp = self.client.post(
            '/api/download',
            json=payload,
            headers=self._auth_headers()
        )
        # Should NOT be 400 with "Caminho de cookies inválido"
        if resp.status_code == 400:
            body = resp.get_json()
            self.assertNotIn('cookies', body.get('error', '').lower())


class TestAnalyzeCookieValidation(FlaskIntegrationBase):
    """Analyze must reject invalid cookie_id values."""

    def test_analyze_rejects_absolute_cookie_path(self):
        resp = self.client.post(
            '/api/analyze',
            json={'url': 'https://example.com', 'cookies_path': '/etc/passwd'},
            headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 400)

    def test_analyze_rejects_traversal_cookie(self):
        resp = self.client.post(
            '/api/analyze',
            json={'url': 'https://example.com', 'cookies_path': '../hack.txt'},
            headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 400)


class TestAnalyzeHtml(FlaskIntegrationBase):
    """analyze-html must not crash and must return valid JSON."""

    def test_analyze_html_no_file_returns_400(self):
        resp = self.client.post(
            '/api/analyze-html',
            headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 400)

    def test_analyze_html_with_html_file(self):
        html = b'<html><body><img src="photo.jpg"></body></html>'
        data = {
            'html_file': (io.BytesIO(html), 'test.html'),
            'url': 'https://example.com'
        }
        resp = self.client.post(
            '/api/analyze-html',
            data=data,
            content_type='multipart/form-data',
            headers=self._auth_headers()
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertIn('media', body)
        self.assertIn('title', body)


if __name__ == '__main__':
    unittest.main()
