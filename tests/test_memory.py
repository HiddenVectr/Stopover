import asyncio
import copy
import json
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from starlette.testclient import TestClient

from stopover.server import create_app
from stopover.store import Store


def entry(key='communication.length', content='Prefers concise answers.', revision=0, **extra):
    return dict(key=key, content=content, expected_revision=revision,
                category='preference', basis='stated', source={'client': 'codex'},
                evidence='The user explicitly requested concise answers.', **extra)


def update(*entries, client='codex'):
    return {'operation_id': str(uuid.uuid4()), 'client': client, 'memories': list(entries)}


def forget(key, revision):
    return {'operation_id': str(uuid.uuid4()), 'memories': [{'key': key, 'expected_revision': revision}]}


def success(store, tool, args=None):
    result = store.execute('stopover_memory_' + tool, args or {})
    assert result['ok'], result
    return result['data']


def test_capture_update_retry_and_provenance(store):
    args = update(entry())
    args['coverage'] = {'basis': 'Current chat and accessible memory', 'omitted': ['Older inaccessible chats']}
    saved = success(store, 'update', args)
    assert saved['coverage']['omitted'] == ['Older inaccessible chats']
    assert saved['items'][0]['action'] == 'added'
    assert store.execute('stopover_memory_update', args)['replayed']
    assert success(store, 'read')['store_revision'] == 1
    changed = copy.deepcopy(args)
    changed['memories'][0]['content'] = 'Different'
    assert store.execute('stopover_memory_update', changed)['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    corrected = update(entry(content='Prefers detailed explanations.', revision=1), client='claude-code')
    result = success(store, 'update', corrected)
    assert result['store_revision'] == 2
    current = success(store, 'read')['items'][0]
    assert current['id'] == saved['items'][0]['id']
    assert current['source']['client'] == 'codex'
    assert current['updated_by'] == 'claude-code'
    same = update(entry(content='Prefers detailed explanations.', revision=2), client='codex')
    assert success(store, 'update', same)['items'][0]['action'] == 'unchanged'
    assert success(store, 'read')['store_revision'] == 2


def test_atomic_conflict_does_not_erase_other_memories(store):
    success(store, 'update', update(entry()))
    result = store.execute('stopover_memory_update', update(entry('new.fact'), entry(revision=0)))
    assert result['error']['code'] == 'REVISION_CONFLICT'
    assert [m['key'] for m in success(store, 'read')['items']] == ['communication.length']
    success(store, 'update', update(entry('new.fact')))
    assert len(success(store, 'read')['items']) == 2


def test_competing_updates_have_one_winner(store):
    success(store, 'update', update(entry()))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda content: store.execute('stopover_memory_update', update(entry(content=content, revision=1))), ['First correction', 'Second correction']))
    assert sum(r['ok'] for r in results) == 1
    assert next(r for r in results if not r['ok'])['error']['code'] == 'REVISION_CONFLICT'


def test_forget_scrubs_data_and_propagates_without_resurrection(store):
    args = update(entry(content='Personal private content'))
    success(store, 'update', args)
    request = forget('communication.length', 1)
    result = success(store, 'forget', request)
    assert result['items'][0]['action'] == 'deleted'
    assert store.execute('stopover_memory_forget', request)['replayed']
    assert success(store, 'read')['items'] == []
    tombstone = success(store, 'read', {'since_revision': 1, 'category': 'habit', 'q': 'unmatched'})['items'][0]
    assert tombstone['deleted'] and 'content' not in tombstone and 'source' not in tombstone
    assert success(store, 'export', {'include_deleted': True, 'format': 'markdown'})['items'][0]['deleted']
    assert success(store, 'forget', forget('communication.length', 2))['store_revision'] == 2
    assert store.execute('stopover_memory_update', update(entry(revision=2)))['error']['code'] == 'MEMORY_DELETED'
    assert store.execute('stopover_memory_update', update(entry()))['error']['code'] == 'REVISION_CONFLICT'
    # Old successful update receipts do not retain or resurrect forgotten bodies.
    assert store.execute('stopover_memory_update', args)['replayed']
    assert success(store, 'read')['items'] == []
    assert store.db.execute('SELECT body FROM personal_memories').fetchone()[0] is None
    receipts = str([tuple(r) for r in store.db.execute('SELECT * FROM memory_receipts')])
    assert 'Personal private content' not in receipts and 'explicitly requested' not in receipts


