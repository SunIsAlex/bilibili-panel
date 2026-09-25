const $ = id => document.getElementById(id);
let token, analysis;
let collectionItems = [], batchRunning = false, collectionLoading = false, stopBatch = false;
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
$('form').addEventListener('submit',async e=>{e.preventDefault();if(batchRunning||collectionLoading)return;if($('url').value.includes('合集')||$('url').value.includes('space.bilibili.com/')){await loadCollection();return;}error('');$('analyze').disabled=true;$('analyze').textContent='正在解析…';$('preview').hidden=true;analysis=null;try{if(!token)await refresh();analysis=await api('/api/analyze',{url:$('url').value});$('title').textContent=analysis.title;$('warnings').textContent=(analysis.warnings||[]).join('；');$('warnings').hidden=!analysis.warnings?.length;$('meta').textContent=`${analysis.uploader||'未知 UP 主'} · ${Math.floor((analysis.duration||0)/60)} 分 ${Math.round((analysis.duration||0)%60)} 秒`;$('formats').replaceChildren();for(const f of analysis.formats){const o=document.createElement('option');o.value=f.key;o.textContent=`${f.note||(f.height?f.height+'p':'原画')} · ${f.codec||f.ext||'视频'}${f.fps?' · '+f.fps+' fps':''} · ${size(f.size)}`;$('formats').append(o);}renderSubtitles(analysis.subtitles || []);$('preview').hidden=false;}catch(e){error(e.message);}finally{$('analyze').disabled=false;$('analyze').textContent='解析视频 ↗';}});
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

async function loadCollection() {
  if (batchRunning || collectionLoading) return;
  collectionLoading = true;
  error('');
  $('collection-load').disabled = true;
  $('analyze').disabled = true;
  $('collection-parse').disabled = true;
  $('collection-load').textContent = '读取合集…';
  try {
    if (!token) await refresh();
    const result = await api('/api/collection', {url:$('url').value});
    $('collection-title').textContent = `${result.title} · ${result.total} 个视频`;
    $('collection-items').replaceChildren();
    collectionItems = result.entries.map((entry, index) => {
      const row = el('div', 'collection-item'), label = el('label', '');
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox'; checkbox.checked = true;
      label.append(checkbox, el('span', '', `${index + 1}. ${entry.title}`));
      const state = el('div', 'collection-state', '等待解析'), detail = el('div', 'collection-detail');
      row.append(label, state, detail); $('collection-items').append(row);
      return {entry, checkbox, state, detail, analysis:null};
    });
    $('collection-all').checked = true;
    $('collection-progress').textContent = '已读取目录，勾选后解析画质';
    $('collection-panel').hidden = false;
    $('collection-panel').scrollIntoView({behavior:'smooth', block:'start'});
  } catch(e) { error(e.message); }
  finally {
    collectionLoading = false;
    $('collection-load').disabled = false;
    $('analyze').disabled = false;
    $('collection-parse').disabled = false;
    $('collection-load').textContent = '解析合集';
  }
}
function renderCollectionAnalysis(item, info) {
  item.detail.replaceChildren();
  const select = document.createElement('select'); select.setAttribute('aria-label', item.entry.title + ' 画质');
  for (const f of info.formats) {
    const option = document.createElement('option'); option.value = f.key;
    option.textContent = `${f.note || f.height + 'p'} · ${f.codec || f.ext} · ${size(f.size)}`;
    select.append(option);
  }
  const row = el('div', 'row'), download = el('button', '', '加入下载队列 ↓'); download.type = 'button';
  row.append(select, download);
  const subs = el('div', 'collection-subtitles');
  for (const track of info.subtitles || []) {
    const label = el('label', ''), checkbox = document.createElement('input');
    checkbox.type = 'checkbox'; checkbox.value = track.language;
    label.append(checkbox, el('span', '', track.name + ' 字幕')); subs.append(label);
  }
  download.addEventListener('click', async () => {
    download.disabled = true;
    try {
      await api('/api/download', {id:info.id, format:select.value,
        subtitles:[...subs.querySelectorAll('input:checked')].map(input => input.value)});
      item.state.textContent = '已加入下载队列'; item.state.className = 'collection-state'; await refresh();
    } catch(e) { item.state.textContent = e.message; item.state.className = 'collection-state failed'; }
    finally { download.disabled = false; }
  });
  item.detail.append(row, subs);
  if (info.warnings?.length) item.detail.append(el('p', 'hint', info.warnings.join('；')));
}
$('collection-load').addEventListener('click', loadCollection);
$('collection-all').addEventListener('change', () => {
  for (const item of collectionItems) item.checkbox.checked = $('collection-all').checked;
});
$('collection-stop').addEventListener('click', () => { stopBatch = true; $('collection-progress').textContent = '将在当前条目完成后停止'; });
$('collection-parse').addEventListener('click', async () => {
  if (batchRunning || collectionLoading) return;
  const selected = collectionItems.filter(item => item.checkbox.checked);
  if (!selected.length) { $('collection-progress').textContent = '请至少选择一个视频'; return; }
  batchRunning = true; stopBatch = false;
  $('collection-parse').disabled = true; $('collection-load').disabled = true; $('analyze').disabled = true;
  $('collection-stop').hidden = false;
  let completed = 0, failed = 0;
  try {
    for (const item of selected) {
      if (stopBatch) break;
      item.analysis = null; item.detail.replaceChildren();
      item.state.className = 'collection-state'; item.state.textContent = '正在解析…';
      $('collection-progress').textContent = `正在解析 ${completed + 1} / ${selected.length}`;
      try {
        const info = await api('/api/analyze', {url:item.entry.url});
        item.analysis = info; renderCollectionAnalysis(item, info);
        item.state.textContent = `已解析 · ${info.formats.length} 个格式 · ${(info.subtitles || []).length} 种字幕`;
      } catch(e) { failed++; item.state.textContent = e.message; item.state.className = 'collection-state failed'; }
      completed++;
    }
  } finally {
    batchRunning = false;
    $('collection-parse').disabled = false; $('collection-load').disabled = false; $('analyze').disabled = false;
    $('collection-stop').hidden = true;
    $('collection-progress').textContent = `${stopBatch ? '已停止' : '解析完成'} · ${completed}/${selected.length} · 成功 ${completed - failed} · 失败 ${failed}`;
  }
});
