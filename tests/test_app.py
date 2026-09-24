import unittest
from unittest.mock import patch
import tempfile
from pathlib import Path
import app

class PanelTests(unittest.TestCase):
    def test_urls(self):
        self.assertEqual(app.normalize_url('BV1xx411c7mD'),'https://www.bilibili.com/video/BV1xx411c7mD?p=1')
        self.assertEqual(app.normalize_url('https://www.bilibili.com/video/av170001?p=2&x=y'),'https://www.bilibili.com/video/av170001?p=2')
    def test_rejected_urls(self):
        for url in ['http://127.0.0.1/video/av1','https://bilibili.com.evil.org/video/av1','file:///etc/passwd','https://u@www.bilibili.com/video/av1','https://www.bilibili.com:999/video/av1','https://www.bilibili.com/video/av1?p=-1']:
            with self.subTest(url=url),self.assertRaises(ValueError):app.normalize_url(url)
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
