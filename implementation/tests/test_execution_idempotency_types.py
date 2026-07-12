"""B5B pure execution-idempotency identity and typed-value tests."""
from dataclasses import fields
from datetime import datetime, timedelta, timezone

import pytest

from atos.execution_idempotency_types import (
    ATTEMPT_ID_PREFIX,
    ATTEMPT_ID_VERSION,
    CLIENT_ORDER_ID_LENGTH,
    CLIENT_ORDER_ID_VERSION,
    LIVE,
    ConcurrentExecutionTransitionError,
    DispatchCommitCommand,
    DispatchCommitResult,
    DispatchOutcomeCommand,
    ExecutionIdempotencyClaim,
    ExecutionIdempotencyCommand,
    ExecutionIdempotencyConflictError,
    ExecutionIdempotencyError,
    ExecutionIdempotencyInvariantError,
    ExecutionIdempotencyOutcome,
    ExecutionIdempotencyPreconditionError,
    ExecutionIdempotencyValidationError,
    ExecutionRecoveryDecision,
    derive_attempt_id,
    derive_client_order_id,
    derive_idempotency_key,
)
from atos.lifecycle_types import DispatchAttemptStatus, ExecutionStatus, OrderSide

UTC_TIME = datetime(2026, 7, 12, 18, 0, tzinfo=timezone.utc)
HASH_ZERO = "0" * 64
EXPECTED_KEY = "91dd403656edee3085c73b639232a375f03f09d0297e13b15f066b9890cbdd1d"
EXPECTED_CLIENT_ORDER_ID = "a591dd403656edee3085c73b639232"
EXPECTED_ATTEMPT_ID = (
    "att_645cd71507d26afd43d15a39363c8dc4712c7266df00269477cdaf96e2ee3c54"
)


def _command(**overrides):
    values = {
        "execution_intent_id": "execution-1",
        "venue": "okx_paper",
        "account_scope": "acct-1",
        "symbol": "BTC/USDT",
        "action": OrderSide.BUY,
        "normalized_intent_hash": HASH_ZERO,
        "created_at": UTC_TIME,
    }
    values.update(overrides)
    return ExecutionIdempotencyCommand(**values)


def _claim(command=None, **overrides):
    command = command or _command()
    values = {
        "idempotency_key": command.idempotency_key,
        "execution_intent_id": command.execution_intent_id,
        "venue": command.venue,
        "account_scope": command.account_scope,
        "symbol": command.symbol,
        "action": command.action,
        "normalized_intent_hash": command.normalized_intent_hash,
        "client_order_id": command.client_order_id,
        "created_at": command.created_at,
    }
    values.update(overrides)
    return ExecutionIdempotencyClaim(**values)


def test_frozen_constants_and_enums():
    assert LIVE == "FORBIDDEN"
    assert CLIENT_ORDER_ID_VERSION == "a5"
    assert CLIENT_ORDER_ID_LENGTH == 30
    assert ATTEMPT_ID_VERSION == "b5.v1"
    assert ATTEMPT_ID_PREFIX == "att_"
    assert tuple(item.value for item in ExecutionIdempotencyOutcome) == (
        "CLAIMED",
        "REPLAY_PREPARED",
        "RECONCILE_REQUIRED",
        "TERMINAL_NOOP",
    )
    assert tuple(item.value for item in ExecutionRecoveryDecision) == (
        "SAFE_COMMIT_DISPATCH",
        "RECONCILE_REQUIRED",
        "TERMINAL_NOOP",
        "PAUSE_RECOVERY",
    )


def test_error_hierarchy():
    for error in (
        ExecutionIdempotencyValidationError,
        ExecutionIdempotencyPreconditionError,
        ExecutionIdempotencyConflictError,
        ExecutionIdempotencyInvariantError,
        ConcurrentExecutionTransitionError,
    ):
        assert issubclass(error, ExecutionIdempotencyError)


def test_exact_frozen_identity_vector():
    command = _command()
    assert command.idempotency_key == EXPECTED_KEY
    assert command.client_order_id == EXPECTED_CLIENT_ORDER_ID
    assert derive_attempt_id(command.idempotency_key, 1) == EXPECTED_ATTEMPT_ID


def test_derived_id_formats():
    command = _command()
    assert len(command.idempotency_key) == 64
    assert set(command.idempotency_key) <= set("0123456789abcdef")
    assert len(command.client_order_id) == 30
    assert command.client_order_id.startswith("a5")
    assert set(command.client_order_id) <= set("0123456789abcdefghijklmnopqrstuvwxyz")
    attempt_id = derive_attempt_id(command.idempotency_key)
    assert len(attempt_id) == 68
    assert attempt_id.startswith("att_")
    assert set(attempt_id[4:]) <= set("0123456789abcdef")


