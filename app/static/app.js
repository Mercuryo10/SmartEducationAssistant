// EduMentor 前端核心（docs/09 §7）：Tab 切换、工具函数、初始化、智能答疑（SSE 流式）。
// 其余四面板（批改/错题/出题/推送）见 panels.js，两文件共享顶层全局作用域。
const PANELS = ['chat', 'grading', 'mistakes', 'exercises', 'push'];
let conversationId = null;   // 当前会话 id，续接实现多轮
let busy = false;
let currentUserId = null;    // 当前用户 id（GET /auth/me，push 接口请求体需要）

// ---------- Tab 切换 ----------
document.querySelectorAll('.tab').forEach(t => t.onclick = () => switchTab(t.dataset.panel));
function switchTab(name) {
  document.querySelectorAll('.tab').forEach(x => x.classList.toggle('active', x.dataset.panel === name));
  PANELS.forEach(p => document.getElementById('panel-' + p).classList.toggle('active', p === name));
}

// ---------- 工具函数 ----------
function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s == null ? '' : String(s);
  return d.innerHTML;
}
// 本地时间字符串（datetime-local / date）转 UTC ISO 字符串
function toUtcIso(localValue, dateOnly) {
  if (!localValue) return '';
  const d = dateOnly ? new Date(localValue + 'T00:00:00') : new Date(localValue);
  return isNaN(d.getTime()) ? '' : d.toISOString();
}
// 时间展示：ISO 去掉 T/时区后缀 → "YYYY-MM-DD HH:mm"
function fmtDt(v) {
  if (!v) return '';
  return String(v).replace('T', ' ').slice(0, 16);
}

// ---------- 初始化：健康状态 / 当前用户 / 知识点 ----------
fetch('/api/v1/health').then(r => r.json()).then(d => {
  document.getElementById('health').textContent = `db=${d.db} · llm=${d.llm}`;
}).catch(() => document.getElementById('health').textContent = '服务离线');

fetch('/api/v1/auth/me').then(r => r.json()).then(u => { currentUserId = u.id; }).catch(() => { currentUserId = null; });

async function loadKnowledgePoints() {
  try {
    const res = await fetch('/api/v1/knowledge-points');
    const data = await res.json();
    const fill = (sel, withBlank, blankLabel) => {
      const el = document.getElementById(sel);
      el.innerHTML = '';
      if (withBlank) el.appendChild(new Option(blankLabel, ''));
      (data.items || []).forEach(kp => el.appendChild(new Option(kp.name, kp.id)));
    };
    fill('msKp', true, '（由 AI 自动关联）');
    fill('exKp', false, '');
    fill('puKp', false, '');
  } catch (e) { /* 知识点加载失败不阻塞其他面板 */ }
}
loadKnowledgePoints();

// =============== 智能答疑（Supervisor → QA 子图 → SSE 流式） ===============
const chatEl = document.getElementById('chat');
const inputEl = document.getElementById('input');
const sendBtn = document.getElementById('send');
const fileBtn = document.getElementById('fileBtn');
const fileNameEl = document.getElementById('fileName');

function addMsg(role, text, streaming) {
  const row = document.createElement('div');
  row.className = 'msg ' + role;
  const bubble = document.createElement('div');
  bubble.className = 'bubble' + (streaming ? ' streaming' : '');
  bubble.textContent = text;
  row.appendChild(bubble);
  chatEl.appendChild(row);
  chatEl.scrollTop = chatEl.scrollHeight;
  return bubble;
}

function addError(text) {
  const b = addMsg('assistant', '⚠️ ' + text);
  b.classList.add('error');
}

function addRefs(refs) {
  const rows = chatEl.querySelectorAll('.msg.assistant');
  const last = rows[rows.length - 1];
  const wrap = document.createElement('div');
  wrap.className = 'refs';
  wrap.innerHTML = '<details><summary>溯源 ' + refs.length + ' 条</summary>' +
    refs.map(r => '<div class="ref">' + escapeHtml(r.source) + '<span class="snip">' + escapeHtml((r.snippet || '').slice(0, 80)) + '…</span></div>').join('') +
    '</details>';
  last.appendChild(wrap);
}

async function send() {
  const text = inputEl.value.trim();
  const file = fileBtn.files[0];
  if (busy || (!text && !file)) return;
  busy = true;
  sendBtn.disabled = true;

  addMsg('user', text || (file ? '（已上传 ' + file.name + '）' : ''));
  const cur = addMsg('assistant', '', true);

  const fd = new FormData();
  if (text) fd.append('message', text);
  if (conversationId) fd.append('conversation_id', conversationId);
  if (file) fd.append('file', file);
  inputEl.value = ''; fileBtn.value = ''; fileNameEl.textContent = '';

  try {
    const res = await fetch('/api/v1/chat', { method: 'POST', body: fd });
    if (!res.ok) { addError('请求失败 HTTP ' + res.status); return; }
    const reader = res.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buf = '', doneData = null;

    const consume = () => {
      let idx;
      while ((idx = buf.indexOf('\n\n')) !== -1) {
        const block = buf.slice(0, idx); buf = buf.slice(idx + 2);
        let type = '', data = '';
        block.split('\n').forEach(line => {
          if (line.startsWith('event:')) type = line.slice(6).trim();
          if (line.startsWith('data:')) data += line.slice(5).trim();
        });
        if (type === 'meta') {
          const m = JSON.parse(data);
          conversationId = m.conversation_id;
        } else if (type === 'token') {
          cur.textContent += JSON.parse(data).text;
          chatEl.scrollTop = chatEl.scrollHeight;
        } else if (type === 'done') {
          doneData = JSON.parse(data);
        } else if (type === 'error') {
          const e = JSON.parse(data);
          addError(e.message + (e.detail ? '：' + e.detail : ''));
        }
      }
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      consume();
    }
    consume(); // 收尾剩余
    cur.classList.remove('streaming');
    if (doneData && doneData.source_refs && doneData.source_refs.length) addRefs(doneData.source_refs);
  } catch (err) {
    addError('网络异常：' + err.message);
  } finally {
    busy = false;
    sendBtn.disabled = false;
    inputEl.focus();
  }
}

sendBtn.onclick = send;
inputEl.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } });
fileBtn.onchange = () => { fileNameEl.textContent = fileBtn.files[0] ? fileBtn.files[0].name : ''; };