def test_pagination_filters_changes_and_export(store):
    success(store, 'update', update(*(entry(f'topic.{i:02}', f'Memory {i}') for i in range(25))))
    first = success(store, 'read', {'limit': 10})
    assert first['next_cursor'] and not first['complete']
    second = success(store, 'read', {'limit': 20, 'cursor': first['next_cursor']})
    assert len(first['items'] + second['items']) == 25
    assert second['complete']
    assert len(success(store, 'read', {'q': 'Memory 12'})['items']) == 1
    assert success(store, 'read', {'category': 'habit'})['items'] == []
    assert store.execute('stopover_memory_read', {'cursor': first['next_cursor'], 'q': 'different'})['error']['code'] == 'INVALID_CURSOR'
    success(store, 'update', update(entry('topic.12', 'Changed memory', revision=13)))
    # Pagination continues across writes; every page reports the first page's checkpoint.
    continued = success(store, 'read', {'limit': 20, 'cursor': first['next_cursor']})
    assert len(first['items'] + continued['items']) == 25 and continued['store_revision'] == first['store_revision'] == 25
    changes = success(store, 'read', {'since_revision': continued['store_revision']})
    assert [m['content'] for m in changes['items']] == ['Changed memory']
    exported = success(store, 'export', {'format': 'markdown', 'limit': 50})
    assert exported['schema_version'] == '1.0' and exported['complete']
    assert 'Changed memory' in exported['markdown'] and 'Source:' in exported['markdown']
    assert store.execute('stopover_memory_read', {'since_revision': 999})['error']['code'] == 'REVISION_CONFLICT'


@pytest.mark.parametrize('cursor', ['not-base64', 'bnVsbA', 'W10', 'e30'])
def test_invalid_cursors_are_errors(store, cursor):
    assert store.execute('stopover_memory_read', {'cursor': cursor})['error']['code'] == 'INVALID_CURSOR'


@pytest.mark.parametrize('change', [
    lambda a: a['memories'][0].update(content=' '),
    lambda a: a['memories'][0].update(expected_revision=-1),
    lambda a: a['memories'][0].update(expected_revision=True),
    lambda a: a['memories'][0].update(key='../escape'),
    lambda a: a['memories'].append(copy.deepcopy(a['memories'][0])),
    lambda a: a.update(user_id='another-user'),
    lambda a: a.update(memories=[entry(f'key.{i}', 'x' * 4096) for i in range(15)]),
])
def test_strict_validation(store, change):
    args = update(entry())
    change(args)
    assert store.execute('stopover_memory_update', args)['error']['code'] == 'VALIDATION_ERROR'
    assert success(store, 'read')['items'] == []


def test_existing_store_upgrade_restart_and_retention(tmp_path, record):
    store = Store(tmp_path)
    handoff = store.execute('stopover_save', {'record': record})['data']
    store.close()
    # Simulate a pre-memory database using the established schema 2.
    import sqlite3
    db = sqlite3.connect(tmp_path / 'stopover.sqlite3')
    db.executescript("DROP TABLE personal_memories; DROP TABLE memory_receipts; DELETE FROM meta WHERE key='memory_revision';")
    db.close()
    store = Store(tmp_path, retention_days=.001)
    try:
        assert store.execute('stopover_get', {'id': handoff['id']})['ok']
        success(store, 'update', update(entry()))
    finally:
        store.close()
    store = Store(tmp_path)
    try:
        assert success(store, 'read')['items'][0]['content'] == 'Prefers concise answers.'
        assert store.overview()['memories'] == 1
        success(store, 'forget', forget('communication.length', 1))
        assert store.overview()['memories'] == 0
    finally:
        store.close()


def test_memory_dashboard_api_is_read_only_and_no_auth(tmp_path):
    app = create_app(tmp_path)
    success(app.state.store, 'update', update(entry()))
    with TestClient(app, base_url='https://handoff.example-tailnet.ts.net') as client:
        assert client.get('/memories').status_code == 200
        assert client.get('/memories/communication.length').status_code == 200
        assert client.get('/api/memories').json()['data']['items'][0]['content'] == 'Prefers concise answers.'
        assert client.get('/api/memories/communication.length').json()['data']['items'][0]['revision'] == 1
        assert client.get('/api/memories?since_revision=0').status_code == 200
        assert client.get('/api/memories?limit=oops').status_code == 400
        assert client.get('/api/memories?since_revision=-1').status_code == 400
        assert client.post('/api/memories', json=update(entry())).status_code == 405
        assert client.get('/api/memories', headers={'sec-fetch-site': 'cross-site'}).status_code == 403
        assert 'set-cookie' not in client.get('/memories').headers


