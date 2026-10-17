'use strict';

const $ = (id) => document.getElementById(id);
const labels = { inbox: 'Inbox', done: 'Done', search: 'Search' };
const state = { view: 'inbox', project: '', sections: { needs: [], ready: [], busy: [] }, total: 0, folds: new Set(), selected: location.pathname.startsWith('/handoffs/') ? location.pathname.split('/')[2] : null, detail: null, cursor: null, items: [], generation: 0, pages: 1 };
let toastTimer, searchTimer;
let session = null;  // Set when the host serves /api/session.
// The product name the server put in the page (a host can rebrand it with create_app(brand=...)).
const BRAND = document.querySelector('[data-brand="name"]')?.textContent || 'Stopover';

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
function day(value) { return value ? new Date(value).toLocaleDateString([], { dateStyle: 'medium' }) : '—'; }
function relative(value) {
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(value)) / 60000));
  return minutes < 1 ? 'Just now' : minutes < 60 ? `${minutes}m ago` : minutes < 1440 ? `${Math.floor(minutes / 60)}h ago` : new Date(value).toLocaleDateString([], { month: 'short', day: 'numeric' });
}
function badge(kind, text) { return el('span', `badge ${kind}`, text); }
// Agents report their own names ("claude-code", "Codex"); show the familiar ones nicely and the rest as given.
const AGENTS = { 'claude-code': 'Claude Code', claudecode: 'Claude Code', codex: 'Codex', cursor: 'Cursor', omp: 'OMP', hermes: 'Hermes', 'muse-code': 'Muse Code' };
function agentName(value) { return value ? AGENTS[String(value).toLowerCase().replace(/[\s_]+/g, '-')] || value : 'an agent'; }
function waitingQuestions(item) { return item.questions ? item.questions.open - item.questions.answered : 0; }
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
const narrow = () => matchMedia('(max-width: 900px)').matches;
const sentence = (text) => text.charAt(0).toUpperCase() + text.slice(1);
// "Saved 5m ago", "Saved just now", "Saved Oct 3".
const since = (value) => relative(value).replace(/^Just now$/, 'just now');
// Phones show one pane at a time (the list, or a detail with a Back button); wider screens show both.
function syncPanes() {
  document.body.classList.toggle('detail-open', !memories.active && Boolean(state.selected));
  document.body.classList.toggle('memory-open', memories.active && Boolean(memories.selected));
}
function backButton(label, callback) {
  const node = button('', 'back-button', callback);
  node.append(el('span', '', '←'), el('span', '', label));
  node.setAttribute('aria-label', 'Back to ' + label.toLowerCase());
  return node;
}

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

const TOKEN_KEY = 'stopover.accessToken';
function accessToken() { try { return localStorage.getItem(TOKEN_KEY) || ''; } catch { return ''; } }
function storeToken(value) {
  try { if (value) localStorage.setItem(TOKEN_KEY, value); else localStorage.removeItem(TOKEN_KEY); } catch { /* storage unavailable */ }
  updateAuthUI();
}
function authHeaders(value = accessToken()) { return value ? { authorization: 'Bearer ' + value } : {}; }

// Servers that wrap Stopover with authentication answer 401; ask for an access token instead of failing.
function requireSignIn() {
  if (accessToken()) storeToken('');
  if (!$('signin-dialog').open) { $('signin-error').hidden = true; $('signin-dialog').showModal(); $('signin-token').focus(); }
}

let redirectingToLogin = false;
function goToLogin(loginUrl) {
  const target = new URL(loginUrl, location.origin);
  if (target.origin !== location.origin) return false;  // Only follow same-origin login pages.
  // Several requests can fail at once; start a single sign-in so its state cookie matches the redirect.
  if (redirectingToLogin) return true;
  redirectingToLogin = true;
  target.searchParams.set('return_to', location.pathname + location.search);
  location.assign(target.href);
  return true;
}

