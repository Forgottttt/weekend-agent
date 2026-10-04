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
$('trip-form').addEventListener('submit', async event => {
  event.preventDefault(); $('generate').disabled = true; $('reset').disabled = true;
  $('status').textContent = '正在安排，请稍候……';
  const request = {city:'杭州', travel_date:$('travel_date').value, budget_per_person:Number($('budget').value),
    group_size:Number($('group').value), tags:$('tags').value.split(/[,，、]/).map(s=>s.trim()).filter(Boolean),
    indoor:$('indoor').value === 'any' ? null : $('indoor').value === 'inside', rain:$('rain').checked,
    start_time:$('start').value, end_time:$('end').value, include_meal:$('meal').checked};
  try {
    const response = await fetch('/api/plan', {method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({request, question:$('question').value.trim() || '请根据表单规划行程。', mode:$('mode').value, session_id:sessionId})});
    const result = await response.json(); if (!response.ok) throw new Error(result.error || '生成失败');
    sessionId = result.session_id; localStorage.setItem('weekend-session', sessionId); render(result);
    $('status').textContent = '安排已保存。修改条件后再生成可查看变化；刷新页面可以恢复最近一次结果。';
  } catch (error) { $('status').textContent = error.message; }
  finally { $('generate').disabled = false; $('reset').disabled = false; }
});
$('reset').addEventListener('click', () => {
  sessionId = null; localStorage.removeItem('weekend-session');
  $('schedule').replaceChildren(); $('citations').replaceChildren(); $('trace').replaceChildren();
  $('plan-status').textContent = '等待生成'; $('summary').textContent = '按当前条件生成一份新的安排。';
  $('status').textContent = '已新建会话，下次生成开始新的记录。';
});
async function restore() {
  if (!sessionId) return;
  try { const response = await fetch(`/api/session?id=${encodeURIComponent(sessionId)}`); const saved = await response.json();
    if (!response.ok || !saved.result.plan) throw new Error('会话不可恢复'); fill(saved.request, saved.result.mode); render(saved.result); $('status').textContent = '已恢复最近一次安排。';
  } catch { sessionId = null; localStorage.removeItem('weekend-session'); }
}
restore();
