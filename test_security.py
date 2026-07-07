"""Security tests for Vortex SSRF protection, proxy safety, cookie safety, and path safety."""

import os
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from services.proxy_safety import is_safe_url, is_safe_redirect, _is_restricted_ip
from services.file_safety import is_safe_cookie_path, resolve_cookie_path, is_safe_path


class TestIsRestrictedIp(unittest.TestCase):
    def test_loopback_127(self):
        self.assertTrue(_is_restricted_ip('127.0.0.1'))

    def test_loopback_ipv6(self):
        self.assertTrue(_is_restricted_ip('::1'))

    def test_private_10(self):
        self.assertTrue(_is_restricted_ip('10.0.0.1'))

    def test_private_192_168(self):
        self.assertTrue(_is_restricted_ip('192.168.0.1'))

    def test_private_172_16(self):
        self.assertTrue(_is_restricted_ip('172.16.0.1'))

    def test_link_local(self):
        self.assertTrue(_is_restricted_ip('169.254.169.254'))

    def test_multicast(self):
        self.assertTrue(_is_restricted_ip('224.0.0.1'))

    def test_unspecified(self):
        self.assertTrue(_is_restricted_ip('0.0.0.0'))

    def test_public_ip(self):
        self.assertFalse(_is_restricted_ip('93.184.216.34'))

    def test_unparseable_returns_true(self):
        self.assertTrue(_is_restricted_ip('not-an-ip'))


class TestIsSafeUrl(unittest.TestCase):
    def test_empty_url(self):
        self.assertFalse(is_safe_url(''))
        self.assertFalse(is_safe_url(None))

    def test_non_http_scheme(self):
        self.assertFalse(is_safe_url('ftp://example.com'))
        self.assertFalse(is_safe_url('file:///etc/passwd'))

    @patch('services.proxy_safety.socket.getaddrinfo')
    def test_localhost_blocked(self, mock_dns):
        mock_dns.return_value = [(2, None, None, None, ('127.0.0.1', 0))]
        self.assertFalse(is_safe_url('http://localhost/admin'))

    @patch('services.proxy_safety.socket.getaddrinfo')
    def test_127_0_0_1_blocked(self, mock_dns):
        mock_dns.return_value = [(2, None, None, None, ('127.0.0.1', 0))]
        self.assertFalse(is_safe_url('http://127.0.0.1:8080/secret'))

    @patch('services.proxy_safety.socket.getaddrinfo')
    def test_10_0_0_1_blocked(self, mock_dns):
        mock_dns.return_value = [(2, None, None, None, ('10.0.0.1', 0))]
        self.assertFalse(is_safe_url('http://10.0.0.1/api'))

    @patch('services.proxy_safety.socket.getaddrinfo')
    def test_192_168_0_1_blocked(self, mock_dns):
        mock_dns.return_value = [(2, None, None, None, ('192.168.0.1', 0))]
        self.assertFalse(is_safe_url('http://192.168.0.1/admin'))

    @patch('services.proxy_safety.socket.getaddrinfo')
    def test_172_16_0_1_blocked(self, mock_dns):
        mock_dns.return_value = [(2, None, None, None, ('172.16.0.1', 0))]
        self.assertFalse(is_safe_url('http://172.16.0.1/internal'))

    @patch('services.proxy_safety.socket.getaddrinfo')
    def test_169_254_169_254_blocked(self, mock_dns):
        mock_dns.return_value = [(2, None, None, None, ('169.254.169.254', 0))]
        self.assertFalse(is_safe_url('http://169.254.169.254/latest/meta-data/'))

    @patch('services.proxy_safety.socket.getaddrinfo')
    def test_ipv6_loopback_blocked(self, mock_dns):
        mock_dns.return_value = [(10, None, None, None, ('::1', 0))]
        self.assertFalse(is_safe_url('http://[::1]/admin'))

    @patch('services.proxy_safety.socket.getaddrinfo')
    def test_public_url_allowed(self, mock_dns):
        mock_dns.return_value = [(2, None, None, None, ('93.184.216.34', 0))]
        self.assertTrue(is_safe_url('https://example.com/page'))

    @patch('services.proxy_safety.socket.getaddrinfo')
    def test_dns_failure_blocks(self, mock_dns):
        mock_dns.side_effect = socket.gaierror('DNS resolution failed')
        self.assertFalse(is_safe_url('http://nonexistent.invalid/path'))