async function api(path, options = {}) {
  // Same-origin credentials let hosts that wrap Stopover use session cookies; plain Stopover sets none.
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

async function overview() {
  const data = await api('/api/overview');
  $('count-memories').textContent = data.memories;
  $('memory-total').textContent = data.memories;
  state.total = data.total;
  $('count-open').textContent = data.counts.available + data.counts.claimed;
  $('count-completed').textContent = data.counts.completed;
  const waiting = data.counts.needs_you ?? 0;
  $('count-needs_you').textContent = waiting;
  $('count-needs_you').hidden = !waiting;
}

const searching = () => Boolean($('search').value.trim());
// What the list shows: the inbox (open work in sections), done work, or search results across everything.
const mode = () => searching() ? 'search' : state.view;

function setProject(project) {
  state.project = project;
  $('project-chip').hidden = !project;
  $('project-chip').textContent = project ? `${project} ×` : '';
  $('project-chip').setAttribute('aria-label', project ? `Showing ${project} only. Show all projects` : '');
  loadList();
}

function clearFilters() {
  $('search').value = '';
  setProject('');
}

// Rebuilding a list (selection, or the 15-second refresh) must not lose keyboard focus or the list's scroll position.
function keepPlace(container, render) {
  const focused = container.contains(document.activeElement) ? document.activeElement.dataset.key : null;
  const scroller = container.closest('.list') || container;
  const top = scroller.scrollTop;
  render();
  scroller.scrollTop = top;
  if (focused) container.querySelector(`[data-key="${CSS.escape(focused)}"]`)?.focus({ preventScroll: true });
}

function renderList() {
  const container = $('handoff-list');
  keepPlace(container, () => mode() === 'inbox' ? renderInbox(container) : renderRows(container));
  if (!state.selected) $('detail').replaceChildren(idlePanel());
}

// Summary paragraphs: the saving agent's paragraph or two. Short or missing summaries (older handoffs) are filled out
// with where things stand and the first next step.
function summary(parent, context, data) {
  const box = el('div', 'detail-summary');
  const paragraphs = (context.summary || '').split(/\n\s*\n/).map((text) => text.trim()).filter(Boolean);
  if (!paragraphs.length) paragraphs.push(context.objective.trim());
  const brief = paragraphs.length < 2 && paragraphs[0].length < 320;
  const where = context.current_state.trim();
  if (brief && where && !paragraphs.includes(where)) paragraphs.push(where);
  for (const text of paragraphs) box.append(el('p', 'glance-summary', text));
  const first = context.next_steps[0];
  if (brief && !data.completion && first) {
    const next = el('p', 'glance-next');
    next.append(el('strong', '', 'Next: '), document.createTextNode(first.action));
    box.append(next);
  }
  parent.append(box);
}

// Handoffs grouped by project, in order of each project's newest handoff; those without a project come last.
function byProject(items) {
  const groups = new Map();
  for (const item of items) {
    const key = item.project_key || '';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  }
  const keys = [...groups.keys()].filter(Boolean);
  if (groups.has('')) keys.push('');
  return keys.map((key) => [key, groups.get(key)]);
}

// Rows under small project labels. A label is only shown when it tells you something: several projects, and no
// project filter already applied.
function groupedRows(container, items, options = {}) {
  const groups = byProject(items);
  const labelled = !state.project && !(groups.length === 1 && groups[0][0] === '') && (groups.length > 1 || options.alwaysLabel);
  for (const [project, rows] of groups) {
    if (labelled) {
      const label = project ? button(project, 'project-label', () => setProject(project)) : el('div', 'project-label none', 'No project');
      if (project) label.title = `Show only ${project}`;
      container.append(label);
    }
    for (const item of rows) container.append(handoffRow(item, { showProject: !labelled && !state.project, ...options }));
  }
}

function emptyList(container, title, text, ...actions) {
  const empty = el('div', 'empty-list');
  empty.append(el('strong', '', title), el('p', '', text), ...actions);
  container.append(empty);
}

function renderInbox(container) {
  container.replaceChildren();
  const { needs, ready, busy } = state.sections;
  if (!needs.length && !ready.length && !busy.length) {
    if (state.project) emptyList(container, `Nothing open in ${state.project}.`, 'Its handoffs are all done.', button('Show all projects', 'button secondary', () => setProject('')));
    else if (state.total) emptyList(container, 'You’re all caught up.', 'Nothing is waiting. When an agent saves a handoff, it appears here, ready for the next one to continue.');
    else emptyList(container, 'No handoffs yet.', 'Ask your AI agent to save a handoff. Its context will appear here, ready for the next session.', button('Connect your agents ↗', 'button secondary', () => $('setup-dialog').showModal()));
  }
  for (const [title, items, note] of [['Needs you', needs, 'Answer before the next agent continues'], ['Ready to continue', ready, ''], ['With an agent', busy, '']]) {
    if (!items.length) continue;
    const heading = el('div', 'list-section');
    heading.append(el('h2', '', title), el('span', 'count', items.length));
    container.append(heading);
    if (note) container.append(el('p', 'list-section-note', note));
    groupedRows(container, items);
  }
  $('load-more').hidden = true;
}

function renderRows(container) {
  container.replaceChildren();
  if (!state.items.length) {
    if (mode() === 'search' || state.project) emptyList(container, 'No matching handoffs.', 'Nothing matches this search or project.', button('Clear filters', 'button secondary', clearFilters));
    else emptyList(container, 'Nothing done yet.', 'When an agent finishes a handoff, its outcome appears here.');
  }
  groupedRows(container, state.items, { showStatus: mode() === 'search' });
  $('load-more').hidden = !state.cursor;
}

function handoffRow(item, { showProject = false, showStatus = false } = {}) {
  const row = button('', 'handoff-row' + (item.id === state.selected ? ' selected' : ''), () => choose(item.id, true, true));
  row.dataset.key = item.id;
  row.setAttribute('aria-pressed', String(item.id === state.selected));
  const top = el('div', 'row-top');
  const when = el('time', '', relative(item.created_at));
  when.dateTime = item.created_at;
  when.title = date(item.created_at);
  top.append(el('span', 'row-title', item.title), when);
  const meta = el('div', 'row-meta');
  // A badge only when it tells you something the section doesn't.
  if (item.needs_you) meta.append(badge('needs_you', plural(waitingQuestions(item), 'question') + ' for you'));
  else if (item.claim.active) meta.append(badge('claimed', 'With ' + agentName(item.claim.holder_label)));
  else if (showStatus && item.effective_status === 'completed') meta.append(badge('completed', 'Done'));
  else if (showStatus) meta.append(badge('available', 'Ready'));
  const facts = [];
  if (showProject && item.project_key) facts.push(item.project_key);
  facts.push('from ' + agentName(item.source_client));
  if (item.target_client && !item.claim.active && item.effective_status !== 'completed') facts.push('for ' + agentName(item.target_client));
  meta.append(el('span', 'row-facts', facts.join(' · ')));
  // A lapsed claim isn't proof the agent stopped, but anyone can continue it now.
  if (item.status === 'claimed' && !item.claim.active) meta.append(el('span', 'row-note', `${agentName(item.claim.holder_label)}’s claim expired`));
  row.append(top, el('div', 'row-preview', item.preview), meta);
  return row;
}

async function fetchAll(status, pages = 5) {
  let items = [], cursor = null;
  for (let page = 0; page < pages; page += 1) {
    const query = new URLSearchParams({ status, limit: '20' });
    if (state.project) query.set('project_key', state.project);
    if (cursor) query.set('cursor', cursor);
    const response = await api('/api/handoffs?' + query);
    items = items.concat(response.data.items);
    cursor = response.data.next_cursor;
    if (!cursor) break;
  }
  return items;
}

async function loadInbox(generation) {
  const [needs, available, claimed] = await Promise.all([fetchAll('needs_you'), fetchAll('available'), fetchAll('claimed')]);
  if (generation !== state.generation) return;
  const asking = new Set(needs.map((item) => item.id));
  const sections = { needs, ready: available.filter((item) => !asking.has(item.id)), busy: claimed.filter((item) => !asking.has(item.id)) };
  const view = JSON.stringify(['inbox', sections, state.project, state.selected, state.total]);
  state.sections = sections;
  state.items = [...sections.needs, ...sections.ready, ...sections.busy];
  state.cursor = null;
  state.pages = 1;
  if (view !== state.view_) { state.view_ = view; renderList(); }
}

async function loadList(append = false) {
  const generation = ++state.generation;
  $('page-title').textContent = labels[mode()];
  try {
    if (mode() === 'inbox') await loadInbox(generation);
    else {
      const query = new URLSearchParams({ status: mode() === 'done' ? 'completed' : 'all', limit: '20' });
      if (searching()) query.set('q', $('search').value.trim());
      if (state.project) query.set('project_key', state.project);
      if (append && state.cursor) query.set('cursor', state.cursor);
      $('load-more').disabled = true;
      const response = await api('/api/handoffs?' + query);
      if (generation !== state.generation) return;
      const items = append ? [...state.items, ...response.data.items] : response.data.items;
      const view = JSON.stringify([mode(), items, response.data.next_cursor, state.project, state.selected]);
      state.items = items;
      state.cursor = response.data.next_cursor;
      state.pages = append ? state.pages + 1 : 1;
      if (view !== state.view_) { state.view_ = view; renderList(); }
    }
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

// A collapsed section for everything that isn't needed to act. Remembers whether you opened it.
function fold(parent, title, build) {
  const node = el('details', 'fold');
  node.open = state.folds.has(title);
  node.addEventListener('toggle', () => { if (node.open) state.folds.add(title); else state.folds.delete(title); });
  const body = el('div', 'fold-body');
  build(body);
  if (!body.childElementCount) return null;
  node.append(el('summary', '', title), body);
  parent.append(node);
  return node;
}

function statusBadge(data) {
  if (data.completion) return badge('completed', `Done · ${data.completion.outcome}`);
  const waiting = data.record.context.open_questions.length - (data.answers || []).length;
  if (waiting > 0) return badge('needs_you', 'Needs you');
  if (data.claim.active) return badge('claimed', 'With ' + agentName(data.claim.holder_label));
  return badge('available', 'Ready');
}

function moreMenu(data) {
  const menu = el('details', 'more-menu');
  const toggle = el('summary', '', '⋯');
  toggle.setAttribute('aria-label', 'More actions');
  toggle.title = 'More actions';
  const items = el('div', 'more-items');
  const close = (callback) => () => { menu.open = false; callback(); };
  items.append(button('Copy full record', '', close(() => copy(JSON.stringify(data, null, 2)))),
               button('Copy ID', '', close(() => copy(data.id))),
               button('Delete', 'danger-text', close(() => confirmDelete(data))));
  menu.append(toggle, items);
  return menu;
}

function renderDetail(data) {
  const panel = $('detail');
  panel.replaceChildren();
  const record = data.record;
  const context = record.context;
  const header = el('header', 'detail-header');
  const bar = el('div', 'detail-bar');
  bar.append(backButton(labels[mode()], closeDetail), moreMenu(data));
  const title = el('h2', '', record.title);
  title.tabIndex = -1;
  const meta = el('p', 'detail-meta');
  const saved = el('time', '', since(data.created_at));
  saved.dateTime = data.created_at;
  saved.title = date(data.created_at);
  meta.append(statusBadge(data), el('span', '', `Saved by ${agentName(record.source.client)} ·`), saved);
  if (record.target_client && !data.completion) meta.append(el('span', '', `· for ${agentName(record.target_client)}`));
  if (record.project_key) meta.append(button(record.project_key, 'project-tag', () => { setProject(record.project_key); closeDetail(); }));
  header.append(bar, title, meta);
  summary(header, context, data);
  const content = el('div', 'detail-content');
  // With questions still unanswered, answering comes first and continuing second.
  const waiting = !data.completion && data.record.context.open_questions.length > (data.answers || []).length;
  if (data.completion) {
    // Done: nothing to continue.
  } else if (data.claim.active) {
    header.append(el('p', 'claim-note', `${agentName(data.claim.holder_label)} is working on this. Its claim lasts until ${date(data.claim.expires_at)}.`));
  } else {
    if (data.status === 'claimed') header.append(el('p', 'claim-note', `${agentName(data.claim.holder_label)}’s claim expired ${date(data.claim.expires_at)}. Any agent can continue it now.`));
    const resume = el('div', 'resume-box');
    const text = el('div', 'resume-text');
    text.append(el('span', 'resume-label', waiting ? 'Then continue in another agent' : 'Continue in another agent'), el('code', '', `Resume Handoff ${data.id}`));
    resume.append(text, button('Copy resume prompt', waiting ? 'button secondary' : 'button primary', () => copy(`Resume Handoff ${data.id}`)));
    state.resumeBox = resume;
  }
  if (!waiting && state.resumeBox) header.append(state.resumeBox);
  if (data.completion) {
    const outcome = section(content, 'Outcome');
    outcome.append(el('p', '', data.completion.summary));
    listSection(content, 'Remaining work', data.completion.remaining_work);
  }
  questions(content, data);
  if (waiting && state.resumeBox) content.append(state.resumeBox);
  state.resumeBox = null;
  if (!data.completion) {
    const next = section(content, 'Next steps');
    const ordered = el('ol', 'steps');
    for (const step of context.next_steps) { const li = el('li', 'next-step'); li.append(el('span', 'step-action', step.action), el('span', 'done-when', 'Done when: ' + step.done_when)); ordered.append(li); }
    next.append(ordered);
  }
  const renderReference = (card, item) => {
    card.append(el('span', 'card-label', `${item.id} · ${item.kind} · ${item.availability.replaceAll('_', ' ')}`), el('strong', '', item.purpose), el('p', 'mono', item.locator));
    if (item.excerpt) card.append(el('pre', '', item.excerpt));
    if (item.sha256) card.append(el('p', 'small mono', 'SHA-256: ' + item.sha256));
    if (item.observed_at) card.append(el('p', 'small muted', 'Observed ' + date(item.observed_at)));
  };
  fold(content, 'Details', (body) => {
    textSection(body, 'Objective', context.objective);
    textSection(body, 'Where things stand', context.current_state);
    if (data.completion) listSection(body, 'Planned next steps', context.next_steps.map((step) => step.action));
    listSection(body, 'Definition of done', context.acceptance_criteria);
    if (data.completion) cards(body, 'Acceptance results', data.completion.acceptance_results, (card, item) => { card.append(el('span', 'card-label', item.result), el('strong', '', item.criterion), el('p', 'muted', item.evidence)); });
    cards(body, 'Decisions & reasons', context.decisions, (card, item) => { card.append(el('strong', '', item.decision), el('p', 'muted', item.reason)); evidence(card, item); });
    cards(body, 'What has been tried', context.attempts, (card, item) => { card.append(el('span', 'card-label', item.verification.replaceAll('_', ' ')), el('strong', '', item.action), el('p', 'muted', item.result)); evidence(card, item); });
    textSection(body, 'Background', context.background);
    listSection(body, 'Constraints', context.constraints);
    cards(body, 'Facts & assumptions', context.facts, (card, item) => { card.append(el('span', 'card-label', item.basis), el('p', '', item.text)); evidence(card, item); });
    cards(body, 'References', record.references, renderReference);
    if (data.completion) cards(body, 'Result artifacts', data.completion.artifacts, renderReference);
  });
  let activity;
  fold(content, 'Record & history', (body) => {
    activity = section(body, 'Activity');
    activity.id = 'activity';
    activity.append(el('p', 'small muted', 'Loading history…'));
    const source = section(body, 'Source & scope');
    source.append(el('p', '', record.authorization.scope));
    if (record.authorization.user_request_excerpt) source.append(el('p', 'muted', record.authorization.user_request_excerpt));
    source.append(el('p', 'small muted', `Authored as ${record.source.authoring_method.replaceAll('_', ' ')} · ${record.source.transfer_method.replaceAll('_', ' ')}`));
    if (record.source.model) source.append(el('p', 'small muted', 'Model: ' + record.source.model));
    if (record.source.captured_at) source.append(el('p', 'small muted', 'Captured: ' + date(record.source.captured_at)));
    if (record.source.conversation_ref) source.append(el('p', 'small mono', record.source.conversation_ref));
    if (record.parent_id) source.append(button('View parent handoff', 'button secondary', () => choose(record.parent_id)));
    listSection(body, 'Reported confirmation requirements', record.authorization.requires_confirmation);
    listSection(body, 'Suggestions for the next agent', context.resume_instructions);
    textSection(body, 'Summary coverage', record.coverage.basis);
    listSection(body, 'Omitted context', record.coverage.omitted);
    const metadata = el('dl', 'metadata');
    const fields = [['From', record.source.client], ['To', record.target_client || 'Any agent'], ['Project', record.project_key || 'No project'], ['Created', date(data.created_at)], ['Last updated', date(data.updated_at)], ['Revision', data.revision], ['ID', data.id]];
    if (data.claim.holder_label) fields.push(['Claim holder', data.claim.holder_label], ['Claim expires', date(data.claim.expires_at) + (data.claim.active ? '' : ' (inactive)')]);
    for (const [key, value] of fields) { const pair = el('div'); pair.append(el('dt', '', key), el('dd', '', value)); metadata.append(pair); }
    section(body, 'Metadata').append(metadata);
    const raw = el('details', 'raw-details');
    raw.append(el('summary', '', 'Full record · schema ' + record.schema_version), el('pre', '', JSON.stringify(data, null, 2)));
    body.append(raw, el('p', 'trust-note', data.trust_notice));
  });
  panel.append(header, content);
  if (state.focusDetail) { state.focusDetail = false; title.focus({ preventScroll: !narrow() }); }
  loadEvents(data.id, activity).catch((exception) => { activity.append(el('p', 'error', exception.message)); });
}

// Unsent answers survive refreshes and re-renders: "<handoff id>:<question index>" → text.
const drafts = new Map();

// Open questions the saving agent left, with the user's answers. Answers go to the next agent that reads the handoff.
function questions(parent, data) {
  const asked = data.record.context.open_questions;
  if (!asked.length) return;
  const answers = new Map((data.answers || []).map((item) => [item.index, item]));
  const open = !data.completion;
  const waiting = asked.length - answers.size;
  const node = section(parent, open && waiting ? `Questions for you · ${waiting} waiting` : 'Open questions');
  if (open) node.append(el('p', 'small muted', data.claim.active
    ? `${data.claim.holder_label} has picked this up. It sees your answers the next time it reads the handoff.`
    : 'Your answers go to the next agent that resumes this handoff.'));
  asked.forEach((question, index) => {
    const card = el('div', 'question-card');
    card.append(el('strong', '', question));
    const answer = answers.get(index);
    const key = `${data.id}:${index}`;
    if (open && (!answer || drafts.has(key))) {
      card.classList.add('waiting');
      const box = el('textarea');
      box.value = drafts.get(key) ?? '';
      box.maxLength = 4096;
      box.placeholder = 'Your answer';
      box.setAttribute('aria-label', 'Your answer to: ' + question);
      box.addEventListener('input', () => drafts.set(key, box.value));
      const row = el('div', 'question-actions');
      const save = button('Save answer', 'button primary', () => submitAnswer(data.id, index, box, save));
      row.append(save);
      if (answer) row.append(button('Cancel', 'button secondary', () => { drafts.delete(key); renderDetail(state.detail); }));
      card.append(box, row);
    } else if (answer) {
      card.append(el('p', 'answer', answer.answer));
      const row = el('div', 'question-actions');
      row.append(el('span', '', 'Answered ' + since(answer.answered_at)));
      if (open) row.append(button('Edit answer', 'button secondary', () => { drafts.set(key, answer.answer); renderDetail(state.detail); }));
      card.append(row);
    } else card.append(el('p', 'small muted', 'Not answered.'));
    node.append(card);
  });
}

async function submitAnswer(id, index, box, control) {
  const text = box.value.trim();
  if (!text) { box.focus(); showToast('Write an answer first.'); return; }
  control.disabled = true;
  try {
    const response = await api(`/api/handoffs/${encodeURIComponent(id)}/answers`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ answers: [{ index, answer: text }] }) });
    drafts.delete(`${id}:${index}`);
    if (state.selected === id) { state.detail = response.data; renderDetail(response.data); }
    showToast('Answer saved');
    overview().then(() => loadList()).catch((exception) => error(exception.message));  // it may leave Needs you
  } catch (exception) { showToast(exception.message); control.disabled = false; }
}