def test_command_constructor_does_not_accept_derived_identity_fields():
    names = {field.name for field in fields(ExecutionIdempotencyCommand)}
    assert "idempotency_key" not in names
    assert "client_order_id" not in names
    assert "attempt_id" not in names


def test_identity_ignores_execution_provenance_and_time():
    original = _command()
    replay = _command(
        execution_intent_id="execution-from-another-cycle",
        created_at=UTC_TIME + timedelta(days=30),
    )
    assert replay.idempotency_key == original.idempotency_key
    assert replay.client_order_id == original.client_order_id


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    (
        ("venue", "another_venue"),
        ("account_scope", "acct-2"),
        ("symbol", "ETH/USDT"),
        ("action", OrderSide.SELL),
        ("normalized_intent_hash", "1" * 64),
    ),
)
def test_each_semantic_component_changes_key(field_name, replacement):
    original = _command()
    changed = _command(**{field_name: replacement})
    assert changed.idempotency_key != original.idempotency_key


def test_derive_function_matches_command_properties():
    command = _command()
    key = derive_idempotency_key(
        venue=command.venue,
        account_scope=command.account_scope,
        symbol=command.symbol,
        action=command.action,
        normalized_intent_hash=command.normalized_intent_hash,
    )
    assert key == command.idempotency_key
    assert derive_client_order_id(key) == command.client_order_id


def test_claim_reconstructs_exact_derived_values():
    claim = _claim()
    assert claim.idempotency_key == EXPECTED_KEY
    assert claim.client_order_id == EXPECTED_CLIENT_ORDER_ID


def test_claim_rejects_key_component_mismatch():
    with pytest.raises(ExecutionIdempotencyInvariantError, match="idempotency_key"):
        _claim(idempotency_key="1" * 64)


def test_claim_rejects_client_order_id_mismatch():
    with pytest.raises(ExecutionIdempotencyInvariantError, match="client_order_id"):
        _claim(client_order_id="a5" + "1" * 28)


@pytest.mark.parametrize(
    "bad_hash",
    (
        "a" * 63,
        "a" * 65,
        "A" * 64,
        "g" + "a" * 63,
        " " * 64,
    ),
)
def test_bad_normalized_intent_hash_rejected(bad_hash):
    with pytest.raises(ExecutionIdempotencyValidationError):
        _command(normalized_intent_hash=bad_hash)


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    (
        ("execution_intent_id", ""),
        ("execution_intent_id", "   "),
        ("venue", ""),
        ("account_scope", "\t"),
        ("symbol", ""),
    ),
)
def test_blank_identities_rejected(field_name, bad_value):
    with pytest.raises(ExecutionIdempotencyValidationError):
        _command(**{field_name: bad_value})


def test_plain_string_action_rejected():
    with pytest.raises(ExecutionIdempotencyValidationError, match="OrderSide"):
        _command(action="BUY")


def test_naive_timestamp_rejected():
    with pytest.raises(ExecutionIdempotencyValidationError, match="timezone-aware UTC"):
        _command(created_at=datetime(2026, 7, 12, 18, 0))


def test_non_utc_timestamp_rejected():
    with pytest.raises(ExecutionIdempotencyValidationError, match="UTC offset"):
        _command(created_at=datetime(2026, 7, 12, 18, 0, tzinfo=timezone(timedelta(hours=8))))


@pytest.mark.parametrize("attempt_no", (True, False, 0, -1, 1.0, "1", None))
def test_invalid_attempt_number_rejected(attempt_no):
    with pytest.raises(ExecutionIdempotencyValidationError, match="attempt_no"):
        derive_attempt_id(EXPECTED_KEY, attempt_no)


def test_attempt_number_changes_attempt_identity():
    assert derive_attempt_id(EXPECTED_KEY, 1) != derive_attempt_id(EXPECTED_KEY, 2)


def test_dispatch_commit_command_validates_identity_and_utc():
    command = DispatchCommitCommand("execution-1", UTC_TIME)
    assert command.execution_intent_id == "execution-1"
    with pytest.raises(ExecutionIdempotencyValidationError):
        DispatchCommitCommand("", UTC_TIME)
    with pytest.raises(ExecutionIdempotencyValidationError):
        DispatchCommitCommand("execution-1", datetime(2026, 1, 1))


