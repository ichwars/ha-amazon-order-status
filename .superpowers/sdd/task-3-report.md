# Task 3 Report: Coordinator 2.0 Storage And Shipment Upserts

## Summary

Implemented shipment-first coordinator state handling in `custom_components/amazon_order_status/coordinator.py`, added the required regression coverage in `tests/test_coordinator_state.py`, and kept the work scoped to the owned files for Task 3.

## RED/GREEN TDD Evidence

### RED

Command:

```text
python -m unittest tests.test_coordinator_state
```

Result:

```text
FAILED (failures=1, errors=3)
```

Observed failures before implementation:

- Missing coordinator methods: `_upsert_order_event`, `async_mark_delivered`, `async_ignore_order`, `async_restore_order`
- `_current_data()` still exposed legacy 1.x order records without `shipments`

### GREEN

Command:

```text
python -m unittest tests.test_coordinator_state
```

Result:

```text
Ran 4 tests in 0.081s
OK
```

### Regression

Command:

```text
python -m unittest tests.test_models tests.test_parser_helpers tests.test_coordinator_state
```

Result:

```text
Ran 31 tests in 0.118s
OK
```

Note: the existing negative-path IMAP regression still emits `IMAP search failed` during the run while the suite remains green.

## Files Changed

- `custom_components/amazon_order_status/coordinator.py`
- `tests/test_coordinator_state.py`

## Production Changes

- Bumped coordinator storage version to `2`
- Filtered `_current_data()` to expose only shipment-backed 2.0 orders
- Added shipment-aware `_upsert_order_event(...)`
- Switched email processing updates to use `_upsert_order_event(...)`
- Added manual coordinator workflow methods:
  - `async_set_status(...)`
  - `async_mark_delivered(...)`
  - `async_ignore_order(...)`
  - `async_restore_order(...)`
- Kept validated Amazon HTTPS tracking URLs only through model helpers
- Left legacy 1.x stored records out of current sensor data until users rebuild with rescan

## Self-Review

- Verified the task-specific coordinator state tests failed before implementation and passed after implementation
- Verified model/parser regression tests still pass with the coordinator changes
- Kept edits limited to the owned coordinator and test files before writing this report
- Preserved IMAP connection/login/select/search flow; only the order state update path changed

## Concerns

- Scan diagnostic counters such as `enriched_count`, `skipped_status_regression`, and `skipped_older_duplicate` are no longer updated with the same fidelity as the old 1.x order-centric path. No current test covers those counters, but they are worth revisiting when the remaining 2.0 coordinator/sensor work lands.