function confirmDelete(data) {
  const dialog = $('delete-dialog');
  $('delete-text').textContent = (data.claim.active ? `${data.claim.holder_label} has picked this up; after deleting, it can’t record its result. ` : '')
    + 'This permanently removes the handoff, your answers and its history. It can’t be undone.';
  dialog.dataset.id = data.id;
  dialog.returnValue = '';
  dialog.showModal();
}

$('delete-dialog').addEventListener('close', async () => {
  const dialog = $('delete-dialog');
  if (dialog.returnValue !== 'delete') return;
  const id = dialog.dataset.id;
  try {
    await api('/api/handoffs/' + encodeURIComponent(id), { method: 'DELETE' });
    for (const key of drafts.keys()) if (key.startsWith(id + ':')) drafts.delete(key);
    showToast('Handoff deleted');
    if (state.selected === id) closeDetail();
    await refresh();
  } catch (exception) { showToast(exception.message); }
});

async function loadEvents(id, target, before = null) {
  const response = await api(`/api/handoffs/${encodeURIComponent(id)}/events${before ? '?before=' + before : ''}`);
  if (state.selected !== id || !target.isConnected) return;
  if (!before) { target.replaceChildren(el('h3', '', 'Activity')); target.append(el('ul', 'timeline')); }
  target.querySelector('.load-events')?.remove();
  const list = target.querySelector('ul');
  for (const item of response.items) {
    const li = el('li');
    const name = { pushed: 'Handoff saved', answered: 'You answered', acquire: 'Picked up', release: 'Released', renew: 'Claim renewed' }[item.event] || sentence(item.event);
    li.append(el('strong', '', `${name} · revision ${item.revision}`), el('time', '', date(item.at)));
    for (const [key, value] of Object.entries(item.details)) {
      if (key === 'answers' && Array.isArray(value)) value.forEach((answer) => li.append(el('div', 'small', `Question ${answer.index + 1}: ${answer.answer}`)));
      else if (value != null) li.append(el('div', 'small', key.replaceAll('_', ' ') + ': ' + value));
    }
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

function loading(text) {
  const node = el('div', 'empty-detail');
  node.setAttribute('role', 'status');
  node.append(el('p', '', text));
  return node;
}

function choose(id, updateURL = true, focusDetail = false) {
  if (!state.selected) state.listScroll = scrollY;
  state.selected = id;
  state.detail = null;
  state.focusDetail = focusDetail;
  if (updateURL) history.pushState({}, '', '/handoffs/' + encodeURIComponent(id));
  $('detail').replaceChildren(loading('Loading handoff…'));
  renderList();
  syncPanes();
  detail(id);
  if (narrow()) scrollTo({ top: 0, behavior: 'instant' });
}

function emptyDetail() {
  const empty = el('div', 'empty-detail');
  const steps = el('ol', 'empty-steps');
  for (const [title, text] of [['Save', 'In any connected agent, say “Save a handoff so I can continue later.”'],
                               ['Resume', 'In another agent, paste the prompt it returns: “Resume Handoff <id>”.'],
                               ['Track', 'Select a handoff here to see its summary, questions and next steps.']]) {
    const li = el('li');
    li.append(el('strong', '', title), el('span', '', text));
    steps.append(li);
  }
  empty.append(el('span', 'empty-icon', '⇄'), el('h2', '', 'Pick up where your last agent left off'), steps,
               button('Show connection steps', 'button secondary', () => $('setup-dialog').showModal()));
  return empty;
}

// The right-hand panel when nothing is selected: what to do next, or the getting-started steps in an empty workspace.
function idlePanel() {
  const item = mode() === 'inbox' ? state.sections.needs[0] || state.sections.ready[0] : null;
  if (!item) return state.total ? quiet() : emptyDetail();
  const card = el('div', 'empty-detail next-up');
  card.append(el('span', 'resume-label', 'Next up'), el('h2', '', item.title), el('p', 'next-up-preview', item.preview));
  const actions = el('div', 'next-up-actions');
  if (item.needs_you) actions.append(button(`Answer ${plural(waitingQuestions(item), 'question')}`, 'button primary', () => choose(item.id, true, true)));
  else actions.append(button('Copy resume prompt', 'button primary', () => copy(`Resume Handoff ${item.id}`)), button('Open', 'button secondary', () => choose(item.id, true, true)));
  card.append(actions);
  return card;
}

function quiet() {
  const node = el('div', 'empty-detail');
  node.append(el('span', 'empty-icon', '✓'), el('h2', '', mode() === 'inbox' ? 'Nothing waiting on you' : 'Select a handoff'),
              el('p', '', mode() === 'inbox' ? 'When an agent saves a handoff or asks you something, it shows up here.' : 'Its outcome, summary and history open here.'));
  return node;
}

function closeDetail() {
  const position = state.listScroll || 0;
  const previous = state.selected;
  state.selected = null;
  state.detail = null;
  history.pushState({}, '', '/');
  renderList();
  syncPanes();
  if (narrow()) scrollTo({ top: position, behavior: 'instant' });
  $('handoff-list').querySelector(`[data-key="${CSS.escape(previous || '')}"]`)?.focus({ preventScroll: true });
}

async function refresh() {
  try {
    await overview();
    await loadList();
    if (state.selected) await detail(state.selected, true);
  } catch (exception) { error(exception.message); }
}

async function enter() {
  if (!state.selected) $('detail').replaceChildren(loading('Loading…'));
  await refresh();
}

for (const item of document.querySelectorAll('[data-status]')) item.addEventListener('click', () => {
  showMemoryView(false);
  history.pushState({}, '', state.selected ? '/handoffs/' + encodeURIComponent(state.selected) : '/');
  state.view = item.dataset.status;
  $('search').value = '';
  for (const other of document.querySelectorAll('[data-status]')) other.classList.toggle('active', other === item);
  revealActiveChip();
  loadList();
});
$('search').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => loadList(), 250); });
$('project-chip').addEventListener('click', () => setProject(''));
$('load-more').addEventListener('click', () => loadList(true));
const mcpUrl = new URL('/mcp', location.origin).href;
$('mcp-url').textContent = mcpUrl;
function sameOriginPath(url) {
  return typeof url === 'string' && url.startsWith('/') && !url.startsWith('//');
}

