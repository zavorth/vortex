"""Unit tests for site-specific extractors."""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from extractors.pornhub import PornHubExtractor
from extractors.xhamster import XHamsterExtractor
from extractors.xvideos import XVideosExtractor
from extractors.spankbang import SpankBangExtractor
from extractors.redtube import RedTubeExtractor


class TestExtractorDomainMatching(unittest.TestCase):
    """Test that each extractor matches its expected domains."""

    def test_pornhub_domains(self):
        ext = PornHubExtractor()
        self.assertTrue(ext.can_handle('https://www.pornhub.com/view_video.php?viewkey=abc'))
        self.assertTrue(ext.can_handle('https://pornhub.com/watch/xyz'))
        self.assertFalse(ext.can_handle('https://xvideos.com/video123'))

    def test_xhamster_domains(self):
        ext = XHamsterExtractor()
        self.assertTrue(ext.can_handle('https://xhamster.com/videos/some-video-123'))
        self.assertTrue(ext.can_handle('https://xhamster3.com/videos/test'))
        self.assertFalse(ext.can_handle('https://pornhub.com/video'))

    def test_xvideos_domains(self):
        ext = XVideosExtractor()
        self.assertTrue(ext.can_handle('https://www.xvideos.com/video12345/title'))
        self.assertTrue(ext.can_handle('https://xvideos2.com/video99'))
        self.assertFalse(ext.can_handle('https://redtube.com/video'))

    def test_spankbang_domains(self):
        ext = SpankBangExtractor()
        self.assertTrue(ext.can_handle('https://spankbang.com/video123/title'))
        self.assertTrue(ext.can_handle('https://www.spankbang.com/abc'))
        self.assertFalse(ext.can_handle('https://xhamster.com/video'))

    def test_redtube_domains(self):
        ext = RedTubeExtractor()
        self.assertTrue(ext.can_handle('https://www.redtube.com/video123/title'))
        self.assertTrue(ext.can_handle('https://redtube.com/watch/xyz'))
        self.assertFalse(ext.can_handle('https://pornhub.com/video'))


class TestExtractorCleanFilename(unittest.TestCase):
    """Test filename sanitization in extractors."""

    def test_pornhub_clean_filename(self):
        ext = PornHubExtractor()
        result = ext._clean_filename('Test: Video "With" <Special> Chars')
        self.assertNotIn('<', result)
        self.assertNotIn('>', result)
        self.assertNotIn('"', result)
        self.assertTrue(len(result) <= 100)

    def test_xhamster_clean_filename(self):
        ext = XHamsterExtractor()
        result = ext._clean_filename('Normal Video Title')
        self.assertEqual(result, 'Normal Video Title')

    def test_empty_title(self):
        ext = XVideosExtractor()
        result = ext._clean_filename('')
        self.assertEqual(result, 'video')


class TestExtractorExtraction(unittest.TestCase):
    """Test extraction with mock HTML responses."""

    @patch('extractors.pornhub.requests.Session')
    def test_pornhub_extracts_from_og_video(self, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '''
        <html>
        <head>
            <meta property="og:title" content="Test Video Title" />
            <meta property="og:video" content="https://example.com/video.mp4" />
            <meta property="og:image" content="https://example.com/thumb.jpg" />
        </head>
        <body></body>
        </html>
        '''
        mock_session.get.return_value = mock_response

        ext = PornHubExtractor()
        media, title = ext.extract('https://www.pornhub.com/view_video.php?viewkey=abc')

        self.assertEqual(title, 'Test Video Title')
        self.assertTrue(len(media) > 0)
        self.assertEqual(media[0]['type'], 'video')
        self.assertIn('video.mp4', media[0]['url'])

    @patch('extractors.xvideos.requests.Session')
    def test_xvideos_extracts_from_og_video(self, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '''
        <html>
        <head>
            <meta property="og:title" content="XVideos Test" />
            <meta property="og:video" content="https://example.com/xv_video.mp4" />
        </head>
        <body></body>
        </html>
        '''
        mock_session.get.return_value = mock_response

        ext = XVideosExtractor()
        media, title = ext.extract('https://www.xvideos.com/video12345/test')

        self.assertEqual(title, 'XVideos Test')
        self.assertTrue(len(media) > 0)
        self.assertEqual(media[0]['type'], 'video')

    @patch('extractors.spankbang.requests.Session')
    def test_spankbang_extracts_from_og_video(self, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '''
        <html>
        <head>
            <meta property="og:title" content="SpankBang Test" />
            <meta property="og:video" content="https://example.com/sb_video.mp4" />
        </head>
        <body></body>
        </html>
        '''
        mock_session.get.return_value = mock_response

        ext = SpankBangExtractor()
        media, title = ext.extract('https://spankbang.com/video123/test')

        self.assertEqual(title, 'SpankBang Test')
        self.assertTrue(len(media) > 0)

    @patch('extractors.redtube.requests.Session')
    def test_redtube_extracts_from_og_video(self, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '''
        <html>
        <head>
            <meta property="og:title" content="RedTube Test" />
            <meta property="og:video" content="https://example.com/rt_video.mp4" />
        </head>
        <body></body>
        </html>
        '''
        mock_session.get.return_value = mock_response

        ext = RedTubeExtractor()
        media, title = ext.extract('https://www.redtube.com/video123/test')

        self.assertEqual(title, 'RedTube Test')
        self.assertTrue(len(media) > 0)


class TestDownloadHistory(unittest.TestCase):
    """Test download history persistence."""

    def setUp(self):
        self.history_file = os.path.join(os.getcwd(), '_test_history.json')
        import services.download_history as dh
        self._orig_file = dh.HISTORY_FILE
        dh.HISTORY_FILE = self.history_file

    def tearDown(self):
        import services.download_history as dh
        dh.HISTORY_FILE = self._orig_file
        if os.path.exists(self.history_file):
            os.remove(self.history_file)

    def test_add_and_get_history(self):
        from services.download_history import add_download_record, get_history
        add_download_record('Test Video', ['file.mp4'], '/downloads', 'completed')
        history = get_history(limit=10)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['title'], 'Test Video')
        self.assertEqual(history[0]['status'], 'completed')

    def test_clear_history(self):
        from services.download_history import add_download_record, clear_history, get_history
        add_download_record('Video', ['f.mp4'], '/dl', 'completed')
        clear_history()
        history = get_history()
        self.assertEqual(len(history), 0)


if __name__ == '__main__':
    unittest.main()
