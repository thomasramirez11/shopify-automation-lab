# Shopify Automation Lab — V2.8B / Checkpoint 1

## Purpose

Offline-only, additive safety-contract code for **preparing** a Shopify `inventorySetQuantities` GraphQL request for exactly two mapped items. It does **not** write to Shopify, make network requests, authenticate, run supplier feeds, or write SQLite. This is **not V2.8B live execution**.

## Included files

- `supplier/batch/live_request_contract.py` — frozen inputs, strict fail-closed validation, GraphQL request construction
- `scripts/supplier_batch_live_request_contract_demo.py` — synthetic offline demonstration
- `tests/test_supplier_batch_live_request_contract.py` — focused regression tests

These are **new files only**. None of your existing modules or source files are replaced.

## Setup

1. Ensure V2.8A has passed all 1170 tests (already demonstrated in the supplied log).
2. Confirm a clean Git worktree or make a checkpoint commit; preserve all current code.
3. Unzip into the repository root, preserving the `supplier`, `scripts`, and `tests` paths.
4. Run from repo root with your `.venv` activated:

```powershell
python -m compileall supplier/batch/live_request_contract.py scripts/supplier_batch_live_request_contract_demo.py tests/test_supplier_batch_live_request_contract.py
python -m pytest tests/test_supplier_batch_live_request_contract.py -q
python -m pytest -q
python scripts/supplier_batch_live_request_contract_demo.py
```

The focused tests should pass (the exact pass count is printed by pytest). Full-suite count should become 1170 plus the number of additional test cases in this checkpoint; any existing failures require investigation.

Expected demo end:

```
STATUS: CONTRACT BUILT — EXECUTION NOT ENABLED
NETWORK CALLS: 0
SQLITE WRITES: 0
SHOPIFY WRITES: 0
```

The demo deliberately uses fake inventory item IDs and fake hash values, and MUST NEVER be adapted into a real write by copying its values.

## Why this matters

Shopify Admin GraphQL 2026-04 and later require an explicit `changeFromQuantity` value per inventory input, and an `@idempotent` key for the `inventorySetQuantities` mutation. **Never use null CAS or `ignoreCompareQuantity` for our controlled execution.**

Authoritative docs:

- https://shopify.dev/docs/api/admin-graphql/2026-10/mutations/inventorySetQuantities
- https://shopify.dev/docs/api/usage/idempotent-requests

## Safety conditions for the eventual live adapter

- **Trust binding:** the caller must obtain `PreflightEvidence` from the current verified V2.8A objects, not a string copied from a terminal or arbitrary arguments. Fingerprint format checks alone do **not** authenticate approval or preflight.
- **Execution identity:** generate and **persist** one unique operation UUID before first mutation attempt, and bind it to the exact request payload. A retry of the same operation must reuse the same key and same payload; never assign a new key automatically after a timeout.
- **Freshness:** compare Shopify's current quantities immediately before submitting the mutation. V2.8A result from a previous session is insufficient.
- **Atomicity:** do not assume a multi-item mutation is all-or-nothing. On any ambiguous response or `userErrors`, stop new requests and reconcile each item from Shopify reads and the audit ledger. Do not automatically undo or repeat inventory writes.
- **Proof:** record the operation and response in the existing append-only audit ledger and then refresh V1 inventory snapshots after execution.
- **Supplier truth:** V2.8A quantities are synthetic proposals for a controlled test, not supplier feed results.
- **No live writes until the adapter is implemented and tested against the actual repository source.**

## Source files needed for safe integration

To integrate into the existing client/audit/preflight implementation **without overwriting working code**, use the current versions of: `supplier/preflight/{models,service}.py`, `supplier/batch/{builder,approval}.py`, `scripts/supplier_live_batch_preflight.py`, the previous one-item live writer, relevant audit repository/service files, `shopify/client.py`, and relevant tests. Share a source-only ZIP (exclude `.env`, tokens, `.venv`, `.git`, SQLite DBs, and any customer/order exports).

## What This Lesson Demonstrates

- **Pure functions and immutable dataclasses:** generate a repeatable request without side effects.
- **Fail-closed input validation:** reject stale baselines, unapproved manifests, duplicate IDs, invalid GIDs and unsafe deltas.
- **CAS / optimistic concurrency:** verify the expected pre-write stock matches Shopify's observed stock.
- **Idempotency:** reuse a persisted operation UUID to recognize a retry of the *same* command.
- **Separation of concerns:** request construction is not permission to execute it.