function updateAuthUI() {
  // Hosts with MCP OAuth (session.mcp_sign_in): agents sign in through the browser, so no token goes in the command.
  const oauth = Boolean(session?.mcp_sign_in);
  // Token instructions apply when the dashboard itself uses a token, or the host issues access tokens without OAuth.
  const signedIn = !oauth && (Boolean(accessToken()) || sameOriginPath(session?.access_token_url));
  $('signout-button').hidden = !accessToken() && !session?.logout_url;
  // Small screens move account links and Sign out behind an account button in the top bar.
  document.body.classList.toggle('has-account', !$('signout-button').hidden || !$('host-links').hidden);
  $('account-button').textContent = $('workspace-avatar').textContent;
  $('setup-token-link').hidden = !sameOriginPath(session?.access_token_url);
  if (sameOriginPath(session?.access_token_url)) $('setup-token-anchor').href = session.access_token_url;
  $('setup-token-anchor').textContent = oauth ? 'Or create an access token' : 'Create an access token';
  $('setup-token-anchor').className = oauth ? 'button secondary' : 'button primary';
  // Show a placeholder rather than the real token so it never appears in screenshots or screen shares.
  $('codex-add').textContent = oauth ? `codex mcp add stopover --url ${mcpUrl}\ncodex mcp login stopover`
    : signedIn ? `export STOPOVER_TOKEN=YOUR_TOKEN\ncodex mcp add stopover --url ${mcpUrl} --bearer-token-env-var STOPOVER_TOKEN` : `codex mcp add stopover --url ${mcpUrl}`;
  $('claude-add').textContent = `claude mcp add --scope user --transport http stopover ${mcpUrl}` + (signedIn ? ' --header "Authorization: Bearer YOUR_TOKEN"' : '');
  $('setup-intro').textContent = oauth ? 'Add this MCP server to your agent. The first time it connects, it opens your browser to sign in; there is no token to copy. In Claude Code, run /mcp and choose Authenticate if it asks.'
    : signedIn ? 'Add this Streamable HTTP MCP server to your agent. Requests need your access token (replace YOUR_TOKEN).'
    : 'Add this Streamable HTTP MCP server to your agent. No token or login is needed.';
  $('setup-auth').textContent = oauth ? 'In Cursor, OMP, Hermes Agent, or another client that supports MCP sign-in, add an HTTP server with the URL above. For clients without sign-in, create an access token and send it as Authorization: Bearer.'
    : signedIn ? 'In Cursor, OMP, Hermes Agent, or another compatible client, add an HTTP server with the URL above and the header Authorization: Bearer YOUR_TOKEN.'
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

// A host can report plan usage in /api/session as usage: {title, url?, items: [{label, used, limit (null: none)}]}.
function renderUsage(box, usage) {
  const items = Array.isArray(usage?.items) ? usage.items.filter((item) => item && typeof item.label === 'string' && Number.isFinite(item.used)) : [];
  box.hidden = !items.length;
  if (!items.length) return box.replaceChildren();
  const title = el('p', 'usage-title');
  title.append(el('span', '', typeof usage.title === 'string' ? usage.title : 'Usage'));
  if (sameOriginPath(usage.url)) { const details = el('a', '', 'Details'); details.href = usage.url; title.append(details); }
  box.replaceChildren(title);
  for (const item of items) {
    const row = el('div', 'usage-item');
    const limited = Number.isFinite(item.limit);
    const left = limited ? Math.max(0, item.limit - item.used) : null;
    const head = el('div', 'usage-head' + (limited && !left ? ' out' : ''));
    head.append(el('span', '', item.label), el('strong', '', limited ? `${left.toLocaleString()} of ${item.limit.toLocaleString()} left` : 'No limit'));
    row.append(head);
    if (limited) {
      const bar = el('div', 'usage-bar');
      const share = item.used / Math.max(item.limit, 1);
      const fill = el('div', 'usage-fill' + (share >= 1 ? ' out' : share >= 0.8 ? ' low' : ''));
      fill.style.width = `${Math.min(100, 100 * share)}%`;
      bar.append(fill);
      row.append(bar);
    }
    box.append(row);
  }
}

// A host can offer getting-started steps in /api/session as checklist: {id, title, items: [{label, detail?, done,
// action? ('connect' opens the connection steps)}]}. It shows above the inbox until the person hides it; hiding is
// remembered per checklist id in this browser.
const CHECKLIST_KEY = 'stopover.checklist.hidden';
function checklistHidden(id) { try { return localStorage.getItem(CHECKLIST_KEY) === id; } catch { return false; } }
function renderChecklist(box, checklist) {
  const items = Array.isArray(checklist?.items) ? checklist.items.filter((item) => item && typeof item.label === 'string') : [];
  const id = typeof checklist?.id === 'string' ? checklist.id : 'checklist';
  box.hidden = !items.length || checklistHidden(id);
  if (box.hidden) return box.replaceChildren();
  const done = items.filter((item) => item.done === true).length;
  const head = el('div', 'checklist-head');
  const title = el('h2', '', typeof checklist.title === 'string' ? checklist.title : 'Get started');
  title.id = 'checklist-title';
  const progress = el('span', '', done === items.length ? 'All done' : `${done} of ${items.length} done`);
  const hide = button(done === items.length ? 'Dismiss' : 'Hide', 'copy-small', () => {
    try { localStorage.setItem(CHECKLIST_KEY, id); } catch { /* storage unavailable: hide until reload */ }
    box.hidden = true;
  });
  const end = el('div', 'checklist-actions');
  end.append(progress, ' ', hide);
  head.append(title, end);
  const steps = el('ol', 'checklist-steps');
  const next = items.findIndex((item) => item.done !== true);
  items.forEach((item, index) => {
    const li = el('li', 'checklist-step' + (item.done === true ? ' done' : index === next ? ' next' : ''));
    li.append(el('span', 'checklist-mark', item.done === true ? '✓' : index + 1));
    const text = el('div');
    text.append(el('strong', '', item.label));
    if (typeof item.detail === 'string') text.append(el('span', '', item.detail));
    if (index === next && item.action === 'connect') text.append(button('Connect your agents', 'button secondary', () => $('setup-dialog').showModal()));
    li.append(text);
    if (item.done === true) li.setAttribute('aria-label', `Done: ${item.label}`);
    steps.append(li);
  });
  box.replaceChildren(head, steps);
}

// Hosts that add accounts can describe the signed-in user at /api/session; plain Stopover answers 404.
async function loadSession() {
  try {
    const response = await fetch('/api/session', { credentials: 'same-origin', cache: 'no-store', headers: authHeaders() });
    if (!response.ok) return;
    session = await response.json();
    const name = session.user?.name || session.user?.login || 'Signed in';
    $('workspace-name').textContent = session.workspace?.name || name;
    $('workspace-detail').textContent = session.user?.login ? `Signed in as ${session.user.login}` : 'Signed in';
    $('workspace-avatar').textContent = name.trim().charAt(0).toUpperCase() || '·';
    // Host-provided account links (e.g. access tokens); same-origin paths only.
    const links = (Array.isArray(session.links) ? session.links : []).filter((link) => link && typeof link.label === 'string' && sameOriginPath(link.url));
    $('host-links').replaceChildren(...links.map((link) => { const a = el('a', '', link.label); a.href = link.url; return a; }));
    $('host-links').hidden = !links.length;
    renderUsage($('host-usage'), session.usage);
    renderChecklist($('host-checklist'), session.checklist);
    updateAuthUI();
  } catch { /* optional */ }
}
loadSession();
$('copy-mcp-url').addEventListener('click', () => copy(mcpUrl));
$('setup-button').addEventListener('click', () => $('setup-dialog').showModal());

function openAccount() {
  $('account-avatar').textContent = $('workspace-avatar').textContent;
  $('account-name').textContent = $('workspace-name').textContent;
  $('account-detail').textContent = $('workspace-detail').textContent;
  const links = [...$('host-links').querySelectorAll('a')].map((link) => { const a = el('a', 'account-link', link.textContent); a.href = link.getAttribute('href'); return a; });
  const items = [...links];
  if (!$('signout-button').hidden) items.push(button('Sign out', 'account-link signout', () => { $('account-dialog').close(); $('signout-button').click(); }));
  $('account-links').replaceChildren(...items);
  renderUsage($('account-usage'), session?.usage);
  $('account-dialog').showModal();
}
$('account-button').addEventListener('click', openAccount);
$('close-account').addEventListener('click', () => $('account-dialog').close());
// Tapping the backdrop closes the sheet.
$('account-dialog').addEventListener('click', (event) => { if (event.target === $('account-dialog')) $('account-dialog').close(); });
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
  for (const item of document.querySelectorAll('[data-status]')) item.classList.toggle('active', !active && item.dataset.status === state.view);
  revealActiveChip();
}

