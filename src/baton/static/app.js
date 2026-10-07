'use strict';

const $ = (id) => document.getElementById(id);
const labels = { all: 'All handoffs', available: 'Ready to resume', claimed: 'In progress', completed: 'Completed' };
const state = { status: 'all', selected: location.pathname.startsWith('/handoffs/') ? location.pathname.split('/')[2] : null, detail: null, cursor: null, items: [], generation: 0, pages: 1 };
let toastTimer, searchTimer;
let session = null;  // Set when the host serves /api/session.

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

const TOKEN_KEY = 'baton.accessToken';
function accessToken() { try { return localStorage.getItem(TOKEN_KEY) || ''; } catch { return ''; } }
function storeToken(value) {
  try { if (value) localStorage.setItem(TOKEN_KEY, value); else localStorage.removeItem(TOKEN_KEY); } catch { /* storage unavailable */ }
  updateAuthUI();
}
function authHeaders(value = accessToken()) { return value ? { authorization: 'Bearer ' + value } : {}; }

// Servers that wrap Baton with authentication answer 401; ask for an access token instead of failing.
function requireSignIn() {
  if (accessToken()) storeToken('');
  if (!$('signin-dialog').open) { $('signin-error').hidden = true; $('signin-dialog').showModal(); $('signin-token').focus(); }
}

function goToLogin(loginUrl) {
  const target = new URL(loginUrl, location.origin);
  if (target.origin !== location.origin) return false;  // Only follow same-origin login pages.
  target.searchParams.set('return_to', location.pathname + location.search);
  location.assign(target.href);
  return true;
}

async function api(path, options = {}) {
  // Same-origin credentials let hosts that wrap Baton use session cookies; plain Baton sets none.
  const response = await fetch(path, { credentials: 'same-origin', cache: 'no-store', ...options, headers: { ...(options.headers || {}), ...authHeaders() } });
  if (response.status === 401) {
    const body = await response.json().catch(() => ({}));
    if (!body.login_url || !goToLogin(body.login_url)) requireSignIn();
    throw new Error('Sign in to continue.');
  }
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
  $('count-memories').textContent = data.memories;
  $('memory-total').textContent = data.memories;
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
  showMemoryView(false);
  history.pushState({}, '', state.selected ? '/handoffs/' + encodeURIComponent(state.selected) : '/');
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
function updateAuthUI() {
  const signedIn = Boolean(accessToken());
  $('signout-button').hidden = !signedIn && !session?.logout_url;
  // Show a placeholder rather than the real token so it never appears in screenshots or screen shares.
  $('codex-add').textContent = signedIn ? `export BATON_TOKEN=YOUR_TOKEN\ncodex mcp add baton --url ${mcpUrl} --bearer-token-env-var BATON_TOKEN` : `codex mcp add baton --url ${mcpUrl}`;
  $('claude-add').textContent = `claude mcp add --scope user --transport http baton ${mcpUrl}` + (signedIn ? ' --header "Authorization: Bearer YOUR_TOKEN"' : '');
  $('setup-intro').textContent = signedIn ? 'Add this Streamable HTTP MCP server to your harness. Requests need your access token (replace YOUR_TOKEN).'
    : 'Add this Streamable HTTP MCP server to your harness. No token or login is needed.';
  $('setup-auth').textContent = signedIn ? 'In Cursor, OMP, Hermes Agent, or another compatible client, add an HTTP server with the URL above and the header Authorization: Bearer YOUR_TOKEN.'
    : 'In Cursor, OMP, Hermes Agent, or another compatible client, add an HTTP server with the URL above and authentication set to None.';
}
updateAuthUI();
$('signin-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const value = $('signin-token').value.trim();
  if (!value) return;
  $('signin-submit').disabled = true;
  try {
    const response = await fetch('/api/overview', { credentials: 'omit', cache: 'no-store', headers: authHeaders(value) });
    if (!response.ok) throw new Error(response.status === 401 ? 'That token was not accepted.' : 'The server could not check the token.');
    storeToken(value);
    $('signin-token').value = '';
    $('signin-dialog').close();
    error();
    route();
  } catch (exception) { $('signin-error').textContent = exception.message; $('signin-error').hidden = false; }
  finally { $('signin-submit').disabled = false; }
});
$('signout-button').addEventListener('click', async () => {
  if (session?.logout_url) {
    await fetch(session.logout_url, { method: 'POST', credentials: 'same-origin' }).catch(() => {});
    location.assign('/');
    return;
  }
  storeToken(''); requireSignIn();
});