class TestIsSafeRedirect(unittest.TestCase):
    @patch('services.proxy_safety.socket.getaddrinfo')
    def test_redirect_to_private_blocked(self, mock_dns):
        mock_dns.return_value = [(2, None, None, None, ('192.168.1.1', 0))]
        self.assertFalse(is_safe_redirect('http://192.168.1.1/admin'))

    @patch('services.proxy_safety.socket.getaddrinfo')
    def test_redirect_cross_host_blocked(self, mock_dns):
        mock_dns.return_value = [(2, None, None, None, ('93.184.216.34', 0))]
        self.assertFalse(
            is_safe_redirect('https://evil.com/steal', 'https://example.com/page')
        )

    @patch('services.proxy_safety.socket.getaddrinfo')
    def test_redirect_same_host_allowed(self, mock_dns):
        mock_dns.return_value = [(2, None, None, None, ('93.184.216.34', 0))]
        self.assertTrue(
            is_safe_redirect('https://example.com/other', 'https://example.com/page')
        )


class TestIsSafeCookiePath(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cookies_dir = os.path.join(self.tmpdir, 'saved_cookies')
        os.makedirs(self.cookies_dir)
        # Create a test cookie file
        self.test_cookie = os.path.join(self.cookies_dir, 'test_cookie.txt')
        with open(self.test_cookie, 'w') as f:
            f.write('# test cookies\n')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_path_is_safe(self):
        self.assertTrue(is_safe_cookie_path('', self.tmpdir))
        self.assertTrue(is_safe_cookie_path(None, self.tmpdir))

    def test_absolute_path_rejected(self):
        self.assertFalse(is_safe_cookie_path('/etc/passwd', self.tmpdir))
        self.assertFalse(is_safe_cookie_path('C:\\Windows\\System32\\config', self.tmpdir))

    def test_non_txt_rejected(self):
        self.assertFalse(is_safe_cookie_path('cookies.py', self.tmpdir))
        self.assertFalse(is_safe_cookie_path('cookies.exe', self.tmpdir))

    def test_traversal_rejected(self):
        self.assertFalse(is_safe_cookie_path('../etc/passwd.txt', self.tmpdir))
        self.assertFalse(is_safe_cookie_path('sub/../../etc/passwd.txt', self.tmpdir))

    def test_valid_cookie_accepted(self):
        self.assertTrue(is_safe_cookie_path('test_cookie.txt', self.tmpdir))

    def test_nonexistent_file_rejected(self):
        self.assertFalse(is_safe_cookie_path('does_not_exist.txt', self.tmpdir))


class TestResolveCookiePath(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cookies_dir = os.path.join(self.tmpdir, 'saved_cookies')
        os.makedirs(self.cookies_dir)
        self.test_cookie = os.path.join(self.cookies_dir, 'my_cookies.txt')
        with open(self.test_cookie, 'w') as f:
            f.write('# test\n')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_valid_cookie_id_resolves(self):
        result = resolve_cookie_path('my_cookies.txt', self.tmpdir)
        self.assertEqual(result, os.path.abspath(self.test_cookie))

    def test_absolute_path_rejected(self):
        self.assertIsNone(resolve_cookie_path('/etc/passwd', self.tmpdir))

    def test_traversal_rejected(self):
        self.assertIsNone(resolve_cookie_path('../etc/passwd.txt', self.tmpdir))

    def test_nonexistent_rejected(self):
        self.assertIsNone(resolve_cookie_path('no_such_file.txt', self.tmpdir))

    def test_non_txt_rejected(self):
        self.assertIsNone(resolve_cookie_path('script.py', self.tmpdir))

    def test_empty_returns_none(self):
        self.assertIsNone(resolve_cookie_path('', self.tmpdir))
        self.assertIsNone(resolve_cookie_path(None, self.tmpdir))


class TestIsSafePath(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.allowed = os.path.join(self.tmpdir, 'downloads')
        os.makedirs(self.allowed)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_path(self):
        self.assertFalse(is_safe_path('', [self.allowed]))

    def test_inside_allowed(self):
        filepath = os.path.join(self.allowed, 'file.mp4')
        self.assertTrue(is_safe_path(filepath, [self.allowed]))

    def test_outside_allowed(self):
        filepath = os.path.join(self.tmpdir, 'secret.txt')
        self.assertFalse(is_safe_path(filepath, [self.allowed]))

    def test_traversal_attack(self):
        filepath = os.path.join(self.allowed, '..', 'secret.txt')
        self.assertFalse(is_safe_path(filepath, [self.allowed]))

    def test_exact_dir_match(self):
        self.assertTrue(is_safe_path(self.allowed, [self.allowed]))


if __name__ == '__main__':
    unittest.main()
