# Task 2 Report: Parser Split And Structured Delivery Details

Date: 2026-06-26
Release target: 2.0.0

## Scope

Owned files changed:
- `custom_components/amazon_order_status/parser.py`
- `custom_components/amazon_order_status/coordinator.py`
- `tests/test_parser_helpers.py`

No other repository files were modified. Untracked `__pycache__` directories were left unstaged.

## TDD Evidence

### RED

Command:

```powershell
python -m unittest tests.test_parser_helpers
```

Result:
- `FAIL`
- Failure reason was expected: `FileNotFoundError` for `custom_components/amazon_order_status/parser.py` during test module loading after the new parser import path and parser-focused tests were added.

### GREEN

Command:

```powershell
python -m unittest tests.test_parser_helpers
```

Result:
- `PASS`
- `Ran 19 tests in 0.032s`

### Regression

Command:

```powershell
python -m unittest tests.test_models tests.test_parser_helpers
```

Result:
- `PASS`
- `Ran 26 tests in 0.032s`

## Implementation Summary

- Added `parser.py` as the parser helper module and moved parsing behavior there.
- Kept Amazon-only HTTPS URL validation for tracking links and Amazon image CDN validation for product image URLs.
- Added new 2.0 status recognition:
  - `Pickup ready`
  - `Delayed`
  - `Delivery problem`
  - `Undeliverable`
  - `Canceled`
  - `Return started`
  - `Refunded`
- Added structured delivery parsing:
  - `delivery_date_start`
  - `delivery_date_end`
  - `delivery_window_start`
  - `delivery_window_end`
  - `delivery_is_delayed`
- Preserved existing parser behavior for prior tests, including item title extraction, safe sender checks, safe URL checks, image extraction, and delivery update recognition.
- Updated coordinator integration to:
  - import parser helpers
  - keep compatibility through existing private helper names
  - pass `received_at` into body parsing so relative dates can be resolved
  - use model-defined `ORDER_DETAIL_FIELDS`

## Privacy/Safety Review

- No raw email body text is stored.
- No sender addresses are stored.
- No payment amounts are parsed or stored.
- No third-party tracking numbers are added.
- Tracking URLs remain restricted to validated HTTPS Amazon-domain URLs.
- No external network calls or carrier API calls were introduced.

## Self-Review

- Confirmed parser output remains structured and sanitized.
- Confirmed nested detail enrichment still flows through `ORDER_DETAIL_FIELDS` from `models.py`.
- Confirmed coordinator compatibility wrappers preserve current private helper entry points used by existing tests.
- Confirmed subject-based status ranking in coordinator now follows parser 2.0 ranks.

## Concerns

- `coordinator.py` still contains some older parser-local definitions that are now shadowed by imported parser helpers. Behavior is correct and tests pass, but a later cleanup task could remove that duplication once downstream callers are fully moved over.
- Existing unittest output still includes the expected `IMAP search failed` log line from the regression test fixture; this is pre-existing test behavior, not a new failure.
