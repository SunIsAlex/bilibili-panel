const $ = id => document.getElementById(id);
let token, analysis;
const statuses = {queued:'等待下载',downloading:'下载中',merging:'合并 / 处理中',done:'已完成',error:'下载失败'};
const size = n => n ? (n/1048576).toFixed(1)+' MB' : '大小未知';
function error(s){$('error').textContent=s;$('error').hidden=!s;}
function el(tag,cls,text){const e=document.createElement(tag);e.className=cls;if(text!=null)e.textContent=text;return e;}
async function api(path,data){const r=await fetch(path,data?{method:'POST',headers:{'Content-Type':'application/json','X-Panel-Token':token},body:JSON.stringify(data)}:{});const d=await r.json();if(!r.ok)throw new Error(d.error||'请求失败');return d;}
function updateThumbnail(row, value) {
  let source = '';
  try {
    const url = new URL(value);
    if (url.protocol === 'https:' || url.protocol === 'http:') source = url.href;
  } catch {}
  if (row.dataset.thumbnail === source) return;
  row.dataset.thumbnail = source;
  const cover = row.querySelector('.job-cover');
  cover.replaceChildren(el('span', 'cover-placeholder', '暂无封面'));
  if (!source) return;
  const img = el('img', 'job-thumbnail');
  img.alt = '视频封面';
  img.loading = 'lazy';
  img.decoding = 'async';
  img.referrerPolicy = 'no-referrer';
  img.addEventListener('load', () => { cover.querySelector('.cover-placeholder')?.remove(); });
  img.addEventListener('error', () => { img.remove(); });
  img.src = source;
  cover.append(img);
}
async function refresh() {
  try {
    const s = await api('/api/state');
    token = s.token;
    $('health').textContent = `${s.ffmpeg ? '● FFmpeg 已就绪' : '○ 缺少 FFmpeg'} · ${s.cookies ? '已配置 Cookie' : '访客模式'}`;
    $('count').textContent = s.jobs.length + ' 个任务';
    if (!s.jobs.length) return;
    $('jobs').querySelector('.empty')?.remove();
    const existing = new Map([...$('jobs').children].map(row => [row.dataset.id, row]));
    for (const [index, j] of s.jobs.entries()) {
      let row = existing.get(j.id);
      if (!row) {
        row = el('div', 'job');
        row.dataset.id = j.id;
        row.append(el('div', 'job-cover'), el('div', 'job-body'));
      }
      existing.delete(j.id);
      updateThumbnail(row, j.thumbnail);
      const top = el('div', 'job-top'), track = el('div', 'track'), bar = el('div', 'bar');
      top.append(el('span', 'job-title', j.title), el('span', 'badge', statuses[j.status]));
      bar.style.width = (j.progress || 0) + '%';
      track.append(bar);
      const detail = j.status === 'error' ? j.error : j.status === 'done' ? size(j.size) : j.status === 'merging' ? '正在准备或合并音视频…' : `当前流 ${j.progress || 0}%${j.speed ? ' · ' + size(j.speed) + '/s' : ''}${j.eta != null ? ' · 约 ' + j.eta + ' 秒' : ''}`;
      const body = row.querySelector('.job-body');
      body.replaceChildren(top, track, el('div', 'detail', detail));
      if (j.mode === 'subtitles') body.append(el('div', 'task-mode', '仅字幕'));
      if (j.status === 'done') {
        if (j.filename) {
          const a = el('a', 'save', '保存视频 ↓');
          a.href = '/api/files/' + j.id;
          body.append(a);
        }
        const subtitles = el('div', 'subtitle-files');
        for (const f of j.subtitle_files || []) {
          const a = el('a', 'save save-subtitle', `${f.language} · ${f.filename.split('.').pop().toUpperCase()} ↓`);
          a.href = '/api/files/' + j.id + '?subtitle=' + encodeURIComponent(f.id);
          subtitles.append(a);
        }
        body.append(subtitles);
      }
      if ($('jobs').children[index] !== row) $('jobs').insertBefore(row, $('jobs').children[index] || null);
    }
    for (const row of existing.values()) row.remove();
  } catch (e) {
    $('health').textContent = '○ 无法连接服务，请检查后端';
  }
}
$('form').addEventListener('submit',async e=>{e.preventDefault();error('');$('analyze').disabled=true;$('analyze').textContent='正在解析…';$('preview').hidden=true;analysis=null;try{if(!token)await refresh();analysis=await api('/api/analyze',{url:$('url').value});$('title').textContent=analysis.title;$('warnings').textContent=(analysis.warnings||[]).join('；');$('warnings').hidden=!analysis.warnings?.length;$('meta').textContent=`${analysis.uploader||'未知 UP 主'} · ${Math.floor((analysis.duration||0)/60)} 分 ${Math.round((analysis.duration||0)%60)} 秒`;$('formats').replaceChildren();for(const f of analysis.formats){const o=document.createElement('option');o.value=f.key;o.textContent=`${f.note||(f.height?f.height+'p':'原画')} · ${f.codec||f.ext||'视频'}${f.fps?' · '+f.fps+' fps':''} · ${size(f.size)}`;$('formats').append(o);}renderSubtitles(analysis.subtitles || []);$('preview').hidden=false;}catch(e){error(e.message);}finally{$('analyze').disabled=false;$('analyze').textContent='解析视频 ↗';}});
function selectedSubtitles() {
  return [...$('subtitle-options').querySelectorAll('input:checked')].map(input => input.value);
}
function renderSubtitles(tracks) {
  $('subtitle-options').replaceChildren();
  for (const track of tracks) {
    const label = el('label', 'subtitle-choice');
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.value = track.language;
    input.addEventListener('change', () => { $('download-subtitles').disabled = !selectedSubtitles().length; });
    label.append(input, el('span', '', `${track.name} · ${track.formats.join(' / ').toUpperCase()}`));
    $('subtitle-options').append(label);
  }
  $('subtitle-hint').textContent = tracks.length ? '勾选后可随视频保存，也可仅下载字幕；字幕为独立文件。' : '未发现可下载的外挂字幕。画面内嵌字幕无法直接提取，部分字幕需要登录。';
  $('download-subtitles').disabled = true;
}
async function enqueue(mode) {
  if (!analysis) return;
  error('');
  $('download').disabled = true;
  $('download-subtitles').disabled = true;
  try {
    await api('/api/download', {id:analysis.id, format:$('formats').value, mode, subtitles:selectedSubtitles()});
    await refresh();
    $('jobs').scrollIntoView({behavior:'smooth',block:'nearest'});
  } catch(e) { error(e.message); }
  finally {
    $('download').disabled = false;
    $('download-subtitles').disabled = !selectedSubtitles().length;
  }
}
$('download').addEventListener('click', () => enqueue('video'));
$('download-subtitles').addEventListener('click', () => enqueue('subtitles'));
async function poll(){await refresh();setTimeout(poll,1500);}poll();
