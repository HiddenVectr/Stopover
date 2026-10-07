'use strict';

const $ = (id) => document.getElementById(id);
const labels = { all: 'All handoffs', available: 'Ready to resume', claimed: 'In progress', completed: 'Completed' };
const state = { status: 'all', selected: location.pathname.split('/')[2] || null, detail: null, cursor: null, items: [], generation: 0, pages: 1 };
let toastTimer, searchTimer;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function button(text, className, callback) {
  const node = el('button', className, text);
  node.type = 'button';
  node.addEventListener('click', callback);
  return node;
}

function date(value) { return value ? new Date(value).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : '—'; }
function relative(value) {
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(value)) / 60000));
  return minutes < 1 ? 'Just now' : minutes < 60 ? `${minutes}m ago` : minutes < 1440 ? `${Math.floor(minutes / 60)}h ago` : new Date(value).toLocaleDateString([], { month: 'short', day: 'numeric' });
}
function badge(status) { return el('span', `badge ${status}`, labels[status] || status); }

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    showToast('Copied to clipboard');
  } catch {
    $('copy-text').value = text;
    $('copy-dialog').showModal();
    $('copy-text').focus();
    $('copy-text').select();
  }
}

function showToast(message) {
  $('toast').textContent = message;
  $('toast').hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $('toast').hidden = true; }, 3500);
}

async function api(path, options = {}) {
  const response = await fetch(path, { credentials: 'omit', cache: 'no-store', ...options });
  const data = await response.json();
  if (!response.ok || data.ok === false) throw new Error(data.error?.message || data.error || 'The local service could not complete this request.');
  return data;
}

function error(message = '') {
  $('global-error').hidden = !message;
  $('global-error').textContent = message;
  if (message) $('sync-state').textContent = 'Could not refresh';
}

function options(id, values, first) {
  const selected = $(id).value;
  $(id).replaceChildren(new Option(first, ''), ...values.map((value) => new Option(value, value)));
  if (values.includes(selected)) $(id).value = selected;
}

async function overview() {
  const data = await api('/api/overview');
  $('count-all').textContent = data.total;
  $('summary-total').textContent = data.total;
  for (const name of ['available', 'claimed', 'completed']) $('count-' + name).textContent = data.counts[name];
  options('project-filter', data.projects, 'All projects');
  options('target-filter', data.targets, 'All receiving agents');
}

function renderList() {
  const container = $('handoff-list');
  container.replaceChildren();
  if (!state.items.length) {
    const empty = el('div', 'empty-list');
    empty.append(el('strong', '', 'No handoffs here yet.'), el('p', '', 'Ask your AI harness to upload a handoff. Its context will appear here, ready for the next session.'), button('Connect your agents ↗', 'button secondary', () => $('setup-dialog').showModal()));
    container.append(empty);
  }
  for (const item of state.items) {
    const row = button('', 'handoff-row' + (item.id === state.selected ? ' selected' : ''), () => choose(item.id));
    row.setAttribute('aria-pressed', String(item.id === state.selected));
    const top = el('div', 'row-top');
    const when = el('time', '', relative(item.created_at));
    when.dateTime = item.created_at;
    when.title = date(item.created_at);
    top.append(badge(item.effective_status), when);
    const bottom = el('div', 'row-bottom');
    if (item.project_key) bottom.append(el('span', 'project-tag', item.project_key));
    bottom.append(el('span', 'agent-route', `${item.source_client} → ${item.target_client || 'Any agent'}`));
    row.append(top, el('div', 'row-title', item.title), el('div', 'row-preview', item.preview), bottom);
    container.append(row);
  }
  $('load-more').hidden = !state.cursor;
}

async function loadList(append = false) {
  const generation = ++state.generation;
  const query = new URLSearchParams({ status: state.status, limit: '20' });
  for (const [field, id] of [['q', 'search'], ['project_key', 'project-filter'], ['target_client', 'target-filter']]) {
    if ($(id).value.trim()) query.set(field, $(id).value.trim());
  }
  if (append && state.cursor) query.set('cursor', state.cursor);
  $('load-more').disabled = true;
  try {
    const response = await api('/api/handoffs?' + query);
    if (generation !== state.generation) return;
    state.items = append ? [...state.items, ...response.data.items] : response.data.items;
    state.cursor = response.data.next_cursor;
    state.pages = append ? state.pages + 1 : 1;
    renderList();
    $('sync-state').textContent = 'Updated ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    error();
  } catch (exception) { error(exception.message); }
  finally { $('load-more').disabled = false; }
}

function section(parent, title) {
  const node = el('section', 'section');
  node.append(el('h3', '', title));
  parent.append(node);
  return node;
}

function textSection(parent, title, text) {
  if (text) section(parent, title).append(el('p', '', text));
}

function listSection(parent, title, items) {
  if (!items?.length) return;
  const list = el('ul');
  items.forEach((item) => list.append(el('li', '', item)));
  section(parent, title).append(list);
}

function cards(parent, title, items, render) {
  if (!items?.length) return;
  const node = section(parent, title);
  for (const item of items) {
    const card = el('div', 'detail-card');
    render(card, item);
    node.append(card);
  }
}

