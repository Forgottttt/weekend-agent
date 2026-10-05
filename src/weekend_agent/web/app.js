const $ = id => document.getElementById(id);
let sessionId = localStorage.getItem('weekend-session') || null;
let working = false;
function setWorking(value) {
  working = value;
  document.querySelectorAll('main input,main select,main textarea,main button').forEach(control => { control.disabled = value; });
}
function textElement(tag, text) { const element = document.createElement(tag); element.textContent = text; return element; }
function showEmpty() {
  $('empty-state').hidden = false; $('summary').hidden = true;
  $('references').hidden = true;
}
function render(result) {
  const plan = result.plan;
  $('empty-state').hidden = true; $('summary').hidden = false;
  $('progress-panel').hidden = true;
  $('schedule').replaceChildren(); $('citations').replaceChildren(); $('trace').replaceChildren();
  $('plan-status').textContent = plan.status === 'planned' ? '校验通过' : '未找到候选';
  $('plan-status').dataset.state = plan.status;
  $('summary').replaceChildren(); $('summary').classList.toggle('no-plan', !plan.checked);
  if (plan.checked) {
    const checked = plan.checked;
    for (const [label, value, unit] of [['每人费用', checked.cost_per_person, '元'],
      ['同行合计', checked.total_group_cost, '元'], ['行程地点', checked.schedule.length, '站']]) {
      const stat = document.createElement('div'); stat.className = 'stat';
      const amount = textElement('strong', String(value)); amount.className = 'stat-value';
      const suffix = textElement('span', unit); suffix.className = 'stat-unit'; amount.append(suffix);
      const caption = textElement('span', label); caption.className = 'stat-label';
      stat.append(caption, amount); $('summary').append(stat);
    }
    for (const [index, stop] of checked.schedule.entries()) {
      const row = document.createElement('article'); row.className = 'stop';
      row.append(textElement('time', `${stop.start}–${stop.end}`));
      const content = document.createElement('div'); content.className = 'stop-content';
      const number = textElement('span', `STOP ${String(index + 1).padStart(2, '0')}`); number.className = 'stop-index';
      content.append(number, textElement('h3', stop.name));
      content.append(textElement('p', `地点费用 · 每人 ${stop.price_per_person} 元`));
      if (stop.route_from_previous) {
        const route = textElement('span', `从上一站约 ${stop.route_from_previous.minutes} 分钟 · 交通每人 ${stop.route_from_previous.fare_per_person} 元`);
        route.className = 'route-tag'; content.append(route);
      }
      row.append(content); $('schedule').append(row);
    }
  } else $('summary').textContent = '本轮未找到通过校验的候选方案。可以增加预算、放宽时间或取消用餐要求后重试；这不证明不存在可行方案。';
  $('references').hidden = !plan.citations.length;
  for (const citation of plan.citations) $('citations').append(textElement('p', `[${citation.id}] ${citation.title}：${citation.text}`));
  $('trace').append(textElement('p', `模型请求 ${result.model_calls} 次；工具请求 ${result.tool_calls} 次；最终校验 ${result.final_checks} 次；耗时 ${result.duration_seconds} 秒。`));
  $('trace').append(textElement('p', `模型：${result.model}；HTTP 尝试 ${result.http_attempts ?? 0} 次；输入 ${result.input_tokens ?? 0} token，输出 ${result.output_tokens ?? 0} token（仅已收到的用量）。`));
  for (const event of result.events) {
    if (event.kind === 'tool') $('trace').append(textElement('p', `${event.name} → ${event.result.ok ? '执行成功' : event.result.error}`));
    if (event.kind === 'final_rejected') $('trace').append(textElement('p', `最终校验拒绝：${event.error}`));
  }
}
function fill(request, mode) {
  document.querySelectorAll('[data-preset]').forEach(item => item.setAttribute('aria-pressed', 'false'));
  $('travel_date').value = request.travel_date; $('budget').value = request.budget_per_person;
  $('group').value = request.group_size; $('start').value = request.start_time; $('end').value = request.end_time;
  $('tags').value = request.tags.join('，'); $('rain').checked = request.rain; $('meal').checked = request.include_meal;
  $('indoor').value = request.indoor === null ? 'any' : request.indoor ? 'inside' : 'outside'; $('mode').value = mode;
}
function describeEvent(event) {
  if (event.kind === 'phase' && event.phase === 'session') {
    return `已建立会话 · ${event.mode === 'live' ? '真实模型 ' + event.model : '离线规则'}`;
  }
  if (event.kind === 'tool') return `${event.name} → ${event.result.ok ? '成功' : event.result.error}`;
  if (event.kind === 'final_rejected') return `终审拒绝（${event.via}）：${event.error}`;
  if (event.kind === 'final_via_text_fallback') return '注意：本轮走了文本兜底通道，而不是 submit_plan';
  if (event.kind === 'final_validation') return '终审通过';
  return null;
}

