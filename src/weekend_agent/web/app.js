const $ = id => document.getElementById(id);
let sessionId = localStorage.getItem('weekend-session') || null;
function textElement(tag, text) { const element = document.createElement(tag); element.textContent = text; return element; }
function render(result) {
  const plan = result.plan;
  $('schedule').replaceChildren(); $('citations').replaceChildren(); $('trace').replaceChildren();
  $('plan-status').textContent = plan.status === 'planned' ? '校验通过' : '未找到候选方案';
  if (plan.checked) {
    const checked = plan.checked;
    $('summary').textContent = `每人 ${checked.cost_per_person} 元 · ${checked.group_size} 人共 ${checked.total_group_cost} 元 · ${checked.schedule.length} 个地点`;
    for (const stop of checked.schedule) {
      const row = document.createElement('article'); row.className = 'stop';
      row.append(textElement('time', `${stop.start}–${stop.end}`));
      const content = document.createElement('div'); content.append(textElement('h3', stop.name));
      let detail = `地点费用：每人 ${stop.price_per_person} 元`;
      if (stop.route_from_previous) detail += ` · 从上一站出发约 ${stop.route_from_previous.minutes} 分钟，交通每人 ${stop.route_from_previous.fare_per_person} 元`;
      content.append(textElement('p', detail)); row.append(content); $('schedule').append(row);
    }
  } else $('summary').textContent = '本轮未找到通过校验的候选方案。可以增加预算、放宽时间或取消用餐要求后重试；这不证明不存在可行方案。';
  for (const citation of plan.citations) $('citations').append(textElement('p', `[${citation.id}] ${citation.title}：${citation.text}`));
  $('trace').append(textElement('p', `模型请求 ${result.model_calls} 次；工具请求 ${result.tool_calls} 次；最终校验 ${result.final_checks} 次；耗时 ${result.duration_seconds} 秒。`));
  $('trace').append(textElement('p', `模型：${result.model}；HTTP 尝试 ${result.http_attempts ?? 0} 次；输入 ${result.input_tokens ?? 0} token，输出 ${result.output_tokens ?? 0} token（仅已收到的用量）。`));
  for (const event of result.events) {
    if (event.kind === 'tool') $('trace').append(textElement('p', `${event.name} → ${event.result.ok ? '执行成功' : event.result.error}`));
    if (event.kind === 'final_rejected') $('trace').append(textElement('p', `最终校验拒绝：${event.error}`));
  }
}
function fill(request, mode) {
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
  const controls = [...$('trip-form').querySelectorAll('input,select,textarea,button')];
  controls.forEach(control => { control.disabled = true; });
  $('status').textContent = '正在安排，请稍候……';
  const request = {city:'杭州', travel_date:$('travel_date').value, budget_per_person:Number($('budget').value),
    group_size:Number($('group').value), tags:$('tags').value.split(/[,，、]/).map(s=>s.trim()).filter(Boolean),
    indoor:$('indoor').value === 'any' ? null : $('indoor').value === 'inside', rain:$('rain').checked,
    start_time:$('start').value, end_time:$('end').value, include_meal:$('meal').checked};
  try {
    $('trace').replaceChildren();
    const progress = [];
    let result = null, failure = null;
    await planStream({request, question:$('question').value.trim() || '请根据表单规划行程。',
                      mode:$('mode').value, session_id:sessionId}, payload => {
      if (payload.kind === 'result') { result = payload.result; return; }
      if (payload.kind === 'error') { failure = payload.error; return; }
      const text = describeEvent(payload);
      if (text) { progress.push(text); $('trace').append(textElement('p', text)); }
    });
    if (failure) throw new Error(failure);
    if (!result) throw new Error('没有收到结果，请重试');
    sessionId = result.session_id; localStorage.setItem('weekend-session', sessionId);
    render(result);
    // render 会清空 trace，这里把刚才的实时进度补回末尾。
    for (const text of progress) $('trace').append(textElement('p', text));
    $('status').textContent = '安排已保存。修改条件后再生成可查看变化；刷新页面可以恢复最近一次结果。';
  } catch (error) { $('status').textContent = error.message; }
  finally { controls.forEach(control => { control.disabled = false; }); }
});
function resetSession(message) {
  sessionId = null; localStorage.removeItem('weekend-session');
  $('schedule').replaceChildren(); $('citations').replaceChildren(); $('trace').replaceChildren();
  $('plan-status').textContent = '等待生成'; $('summary').textContent = '按当前条件生成一份新的安排。';
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
  const button = $('extract'); button.disabled = true;
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
  finally { button.disabled = false; }
});
async function checkModelConfig() {
  try {
    const response = await fetch('/api/health');
    const health = await response.json();
    const model = health.model || {};
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
restore();
checkModelConfig();