def test_valid_dispatch_commit_result():
    result = DispatchCommitResult(
        execution_intent_id="execution-1",
        idempotency_key=EXPECTED_KEY,
        attempt_id=EXPECTED_ATTEMPT_ID,
        client_order_id=EXPECTED_CLIENT_ORDER_ID,
        attempt_no=1,
        attempt_status=DispatchAttemptStatus.PRE_DISPATCH_PROVEN,
        execution_status=ExecutionStatus.DISPATCH_COMMITTED,
    )
    assert result.attempt_no == 1


@pytest.mark.parametrize("attempt_no", (0, 2, True))
def test_dispatch_commit_result_enforces_one_attempt_rule(attempt_no):
    with pytest.raises(ExecutionIdempotencyValidationError, match="exactly 1"):
        DispatchCommitResult(
            execution_intent_id="execution-1",
            idempotency_key=EXPECTED_KEY,
            attempt_id=EXPECTED_ATTEMPT_ID,
            client_order_id=EXPECTED_CLIENT_ORDER_ID,
            attempt_no=attempt_no,
            attempt_status=DispatchAttemptStatus.PRE_DISPATCH_PROVEN,
            execution_status=ExecutionStatus.DISPATCH_COMMITTED,
        )


def test_dispatch_commit_result_rejects_derived_identity_drift():
    with pytest.raises(ExecutionIdempotencyInvariantError, match="attempt_id"):
        DispatchCommitResult(
            execution_intent_id="execution-1",
            idempotency_key=EXPECTED_KEY,
            attempt_id="att_" + "0" * 64,
            client_order_id=EXPECTED_CLIENT_ORDER_ID,
            attempt_no=1,
            attempt_status=DispatchAttemptStatus.PRE_DISPATCH_PROVEN,
            execution_status=ExecutionStatus.DISPATCH_COMMITTED,
        )
    with pytest.raises(ExecutionIdempotencyInvariantError, match="client_order_id"):
        DispatchCommitResult(
            execution_intent_id="execution-1",
            idempotency_key=EXPECTED_KEY,
            attempt_id=EXPECTED_ATTEMPT_ID,
            client_order_id="a5" + "0" * 28,
            attempt_no=1,
            attempt_status=DispatchAttemptStatus.PRE_DISPATCH_PROVEN,
            execution_status=ExecutionStatus.DISPATCH_COMMITTED,
        )


def test_dispatch_commit_result_rejects_wrong_states():
    with pytest.raises(ExecutionIdempotencyValidationError, match="PRE_DISPATCH_PROVEN"):
        DispatchCommitResult(
            execution_intent_id="execution-1",
            idempotency_key=EXPECTED_KEY,
            attempt_id=EXPECTED_ATTEMPT_ID,
            client_order_id=EXPECTED_CLIENT_ORDER_ID,
            attempt_no=1,
            attempt_status=DispatchAttemptStatus.SUBMITTED,
            execution_status=ExecutionStatus.DISPATCH_COMMITTED,
        )
    with pytest.raises(ExecutionIdempotencyValidationError, match="DISPATCH_COMMITTED"):
        DispatchCommitResult(
            execution_intent_id="execution-1",
            idempotency_key=EXPECTED_KEY,
            attempt_id=EXPECTED_ATTEMPT_ID,
            client_order_id=EXPECTED_CLIENT_ORDER_ID,
            attempt_no=1,
            attempt_status=DispatchAttemptStatus.PRE_DISPATCH_PROVEN,
            execution_status=ExecutionStatus.PREPARED,
        )


def test_dispatch_outcome_command_requires_typed_states_and_utc():
    command = DispatchOutcomeCommand(
        execution_intent_id="execution-1",
        attempt_id=EXPECTED_ATTEMPT_ID,
        attempt_status=DispatchAttemptStatus.AMBIGUOUS,
        execution_status=ExecutionStatus.AMBIGUOUS,
        observed_at=UTC_TIME,
        error_class="TransportTimeout",
    )
    assert command.error_class == "TransportTimeout"
    with pytest.raises(ExecutionIdempotencyValidationError):
        DispatchOutcomeCommand(
            execution_intent_id="execution-1",
            attempt_id=EXPECTED_ATTEMPT_ID,
            attempt_status="AMBIGUOUS",
            execution_status=ExecutionStatus.AMBIGUOUS,
            observed_at=UTC_TIME,
        )
    with pytest.raises(ExecutionIdempotencyValidationError):
        DispatchOutcomeCommand(
            execution_intent_id="execution-1",
            attempt_id=EXPECTED_ATTEMPT_ID,
            attempt_status=DispatchAttemptStatus.AMBIGUOUS,
            execution_status="AMBIGUOUS",
            observed_at=UTC_TIME,
        )
