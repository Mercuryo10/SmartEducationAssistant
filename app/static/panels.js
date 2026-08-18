// EduMentor 前端面板逻辑（docs/09 §7）：批改 / 错题 / 出题 / 推送。
// 依赖 app.js 中定义的全局函数与变量（escapeHtml / fmtDt / toUtcIso / currentUserId）。
// 四个面板各自对接独立接口，均在 dev 环境默认以 demo 用户身份访问。

// =============== 作业批改 ===============
const gradeFileEl = document.getElementById('gradeFile');
const gradeKeyEl = document.getElementById('gradeKey');
const gradeHintEl = document.getElementById('gradeHint');
const gradeBtn = document.getElementById('gradeSend');
const gradeResultEl = document.getElementById('gradeResult');
const DEMO_ANSWER_KEY = '1: B\n2: 对\n3: 信息\n4: RAG 通过检索相关证据片段约束生成，降低了对参数化记忆的依赖，从而减少了模型编造事实的可能。';

document.getElementById('fillDemoKey').onclick = () => {
  gradeKeyEl.value = DEMO_ANSWER_KEY;
  gradeResultEl.innerHTML = '<div class="hint">已填入示例答案，选择 homework_demo.jpg 后点「开始批改」</div>';
};

async function sendGrade() {
  const files = gradeFileEl.files;
  if (!files.length) { gradeResultEl.innerHTML = '<div class="error">请先选择作业图片</div>'; return; }
  gradeBtn.disabled = true;
  gradeResultEl.innerHTML = '<div class="hint">批改中：OCR 识别 → 客观题判分 → 主观题 AI 评分 …</div>';
  const fd = new FormData();
  for (const f of files) fd.append('file', f);
  if (gradeKeyEl.value.trim()) fd.append('answer_key', gradeKeyEl.value);
  if (gradeHintEl.value.trim()) fd.append('question_type_hint', gradeHintEl.value);
  try {
    const res = await fetch('/api/v1/homework/grade', { method: 'POST', body: fd });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      gradeResultEl.innerHTML = '<div class="error">请求失败 HTTP ' + res.status + '：' + escapeHtml(err.detail || err.message || '') + '</div>';
      return;
    }
    renderGradeResult(await res.json());
  } catch (err) {
    gradeResultEl.innerHTML = '<div class="error">网络异常：' + err.message + '</div>';
  } finally { gradeBtn.disabled = false; }
}

function renderGradeResult(d) {
  if (d.status === 'failed') {
    gradeResultEl.innerHTML = '<div class="error">⚠️ 批改失败：' + escapeHtml(d.error || '未知错误') + '</div>';
    return;
  }
  const s = d.summary || {};
  let html = '<div class="grade-summary">提交 #' + d.submission_id + ' · 共 <b>' + s.total + '</b> 题 · 对 <b>' + s.correct + '</b> 题 · 客观题得分率 <b>' + s.objective_score + '</b></div>';
  html += '<div class="grade-items">' + (d.items || []).map(it => {
    const tag = it.question_type === 'subjective'
      ? '<span class="tag subj">主观 · AI 评分</span>'
      : '<span class="tag obj">客观</span>';
    const verdict = it.question_type === 'subjective'
      ? (it.is_ai_scored ? 'AI 得分 ' + (it.score != null ? it.score : '-') : 'AI 未评分')
      : (it.is_correct ? '✅ 判对' : '❌ 判错');
    return '<div class="grade-item">'
      + '<div class="gi-head">' + tag + ' <b>Q' + it.question_no + '</b> ' + verdict + '</div>'
      + '<div class="gi-row"><label>题干</label>' + escapeHtml(it.question_text) + '</div>'
      + '<div class="gi-row"><label>学生答案</label>' + escapeHtml(it.student_answer || '（空）') + '</div>'
      + '<div class="gi-row"><label>参考答案</label>' + escapeHtml(it.reference_answer || '（无）') + '</div>'
      + (it.comment ? '<div class="gi-row"><label>评语</label>' + escapeHtml(it.comment) + '</div>' : '')
      + (it.suggestion ? '<div class="gi-row"><label>建议</label>' + escapeHtml(it.suggestion) + '</div>' : '')
      + '</div>';
  }).join('') + '</div>';
  gradeResultEl.innerHTML = html;
}

gradeBtn.onclick = sendGrade;

// =============== 错题分析 ===============
const msAddResultEl = document.getElementById('msAddResult');
const msListEl = document.getElementById('msList');
const msWeakEl = document.getElementById('msWeak');

