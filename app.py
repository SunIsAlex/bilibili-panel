import concurrent.futures
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import functools
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs, urlencode, quote
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError
import yt_dlp

ROOT = Path(__file__).resolve().parent
DOWNLOADS = ROOT / 'downloads'
DOWNLOADS.mkdir(exist_ok=True)
# Codex Termux may inject an older bundled libc++; use system libraries for media tools.
if 'LD_LIBRARY_PATH' in os.environ:
    paths = [p for p in os.environ['LD_LIBRARY_PATH'].split(':') if 'codex-cli-termux' not in p]
    if paths:
        os.environ['LD_LIBRARY_PATH'] = ':'.join(paths)
    else:
        os.environ.pop('LD_LIBRARY_PATH', None)

@functools.lru_cache(maxsize=1)
def media_ready():
    try:
        return all(subprocess.run([name, '-version'], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=5).returncode == 0 for name in ('ffmpeg', 'ffprobe'))
    except (OSError, subprocess.TimeoutExpired):
        return False

TOKEN = secrets.token_urlsafe(32)
LOCK = threading.RLock()
JOBS = {}
ANALYSES = {}
POOL = concurrent.futures.ThreadPoolExecutor(max_workers=2)
DEFAULT_COOKIES = Path.home() / '.config' / 'bilibili-panel' / 'cookies.txt'
COOKIES = os.environ.get('BILI_COOKIES') or (str(DEFAULT_COOKIES) if DEFAULT_COOKIES.is_file() else None)

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

def normalize_url(value):
    value = str(value).strip()
    if re.fullmatch(r'ep[1-9]\d*', value):
        value = 'https://www.bilibili.com/bangumi/play/' + value
    elif re.fullmatch(r'(BV[0-9A-Za-z]{10}|av\d+)', value):
        value = 'https://www.bilibili.com/video/' + value
    u = urlsplit(value)
    if u.scheme not in ('http', 'https') or u.username or u.password or u.port not in (None, 80, 443):
        raise ValueError('请输入有效的 Bilibili 视频链接或 BV / av / ep 号')
    if u.hostname == 'b23.tv':
        if not re.fullmatch(r'/[A-Za-z0-9]+/?', u.path):
            raise ValueError('无效的短链接')
        try:
            build_opener(NoRedirect).open(Request('https://b23.tv' + u.path), timeout=15).close()
        except HTTPError as e:
            e.close()
            if e.code not in (301, 302, 303, 307, 308):
                raise ValueError('短链接解析失败') from e
            target = e.headers.get('Location', '')
            if urlsplit(target).hostname not in ('www.bilibili.com', 'm.bilibili.com', 'bilibili.com'):
                raise ValueError('短链接未指向 Bilibili 视频')
            return normalize_url(target)
        raise ValueError('短链接未返回视频地址')
    if u.hostname not in ('www.bilibili.com', 'm.bilibili.com', 'bilibili.com'):
        raise ValueError('仅支持 bilibili.com 视频和 b23.tv 短链接')
    episode = re.fullmatch(r'/bangumi/play/(ep[1-9]\d*)/?', u.path)
    if episode:
        return f'https://www.bilibili.com/bangumi/play/{episode[1]}'
    match = re.fullmatch(r'/video/(BV[0-9A-Za-z]{10}|av\d+)/?', u.path)
    if not match:
        raise ValueError('支持 BV / av 普通视频与 /bangumi/play/ep… 单集链接；请勿使用整季或直播链接')
    p = parse_qs(u.query).get('p', ['1'])[0]
    if not p.isdigit() or not 1 <= int(p) <= 10000:
        raise ValueError('分 P 参数无效')
    return f'https://www.bilibili.com/video/{match[1]}?' + urlencode({'p': int(p)})

class QuietLogger:
    def __init__(self):
        self.warnings = []
    def debug(self, msg): pass
    def warning(self, msg):
        self.warnings.append(clean_error(msg))
    def error(self, msg): pass

def options():
    result = dict(quiet=True, logger=QuietLogger(), noplaylist=True, socket_timeout=20,
                  retries=2, fragment_retries=2, cachedir=False)
    if COOKIES:
        result['cookiefile'] = COOKIES
    return result

def analyze(url):
    opts = options()
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info or info.get('_type') in ('playlist', 'multi_video'):
        raise ValueError('请使用单个视频、带 p 参数的分 P 链接或 ep 单集链接')
    formats = []
    selectors = {}
    for f in reversed(info.get('formats', [])):
        if f.get('vcodec') == 'none' or not f.get('format_id'):
            continue
        key = secrets.token_hex(8)
        fid = f['format_id']
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', fid):
            continue
        selectors[key] = fid + ('+bestaudio' if f.get('acodec') == 'none' else '')
        formats.append(dict(key=key, height=f.get('height'), fps=f.get('fps'),
                            codec=f.get('vcodec'), ext=f.get('ext'),
                            note=f.get('format_note') or f.get('format'),
                            size=f.get('filesize') or f.get('filesize_approx')))
    if not formats:
        raise ValueError('没有可下载的视频流；该视频可能需要登录或相应权限')
    aid = secrets.token_hex(16)
    title = info.get('title') or info.get('id')
    if info.get('episode_id'):
        title = ' · '.join(str(part) for part in (info.get('series') or info.get('season'),
                                                title, 'ep' + info['episode_id']) if part)
    result = dict(id=aid, title=title, uploader=info.get('uploader') or info.get('series'),
                  duration=info.get('duration'), thumbnail=info.get('thumbnail'), formats=formats,
                  warnings=opts['logger'].warnings)
    with LOCK:
        now = time.time()
        for old in list(ANALYSES):
            if now - ANALYSES[old]['time'] > 1800:
                del ANALYSES[old]
        if len(ANALYSES) >= 100:
            del ANALYSES[next(iter(ANALYSES))]
        ANALYSES[aid] = dict(url=url, selectors=selectors, title=result['title'], thumbnail=result['thumbnail'], time=now)
    return result