async def test_memory_http_stdio_round_trip(live_server):
    url = live_server['url'] + '/mcp'
    async with httpx.AsyncClient(headers={'host': 'handoff.example-tailnet.ts.net'}) as http:
        async with streamable_http_client(url, http_client=http) as (read, write, _):
            async with ClientSession(read, write) as codex:
                init = await codex.initialize()
                assert 'ALL' in init.instructions and 'Stopover never reads or writes' in init.instructions
                tools = {t.name: t for t in (await codex.list_tools()).tools}
                assert tools['stopover_memory_read'].annotations.readOnlyHint
                assert tools['stopover_memory_export'].annotations.readOnlyHint
                assert tools['stopover_memory_forget'].annotations.destructiveHint
                assert all(len(tools[name].description) < 1000 for name in tools if 'memory' in name)
                assert tools['stopover_memory_update'].annotations.destructiveHint  # it can overwrite a memory
                assert 'ALL' in (await codex.get_prompt('memory-update')).messages[0].content.text
                saved = await codex.call_tool('stopover_memory_update', update(entry()))
                assert not saved.isError
                params = StdioServerParameters(command=sys.executable,
                    env={'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')},
                    args=['-m', 'stopover', '--url', url, 'bridge'])
                async with stdio_client(params) as (incoming, outgoing):
                    async with ClientSession(incoming, outgoing) as claude:
                        await claude.initialize()
                        imported = await claude.call_tool('stopover_memory_read', {})
                        memory = imported.structuredContent['data']['items'][0]
                        assert memory['content'] == 'Prefers concise answers.'
                        prompt = await claude.get_prompt('memory-import')
                        assert 'persistent local import' in prompt.messages[0].content.text
                        corrected = await claude.call_tool('stopover_memory_update', update(entry(content='Prefers examples.', revision=memory['revision']), client='claude-code'))
                        assert not corrected.isError
                imported = await codex.call_tool('stopover_memory_read', {'since_revision': 1})
                assert imported.structuredContent['data']['items'][0]['content'] == 'Prefers examples.'
                assert (await codex.call_tool('stopover_memory_export', {'format': 'markdown'})).structuredContent['data']['complete']


def test_resync_keeps_original_provenance(store):
    def entry(content='Prefers concise answers.', revision=0, **overrides):
        return {**globals()['entry'](content=content, revision=revision), **overrides}
    success(store, 'update', update(entry()))
    resync = update(entry(revision=1, source={'client': 'claude-code'}, evidence='Imported from codex'), client='claude-code')
    assert success(store, 'update', resync)['items'][0]['action'] == 'unchanged'
    current = success(store, 'read')['items'][0]
    assert current['source']['client'] == 'codex' and current['revision'] == 1
    recategorised = update(entry(revision=1, category='habit', source={'client': 'claude-code'}), client='claude-code')
    assert success(store, 'update', recategorised)['items'][0]['action'] == 'updated'
    current = success(store, 'read')['items'][0]
    assert current['category'] == 'habit' and current['source']['client'] == 'codex' and current['updated_by'] == 'claude-code'
    changed = update(entry(content='Prefers bullet points.', revision=2, source={'client': 'claude-code'}), client='claude-code')
    success(store, 'update', changed)
    assert success(store, 'read')['items'][0]['source']['client'] == 'claude-code'