async function addMistake() {
  const question_text = document.getElementById('msQuestion').value.trim();
  const wrong_answer = document.getElementById('msWrong').value.trim();
  if (!question_text || !wrong_answer) {
    msAddResultEl.innerHTML = '<div class="error">题干与错误答案不能为空</div>';
    return;
  }
  const body = { question_text, wrong_answer };
  const correct = document.getElementById('msCorrect').value.trim();
  if (correct) body.correct_answer = correct;
  const kp = document.getElementById('msKp').value;
  if (kp) body.knowledge_point_name = document.getElementById('msKp').selectedOptions[0].text;
  msAddResultEl.innerHTML = '<div class="hint">录入中：自动关联知识点…</div>';
  try {
    const res = await fetch('/api/v1/mistakes', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      msAddResultEl.innerHTML = '<div class="error">录入失败：' + escapeHtml(err.detail || err.message || '') + '</div>';
      return;
    }
    const d = await res.json();
    msAddResultEl.innerHTML = '<div class="success">✅ 错题已录入 #' + d.id + '，关联知识点：' + escapeHtml(d.knowledge_point_name || '未关联') + '</div>';
    document.getElementById('msQuestion').value = '';
    document.getElementById('msWrong').value = '';
    document.getElementById('msCorrect').value = '';
    document.getElementById('msKp').value = '';
    loadMistakes();
    loadWeakPoints();
  } catch (err) {
    msAddResultEl.innerHTML = '<div class="error">网络异常：' + err.message + '</div>';
  }
}

async function loadMistakes() {
  try {
    const res = await fetch('/api/v1/mistakes?page_size=50');
    const d = await res.json();
    const items = d.items || [];
    if (!items.length) {
      msListEl.innerHTML = '<div class="hint">暂无错题，录入几道试试</div>';
      return;
    }
    msListEl.innerHTML = items.map(m => {
      return '<div class="item">'
        + '<div class="item-head"><span>#' + m.id + ' · ' + escapeHtml(m.knowledge_point_name || '未关联知识点') + '</span>'
        + '<button class="btn-mini" data-analyze="' + m.id + '">讲解</button></div>'
        + '<div class="item-body"><span class="q">' + escapeHtml(m.question_text) + '</span></div>'
        + '<div class="item-row"><b>错误答案：</b>' + escapeHtml(m.wrong_answer) + '</div>'
        + (m.correct_answer ? '<div class="item-row"><b>正确答案：</b>' + escapeHtml(m.correct_answer) + '</div>' : '')
        + '<div class="item-row" style="color:#9ca3af">' + fmtDt(m.created_at) + '</div>'
        + '<div class="answer-box" id="analyze-' + m.id + '" style="display:none"></div>'
        + '</div>';
    }).join('');
  } catch (err) {
    msListEl.innerHTML = '<div class="error">加载失败：' + err.message + '</div>';
  }
}

async function analyzeMistake(id, btn) {
  const box = document.getElementById('analyze-' + id);
  box.style.display = 'block';
  box.innerHTML = '<div class="hint">讲解生成中…</div>';
  btn.disabled = true;
  try {
    const res = await fetch('/api/v1/mistakes/' + id + '/analyze', { method: 'POST' });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      box.innerHTML = '<div class="error">讲解失败：' + escapeHtml(err.detail || err.message || '') + '</div>';
      return;
    }
    const d = await res.json();
    let html = '<div class="item-row"><b>知识点：</b>' + escapeHtml(d.knowledge_point || '-') + '</div>';
    if (d.analysis) html += '<div class="item-row"><b>错误模式：</b>' + escapeHtml(d.analysis) + '</div>';
    if (d.explanation) html += '<div class="item-row"><b>讲解：</b>' + escapeHtml(d.explanation) + '</div>';
    if (d.common_mistakes && d.common_mistakes.length) html += '<div class="item-row"><b>常见错误：</b>' + d.common_mistakes.map(escapeHtml).join('；') + '</div>';
    if (d.variant_exercise) html += '<div class="item-row"><b>变式题：</b>' + escapeHtml(d.variant_exercise) + '</div>';
    box.innerHTML = html;
  } catch (err) {
    box.innerHTML = '<div class="error">网络异常：' + err.message + '</div>';
  } finally { btn.disabled = false; }
}

async function loadWeakPoints() {
  try {
    const res = await fetch('/api/v1/mistakes/weak-points?limit=10');
    const d = await res.json();
    const items = d.items || [];
    if (!items.length) {
      msWeakEl.innerHTML = '<div class="hint">暂无错题数据</div>';
      return;
    }
    msWeakEl.innerHTML = items.map(w => '<span class="weak-pill">' + escapeHtml(w.knowledge_point_name) + ' ×' + w.mistake_count + '</span>').join('');
  } catch (err) {
    msWeakEl.innerHTML = '<div class="error">加载失败：' + err.message + '</div>';
  }
}

document.getElementById('msAdd').onclick = addMistake;
document.getElementById('msRefresh').onclick = loadMistakes;
document.getElementById('msRefreshWeak').onclick = loadWeakPoints;
msListEl.addEventListener('click', e => {
  const btn = e.target.closest('[data-analyze]');
  if (btn) analyzeMistake(btn.dataset.analyze, btn);
});
loadMistakes();
loadWeakPoints();

// =============== 出题练习 ===============
const exResultEl = document.getElementById('exResult');