function revealActiveChip() {
  if (narrow()) document.querySelector('.nav-item.active')?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
}

function renderMemories() {
  const list = $('memory-list');
  keepPlace(list, () => renderMemoryRows(list));
}

function renderMemoryRows(list) {
  list.replaceChildren();
  if (!memories.items.length) {
    const empty = el('div', 'empty-list');
    const filtered = $('memory-search').value || $('memory-category').value;
    empty.append(el('strong', '', filtered ? 'No matching memories.' : 'No personal memories yet.'), el('p', '', filtered ? 'Try a different search or category.' : 'Tell your AI agent “update my Stopover memory” to save what it knows about you.'));
    list.append(empty);
  }
  for (const item of memories.items) {
    const row = button('', 'handoff-row memory-row' + (item.key === memories.selected ? ' selected' : ''), () => chooseMemory(item.key));
    row.dataset.key = item.key;
    row.setAttribute('aria-pressed', String(item.key === memories.selected));
    const top = el('div', 'row-top');
    top.append(el('span', 'row-title mono-title', item.key), el('time', '', relative(item.updated_at)));
    const bottom = el('div', 'row-bottom');
    bottom.append(el('span', 'badge' + (item.expired ? ' completed' : ''), item.expired ? 'Expired' : sentence(item.category.replaceAll('_', ' '))),
                  el('span', 'agent-route', `${item.source.client} · ${item.basis}${item.expires_at && !item.expired ? ` · expires ${day(item.expires_at)}` : ''}`));
    row.append(top, el('div', 'row-preview', item.content), bottom);
    list.append(row);
  }
  $('memory-more').hidden = !memories.cursor;
}