function evidence(card, item) {
  if (item.evidence_ids?.length) card.append(el('div', 'evidence-ids', 'Evidence: ' + item.evidence_ids.join(', ')));
}

function renderDetail(data) {
  const panel = $('detail');
  panel.replaceChildren();
  const record = data.record;
  const context = record.context;
  const header = el('header', 'detail-header');
  const eyebrow = el('div', 'eyebrow', 'HANDOFF BRIEF');
  eyebrow.append(badge(data.effective_status));
  const id = el('div', 'id-row');
  id.append(el('code', '', data.id), button('Copy ID', 'copy-small', () => copy(data.id)));
  const actions = el('div', 'detail-actions');
  actions.append(button('Copy resume prompt ↗', 'button primary', () => copy(`Resume Handoff ${data.id}`)), button('Copy full record', 'button secondary', () => copy(JSON.stringify(data, null, 2))));
  header.append(eyebrow, el('h2', '', record.title), id, actions);
  const metadata = el('dl', 'metadata');
  const fields = [['FROM', record.source.client], ['TO', record.target_client || 'Any agent'], ['PROJECT', record.project_key || 'No project'], ['CREATED', date(data.created_at)], ['LAST UPDATED', date(data.updated_at)], ['REVISION', data.revision]];
  if (data.claim.holder_label) fields.push(['CLAIM HOLDER', data.claim.holder_label], ['CLAIM EXPIRES', date(data.claim.expires_at) + (data.claim.active ? '' : ' (inactive)')]);
  for (const [key, value] of fields) { const pair = el('div'); pair.append(el('dt', '', key), el('dd', '', value)); metadata.append(pair); }
  const content = el('div', 'detail-content');
  if (data.completion) {
    const complete = section(content, 'Outcome');
    const card = el('div', 'detail-card outcome-card');
    card.append(el('span', 'card-label', data.completion.outcome), el('p', '', data.completion.summary));
    complete.append(card);
    cards(content, 'Acceptance results', data.completion.acceptance_results, (card, item) => { card.append(el('span', 'card-label', item.result), el('strong', '', item.criterion), el('p', 'muted', item.evidence)); });
    listSection(content, 'Remaining work', data.completion.remaining_work);
  }
  textSection(content, 'Objective', context.objective);
  textSection(content, 'Where things stand', context.current_state);
  const next = section(content, 'Next steps');
  const ordered = el('ol');
  for (const step of context.next_steps) { const li = el('li', 'next-step'); li.append(el('strong', '', step.action), el('span', 'done-when', 'Done when: ' + step.done_when)); ordered.append(li); }
  next.append(ordered);
  listSection(content, 'Definition of done', context.acceptance_criteria);
  textSection(content, 'Background', context.background);
  listSection(content, 'Constraints', context.constraints);
  cards(content, 'Decisions & reasons', context.decisions, (card, item) => { card.append(el('strong', '', item.decision), el('p', 'muted', item.reason)); evidence(card, item); });
  cards(content, 'What has been tried', context.attempts, (card, item) => { card.append(el('span', 'card-label', item.verification.replaceAll('_', ' ')), el('strong', '', item.action), el('p', 'muted', item.result)); evidence(card, item); });
  cards(content, 'Facts & assumptions', context.facts, (card, item) => { card.append(el('span', 'card-label', item.basis), el('p', '', item.text)); evidence(card, item); });
  listSection(content, 'Open questions', context.open_questions);
  listSection(content, 'Source resume suggestions', context.resume_instructions);
  const renderReference = (card, item) => {
    card.append(el('span', 'card-label', `${item.id} · ${item.kind} · ${item.availability.replaceAll('_', ' ')}`), el('strong', '', item.purpose), el('p', 'mono', item.locator));
    if (item.excerpt) card.append(el('pre', '', item.excerpt));
    if (item.sha256) card.append(el('p', 'small mono', 'SHA-256: ' + item.sha256));
    if (item.observed_at) card.append(el('p', 'small muted', 'Observed ' + date(item.observed_at)));
  };
  cards(content, 'References', record.references, renderReference);
  if (data.completion) cards(content, 'Result artifacts', data.completion.artifacts, renderReference);
  textSection(content, 'Summary coverage', record.coverage.basis);
  listSection(content, 'Omitted context', record.coverage.omitted);
  const source = section(content, 'Source & scope');
  source.append(el('p', '', record.authorization.scope));
  if (record.authorization.user_request_excerpt) source.append(el('p', 'muted', record.authorization.user_request_excerpt));
  listSection(content, 'Reported confirmation requirements', record.authorization.requires_confirmation);
  source.append(el('p', 'small muted', `Authored as ${record.source.authoring_method.replaceAll('_', ' ')} · ${record.source.transfer_method.replaceAll('_', ' ')}`));
  if (record.source.model) source.append(el('p', 'small muted', 'Model: ' + record.source.model));
  if (record.source.captured_at) source.append(el('p', 'small muted', 'Captured: ' + date(record.source.captured_at)));
  if (record.source.conversation_ref) source.append(el('p', 'small mono', record.source.conversation_ref));
  if (record.parent_id) source.append(button('View parent handoff ↗', 'button secondary', () => choose(record.parent_id)));
  const activity = section(content, 'Activity');
  activity.id = 'activity';
  activity.append(el('p', 'small muted', 'Loading history…'));
  const raw = el('details', 'raw-details');
  raw.append(el('summary', '', 'Full record · schema ' + record.schema_version), el('pre', '', JSON.stringify(data, null, 2)));
  content.append(raw, el('p', 'trust-note', data.trust_notice));
  panel.append(header, metadata, content);
  loadEvents(data.id, activity).catch((exception) => { activity.append(el('p', 'error', exception.message)); });
}

