// 运行观测面板：读取 /api/stats 做汇总，点击某一行再用 /api/trace 展开事件时间线。
// 所有文本都走 textContent / createElement，外部数据不参与 HTML 拼接。
const $ = id => document.getElementById(id);
const TOOL_LABELS = {get_weather: '教学天气', search_places: '地点检索', search_guides: '参考资料',
  get_route: '相邻站交通', check_itinerary: '行程校验', submit_plan: '提交方案'};
const FAILURE_LABELS = {'error': '异常或没有方案快照', 'no_plan': '正常返回但无方案',
  'final_rejected:submit_plan': '终审被拒 · 工具通道', 'final_rejected:text': '终审被拒 · 文本通道',
  'final_rejected:未知通道': '终审被拒 · 未知通道'};
const OUTCOME_LABELS = {planned: '有方案', no_plan: '无方案', error: '异常/缺快照'};

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}
function intText(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString('zh-CN') : '0';
}
function secondsText(value) {
  const number = Number(value);
  return Number.isFinite(number) ? String(Math.round(number * 1000) / 1000) : '—';
}
function percentText(value) {
  const number = Number(value);
  return Number.isFinite(number) ? (number * 100).toFixed(1) : '0.0';
}
function shortId(value) {
  const text = typeof value === 'string' ? value : '';
  return text ? `会话 ${text.slice(0, 8)}` : '会话 —';
}
function formatStamp(value) {
  if (typeof value !== 'string' || !value) return '时间未知';
  const date = new Date(value.replace(' ', 'T') + 'Z');
  if (Number.isNaN(date.valueOf())) return value;
  return date.toLocaleString('zh-CN', {month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'});
}
function statCard(label, value, unit, note) {
  const card = el('div', null, 'stat');
  card.append(el('span', label, 'stat-label'));
  const amount = el('strong', value, 'stat-value');
  if (unit) amount.append(el('span', unit, 'stat-unit'));
  card.append(amount);
  if (note) card.append(el('span', note, 'stat-note'));
  return card;
}
function statusTag(outcome) {
  const tag = el('span', OUTCOME_LABELS[outcome] || '未知结果', 'tag');
  tag.dataset.state = outcome === 'planned' ? 'planned' : outcome === 'no_plan' ? 'no_plan' : 'error';
  return tag;
}

function renderSummary(stats) {
  $('stat-cards').replaceChildren(
    statCard('统计运行数', intText(stats.run_count), '次'),
    statCard('成功率', percentText(stats.success_rate), '%', `有方案 ${intText(stats.planned_runs)} 次`),
    statCard('中位耗时', secondsText(stats.median_duration_seconds), '秒'),
    statCard('P95 耗时', secondsText(stats.p95_duration_seconds), '秒'),
    statCard('总 token（输入/输出）', `${intText(stats.total_input_tokens)} / ${intText(stats.total_output_tokens)}`, ''),
    statCard('总模型调用', intText(stats.sum_model_calls), '次', `真实模型；请求轮次 ${intText(stats.sum_provider_calls)} 次`),
    statCard('总工具调用', intText(stats.sum_tool_calls), '次', `执行失败 ${intText(stats.tool_error_count)} 次`));
  const bits = [`最近一次运行：${formatStamp(stats.latest_run_at)}`,
    `无方案 ${intText(stats.no_plan_runs)} 次`, `异常/缺快照 ${intText(stats.error_runs)} 次`,
    `发生修复轮 ${intText(stats.repair_runs)} 次`, `文本兜底 ${intText(stats.text_fallback_runs)} 次`,
    `统计上限 ${intText(stats.limit)} 条`];
  $('stats-note').textContent = '统计口径：' + bits.join(' · ') + '。';
}

// 纯 CSS 条形图：只设置宽度百分比，不引入任何图表库。
function renderBars(container, entries) {
  container.replaceChildren();
  if (!entries.length) {
    container.append(el('p', '还没有可统计的数据。跑几次生成后刷新本页即可看到。', 'bar-empty'));
    return;
  }
  const max = Math.max.apply(null, entries.map(item => item.count).concat([1]));
  for (const item of entries) {
    const row = el('div', null, 'bar-row');
    const label = el('span', item.label, 'bar-label');
    label.title = item.label;
    const track = el('span', null, 'bar-track');
    const fill = el('span', null, `bar-fill tone-${item.tone}`);
    fill.style.width = item.count > 0 ? `${Math.max(3, Math.round(item.count / max * 100))}%` : '0%';
    track.append(fill);
    row.append(label, track, el('span', intText(item.count), 'bar-value'));
    container.append(row);
  }
}
function histogramEntries(histogram, labels, toneFor) {
  return Object.keys(histogram || {}).map(key => ({key, label: labels[key] || key,
    count: Number(histogram[key]) || 0, tone: toneFor(key)}));
}
function renderHistograms(stats) {
  renderBars($('tool-histogram'),
    histogramEntries(stats.tool_histogram, TOOL_LABELS, () => 'tool'));
  renderBars($('failure-histogram'),
    histogramEntries(stats.failure_histogram, FAILURE_LABELS,
      key => key === 'error' ? 'bad' : key === 'no_plan' ? 'muted' : 'warn'));
}

function describeEvent(event) {
  const kind = event && typeof event === 'object' && typeof event.kind === 'string' ? event.kind : 'unknown';
  if (kind === 'phase') return {state: 'info', title: '建立会话',
    detail: event.mode === 'live' ? `真实模型 ${event.model || ''}` : '离线规则演示'};
  if (kind === 'tool') {
    const name = typeof event.name === 'string' && event.name ? event.name : '未知工具';
    const result = event.result;
    const ok = result && typeof result === 'object' && result.ok === true;
    return {state: ok ? 'ok' : 'fail', title: `${name} · ${TOOL_LABELS[name] || '其他工具'}`,
      detail: ok ? '执行成功' : `执行失败：${(result && result.error) || '未知原因'}`,
      payload: {arguments: event.arguments, result: event.result}};
  }
  if (kind === 'final_rejected') {
    const via = event.via === 'text' ? '文本通道' : event.via === 'submit_plan' ? '工具通道' : (event.via || '未知通道');
    return {state: 'reject', title: `终审被拒 · ${via}`, detail: String(event.error || ''),
      payload: {via: event.via, content_preview: event.content_preview}};
  }
  if (kind === 'final_via_text_fallback') return {state: 'warn', title: '走文本兜底通道',
    detail: '本轮方案来自模型文本解析，说明 submit_plan 工具通道没有交付。'};
  if (kind === 'final_validation') {
    const plan = event.plan && typeof event.plan === 'object' ? event.plan : {};
    const via = event.via === 'text' ? '文本通道' : event.via === 'submit_plan' ? '工具通道' : (event.via || '未知通道');
    return {state: 'final', title: `终审通过 · ${via}`, detail: `方案状态：${plan.status || '未知'}`};
  }
  if (kind === 'answer') return {state: 'final', title: '输出最终回答',
    detail: String(event.content || '').slice(0, 300)};
  if (kind === 'error') return {state: 'fail', title: '运行错误', detail: String(event.error || '服务内部错误')};
  return {state: 'info', title: kind, detail: '未识别的事件类型，原样保留。', payload: event};
}
function eventRow(event, index, round) {
  const described = describeEvent(event);
  const row = el('div', null, 'event-row');
  row.dataset.state = described.state;
  const marker = el('span', round === null ? `#${index + 1}` : `第${round}轮`, 'event-index');
  const body = el('div', null, 'event-body');
  body.append(el('strong', described.title));
  if (described.detail) body.append(el('p', described.detail));
  if (described.payload !== undefined) {
    let text = '';
    try { text = JSON.stringify(described.payload, null, 2); } catch { text = '（这段内容无法序列化）'; }
    const details = el('details');
    details.append(el('summary', '参数与原始结果'), el('pre', text));
    body.append(details);
  }
  row.append(marker, body);
  return row;
}
function renderTimeline(detail, trace) {
  detail.replaceChildren();
  const metrics = trace.metrics || {};
  detail.append(el('p', `#${trace.run_id} · ${shortId(trace.session_id)} · 第 ${trace.version} 次生成 · ${formatStamp(trace.created_at)}`,
    'trace-status'));
  const grid = el('div', null, 'stats-grid trace-metrics');
  grid.append(
    statCard('结果', OUTCOME_LABELS[metrics.outcome] || '未知', '', `plan.status = ${metrics.plan_status || '缺失'}`),
    statCard('耗时', secondsText(metrics.duration_seconds), '秒'),
    statCard('模型调用', intText(metrics.model_calls), '次', `请求轮次 ${intText(metrics.provider_calls)} 次`),
    statCard('工具调用', intText(metrics.tool_calls), '次', `失败 ${intText(metrics.tool_error_count)} 次`),
    statCard('终审次数', intText(metrics.final_checks), '次'),
    statCard('token（输入/输出）', `${intText(metrics.input_tokens)} / ${intText(metrics.output_tokens)}`, ''),
    statCard('交付通道', metrics.submitted_via === 'text' ? '文本兜底' : metrics.submitted_via === 'submit_plan' ? 'submit_plan' : '未交付', ''),
    statCard('事件数', intText(metrics.event_count), '条', `终审被拒 ${intText(metrics.final_rejected_count)} 次`));
  detail.append(grid);
  const list = el('div', null, 'event-timeline');
  const events = Array.isArray(trace.events) ? trace.events : [];
  if (!events.length) list.append(el('p', '这次运行没有保存事件。', 'bar-empty'));
  let round = null;
  events.forEach((event, index) => {
    if (event && typeof event === 'object' && Number.isFinite(Number(event.round))) round = Number(event.round);
    list.append(eventRow(event, index, round));
  });
  detail.append(list);
}

async function readJSON(url) {
  const response = await fetch(url);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || '读取失败');
  return data;
}
function runRow(run) {
  const item = el('div', null, 'run-item');
  const button = el('button', null, 'run-row');
  button.type = 'button';
  button.setAttribute('aria-expanded', 'false');
  const main = el('div', null, 'run-main');
  main.append(el('strong', `#${run.run_id} · ${shortId(run.session_id)}`));
  const bits = [`第 ${run.version} 次生成`];
  if (run.travel_date) bits.push(`出行 ${run.travel_date}`);
  if (run.budget_per_person !== null && run.budget_per_person !== undefined) bits.push(`每人预算 ${run.budget_per_person} 元`);
  main.append(el('p', bits.join(' · ')));
  const tags = el('div', null, 'run-tags');
  tags.append(statusTag(run.outcome), el('span', `${secondsText(run.duration_seconds)} 秒`, 'tag'),
    el('span', `工具 ${intText(run.tool_calls)} 次`, 'tag'),
    el('span', `终审 ${intText(run.final_checks)} 次`, 'tag'));
  if (run.final_rejected_count) tags.append(el('span', `被拒 ${intText(run.final_rejected_count)} 次`, 'tag warn'));
  if (run.submitted_via === 'text') tags.append(el('span', '文本兜底', 'tag warn'));
  if (run.mode) tags.append(el('span', run.mode === 'live' ? '真实模型' : '离线演示', 'tag'));
  button.append(el('span', formatStamp(run.created_at), 'run-time'), main, tags);
  const detail = el('div', null, 'run-detail');
  detail.hidden = true;
  button.addEventListener('click', () => toggleRun(button, detail, run.run_id));
  item.append(button, detail);
  return item;
}
async function toggleRun(button, detail, runId) {
  if (button.getAttribute('aria-expanded') === 'true') {
    button.setAttribute('aria-expanded', 'false');
    detail.hidden = true;
    return;
  }
  button.setAttribute('aria-expanded', 'true');
  detail.hidden = false;
  detail.replaceChildren(el('p', '正在读取这次运行的事件时间线……', 'trace-status'));
  try {
    const trace = await readJSON(`/api/trace?id=${encodeURIComponent(runId)}`);
    renderTimeline(detail, trace);
    $('status').textContent = `已展开运行 #${runId} 的事件时间线。`;
  } catch (error) {
    detail.replaceChildren(el('p', error.message, 'trace-status'));
    $('status').textContent = error.message;
  }
}
function renderRuns(stats) {
  const container = $('run-rows');
  container.replaceChildren();
  const runs = Array.isArray(stats.recent_runs) ? stats.recent_runs : [];
  if (!runs.length) {
    container.append(el('p', '还没有运行记录。先在规划页生成一次，再回到这里查看。', 'history-empty'));
    return;
  }
  for (const run of runs) container.append(runRow(run));
}

async function load() {
  try {
    const stats = await readJSON('/api/stats');
    renderSummary(stats);
    renderHistograms(stats);
    renderRuns(stats);
    $('status').textContent = stats.run_count
      ? `已读取 ${intText(stats.run_count)} 次运行。点击任意一行展开事件时间线。`
      : '数据库里还没有运行快照；先去规划页生成一次。';
  } catch (error) {
    $('status').textContent = error.message;
  }
}
load();