// 用 fetch 的流式读取消费 SSE：服务端每发生一件事就推一条 data: 行。
async function planStream(payload, onEvent) {
  const response = await fetch('/api/plan/stream', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.error || '生成失败');
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const {done, value} = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, {stream: true});
    let cut;
    while ((cut = buffer.indexOf('\n\n')) >= 0) {
      const chunk = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      const line = chunk.split('\n').find(part => part.startsWith('data: '));
      if (line) onEvent(JSON.parse(line.slice(6)));
    }
  }
}

$('trip-form').addEventListener('submit', async event => {
  event.preventDefault();
  setWorking(true);
  $('generate').setAttribute('aria-busy', 'true');
  $('progress-panel').hidden = false;
  $('progress-text').textContent = '正在查看你的条件……';
  $('plan-status').textContent = '正在生成';
  $('plan-status').dataset.state = 'busy';
  $('status').textContent = '正在安排，请稍候……';
  const request = {city:'杭州', travel_date:$('travel_date').value, budget_per_person:Number($('budget').value),
    group_size:Number($('group').value), tags:$('tags').value.split(/[,，、]/).map(s=>s.trim()).filter(Boolean),
    indoor:$('indoor').value === 'any' ? null : $('indoor').value === 'inside', rain:$('rain').checked,
    start_time:$('start').value, end_time:$('end').value, include_meal:$('meal').checked};
  try {
    $('trace').replaceChildren(); $('run-list').replaceChildren();
    const progress = [];
    let result = null, failure = null;
    await planStream({request, question:$('question').value.trim() || '请根据表单规划行程。',
                      mode:$('mode').value, session_id:sessionId}, payload => {
      if (payload.kind === 'result') { result = payload.result; return; }
      if (payload.kind === 'error') { failure = payload.error; return; }
      const text = describeEvent(payload);
      const names = {get_weather:'正在查看教学天气',search_places:'正在寻找合适的地点',search_guides:'正在整理参考资料',get_route:'正在计算相邻站交通',check_itinerary:'正在检查预算与时间'};
      if (payload.kind === 'tool') $('progress-text').textContent = names[payload.name] || '正在整理安排……';
      if (text) { progress.push(text); $('trace').append(textElement('p', text)); }
    });
    if (failure) throw new Error(failure);
    if (!result) throw new Error('没有收到结果，请重试');
    sessionId = result.session_id; localStorage.setItem('weekend-session', sessionId);
    render(result);
    await refreshHistory();
    // render 会清空 trace，这里把刚才的实时进度补回末尾。
    for (const text of progress) $('trace').append(textElement('p', text));
    $('status').textContent = '安排已保存。修改条件后再生成可查看变化；刷新页面可以恢复最近一次结果。';
  } catch (error) { $('status').textContent = error.message;
    $('plan-status').textContent = '生成未完成'; $('plan-status').dataset.state = 'error';
  } finally { $('progress-panel').hidden = true; $('generate').removeAttribute('aria-busy'); setWorking(false); }
});
function resetSession(message) {
  extractBase = ''; $('question').placeholder = DEFAULT_PLACEHOLDER;
  sessionId = null; localStorage.removeItem('weekend-session');
  $('schedule').replaceChildren(); $('citations').replaceChildren(); $('trace').replaceChildren();
  $('plan-status').textContent = '等待灵感'; $('plan-status').dataset.state = '';
  $('progress-panel').hidden = true; $('run-list').replaceChildren(); showEmpty();
  $('status').textContent = message;
}
$('reset').addEventListener('click', () => resetSession('已新建会话，下次生成开始新的记录。'));
$('mode').addEventListener('change', () => resetSession('已切换运行方式并新建会话，当前表单条件已保留。'));

