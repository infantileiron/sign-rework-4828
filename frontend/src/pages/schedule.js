import {api} from '../api/studio.js';
import {empty, heading, panelTitle, stat} from '../components/common/ui.js';
import {features} from '../constants/domain.js';
import {buttonAction, formSubmit} from '../hooks/interaction.js';
import {canEdit, studio} from '../stores/studio.js';
import {esc, fixed} from '../utils/format.js';

const day = value => String(value ?? '').slice(0, 10);
const hours = value => `${fixed(Number(value ?? 0), 2)} h`;

function shiftBoard(board) {
  if (!board.shifts.length) return empty('还没有班次。分析员可先建立日期、名称与工时容量。');
  return `<div class="table-wrap"><table><thead><tr><th>日期</th><th>班次</th><th>容量</th><th>已确认</th><th>余量</th><th>已排工单</th></tr></thead><tbody>
    ${board.shifts.map(shift => {
      const placed = board.assignments.filter(item => item.shift_id === shift.id);
      return `<tr><td class="mono">${day(shift.shift_date)}</td><td><strong>${esc(shift.name)}</strong></td>
        <td class="mono">${hours(shift.capacity_hours)}</td><td class="mono">${hours(shift.confirmed_hours)}</td>
        <td class="mono ${shift.remaining_hours < 0 ? 'error' : 'actual'}">${hours(shift.remaining_hours)}</td>
        <td>${placed.length ? placed.map(item => `<span class="chip mono" title="${esc(item.title)}">${esc(item.code)} · ${hours(item.hours)}</span>`).join(' ') : '<span class="muted">—</span>'}</td></tr>`;
    }).join('')}</tbody></table></div>`;
}

function pendingTable(board) {
  if (!board.pending.length) return empty('暂无待排工单。待排工单确认后即离开此列表。');
  return `<div class="table-wrap"><table><thead><tr><th>工单号 / 视频</th><th>截止日</th><th>成片 / 镜头 / 换景</th><th>状态</th></tr></thead><tbody>
    ${board.pending.map(order => `<tr><td><small class="mono row-code">${esc(order.code)}</small><strong>${esc(order.title)}</strong></td>
      <td class="mono">${day(order.deadline)}</td>
      <td class="mono">${fixed(order.minutes)} min · ${order.shots} · ${order.switches}</td>
      <td><span class="status succeeded">待排</span></td></tr>`).join('')}</tbody></table></div>`;
}

function assignmentTable(assignments) {
  if (!assignments.length) return '<p class="subtle section-note">还没有已确认的安排。</p>';
  return `<div class="table-wrap"><table><thead><tr><th>工单号 / 视频</th><th>截止日</th><th>确认工时</th><th>排入班次</th><th>来源</th></tr></thead><tbody>
    ${assignments.map(item => `<tr><td><small class="mono row-code">${esc(item.code)}</small><strong>${esc(item.title)}</strong></td>
      <td class="mono">${day(item.deadline)}</td><td class="mono">${hours(item.hours)}</td>
      <td class="mono">${day(item.shift_date)} ${esc(item.shift_name)}</td>
      <td class="subtle">${item.recomputed ? '按原试估重算' : '沿用原预排'} · 确认 #${item.confirmation_id}</td></tr>`).join('')}</tbody></table></div>`;
}

function unscheduledTable(items) {
  if (!items.length) return '<p class="subtle section-note">当前没有未排上的工单。</p>';
  return `<div class="table-wrap"><table><thead><tr><th>工单号 / 视频</th><th>截止日</th><th>试估工时</th><th>未排原因</th></tr></thead><tbody>
    ${items.map(item => `<tr><td><small class="mono row-code">${esc(item.code)}</small><strong>${esc(item.title)}</strong></td>
      <td class="mono">${day(item.deadline)}</td><td class="mono">${hours(item.hours)}</td>
      <td class="error">${esc(item.reason || '未排上')}</td></tr>`).join('')}</tbody></table></div>`;
}