// The summary above the list covers every memory, not just the loaded page: the agent-written profile.summary,
// counts by category, what expires soon and how many have expired (agents no longer see those).
const SUMMARY_KEY = 'profile.summary';
const CATEGORY_NAMES = { preference: ['preference', 'preferences'], fact: ['fact', 'facts'], habit: ['habit', 'habits'],
  goal: ['goal', 'goals'], project_context: ['project context item', 'project context items'] };
let memorySummaryView = '';

async function loadMemorySummary() {
  let items = [], cursor = null;
  for (let page = 0; page < 20; page += 1) {  // up to 1,000 memories
    const query = new URLSearchParams({ limit: '50' });
    if (cursor) query.set('cursor', cursor);
    const response = await api('/api/memories?' + query);
    items = items.concat(response.data.items);
    cursor = response.data.next_cursor;
    if (!cursor) break;
  }
  const view = JSON.stringify(items.map((item) => [item.key, item.revision, item.expired || false]));
  if (view !== memorySummaryView) {
    memorySummaryView = view;
    renderMemorySummary(items, Boolean(cursor));
  }
}

function renderMemorySummary(items, partial) {
  const box = $('memory-summary');
  const live = items.filter((item) => !item.deleted && !item.expired);
  box.hidden = !live.length && !items.some((item) => item.expired);
  if (box.hidden) return;
  const profile = live.find((item) => item.key === SUMMARY_KEY);
  const rest = live.filter((item) => item.key !== SUMMARY_KEY);
  box.replaceChildren(el('span', 'glance-label', 'Summary'));
  box.append(el('p', 'glance-summary', profile ? profile.content
    : `Your agents share ${rest.length} memor${rest.length === 1 ? 'y' : 'ies'} about you. Ask one to “update my Stopover memory” to add a written summary here.`));
  const counts = {};
  for (const item of rest) counts[item.category] = (counts[item.category] || 0) + 1;
  const chips = el('div', 'memory-counts');
  for (const [category, [one, many]] of Object.entries(CATEGORY_NAMES)) {
    if (!counts[category]) continue;
    const chip = button(`${counts[category]} ${counts[category] === 1 ? one : many}`, 'count-chip', () => {
      $('memory-category').value = category;
      loadMemories();
    });
    chip.setAttribute('aria-label', `Show ${many}`);
    chips.append(chip);
  }
  if (chips.childElementCount) box.append(chips);
  const soon = rest.filter((item) => item.expires_at && new Date(item.expires_at) - Date.now() < 30 * 86400000)
    .sort((a, b) => a.expires_at.localeCompare(b.expires_at));
  if (soon.length) {
    const list = el('ul', 'expiring');
    for (const item of soon.slice(0, 5)) {
      const entry = el('li');
      const open = button(item.content, 'link-button', () => chooseMemory(item.key));
      entry.append(open, el('span', 'muted', ` · expires ${day(item.expires_at)}`));
      list.append(entry);
    }
    box.append(el('p', 'glance-facts', 'Expiring within 30 days'), list);
  }
  const expired = items.filter((item) => item.expired && !item.deleted).length;
  const notes = [];
  if (expired) notes.push(`${expired} expired memor${expired === 1 ? 'y is' : 'ies are'} no longer shared with agents`);
  if (partial) notes.push('summary covers the first 1,000 memories');
  if (notes.length) box.append(el('p', 'glance-facts', sentence(notes.join('; ')) + '.'));
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
    const items = append ? [...memories.items, ...response.data.items] : response.data.items;
    const view = JSON.stringify([items, response.data.next_cursor, $('memory-search').value, $('memory-category').value, memories.selected]);
    const changed = view !== memories.view;
    memories.view = view;
    memories.items = items;
    memories.cursor = response.data.next_cursor;
    memories.pages = append ? memories.pages + 1 : 1;
    if (changed) renderMemories();
    memoryError();
    $('memory-sync').textContent = 'Updated ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch (exception) { if (generation === memories.generation) memoryError(exception.message); }
  finally { if (generation === memories.generation) $('memory-more').disabled = false; }
}

