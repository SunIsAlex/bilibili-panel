# Bilibili 本地视频工作台

Python + yt-dlp + FFmpeg，无前端构建步骤。支持 BV / av / ep 号、b23.tv 短链接、番剧与影视单集、指定分 P、可用画质选择、双任务并发队列、进度和文件保存。

## 启动

```sh
cd /data/data/com.termux/files/home/bilibili-panel
python -m venv .venv
.venv/bin/pip install -r requirements.txt
# Termux：pkg install ffmpeg
# Ubuntu / Debian：sudo apt install ffmpeg
.venv/bin/python app.py
```

打开 http://127.0.0.1:8765 。环境变量 PORT 可修改端口。仅监听本机，不适合直接发布到公网。

## 登录与使用

未配置 Cookie 时使用访客模式。默认读取 `~/.config/bilibili-panel/cookies.txt`（Netscape 格式）；也可从自己的浏览器导出 Cookie，启动时指定其他路径：

```sh
BILI_COOKIES=/absolute/path/cookies.txt .venv/bin/python app.py
```

Cookie 仅由本地后端读取，请妥善保管。建议凭据目录权限设为 700、文件权限设为 600，文件不要放入版本库。默认文件存在时重启即可加载；失效后需更新。仅获取账号有权访问的视频，不绕过付费、地区或 DRM 限制。

解析链接、选择画质并加入队列。文件保存到 `downloads/<任务ID>/`，完成后点击“保存文件”下载到浏览器。队列和解析结果保存在内存中，重启清空，已下载文件保留，磁盘需自行清理。解析结果有效 30 分钟，下载时重新获取流地址。多 P 用 `?p=2` 指定，不批量下载整套合集；支持 `https://www.bilibili.com/bangumi/play/ep775939`、`https://b23.tv/ep775939` 和 `ep775939` 这类单集链接；不支持直播或整季 ss / md 链接。部分单集需要登录或大会员，仍受账号权限与地区限制。若解析器仅获取到试看流，其警告会显示在画质选择上方。

## 视频格式分析

DASH 包含独立的视频、音频轨；视频可能是 AVC、HEVC 或 AV1，音频可能是 AAC、杜比或 FLAC。旧式 durl 也可能包含多个片段。实际格式取决于视频和账号权限。容器与编码不同，单个视频轨通常没有声音。

采用 yt-dlp 的 Bilibili extractor 处理 WBI 签名、请求头和格式枚举。选择独立视频轨时配对最佳音轨，FFmpeg 无重编码合并到 MKV；完整音视频文件保留原容器。MKV 可保存多种编码，建议用本地播放器播放。

进度是当前流的进度，切换音轨时会重新计数，合并阶段无准确百分比。界面只展示实际返回格式，不承诺访客获得高清画质。平台风控、登录、网络或接口变化会导致失败，可按错误排查或更新 yt-dlp。

来源：[yt-dlp Bilibili 解析器](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/bilibili.py)、[yt-dlp 文档](https://github.com/yt-dlp/yt-dlp#readme)。

## 验证与范围

```sh
.venv/bin/python -m unittest discover -s tests -v
node --check static/app.js
```

后端限定输入域名、普通视频及 ep 单集路径、格式和下载目录；校验本机 Host 与页面令牌。最多两个并发下载、十个未完成任务。用于可信本机用户，未提供多用户认证、持久任务、下载取消或磁盘配额。

## 本机实测

已通过 10 项自动测试、JavaScript 语法检查和 Chromium 无头浏览器页面检查。使用 av170001 的第 1 P 完成真实解析、下载与合并；ffprobe 验证输出包含 HEVC 视频和 AAC 音频，文件下载接口的 SHA-256 与磁盘文件一致。此结果不代表所有视频、账号和网络环境均可下载。

Termux 环境若从 Codex 启动时注入旧版动态库路径，程序仅移除其中 `codex-cli-termux` 路径，避免 FFmpeg 加载不兼容的 libc++。环境状态通过实际执行 ffmpeg 与 ffprobe 检测；安装或修复依赖后请重启服务。

已实测 `https://b23.tv/ep775939`：访客模式成功解析并完整下载，合并文件含 AV1 视频与 AAC 音频，时长 3304.576 秒，大小 101,271,750 字节。该次请求未返回试看警告；其他剧集是否可下载取决于实际账号权限和平台响应。