// 把模型抽取到的槽位填进表单。模型只提出候选值，用户看得到、也改得动。
function applySlots(provided) {
  if (provided.travel_date) $('travel_date').value = provided.travel_date;
  if (provided.budget_per_person !== undefined) $('budget').value = provided.budget_per_person;
  if (provided.group_size !== undefined) $('group').value = provided.group_size;
  if (provided.start_time) $('start').value = provided.start_time;
  if (provided.end_time) $('end').value = provided.end_time;
  if (provided.tags) $('tags').value = provided.tags.join('，');
  if (provided.rain !== undefined) $('rain').checked = provided.rain === true;
  if (provided.include_meal !== undefined) $('meal').checked = provided.include_meal === true;
  if (provided.indoor !== undefined) $('indoor').value = provided.indoor ? 'inside' : 'outside';
}

// 多轮澄清：把用户每次补充并进完整描述，后端每轮都看到全部上下文。
let extractBase = '';
const DEFAULT_PLACEHOLDER = $('question').placeholder;
const SLOT_LABELS = {city:'城市', travel_date:'出行日期', budget_per_person:'每人预算',
  group_size:'同行人数', tags:'兴趣', indoor:'室内外要求', rain:'是否雨天',
  start_time:'开始时间', end_time:'结束时间', include_meal:'是否安排用餐'};