// Hosts that add accounts can describe the signed-in user at /api/session; plain Baton answers 404.
async function loadSession() {
  try {
    const response = await fetch('/api/session', { credentials: 'same-origin', cache: 'no-store', headers: authHeaders() });
    if (!response.ok) return;
    session = await response.json();
    const name = session.user?.name || session.user?.login || 'Signed in';
    $('workspace-name').textContent = session.workspace?.name || name;
    $('workspace-detail').textContent = session.user?.login ? `Signed in as ${session.user.login}` : 'Signed in';
    $('workspace-avatar').textContent = name.trim().charAt(0).toUpperCase() || '·';
    if (session.logout_url) $('signout-button').hidden = false;
  } catch { /* optional */ }
}
loadSession();
$('copy-mcp-url').addEventListener('click', () => copy(mcpUrl));
$('setup-button').addEventListener('click', () => $('setup-dialog').showModal());
$('close-setup').addEventListener('click', () => $('setup-dialog').close());
$('close-copy').addEventListener('click', () => $('copy-dialog').close());

const memories = { active: false, selected: null, items: [], cursor: null, generation: 0, detail: null, pages: 1 };
let memorySearchTimer;

function memoryError(message = '') {
  $('memory-error').hidden = !message;
  $('memory-error').textContent = message;
  if (message) $('memory-sync').textContent = 'Could not refresh';
}

function showMemoryView(active) {
  memories.active = active;
  $('handoff-view').hidden = active;
  $('memory-view').hidden = !active;
  $('memories-button').classList.toggle('active', active);
  for (const item of document.querySelectorAll('[data-status]')) item.classList.toggle('active', !active && item.dataset.status === state.status);
}

function renderMemories() {
  const list = $('memory-list');
  list.replaceChildren();
  if (!memories.items.length) {
    const empty = el('div', 'empty-list');
    const filtered = $('memory-search').value || $('memory-category').value;
    empty.append(el('strong', '', filtered ? 'No matching memories.' : 'No personal memories yet.'), el('p', '', filtered ? 'Try a different search or category.' : 'Tell your AI harness “update my Baton memory” to save what it knows about you.'));
    list.append(empty);
  }
  for (const item of memories.items) {
    const row = button('', 'handoff-row memory-row' + (item.key === memories.selected ? ' selected' : ''), () => chooseMemory(item.key));
    row.setAttribute('aria-pressed', String(item.key === memories.selected));
    const top = el('div', 'row-top');
    top.append(el('span', 'badge', item.category.replaceAll('_', ' ')), el('time', '', relative(item.updated_at)));
    row.append(top, el('div', 'row-title', item.key), el('div', 'row-preview', item.content), el('div', 'row-bottom', `${item.source.client} · ${item.basis}`));
    list.append(row);
  }
  $('memory-more').hidden = !memories.cursor;
}

