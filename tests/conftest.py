import copy
import os
import socket
import subprocess
import sys
import time
import uuid

import httpx
import pytest

from baton.sample import sample_record
from baton.store import Store


@pytest.fixture
def record():
    return copy.deepcopy(sample_record())


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path)
    yield store
    store.close()


@pytest.fixture
def push(store, record):
    def run(**changes):
        data = copy.deepcopy(record)
        data.update(changes)
        result = store.execute("baton_save", {"operation_id": str(uuid.uuid4()), "record": data})
        assert result["ok"], result
        return result["data"]
    return run


@pytest.fixture
def live_server(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    log = open(tmp_path / "server.log", "w+")
    process = subprocess.Popen([sys.executable, "-m", "baton", "--data-dir", str(tmp_path), "serve", "--host", "127.0.0.1", "--port", str(port)], stdout=log, stderr=log)
    try:
        for _ in range(100):
            if process.poll() is not None:
                log.seek(0)
                pytest.fail(log.read())
            try:
                if httpx.get(url + "/healthz", timeout=.5).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(.1)
        else:
            pytest.fail("Server did not become ready")
        yield {"url": url, "directory": tmp_path, "process": process}
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        log.close()
