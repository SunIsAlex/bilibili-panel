import unittest
from unittest.mock import patch
import tempfile
from pathlib import Path
import app
import io
import json
from urllib.error import HTTPError

class PanelTests(unittest.TestCase):
    def test_share_text(self):
        self.assertEqual(app.normalize_url('【电影分享】https://www.bilibili.com/bangumi/play/ep810659'),
                         'https://www.bilibili.com/bangumi/play/ep810659')
        self.assertEqual(app.normalize_url('看看这个 https://www.bilibili.com/video/av170001?p=2。'),
                         'https://www.bilibili.com/video/av170001?p=2')
        with self.assertRaises(ValueError):
            app.normalize_url('https://b23.tv/one https://b23.tv/two')
    def test_episode_drm_error(self):
        with patch('app.yt_dlp.YoutubeDL') as y:
            instance = y.return_value.__enter__.return_value
            instance.extract_info.side_effect = app.yt_dlp.utils.DownloadError('No video formats found')
            instance.urlopen.return_value = io.BytesIO(json.dumps({'result': {'video_info': {'is_drm': True}}}).encode())
            with self.assertRaisesRegex(ValueError, 'DRM'):
                app.analyze('https://www.bilibili.com/bangumi/play/ep810659')
    def test_episode_diagnostic_failure_preserves_error(self):
        with patch('app.yt_dlp.YoutubeDL') as y:
            instance = y.return_value.__enter__.return_value
            instance.extract_info.side_effect = app.yt_dlp.utils.DownloadError('original error')
            instance.urlopen.side_effect = OSError('diagnostic failed')
            with self.assertRaisesRegex(app.yt_dlp.utils.DownloadError, 'original error'):
                app.analyze('https://www.bilibili.com/bangumi/play/ep810659')
    def test_non_drm_preserves_error(self):
        with patch('app.yt_dlp.YoutubeDL') as y:
            instance = y.return_value.__enter__.return_value
            instance.extract_info.side_effect = app.yt_dlp.utils.DownloadError('original error')
            instance.urlopen.return_value = io.BytesIO(b'{"result":{"video_info":{"is_drm":false}}}')
            with self.assertRaisesRegex(app.yt_dlp.utils.DownloadError, 'original error'):
                app.analyze('https://www.bilibili.com/bangumi/play/ep810659')
    def test_urls(self):
        self.assertEqual(app.normalize_url('BV1xx411c7mD'),'https://www.bilibili.com/video/BV1xx411c7mD?p=1')
        self.assertEqual(app.normalize_url('https://www.bilibili.com/video/av170001?p=2&x=y'),'https://www.bilibili.com/video/av170001?p=2')
    def test_rejected_urls(self):
        for url in ['http://127.0.0.1/video/av1','https://bilibili.com.evil.org/video/av1','file:///etc/passwd','https://u@www.bilibili.com/video/av1','https://www.bilibili.com:999/video/av1','https://www.bilibili.com/video/av1?p=-1']:
            with self.subTest(url=url),self.assertRaises(ValueError):app.normalize_url(url)
    def test_episode_urls(self):
        expected = 'https://www.bilibili.com/bangumi/play/ep775939'
        for value in ['ep775939', expected, expected + '/?from=share',
                      'https://m.bilibili.com/bangumi/play/ep775939']:
            with self.subTest(value=value):
                self.assertEqual(app.normalize_url(value), expected)
    def test_episode_short_link(self):
        target = 'https://www.bilibili.com/bangumi/play/ep775939'
        with patch('app.build_opener') as opener:
            opener.return_value.open.side_effect = HTTPError('https://b23.tv/ep775939', 302, '', {'Location': target}, None)
            self.assertEqual(app.normalize_url('https://b23.tv/ep775939'), target)
    def test_short_link_rejects_external_redirect(self):
        with patch('app.build_opener') as opener:
            opener.return_value.open.side_effect = HTTPError('https://b23.tv/test', 302, '', {'Location': 'http://127.0.0.1/private'}, None)
            with self.assertRaises(ValueError):
                app.normalize_url('https://b23.tv/test')
    def test_rejected_episode_urls(self):
        for value in ['https://www.bilibili.com/bangumi/play/ss123',
                      'https://www.bilibili.com/bangumi/play/ep0',
                      'https://www.bilibili.com/bangumi/play/ep775939/extra',
                      'https://www.bilibili.com.evil.org/bangumi/play/ep775939']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                app.normalize_url(value)
    def test_episode_warning_and_title(self):
        info = {'id': '775939', 'episode_id': '775939', 'title': '1', 'series': '测试剧集',
                'formats': [{'format_id': '30011', 'vcodec': 'hevc', 'acodec': 'none'}]}
        with patch('app.yt_dlp.YoutubeDL') as y:
            def extract(*args, **kwargs):
                y.call_args.args[0]['logger'].warning('Only preview format is available')
                return info
            y.return_value.__enter__.return_value.extract_info.side_effect = extract
            result = app.analyze('https://www.bilibili.com/bangumi/play/ep775939')
        self.assertEqual(result['title'], '测试剧集 · 1 · ep775939')
        self.assertEqual(result['warnings'], ['Only preview format is available'])
    def test_formats(self):
        info={'title':'test','formats':[{'format_id':'30280','vcodec':'none'},{'format_id':'100026','vcodec':'avc1','acodec':'none'},{'format_id':'18','vcodec':'avc1','acodec':'aac'}]}
        with patch('app.yt_dlp.YoutubeDL') as y:
            y.return_value.__enter__.return_value.extract_info.return_value=info
            result=app.analyze('https://www.bilibili.com/video/av1')
        self.assertEqual(len(result['formats']),2)
        self.assertEqual(set(app.ANALYSES[result['id']]['selectors'].values()),{'100026+bestaudio','18'})
    def test_download(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(app,'DOWNLOADS',Path(tmp)),patch('app.yt_dlp.YoutubeDL') as y:
            app.JOBS['test']={'status':'queued'}
            def fake(*args,**kwargs):(Path(tmp)/'test'/'video.mkv').write_bytes(b'video')
            y.return_value.__enter__.return_value.extract_info.side_effect=fake
            app.download('test','https://www.bilibili.com/video/av1','18')
            self.assertEqual(app.JOBS['test']['status'],'done')
    def test_failure(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(app,'DOWNLOADS',Path(tmp)),patch('app.yt_dlp.YoutubeDL') as y:
            app.JOBS['fail']={'status':'queued'}
            y.return_value.__enter__.return_value.extract_info.side_effect=RuntimeError('network failed')
            app.download('fail','https://www.bilibili.com/video/av1','18')
            self.assertEqual(app.JOBS['fail']['status'],'error')
if __name__=='__main__':unittest.main()