def test_conflicts_are_all_reported_and_partial_applies_the_rest(store):
    success(store, 'update', update(entry('a.one'), entry('a.two')))
    stale = update(entry('a.one', 'New one'), entry('a.two', 'New two'), entry('a.three', 'Three'))
    error = store.execute('stopover_memory_update', stale)['error']
    assert error['code'] == 'REVISION_CONFLICT'
    assert {c['key']: c['current_revision'] for c in error['conflicts']} == {'a.one': 1, 'a.two': 2}
    assert 'a.one' in error['message'] and 'a.two' in error['message']
    assert len(success(store, 'read')['items']) == 2
    stale['partial'] = True
    stale['operation_id'] = str(uuid.uuid4())
    result = success(store, 'update', stale)
    assert [(i['key'], i['action']) for i in result['items']] == [('a.one', 'conflict'), ('a.two', 'conflict'), ('a.three', 'added')]
    assert result['items'][0]['code'] == 'REVISION_CONFLICT' and result['store_revision'] == 3


def test_forgotten_key_can_be_recreated_explicitly(store):
    success(store, 'update', update(entry()))
    success(store, 'forget', {'memories': [{'key': 'communication.length'}]})
    old_id = success(store, 'read', {'include_deleted': True})['items'][0]['id']
    blocked = store.execute('stopover_memory_update', update(entry(content='Now prefers detail.', revision=2)))['error']
    assert blocked['code'] == 'MEMORY_DELETED' and 'recreate=true' in blocked['message']
    recreated = success(store, 'update', update(entry(content='Now prefers detail.', revision=2, recreate=True)))
    assert recreated['items'][0]['action'] == 'recreated' and recreated['items'][0]['id'] != old_id
    current = success(store, 'read')['items'][0]
    assert current['content'] == 'Now prefers detail.' and not current['deleted']
    assert success(store, 'read', {'since_revision': 2})['items'][0]['content'] == 'Now prefers detail.'


def test_lenient_memory_inputs(store):
    minimal = {'client': 'cursor', 'memories': [{'key': 'Editor Choice', 'content': 'Uses Neovim', 'expected_revision': '0'}]}
    saved = success(store, 'update', minimal)
    assert saved['items'][0]['key'] == 'editor-choice'
    current = success(store, 'read')['items'][0]
    assert current['source']['client'] == 'cursor' and current['category'] == 'fact'
    assert success(store, 'forget', {'memories': [{'key': 'editor-choice'}]})['items'][0]['action'] == 'deleted'


def test_time_bound_memories_expire(store):
    clock = [1_900_000_000.0]  # 2030-03-17
    store.clock = lambda: clock[0]
    lasting = entry('communication.length', 'Prefers concise answers.')
    trial = entry('tools.trial', 'Trying Cursor until the end of the month.', expires_at='2030-03-31')
    stamped = entry('work.oncall', 'On call this week.', expires_at='2030-03-20T09:00:00-04:00')
    saved = success(store, 'update', update(lasting, trial, stamped))['items']
    read = {i['key']: i for i in success(store, 'read', {})['items']}
    assert read['tools.trial']['expires_at'] == '2030-03-31T23:59:59Z'  # a date means the end of that day, UTC
    assert read['work.oncall']['expires_at'] == '2030-03-20T13:00:00Z' and read['communication.length']['expires_at'] is None
    assert 'expired' not in read['tools.trial']
    clock[0] = 1_900_000_000.0 + 10 * 86400  # 2030-03-27: the on-call memory has expired, the trial hasn't
    assert {i['key'] for i in success(store, 'read', {})['items']} == {'communication.length', 'tools.trial'}
    everything = {i['key']: i for i in success(store, 'read', {'include_expired': True})['items']}
    assert everything['work.oncall']['expired'] is True and 'expired' not in everything['tools.trial']
    assert {i['key'] for i in success(store, 'export', {})['items']} == {'communication.length', 'tools.trial'}
    # Changing only the expiry is an update, not "unchanged".
    revision = next(i['revision'] for i in saved if i['key'] == 'tools.trial')
    extended = success(store, 'update', update(entry('tools.trial', 'Trying Cursor until the end of the month.',
                                                                     revision, expires_at='2030-04-30')))['items'][0]
    assert extended['action'] == 'updated'
    # Something already over isn't saved, and an expiry needs a timezone.
    past = store.execute('stopover_memory_update', update(entry('old.fact', 'Was true once.', expires_at='2030-03-01')))
    assert past['error']['code'] == 'VALIDATION_ERROR' and 'has passed' in past['error']['message']
    naive = store.execute('stopover_memory_update', update(entry('x.y', 'z', expires_at='2030-05-01T09:00:00')))
    assert naive['error']['code'] == 'VALIDATION_ERROR'