async function generateExercises() {
  const kp = document.getElementById('exKp').value;
  if (!kp) { exResultEl.innerHTML = '<div class="error">请先选择知识点</div>'; return; }
  const body = {
    knowledge_point_id: Number(kp),
    question_type: document.getElementById('exType').value,
    difficulty: document.getElementById('exDiff').value,
    count: Number(document.getElementById('exCount').value) || 3,
  };
  exResultEl.innerHTML = '<div class="hint">生成中：模板填参 → 可解校验 → 难度解析 …</div>';
  try {
    const res = await fetch('/api/v1/exercises/generate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      exResultEl.innerHTML = '<div class="error">生成失败：' + escapeHtml(err.detail || err.message || '') + '</div>';
      return;
    }
    const d = await res.json();
    const items = d.items || [];
    exResultEl.innerHTML = items.map((it, i) => {
      return '<div class="item">'
        + '<div class="item-body"><span class="q">' + (i + 1) + '. ' + escapeHtml(it.question_text) + '</span></div>'
        + '<div class="answer-box">'
        + '<div class="item-row"><b>参考答案：</b>' + escapeHtml(it.answer) + '</div>'
        + '<div class="item-row"><b>解析：</b>' + escapeHtml(it.explanation) + '</div>'
        + '</div></div>';
    }).join('') || '<div class="hint">未生成题目，请调整参数重试</div>';
  } catch (err) {
    exResultEl.innerHTML = '<div class="error">网络异常：' + err.message + '</div>';
  }
}

document.getElementById('exGenerate').onclick = generateExercises;

// =============== 学习推送 ===============
const puCreateResultEl = document.getElementById('puCreateResult');
const puPlanResultEl = document.getElementById('puPlanResult');
const puLogsEl = document.getElementById('puLogs');

function ensureUserId() {
  if (currentUserId) return currentUserId;
  throw new Error('当前用户未解析成功，请确认已登录（dev 环境默认 demo）');
}

async function createPushTask() {
  const content = document.getElementById('puContent').value.trim();
  const iso = toUtcIso(document.getElementById('puTime').value, false);
  if (!content || !iso) {
    puCreateResultEl.innerHTML = '<div class="error">请填写提醒内容与触发时间</div>';
    return;
  }
  try {
    const body = {
      user_id: ensureUserId(),
      content,
      scheduled_at: iso,
      channel: document.getElementById('puChannel').value,
    };
    const res = await fetch('/api/v1/push/create', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      puCreateResultEl.innerHTML = '<div class="error">创建失败：' + escapeHtml(err.detail || err.message || '') + '</div>';
      return;
    }
    const d = await res.json();
    puCreateResultEl.innerHTML = '<div class="success">✅ 提醒任务 #' + d.id + ' 已创建（' + fmtDt(d.scheduled_at) + '，到时由后台调度触发）</div>';
    document.getElementById('puContent').value = '';
    document.getElementById('puTime').value = '';
  } catch (err) {
    puCreateResultEl.innerHTML = '<div class="error">' + escapeHtml(err.message) + '</div>';
  }
}

async function planReview() {
  const kp = document.getElementById('puKp').value;
  const date = document.getElementById('puDate').value;
  if (!kp || !date) {
    puPlanResultEl.innerHTML = '<div class="error">请选择知识点与起始日期</div>';
    return;
  }
  try {
    const body = {
      user_id: ensureUserId(),
      knowledge_point_id: Number(kp),
      start_date: toUtcIso(date, true),
    };
    const res = await fetch('/api/v1/push/plan', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      puPlanResultEl.innerHTML = '<div class="error">生成失败：' + escapeHtml(err.detail || err.message || '') + '</div>';
      return;
    }
    const d = await res.json();
    puPlanResultEl.innerHTML = '<div class="success">遗忘曲线计划已生成（1/2/4/7 天 09:00 触发）：</div>' +
      (d.items || []).map(it => '<div class="item-row">· ' + fmtDt(it.scheduled_at) + ' — ' + escapeHtml(it.content) + '</div>').join('');
  } catch (err) {
    puPlanResultEl.innerHTML = '<div class="error">' + escapeHtml(err.message) + '</div>';
  }
}

async function loadPushLogs() {
  try {
    const res = await fetch('/api/v1/push/logs?page_size=50');
    const d = await res.json();
    const items = d.items || [];
    if (!items.length) {
      puLogsEl.innerHTML = '<div class="hint">暂无推送日志，创建任务并到点后这里会显示记录</div>';
      return;
    }
    puLogsEl.innerHTML = items.map(log => {
      const stCls = log.status === 'success' ? 'success' : 'failed';
      return '<div class="log-item">'
        + '<span class="st ' + stCls + '">' + (log.status === 'success' ? '成功' : '失败') + '</span>'
        + '<span>任务#' + log.task_id + '</span>'
        + '<span>' + escapeHtml(log.detail || '') + '</span>'
        + '<span class="tm">' + fmtDt(log.created_at) + '</span>'
        + '</div>';
    }).join('');
  } catch (err) {
    puLogsEl.innerHTML = '<div class="error">加载失败：' + err.message + '</div>';
  }
}

document.getElementById('puCreate').onclick = createPushTask;
document.getElementById('puPlan').onclick = planReview;
document.getElementById('puRefresh').onclick = loadPushLogs;
loadPushLogs();
