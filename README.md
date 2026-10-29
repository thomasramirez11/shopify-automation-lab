# Shopify Automation Lab

Shopify Automation Lab is a modular Python backend automation system for Shopify. It connects securely to the Shopify Admin GraphQL API, synchronizes store data into SQLite, tracks operational history, analyzes order profitability, creates persistent alerts, records synchronization health, and generates immutable daily store-health reports.

The project is intentionally built one feature at a time with an emphasis on clean architecture, security, observability, testability, and future extensibility.

---

## V1 Direction

The current V1 focuses on proving a reliable single-store backend before moving into supplier synchronization, fulfillment automation, AI analysis, dashboards, multi-store support, or a public Shopify app.

The goal is not only to automate Shopify operations, but also to use the project as a practical environment for learning Python, APIs, databases, software architecture, logging, testing, and business automation.

---

# Current V1 Status

## Stage 0 — Project Foundation

Completed:

- Python virtual environment
- Modular project structure
- `.env` configuration
- Git repository
- Secure `.gitignore`
- GitHub source control

## Stage 1 — Shopify Connection

Completed:

- Shopify client-credentials authentication
- Reusable `ShopifyClient`
- Shopify Admin GraphQL API connection
- Environment-based credentials
- API-version configuration

## Stage 2 — Product Retrieval

Completed:

- `PRODUCTS_QUERY`
- `ProductService`
- Cursor pagination
- Product retrieval
- Variant retrieval
- SKU retrieval
- Price retrieval
- Inventory quantity retrieval
- Inventory item ID retrieval

## Stage 3 — SQLite Persistence & Change Tracking

Completed:

- SQLite connection management
- Database schema
- Product persistence
- Variant persistence
- Repository pattern
- SQL transactions
- UPSERT synchronization
- Repeatable / idempotent syncs
- Price-change detection
- Inventory-change detection
- Historical variant-change tracking
- Synchronization-run auditing
- Successful-run tracking
- Failed-run tracking
- Error persistence
- Recent synchronization history
- Data-integrity verification

## Stage 4 — Shopify Order Synchronization

Completed:

- Shopify order GraphQL query
- `OrderService`
- Order persistence
- Order-line-item persistence
- New-order detection
- Repeat-safe synchronization
- Order update synchronization
- Financial-status synchronization
- Fulfillment-status synchronization
- Order database verification

## Stage 5 — Cost & Profit Analysis

Completed:

- Manual variant-cost configuration
- `CostRepository`
- Decimal-based financial calculations
- Currency validation
- Per-line-item revenue calculation
- Product-cost calculation
- Estimated gross-profit calculation
- Gross-margin calculation
- Immutable profit snapshots
- Order-level financial summaries
- Financial-completeness detection
- Missing-cost protection
- Historical cost preservation

> Profit figures currently represent estimated **gross product profit**. They do not yet include advertising spend, payment-processing fees, Shopify fees, shipping expense, refunds, or tax liabilities.

## Stage 6 — Logging, Alerts & Operational Monitoring

Completed:

- Structured application logging
- Local log-file output
- Persistent alert history
- Alert deduplication
- Alert occurrence tracking
- Alert resolution
- New-order alerts
- Missing-cost alerts
- Low-inventory alerts
- Synchronization-failure alerts
- Failure isolation
- Controlled synchronization-failure testing
- Operational alert verification

## Stage 7 — Reporting & Store Health

Completed:

- `ReportService`
- Timezone-aware business dates
- Daily order activity
- Historical profitability summaries
- Today's financial performance
- Currency-safe report aggregation
- Recent price/inventory change summaries
- Rule-based store-health status
- Human-readable terminal reports
- Immutable daily-report persistence
- JSON report serialization
- Historical report retrieval
- Report workflow orchestration
- Reporting acceptance testing
- Post-sync report generation and persistence

---

# Architecture