async function loadEvents(id, target, before = null) {
  const response = await api(`/api/handoffs/${encodeURIComponent(id)}/events${before ? '?before=' + before : ''}`);
  if (state.selected !== id || !target.isConnected) return;
  if (!before) { target.replaceChildren(el('h3', '', 'Activity')); target.append(el('ul', 'timeline')); }
  target.querySelector('.load-events')?.remove();
  const list = target.querySelector('ul');
  for (const item of response.items) {
    const li = el('li');
    li.append(el('strong', '', `${item.event === 'pushed' ? 'Handoff saved' : item.event.charAt(0).toUpperCase() + item.event.slice(1)} · revision ${item.revision}`), el('time', '', date(item.at)));
    for (const [key, value] of Object.entries(item.details)) if (value != null) li.append(el('div', 'small', key.replaceAll('_', ' ') + ': ' + value));
    list.append(li);
  }
  if (response.next_cursor) target.append(button('Earlier activity', 'button secondary load-events', () => loadEvents(id, target, response.next_cursor).catch((exception) => showToast(exception.message))));
}

async function detail(id, silent = false) {
  try {
    const response = await api('/api/handoffs/' + encodeURIComponent(id));
    if (state.selected !== id) return;
    if (!silent || !state.detail || state.detail.id !== id || state.detail.revision !== response.data.revision || state.detail.effective_status !== response.data.effective_status) {
      state.detail = response.data;
      renderDetail(response.data);
    }
  } catch (exception) {
    if (state.selected !== id) return;
    if (!silent) { const message = el('div', 'empty-detail'); message.append(el('h2', '', 'Could not open this handoff'), el('p', 'error', exception.message), button('Try again', 'button secondary', () => detail(id))); $('detail').replaceChildren(message); }
    else error(exception.message);
  }
}

function choose(id, updateURL = true) {
  state.selected = id;
  state.detail = null;
  if (updateURL) history.pushState({}, '', '/handoffs/' + encodeURIComponent(id));
  renderList();
  detail(id);
  if (matchMedia('(max-width:620px)').matches) $('detail').scrollIntoView({ behavior: 'instant', block: 'start' });
}

async function refresh() {
  $('refresh-button').disabled = true;
  try {
    await overview();
    await loadList();
    if (state.selected) await detail(state.selected, true);
  } catch (exception) { error(exception.message); }
  finally { $('refresh-button').disabled = false; }
}

async function enter() {
  if (!state.selected) {
    const empty = el('div', 'empty-detail');
    empty.append(el('span', 'empty-icon', '⇄'), el('h2', '', 'A clear place to continue.'), el('p', '', 'Select a handoff to explore its context, decisions, and next steps.'), el('span', 'small muted', 'Any compatible MCP harness'));
    $('detail').replaceChildren(empty);
  }
  await refresh();
}

for (const item of document.querySelectorAll('[data-status]')) item.addEventListener('click', () => {
  state.status = item.dataset.status;
  for (const other of document.querySelectorAll('[data-status]')) other.classList.toggle('active', other === item);
  $('page-title').textContent = labels[state.status];
  loadList();
});
$('search').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => loadList(), 250); });
for (const id of ['project-filter', 'target-filter']) $(id).addEventListener('change', () => loadList());
$('refresh-button').addEventListener('click', refresh);
$('load-more').addEventListener('click', () => loadList(true));
const mcpUrl = new URL('/mcp', location.origin).href;
$('mcp-url').textContent = mcpUrl;
$('codex-add').textContent = `codex mcp add handoff --url ${mcpUrl}`;
$('claude-add').textContent = `claude mcp add --scope user --transport http handoff ${mcpUrl}`;
$('copy-mcp-url').addEventListener('click', () => copy(mcpUrl));
$('setup-button').addEventListener('click', () => $('setup-dialog').showModal());
$('close-setup').addEventListener('click', () => $('setup-dialog').close());
$('close-copy').addEventListener('click', () => $('copy-dialog').close());
addEventListener('popstate', () => { const id = location.pathname.split('/')[2]; if (id) choose(id, false); else { state.selected = null; state.detail = null; enter().catch((exception) => error(exception.message)); } });
setInterval(async () => {
  if (document.hidden || $('setup-dialog').open) return;
  try { await overview(); if (state.pages === 1 && !$('search').matches(':focus')) await loadList(); if (state.selected) await detail(state.selected, true); }
  catch (exception) { error(exception.message); }
}, 15000);
enter().catch((exception) => error(exception.message));
