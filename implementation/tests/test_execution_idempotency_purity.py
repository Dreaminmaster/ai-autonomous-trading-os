"""B5B purity boundary: identity policy must remain free of I/O dependencies."""
from __future__ import annotations

import ast
import inspect

import atos.execution_idempotency_types as idempotency_types


def test_identity_policy_imports_no_database_network_or_executor_modules():
    tree = ast.parse(inspect.getsource(idempotency_types))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden_roots = {
        "sqlite3",
        "urllib",
        "http",
        "httpx",
        "requests",
        "aiohttp",
        "websockets",
        "ccxt",
        "freqtrade",
        "atos.runtime_db",
        "atos.runtime_migrations",
        "atos.lifecycle_persistence",
        "paper_executor",
    }
    assert imported.isdisjoint(forbidden_roots), imported & forbidden_roots


def test_identity_policy_has_no_clock_randomness_or_live_capability():
    source = inspect.getsource(idempotency_types)
    assert "uuid" not in source
    assert "random" not in source
    assert "datetime.now" not in source
    assert "time.time" not in source
    assert idempotency_types.LIVE == "FORBIDDEN"