```text
                           Shopify Store
                                |
                                v
                    Shopify Admin GraphQL API
                                |
                                v
                         ShopifyClient
                         /          \
                        v            v
                ProductService   OrderService
                        |            |
                        v            v
                ProductRepository OrderRepository
                        |            |
                        |            +--> orders
                        |            +--> order_line_items
                        |
                        +--> products
                        +--> variants
                        +--> variant_changes

CostRepository ----------------------+
                                     |
                                     v
                              ProfitService
                                     |
                                     v
                         FinancialProcessingService
                                     |
                                     v
                        ProfitSnapshotRepository
                                     |
                                     +--> variant_costs
                                     +--> order_line_item_profit_snapshots

AlertService ------------------------+
                                     |
                                     v
                              AlertRepository
                                     |
                                     +--> alerts

SyncRunRepository ------------------> sync_runs

ProductRepository -----------+
OrderRepository -------------+
ProfitSnapshotRepository ----+
AlertRepository -------------+----> ReportService
SyncRunRepository -----------+            |
                                          v
                               structured report dictionary
                                  /                  \
                                 v                    v
                    TerminalReportFormatter   DailyReportRepository
                                 |                    |
                                 v                    v
                       human-readable report      daily_reports
                                  \                  /
                                   \                /
                                    v              v
                                     DailyReportService
```

---

# Project Structure

```text
shopify-automation-lab/
|
|-- config/
|   |-- __init__.py
|   |-- logging_config.py
|   |-- settings.py
|
|-- database/
|   |-- __init__.py
|   |-- connection.py
|   |-- schema.py
|
|-- repositories/
|   |-- __init__.py
|   |-- alert_repository.py
|   |-- cost_repository.py
|   |-- daily_report_repository.py
|   |-- order_repository.py
|   |-- product_repository.py
|   |-- profit_snapshot_repository.py
|   |-- sync_run_repository.py
|
|-- services/
|   |-- __init__.py
|   |-- alert_service.py
|   |-- daily_report_service.py
|   |-- financial_processing_service.py
|   |-- order_service.py
|   |-- product_service.py
|   |-- profit_service.py
|   |-- report_formatter.py
|   |-- report_service.py
|
|-- shopify/
|   |-- __init__.py
|   |-- client.py
|   |
|   |-- queries/
|       |-- __init__.py
|       |-- orders.py
|       |-- products.py
|
|-- data/
|   |-- shopify.db                 # local only / Git ignored
|
|-- logs/
|   |-- ...                        # local only / Git ignored
|
|-- .env                           # local only / Git ignored
|-- .env.example
|-- .gitignore
|-- main.py
|-- README.md
```

---

# SQLite Data Model

## `products`

Stores the latest synchronized Shopify product state.

## `variants`

Stores current variant data including:

- Shopify variant ID
- Parent Shopify product ID
- Variant title
- SKU
- Price
- Inventory quantity
- Inventory item ID
- Last synchronization timestamp

## `variant_changes`

Stores historical price and inventory movements.

Example:

```text
AUTO-shirt-L | inventory_quantity | 10 -> 2
AUTO-Cap-001 | inventory_quantity | 19 -> 18
AUTO-shirt-L | price | 27.00 -> 5.00
```

## `sync_runs`

Tracks every synchronization attempt, including:

- Started time
- Completed time
- Status
- Products seen
- Variants seen
- Failure message

## `orders`

Stores synchronized Shopify orders.

## `order_line_items`

Stores the line items belonging to synchronized orders.

## `variant_costs`

Stores configured variant costs used for profit estimation.

## `order_line_item_profit_snapshots`

Stores immutable historical financial snapshots for order line items.

An existing snapshot is intentionally not recalculated if a product's current configured cost later changes.

## `alerts`

Stores persistent operational alerts including:

- New order
- Missing cost
- Low inventory
- Synchronization failure

Alerts support deduplication, occurrence counts, open/resolved state, and historical timestamps.

## `daily_reports`

Stores immutable structured reporting snapshots.

Important fields include:

- Business date
- Report timezone
- UTC generation timestamp
- Health status
- Complete serialized JSON report
- Creation timestamp

Multiple report snapshots may exist for the same business date. They are intentionally preserved instead of overwritten.

---

# Synchronization Flow

A normal `python main.py` execution now follows this high-level flow:

1. Start a synchronization audit.
2. Authenticate with Shopify.
3. Retrieve products and variants.
4. Retrieve orders and line items.
5. Persist current product state.
6. Detect and store price/inventory changes.
7. Synchronize low-inventory alerts.
8. Persist orders and detect new orders.
9. Create new-order alerts.
10. Process order financials.
11. Create or resolve missing-cost alerts.
12. Preserve immutable profit snapshots.
13. Verify Shopify and SQLite record counts.
14. Mark the synchronization run successful.
15. Display recent synchronization history.
16. Generate the store-health report.
17. Format the report for terminal output.
18. Persist the structured report snapshot in `daily_reports`.

If the core synchronization fails:

- The synchronization run is marked failed.
- The original error is persisted.
- A synchronization-failure alert is created.
- The original exception is re-raised.

If reporting fails **after a successful synchronization**, the reporting error is logged separately and does not retroactively mark the successful Shopify sync as failed.

---

# Store Health Reporting

The reporting subsystem summarizes:

- Products and variants monitored
- Total orders and line items
- Today's order activity
- Historical merchandise revenue
- Historical product cost
- Estimated gross profit
- Gross margin
- Financially complete/incomplete orders
- Current low inventory
- Current out-of-stock variants
- Open alerts by severity and type
- Recent product/inventory changes
- Latest synchronization status
- Recent synchronization failures

Health status is rule-based and explainable:

```text
CRITICAL
- Latest synchronization failed
- One or more variants are out of stock

ATTENTION
- Low inventory exists
- Financial data is incomplete
- Missing-cost alerts are open
- Recent synchronization failures exist

HEALTHY
- None of the above conditions are active
```

The report includes the exact reasons behind the current health state rather than using an opaque score.

---

# Example Daily Report

```text
SHOPIFY AUTOMATION LAB — DAILY REPORT
================================================

STORE HEALTH
------------------------------------------------
Status: ATTENTION
Reasons:
  - 2 variants are at or below the low-inventory threshold.
  - 1 failed synchronization run was found in recent history.

TODAY
------------------------------------------------
Orders: 0
Merchandise revenue: N/A
Estimated gross profit: N/A

HISTORICAL PERFORMANCE
------------------------------------------------
Orders: 4
Merchandise revenue: 50.00 USD
Product cost: 21.50 USD
Estimated gross profit: 28.50 USD
Gross margin: 57.00%

INVENTORY
------------------------------------------------
Low inventory variants: 2
Out of stock variants: 0

SYNC HEALTH
------------------------------------------------
Latest run: SUCCESS
Recent failures: 1
```

---

# Important Python & Backend Concepts Demonstrated

## Python

- Classes
- Functions
- Modules
- Packages
- Dictionaries
- Nested data structures
- Loops
- Generator expressions
- Context managers
- Exception handling
- Exception propagation
- Type validation
- `Decimal` financial arithmetic
- `datetime`
- `zoneinfo`
- JSON serialization / deserialization
- Logging
- Assertions
- Dependency injection

## SQL / SQLite

- `CREATE TABLE`
- `SELECT`
- `INSERT`
- `UPDATE`
- UPSERT
- `ON CONFLICT`
- `JOIN`
- Primary keys
- Foreign keys
- Constraints
- `CHECK`
- Indexes
- Transactions
- Commit / rollback
- Historical snapshots
- Audit trails

## Software Architecture

- API client layer
- Service layer
- Repository pattern
- Orchestration services
- Separation of concerns
- Single Responsibility Principle
- Dependency injection
- Idempotent synchronization
- Persistent state
- Historical state
- Immutable snapshots
- Data vs presentation separation
- Failure isolation
- Observability
- Regression testing
- Acceptance testing

---

# Security

Sensitive Shopify credentials remain outside source control.

Never commit:

```text
.env
.venv/
*.db
data/*.db
data/*.db-shm
data/*.db-wal
logs/
__pycache__/
*.pyc
```

Never commit:

- Shopify client secrets
- Access tokens
- Production database files
- Private customer data
- Runtime logs containing sensitive operational details

The committed `.env.example` should contain placeholders only.

---

# Environment Configuration

Create a local `.env` file based on `.env.example`.

Current Shopify configuration includes:

```text
SHOPIFY_STORE_DOMAIN
SHOPIFY_CLIENT_ID
SHOPIFY_CLIENT_SECRET
SHOPIFY_API_VERSION
```

Real values must remain private.

---

# Timezone Dependency

Stage 7 uses Python's standard-library `zoneinfo` support for timezone-aware reporting.

On Windows, the IANA timezone database may need the `tzdata` package:

```powershell
python -m pip install tzdata
```

The current V1 reporting timezone is `America/Bogota`.

A future multi-store version should make store timezone configuration tenant-specific.

---

# Running the Project

## 1. Activate the virtual environment

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

## 2. Initialize or migrate the SQLite schema

```powershell
python -m database.schema
```

The schema uses `CREATE TABLE IF NOT EXISTS`, so existing local data is preserved while missing tables/indexes are created.

## 3. Run the complete Shopify synchronization

```powershell
python main.py
```

A successful run performs synchronization, financial analysis, monitoring, audit verification, reporting, terminal formatting, and immutable report persistence.

## 4. Run a syntax check

```powershell
python -m compileall config database repositories services shopify main.py
```

---

# Testing Philosophy

The project is intentionally developed checkpoint by checkpoint.

Each feature generally follows:

```text
Design
  ↓
Implement
  ↓
Test independently
  ↓
Integrate
  ↓
Regression test
  ↓
Acceptance test
  ↓
Git checkpoint
```

Examples already tested include:

- Repeated product sync without duplicate products
- Product price changes
- Inventory changes
- New Shopify order detection
- Order updates
- Duplicate-order prevention
- Missing-cost recovery
- Immutable profit snapshots
- Alert deduplication
- Alert resolution
- Low-inventory recovery and recurrence
- Controlled synchronization failure
- Historical alert preservation
- Timezone boundary reporting
- Historical profitability aggregation
- Daily business-date attribution
- Daily-report JSON persistence
- Full report persistence round trip

---

# Current Known Limitations

V1 currently has deliberate boundaries:

- Single-store architecture
- Local SQLite database
- Polling/manual execution rather than full webhook-driven synchronization
- Manual variant-cost configuration
- No automatic supplier synchronization
- No automatic fulfillment/tracking synchronization
- No product-deletion reconciliation
- No multi-user authentication
- No frontend dashboard yet
- Alerts are currently persisted locally rather than delivered through email/SMS/push channels
- Profit reporting is estimated gross product profit, not full accounting net profit

These limitations are intentionally being addressed only after the V1 backend is proven stable.

---

# Roadmap

## V1 — Shopify Automation Foundation

Implemented:

- Project foundation
- Shopify authentication
- GraphQL API client
- Product retrieval
- Cursor pagination
- SQLite persistence
- Product/variant synchronization
- Price/inventory history
- Order synchronization
- New-order detection
- Product cost configuration
- Profit analysis
- Immutable financial snapshots
- Structured logging
- Persistent alerts
- Low-inventory monitoring
- Failure monitoring
- Store-health reporting
- Daily report persistence

Remaining V1 focus:

- Final integrated validation
- Documentation cleanup
- Dependency cleanup
- Automated test-suite expansion
- Final V1 GitHub release checkpoint

## V2 — Supplier Synchronization

Potential future capabilities:

- Supplier product mapping
- Supplier cost updates
- Supplier inventory synchronization
- Automated store inventory protection

## V3 — Fulfillment Automation

Potential future capabilities:

- Fulfillment workflows
- Tracking synchronization
- Order-routing logic

## V4 — AI Product & Business Analysis

Potential future capabilities:

- Product analysis
- Store-performance insights
- Automated recommendations

## V5 — Dashboard / Application Interface

Potential architecture:

```text
Python services/repositories
        ↓
FastAPI
        ↓
JSON API
        ↓
React / Next.js dashboard
```

The goal is to place a modern frontend on top of the existing backend rather than rewrite the business logic.

---

# Development Philosophy

This project is intentionally being developed one feature at a time.

Each major feature is:

1. Designed
2. Implemented
3. Tested independently
4. Integrated
5. Verified before continuing

The goal is to produce a working Shopify automation backend while understanding the Python, database, API, security, and software-engineering concepts behind every layer.