function renderMemoryDetail(item) {
  const panel = $('memory-detail');
  panel.replaceChildren();
  const header = el('header', 'detail-header');
  const status = el('div', 'detail-status');
  status.append(el('span', 'badge' + (item.deleted ? ' completed' : ''), item.deleted ? 'FORGOTTEN MEMORY' : sentence(item.category.replaceAll('_', ' '))), el('time', '', 'Updated ' + since(item.updated_at)));
  header.append(backButton('Memories', closeMemory), status, el('h2', 'mono-title', item.key));
  if (!item.deleted) {
    header.append(el('p', 'memory-content', item.content));
    const actions = el('div', 'detail-actions');
    actions.append(button('Copy memory', 'button secondary', () => copy(item.content)));
    header.append(actions);
  }
  const content = el('div', 'detail-content');
  if (item.deleted) {
    textSection(content, 'Forgotten', `This memory was removed from ${BRAND}. Its content and evidence are no longer stored. Other agents learn about the deletion the next time they import your memory.`);
  } else {
    if (item.expires_at) {
      textSection(content, item.expired ? 'Expired' : 'Expires', item.expired
        ? `${date(item.expires_at)}. Agents no longer receive this memory; ask one to forget it, or to update it if it's still true.`
        : date(item.expires_at));
    }
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
  content.append(el('p', 'trust-note', `Ask any agent to correct or forget a memory. ${BRAND} shares personal context; each agent decides whether to remember it locally.`));
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
  if (!memories.selected) memories.listScroll = scrollY;
  memories.selected = key;
  memories.detail = null;
  if (updateURL) history.pushState({}, '', '/memories/' + encodeURIComponent(key));
  renderMemories();
  $('memory-detail').replaceChildren(loading('Loading memory…'));
  syncPanes();
  memoryDetail(key);
  if (narrow()) scrollTo({ top: 0, behavior: 'instant' });
}

function emptyMemory() {
  const empty = el('div', 'empty-detail');
  empty.append(el('span', 'empty-icon', '◎'), el('h2', '', 'Personal context, in one place'),
               el('p', '', 'Select a memory to see its source and latest update. To add or correct memories, tell any agent “update my Stopover memory”.'));
  return empty;
}

function closeMemory() {
  const position = memories.listScroll || 0;
  memories.selected = null;
  memories.detail = null;
  history.pushState({}, '', '/memories');
  $('memory-detail').replaceChildren(emptyMemory());
  renderMemories();
  syncPanes();
  if (narrow()) scrollTo({ top: position, behavior: 'instant' });
}

async function refreshMemories() {
  $('memory-refresh').disabled = true;
  try {
    await overview();
    await Promise.all([loadMemories(), loadMemorySummary()]);
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
    $('memory-detail').replaceChildren(memories.selected ? el('div', 'empty-detail', 'Loading memory…') : emptyMemory());
    syncPanes();
    refreshMemories();
  } else {
    state.selected = location.pathname.split('/')[2] || null;
    state.detail = null;
    syncPanes();
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
  if (document.hidden || $('setup-dialog').open || $('signin-dialog').open || $('delete-dialog').open) return;
  if (memories.active) {
    try {
      await overview();
      if (memories.pages === 1 && !$('memory-search').matches(':focus')) await Promise.all([loadMemories(), loadMemorySummary()]);
      if (memories.selected) await memoryDetail(memories.selected);
    } catch (exception) { memoryError(exception.message); }
    return;
  }
  if (session) loadSession();  // keeps the host's usage figures current
  try { await overview(); if (state.pages === 1 && !$('search').matches(':focus')) await loadList(); if (state.selected) await detail(state.selected, true); }
  catch (exception) { error(exception.message); }
}, 15000);
route();