$('extract').addEventListener('click', async () => {
  const typed = $('question').value.trim();
  if (!typed) {
    $('status').textContent = extractBase
      ? '请在上面输入你的补充。'
      : '请先写一句话，例如：两个人，预算200，11月21号，想拍照。';
    return;
  }
  if ($('mode').value !== 'live') {
    $('status').textContent = '自然语言解析需要把运行方式切到「真实模型」；离线演示只按表单条件运行。';
    return;
  }
  const payload = extractBase ? `${extractBase}\n补充说明：${typed}` : typed;
  setWorking(true);
  $('status').textContent = '正在解析……';
  try {
    const response = await fetch('/api/extract', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({text: payload, mode: $('mode').value})});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || '解析失败');
    applySlots(result.provided || {});
    if (result.question) {
      // 还缺关键条件：记住累积文本，下次点击时把新输入当作补充。
      extractBase = payload;
      $('question').value = '';
      $('question').placeholder = '请补充：' + (result.missing || []).map(n => SLOT_LABELS[n] || n).join('、');
      $('status').textContent = '已填入能确定的条件。' + result.question;
    } else {
      extractBase = '';
      $('question').value = payload;
      $('question').placeholder = DEFAULT_PLACEHOLDER;
      $('status').textContent = '已把解析到的条件填入表单。请核对后再生成安排；模型没提到的条件保持原样。';
    }
  } catch (error) { $('status').textContent = error.message; }
  finally { setWorking(false); }
});
async function checkModelConfig() {
  try {
    const response = await fetch('/api/health');
    const health = await response.json();
    const model = health.model || {};
    if (!sessionId && model.ready) $('mode').value = 'live';
    $('model-status').textContent = model.ready
      ? `模型 ${model.model} 的本地配置已就绪（尚不代表联网验证通过）。真实模型生成会消耗 API 额度。`
      : model.error || '模型密钥尚未配置，可先使用离线演示。按第11课填写本地 .env 后刷新此页。';
  } catch { $('model-status').textContent = '暂时无法读取模型配置，请确认本地服务已启动。'; }
}
async function restore() {
  if (!sessionId) return;
  try { const response = await fetch(`/api/session?id=${encodeURIComponent(sessionId)}`); const saved = await response.json();
    if (!response.ok || !saved.result.plan) throw new Error('会话不可恢复'); fill(saved.request, saved.result.mode); render(saved.result); $('status').textContent = '已恢复最近一次安排。';
  } catch { sessionId = null; localStorage.removeItem('weekend-session'); }
}
async function readJSON(url) {
  const response = await fetch(url); const data = await response.json();
  if (!response.ok) throw new Error(data.error || '读取失败');
  return data;
}
let historyExpanded = false;
function shortDate(value) { return String(value || '').replaceAll('-', '/'); }
function historyTimestamp(value) {
  const date = new Date(String(value).replace(' ', 'T') + 'Z');
  return Number.isNaN(date.valueOf()) ? '' : date.toLocaleDateString('zh-CN', {month:'2-digit', day:'2-digit'});
}
async function refreshHistory() {
  try {
    const data = await readJSON('/api/sessions');
    $('history-list').replaceChildren();
    $('toggle-history').hidden = data.sessions.length <= 6;
    $('toggle-history').textContent = historyExpanded ? '收起记录' : `查看全部 (${data.sessions.length})`;
    for (const item of historyExpanded ? data.sessions : data.sessions.slice(0, 6)) {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'history-item';
      const meta = document.createElement('div'); meta.className = 'history-meta';
      const mode = textElement('span', item.mode === 'live' ? 'DEEPSEEK / 真实模型' : '离线演示'); mode.className = 'history-mode';
      meta.append(mode, textElement('span', historyTimestamp(item.updated_at) + ' 保存'));
      button.append(meta, textElement('strong', shortDate(item.request.travel_date) + ' · 杭州一日'));
      button.append(textElement('p', `每人预算 ${item.request.budget_per_person} 元 · ${item.request.group_size} 人同行`));
      const bottom = document.createElement('div'); bottom.className = 'history-bottom';
      bottom.append(textElement('span', `${(item.request.tags || []).join(' / ') || '随心逛逛'} · ${item.version} 次生成`), textElement('span', '↗'));
      button.append(bottom); button.disabled = working;
      button.addEventListener('click', async () => {
        if (working) return;
        try {
          const saved = await readJSON(`/api/session?id=${encodeURIComponent(item.session_id)}`);
          resetSession('已打开保存的会话，可以调整条件继续生成。');
          sessionId = item.session_id; localStorage.setItem('weekend-session', sessionId);
          fill(saved.request, saved.result.mode); render(saved.result);
          const history = await readJSON(`/api/runs?session_id=${encodeURIComponent(sessionId)}`);
          $('run-list').replaceChildren(textElement('p', history.runs.length ? '查看这个会话的生成记录：' : '这个会话来自旧版本，已恢复最新结果。'));
          for (const run of history.runs) {
            const old = textElement('button', `第${run.version}次 · 每人预算${run.request.budget_per_person}元`);
            old.type = 'button'; old.className = 'secondary';
            old.addEventListener('click', async () => {
              if (working) return;
              try {
                const snapshot = await readJSON(`/api/run?id=${run.run_id}`);
                resetSession('正在查看历史快照；再次生成会创建新会话。');
                fill(snapshot.request, snapshot.result.mode); render(snapshot.result);
              } catch (error) { $('status').textContent = error.message; }
            });
            $('run-list').append(old);
          }
        } catch (error) { $('status').textContent = error.message; }
      });
      $('history-list').append(button);
    }
    if (!data.sessions.length) {
      const empty = textElement('p','还没有保存的安排。第一份周末计划，会从这里开始。');
      empty.className = 'history-empty'; $('history-list').append(empty);
    }
  } catch (error) { $('history-list').textContent = error.message; }
}
$('toggle-history').addEventListener('click', () => { historyExpanded = !historyExpanded; refreshHistory(); });
$('refresh-history').addEventListener('click', refreshHistory);
document.querySelectorAll('[data-preset]').forEach(button => {
  button.setAttribute('aria-pressed', 'false');
  button.addEventListener('click', () => {
    if (working) return;
    const presets = {photo:{tags:'拍照，美食',rain:false,indoor:'any'},
      rain:{tags:'文化，美食',rain:true,indoor:'inside'}, culture:{tags:'文化',rain:false,indoor:'any'}};
    const values = presets[button.dataset.preset];
    $('tags').value = values.tags; $('rain').checked = values.rain; $('indoor').value = values.indoor;
    document.querySelectorAll('[data-preset]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
    $('status').textContent = '已填入偏好。还可以调整日期、预算和时间，再生成安排。';
  });
});
(async () => { await restore(); await checkModelConfig(); await refreshHistory(); })();