async function loadMemories(append = false) {
  const generation = ++memories.generation;
  const query = new URLSearchParams({ limit: '20' });
  if ($('memory-search').value.trim()) query.set('q', $('memory-search').value.trim());
  if ($('memory-category').value) query.set('category', $('memory-category').value);
  if (append && memories.cursor) query.set('cursor', memories.cursor);
  $('memory-more').disabled = true;
  try {
    const response = await api('/api/memories?' + query);
    if (generation !== memories.generation) return;
    memories.items = append ? [...memories.items, ...response.data.items] : response.data.items;
    memories.cursor = response.data.next_cursor;
    memories.pages = append ? memories.pages + 1 : 1;
    renderMemories();
    memoryError();
    $('memory-sync').textContent = 'Updated ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch (exception) { if (generation === memories.generation) memoryError(exception.message); }
  finally { if (generation === memories.generation) $('memory-more').disabled = false; }
}

function renderMemoryDetail(item) {
  const panel = $('memory-detail');
  panel.replaceChildren();
  const header = el('header', 'detail-header');
  header.append(el('div', 'eyebrow', item.deleted ? 'FORGOTTEN MEMORY' : 'PERSONAL MEMORY'), el('h2', '', item.key));
  if (!item.deleted) header.append(button('Copy memory', 'button secondary', () => copy(item.content)));
  const content = el('div', 'detail-content');
  if (item.deleted) {
    textSection(content, 'Forgotten', 'This memory was removed from Baton. Its content and evidence are no longer stored. Other harnesses can retrieve this deletion marker.');
  } else {
    textSection(content, 'Memory', item.content);
    textSection(content, 'Category & basis', `${item.category.replaceAll('_', ' ')} · ${item.basis}`);
    textSection(content, 'Original source', item.source.client);
    if (item.source.model) textSection(content, 'Source model', item.source.model);
    textSection(content, 'Evidence', item.evidence);
    textSection(content, 'Source conversation', item.source.conversation_ref);
    if (item.source.captured_at) textSection(content, 'Source captured', date(item.source.captured_at));
    textSection(content, 'Last updated by', item.updated_by);
  }
  textSection(content, 'Last updated', date(item.updated_at));
  textSection(content, 'Created', date(item.created_at));
  textSection(content, 'Revision', String(item.revision));
  textSection(content, 'Memory ID', item.id);
  content.append(el('p', 'trust-note', 'Ask your harness to correct or forget a memory. Baton shares personal context; each harness decides whether to remember it locally.'));
  panel.append(header, content);
}

async function memoryDetail(key) {
  try {
    const response = await api('/api/memories/' + encodeURIComponent(key));
    if (memories.selected !== key) return;
    const item = response.data.items[0];
    if (!item) {
      memories.detail = null;
      const empty = el('div', 'empty-detail');
      empty.append(el('h2', '', 'Memory not found'), el('p', '', 'Choose a memory from the list.'));
      $('memory-detail').replaceChildren(empty);
    } else if (!memories.detail || memories.detail.key !== key || memories.detail.revision !== item.revision) {
      memories.detail = item;
      renderMemoryDetail(item);
    }
  } catch (exception) { if (memories.selected === key) memoryError(exception.message); }
}

function chooseMemory(key, updateURL = true) {
  memories.selected = key;
  memories.detail = null;
  if (updateURL) history.pushState({}, '', '/memories/' + encodeURIComponent(key));
  renderMemories();
  $('memory-detail').replaceChildren(el('div', 'empty-detail', 'Loading memory…'));
  memoryDetail(key);
  if (matchMedia('(max-width:620px)').matches) $('memory-detail').scrollIntoView({ behavior: 'instant', block: 'start' });
}

async function refreshMemories() {
  $('memory-refresh').disabled = true;
  try {
    await overview();
    await loadMemories();
    if (memories.selected) await memoryDetail(memories.selected);
  } catch (exception) { memoryError(exception.message); }
  finally { $('memory-refresh').disabled = false; }
}

function route() {
  const active = location.pathname === '/memories' || location.pathname.startsWith('/memories/');
  showMemoryView(active);
  if (active) {
    memories.selected = location.pathname.split('/')[2] || null;
    memories.detail = null;
    $('memory-detail').replaceChildren(el('div', 'empty-detail', memories.selected ? 'Loading memory…' : 'Select a memory to see its source and latest update.'));
    refreshMemories();
  } else {
    state.selected = location.pathname.split('/')[2] || null;
    state.detail = null;
    enter().catch((exception) => error(exception.message));
  }
}

$('memories-button').addEventListener('click', () => { history.pushState({}, '', '/memories'); route(); });
$('memory-refresh').addEventListener('click', refreshMemories);
$('memory-more').addEventListener('click', () => loadMemories(true));
$('memory-search').addEventListener('input', () => { clearTimeout(memorySearchTimer); memorySearchTimer = setTimeout(() => loadMemories(), 250); });
$('memory-category').addEventListener('change', () => loadMemories());
addEventListener('popstate', route);
setInterval(async () => {
  if (document.hidden || $('setup-dialog').open || $('signin-dialog').open) return;
  if (memories.active) {
    try {
      await overview();
      if (memories.pages === 1 && !$('memory-search').matches(':focus')) await loadMemories();
      if (memories.selected) await memoryDetail(memories.selected);
    } catch (exception) { memoryError(exception.message); }
    return;
  }
  try { await overview(); if (state.pages === 1 && !$('search').matches(':focus')) await loadList(); if (state.selected) await detail(state.selected, true); }
  catch (exception) { error(exception.message); }
}, 15000);
route();