function trialView(trial, board, rerender) {
  const shiftName = id => board.shifts.find(shift => shift.id === id)?.name ?? `班次 #${id}`;
  const shiftDate = id => day(board.shifts.find(shift => shift.id === id)?.shift_date);
  const confirmed = Boolean(trial.confirmation_id);
  return `<section class="panel trial-panel">${panelTitle(`试估 #${trial.trial.id} · 报告 #${trial.trial.report_id}`,
    `<span class="mono subtle">${trial.summary.scheduled} / ${trial.summary.orders} 单 · ${hours(trial.summary.hours)}</span>`)}
    <p class="subtle section-note">预排不占用工时${confirmed ? '。本试估已确认，下方为确认后的实际安排，工时已扣减。' : '，确认后才扣减班次余量。'}冻结模型：${esc(trial.trial.model)}。</p>
    <div class="table-wrap"><table><thead><tr><th>工单号 / 视频</th><th>截止日</th><th>试估工时</th><th>预排班次</th><th>说明</th></tr></thead><tbody>
    ${trial.items.map(item => `<tr><td><small class="mono row-code">${esc(item.code)}</small><strong>${esc(item.title)}</strong></td>
      <td class="mono">${day(item.deadline)}</td><td class="mono">${hours(item.hours)}</td>
      <td>${item.shift_id ? `${esc(shiftDate(item.shift_id))} <strong>${esc(shiftName(item.shift_id))}</strong>` : '<span class="muted">未排</span>'}</td>
      <td class="${item.reason ? 'error' : 'subtle'}">${item.shift_id ? (item.recomputed ? '余量变化后按原试估重算' : '按截止日前余量预排') : esc(item.reason || '未排上')}${item.outside_range?.length ? ` · <span class="muted">外推：${item.outside_range.map(key => features[key]).join('、')}</span>` : ''}</td></tr>`).join('')}</tbody></table></div>
    ${confirmed ? `<p class="panel-body subtle">已确认，确认记录 #${trial.confirmation_id}。重复确认不会重复扣减工时。</p>`
      : canEdit() ? `<div class="panel-body form-actions"><button id="confirm-trial" class="accent" type="button">确认排班</button><p id="trial-message" class="error" role="alert"></p></div>` : ''}
  </section>`;
}

export function schedulePage(root) {
  let board = null;
  let trial = null;

  async function draw() {
    board = await api.schedule();
    const published = studio.reports.filter(item => item.status === 'published');
    root.innerHTML = `${heading('排期评估', '排班调度', '按已发布报告试估待排工单，在截止日前的班次余量内尽量多排单；预排不占工时，确认后才扣减。', '')}
      <div class="metrics">${stat('班次数', board.shifts.length, '个')}${stat('待排工单', board.pending.length, '单')}${stat('已排工单', board.assignments.length, '单')}</div>
      <div class="split schedule-split">
        <section class="panel">${panelTitle('班次余量', '<span class="caps">确认后扣减</span>')}${shiftBoard(board)}</section>
        <aside class="panel">${panelTitle('新增班次')}${canEdit() ? `<form id="shift-form" class="panel-form">
          <label>班次名称<input name="name" required maxlength="60" placeholder="例：晚班 A"></label>
          <label>日期<input name="date" type="date" required></label>
          <label>工时容量（h）<input name="capacity_hours" type="number" required min="0.5" max="200" step="any" value="8"></label>
          <p class="error" role="alert"></p><button class="accent" type="submit">建立班次</button></form>` : '<p class="subtle section-note">分析员可维护班次。</p>'}</aside>
      </div>
      <div class="split schedule-split">
        <section class="panel">${panelTitle('待排工单', '<span class="caps">截止日前</span>')}${pendingTable(board)}</section>
        <aside class="panel">${panelTitle('新增待排工单')}${canEdit() ? `<form id="pending-form" class="panel-form">
          <label>工单号<input name="code" required pattern="[A-Z][A-Z0-9\\-]{2,19}" placeholder="QY-0701"></label>
          <label>视频名称<input name="title" required maxlength="90" placeholder="轮渡服务｜夜航指引"></label>
          <label>截止日期<input name="deadline" type="date" required></label>
          <div class="fields">${[
            ['minutes', '成片分钟', {min:.01, max:180, step:'any', value:5.5}],
            ['shots', '镜头数', {min:1, max:1000, step:1, value:22}],
            ['switches', '背景切换次数', {min:0, max:999, step:1, value:2}],
          ].map(([key, label, attrs]) => `<label>${label}<input name="${key}" type="number" required min="${attrs.min}" max="${attrs.max}" step="${attrs.step}" value="${attrs.value}"></label>`).join('')}</div>
          <p class="error" role="alert"></p><button class="accent" type="submit">加入待排</button></form>` : '<p class="subtle section-note">分析员可录入待排工单。</p>'}</aside>
      </div>
      <section class="panel trial-launch">${panelTitle('按已发布报告试估', `<span class="mono subtle">${published.length} 份可用报告</span>`)}
        <form id="trial-form" class="panel-form"><label>已发布报告<select name="report_id" required ${published.length ? '' : 'disabled'}>${published.map(item => `<option value="${item.id}">#${item.id} · ${esc(item.plan_name)} · ${esc(item.holdout)}</option>`).join('')}</select></label>
        <p class="subtle">试估冻结报告中的入选模型，只读取待排工单的成片分钟、镜头数和换景次数。</p>
        <p class="error" role="alert"></p><button class="accent" type="submit" ${published.length ? '' : 'disabled'}>试估待排工单</button></form>
      </section>
      <div id="trial-slot"></div>
      <section class="panel assignments-panel">${panelTitle('已确认的排班', '<span class="caps">逐单去向</span>')}${assignmentTable(board.assignments)}</section>
      <section class="panel unscheduled-panel">${panelTitle('未排上的工单')}${unscheduledTable(board.unscheduled)}</section>`;

    bind();
    drawTrial();
  }

  function drawTrial() {
    const slot = root.querySelector('#trial-slot');
    slot.innerHTML = trial ? trialView(trial, board, draw) : '';
    const confirm = slot.querySelector('#confirm-trial');
    if (confirm) confirm.onclick = () => buttonAction(confirm, slot.querySelector('#trial-message'), async () => {
      await api.confirmTrial(trial.trial.id);
      trial = await api.trialDetail(trial.trial.id);
      await draw();
    });
  }

  function bind() {
    const shiftForm = root.querySelector('#shift-form');
    formSubmit(shiftForm, async data => {
      await api.addShift({name: data.get('name'), date: data.get('date'), capacity_hours: Number(data.get('capacity_hours'))});
      await draw();
    });
    const pendingForm = root.querySelector('#pending-form');
    formSubmit(pendingForm, async data => {
      await api.addPending({code: data.get('code'), title: data.get('title'), deadline: data.get('deadline'),
                            minutes: Number(data.get('minutes')), shots: Number(data.get('shots')),
                            switches: Number(data.get('switches'))});
      await draw();
    });
    const trialForm = root.querySelector('#trial-form');
    formSubmit(trialForm, async data => {
      trial = await api.trial(Number(data.get('report_id')));
      await draw();
    });
  }

  root.innerHTML = empty('正在读取排班数据…');
  draw().catch(error => {
    root.innerHTML = `<section class="panel">${empty(error.message)}<div class="panel-body"><button id="retry" class="button">重试</button></div></section>`;
    root.querySelector('#retry').onclick = () => schedulePage(root);
  });
}