def update(jid, **data):
    with LOCK:
        JOBS[jid].update(data)

def download(jid, url, selector):
    folder = DOWNLOADS / jid
    folder.mkdir()
    def progress(d):
        total = d.get('total_bytes') or d.get('total_bytes_estimate')
        update(jid, status='merging' if d['status'] == 'finished' else 'downloading',
               progress=min(99, round(d.get('downloaded_bytes', 0) / total * 100, 1)) if total else 0,
               speed=d.get('speed'), eta=d.get('eta'))
    opts = options() | dict(format=selector, outtmpl=str(folder / '%(title).120B [%(id)s].%(ext)s'),
                            merge_output_format='mkv', progress_hooks=[progress])
    try:
        update(jid, status='downloading')
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=True)
        files = [p for p in folder.iterdir() if p.suffix in ('.mkv', '.mp4', '.flv', '.webm') and not re.search(r'\.f[\w-]+\.', p.name)]
        if len(files) != 1:
            raise ValueError('未找到完整的合并文件')
        update(jid, status='done', progress=100, filename=files[0].name, size=files[0].stat().st_size)
    except Exception as e:
        update(jid, status='error', error=clean_error(e))

def clean_error(e):
    message = re.sub(r'https?://\S+', '[链接]', str(e))
    return message[:600]

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def send_bytes(self, body, content_type, status=200):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.end_headers()
        self.wfile.write(body)
    def json(self, data, status=200):
        self.send_bytes(json.dumps(data, ensure_ascii=False).encode(), 'application/json; charset=utf-8', status)
    def valid_host(self):
        return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')
    def do_GET(self):
        if not self.valid_host():
            return self.json({'error': '不允许的 Host'}, 403)
        path = urlsplit(self.path).path
        if path == '/api/state':
            with LOCK:
                return self.json(dict(token=TOKEN, ffmpeg=media_ready(), cookies=bool(COOKIES), jobs=list(JOBS.values())[::-1]))
        if path.startswith('/api/files/'):
            jid = path.rsplit('/', 1)[-1]
            with LOCK:
                job = JOBS.get(jid, {}).copy()
            if job.get('status') != 'done':
                return self.json({'error': '文件不存在'}, 404)
            file = DOWNLOADS / jid / job['filename']
            if not file.is_file():
                return self.json({'error': '文件已移除'}, 404)
            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Length', str(file.stat().st_size))
            self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + quote(file.name))
            self.end_headers()
            try:
                with file.open('rb') as f:
                    shutil.copyfileobj(f, self.wfile)
            except (BrokenPipeError, ConnectionResetError): pass
            return
        names = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}
        if path not in names:
            return self.json({'error': '未找到'}, 404)
        mime = {'/': 'text/html', '/app.js': 'text/javascript', '/style.css': 'text/css'}[path]
        self.send_bytes((ROOT / 'static' / names[path]).read_bytes(), mime + '; charset=utf-8')
    def do_POST(self):
        if not self.valid_host() or self.headers.get('X-Panel-Token') != TOKEN:
            return self.json({'error': '请刷新面板后重试'}, 403)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 8192:
                raise ValueError('请求大小无效')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('请求格式无效')
            if self.path == '/api/analyze':
                return self.json(analyze(normalize_url(data.get('url', ''))))
            if self.path == '/api/download':
                if not media_ready():
                    raise ValueError('FFmpeg / ffprobe 不可运行，请检查安装及动态库环境后重启服务')
                with LOCK:
                    analysis = ANALYSES.get(str(data.get('id')))
                    if not analysis or time.time() - analysis['time'] > 1800:
                        raise ValueError('解析结果已过期，请重新解析')
                    selector = analysis['selectors'].get(str(data.get('format')))
                    if not selector:
                        raise ValueError('请选择有效的画质')
                    if sum(j['status'] not in ('done', 'error') for j in JOBS.values()) >= 10:
                        raise ValueError('下载队列已满，请稍后重试')
                    jid = secrets.token_hex(12)
                    JOBS[jid] = dict(id=jid, title=analysis['title'], thumbnail=analysis.get('thumbnail'), status='queued', progress=0)
                    POOL.submit(download, jid, analysis['url'], selector)
                return self.json({'id': jid}, 202)
            return self.json({'error': '未找到'}, 404)
        except (ValueError, yt_dlp.utils.DownloadError) as e:
            return self.json({'error': clean_error(e)}, 400)
        except Exception as e:
            return self.json({'error': clean_error(e)}, 502)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8765'))
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(f'Bilibili 面板已启动：http://127.0.0.1:{port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
