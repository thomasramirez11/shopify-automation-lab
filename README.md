Shopify Automation Lab
A modular Python backend automation system for Shopify that synchronizes store data through the Shopify Admin GraphQL API, persists operational state in SQLite, detects changes, tracks orders and profitability, manages alerts, generates daily reports, and records synchronization health.

The project was built incrementally as a learning-focused automation lab with an emphasis on clean architecture, security, reliability, testability, and future extensibility.
V1 Status
V1 backend foundation is feature-complete and in release-candidate hardening.

Current verified capabilities include:
- Shopify client-credentials authentication
- Shopify Admin GraphQL API integration
- Cursor-based product pagination
- Product, variant, SKU, price, and inventory synchronization
- SQLite persistence
- Price-change and inventory-change history
- Order synchronization
- New-order detection
- Variant cost tracking
- Per-line-item profitability snapshots
- Revenue, estimated gross profit, and gross-margin calculations
- Low-inventory alerts
- Missing-cost alerts
- New-order alerts
- Synchronization-failure alerts
- Alert deduplication and resolution lifecycle
- Synchronization audit history
- Database integrity hardening
- Daily operational reports
- Failure isolation and original-error preservation
- Preflight environment validation
- Automated pytest regression suite
- GitHub Actions continuous integration
The current local regression suite contains 433 passing tests at the time of this README update.
Project Goals
Shopify Automation Lab explores how Python can automate and monitor Shopify store operations while maintaining a backend architecture that can grow safely.

The V1 goal is to prove a reliable single-store automation foundation before expanding into later versions.

Possible future directions include:
- Supplier inventory and price synchronization
- Fulfillment and tracking automation
- AI-assisted product and business analysis
- Operational dashboard
- Multi-store architecture
- Shopify app / SaaS packaging
Installation / Setup
1. Requirements
Recommended development environment:
- Python 3.13+
- Git
- A Shopify development or store environment
- Shopify Admin API client credentials
- PowerShell, Terminal, or another command shell
Clone the repository:
git clone <your-repository-url>
cd shopify-automation-lab
Create a virtual environment:
Windows PowerShell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
macOS / Linux
python -m venv .venv
source .venv/bin/activate
Install runtime dependencies:
python -m pip install -r requirements.txt
Install development/testing dependencies:
python -m pip install -r requirements-dev.txt
Verify dependency consistency:
python -m pip check
Configuration
The project reads Shopify configuration from environment variables.

Copy:
.env.example
to:
.env
Then configure the required values.

Example structure:
SHOPIFY_STORE_DOMAIN=your-store.myshopify.com
SHOPIFY_CLIENT_ID=your-client-id
SHOPIFY_CLIENT_SECRET=your-client-secret
SHOPIFY_API_VERSION=2026-07
LOW_INVENTORY_THRESHOLD=5
Required values
SHOPIFY_STORE_DOMAIN
Your Shopify store domain.

Example:
example-store.myshopify.com
SHOPIFY_CLIENT_ID
Client ID for the Shopify app used by the automation.
SHOPIFY_CLIENT_SECRET
Client secret for the Shopify app.
SHOPIFY_API_VERSION
Shopify Admin API version in:
YYYY-MM
format.
LOW_INVENTORY_THRESHOLD
Non-negative integer used to determine when a variant should be considered low inventory.

Example:
5
Security
Secrets and local operational data must never be committed to Git.

The repository intentionally ignores:
.env
.venv/
__pycache__/
*.pyc
*.db
logs/
The following files are safe to commit:
.env.example
requirements.txt
requirements-dev.txt
Secret-handling principles
- Keep real Shopify credentials only in .env or an approved secret manager.
- Never place real client secrets directly in Python source code.
- Never commit .env.
- Never commit the local SQLite database.
- Never print credential values during diagnostics.
- CI uses placeholder configuration and does not authenticate against the live Shopify store.
- python main.py is intentionally not executed in CI.
To verify that .env is ignored:
git check-ignore -v .env
To verify that it is not tracked:
git ls-files .env
The second command should return no output.
Preflight
Before running the live automation, use the V1 preflight checker:
python scripts/preflight.py
The checker validates:
- Supported Python version
- Required project directories
- Required project files
- Local .env
- Required Shopify configuration
- Shopify API version format
- Inventory threshold format
- Runtime dependency declarations
- Development dependency declarations
- .gitignore security rules
A healthy result ends with:
PREFLIGHT STATUS: READY
The preflight checker does not contact Shopify and does not print secret values.
Running the Application
After configuration and preflight validation:
python main.py
The application performs the synchronization workflow, including:
1. Start synchronization audit
2. Authenticate with Shopify
3. Retrieve products
4. Retrieve orders
5. Persist product and variant state
6. Detect price and inventory changes
7. Synchronize low-inventory alerts
8. Persist orders and line items
9. Detect new orders
10. Synchronize new-order alerts
11. Process order financials
12. Create or resolve missing-cost alerts
13. Verify persisted database state
14. Mark synchronization success
15. Display synchronization audit/history
16. Generate and persist the daily report
Failures are isolated so secondary audit or alert errors do not hide the original synchronization exception.
Testing
Run the complete automated test suite:
python -m pytest -q
At the time of this README update, the project has:
433 passed
Run a focused test module:
python -m pytest tests/test_sync_workflow.py -q
Compile the project without executing it:
python -m compileall application config database presentation repositories services shopify scripts main.py tests
Run the release-readiness preflight:
python scripts/preflight.py
Run the V1 release-candidate audit:
python scripts/release_candidate_audit.py
Continuous Integration
The repository includes a GitHub Actions workflow:
.github/workflows/ci.yml
The workflow runs on pushes and pull requests to main.

GitHub Actions:
1. Checks out the repository
2. Creates a clean Python 3.13 environment
3. Installs runtime dependencies
4. Installs development dependencies
5. Runs the V1 preflight in CI mode
6. Compiles the Python project
7. Runs the complete pytest suite
CI uses placeholder Shopify configuration values only.

It intentionally does not run:
python main.py
because the CI pipeline should verify code without accessing a live Shopify store or requiring production credentials.
Architecture
V1 follows a layered, modular design.
Shopify Store
      |
      v
Shopify Admin GraphQL API
      |
      v
ShopifyClient
      |
      +---------------------+
      |                     |
      v                     v
ProductService          OrderService
      |                     |
      +----------+----------+
                 |
                 v
       Application Workflows
                 |
     +-----------+------------+
     |           |            |
     v           v            v
Products     Inventory      Orders
Workflow      Alerts       Workflow
     |                        |
     +-----------+------------+
                 |
                 v
         Financial Workflow
                 |
                 v
       Sync Completion Workflow
                 |
                 v
            Repositories
                 |
                 v
               SQLite
The top-level synchronization coordinator is:
application/sync_workflow.py
Its job is to coordinate high-level workflow phases rather than contain the implementation details of every business rule.

Major application workflow modules include:
application/
├── product_sync_workflow.py
├── inventory_alert_workflow.py
├── order_sync_workflow.py
├── financial_workflow.py
├── sync_completion_workflow.py
├── reporting_workflow.py
├── failure_handler.py
├── presentation_ports.py
└── sync_workflow.py
Project Structure
shopify-automation-lab/
│
├── .github/
│   └── workflows/
│       └── ci.yml
│
├── application/
│   ├── bootstrap.py
│   ├── failure_handler.py
│   ├── financial_workflow.py
│   ├── inventory_alert_workflow.py
│   ├── order_sync_workflow.py
│   ├── presentation_ports.py
│   ├── product_sync_workflow.py
│   ├── reporting_workflow.py
│   ├── sync_completion_workflow.py
│   └── sync_workflow.py
│
├── config/
│   └── settings.py
│
├── database/
│   ├── connection.py
│   ├── integrity.py
│   └── schema.py
│
├── presentation/
│   └── terminal_presenter.py
│
├── repositories/
│   ├── alert_repository.py
│   ├── daily_report_repository.py
│   ├── order_repository.py
│   ├── product_repository.py
│   ├── profit_snapshot_repository.py
│   └── sync_run_repository.py
│
├── scripts/
│   ├── architecture_audit.py
│   ├── main_responsibility_map.py
│   ├── preflight.py
│   ├── release_candidate_audit.py
│   └── sync_workflow_audit.py
│
├── services/
│   ├── alert_service.py
│   ├── daily_report_service.py
│   ├── order_service.py
│   ├── product_service.py
│   ├── profit_service.py
│   ├── report_formatter.py
│   └── report_service.py
│
├── shopify/
│   ├── client.py
│   └── queries/
│
├── tests/
│
├── .env.example
├── .gitignore
├── main.py
├── requirements.txt
├── requirements-dev.txt
└── README.md
SQLite Data
The local SQLite database stores operational state and history.

Important tables include:
- products
- variants
- variant_changes
- orders
- order_line_items
- variant_costs
- order_line_item_profit_snapshots
- alerts
- daily_reports
- sync_runs
Database integrity controls include foreign-key enforcement, value validation, state consistency rules, and immutability protections for historical/audit records where appropriate.

The local database is intentionally excluded from Git.
Alerts
V1 supports persistent alert workflows for:
- New orders
- Missing product/variant costs
- Low inventory
- Synchronization failures
Alerts support deduplication, occurrence counting, open/resolved state, and historical tracking.
Financial Processing
V1 can process persisted Shopify orders and calculate profitability when sufficient cost data is available.

Tracked financial information includes:
- Merchandise revenue
- Product cost
- Estimated gross profit
- Gross-margin percentage
- Per-line-item profit snapshots
When cost information is missing, the financial workflow records the incomplete state and synchronizes a missing-cost alert instead of silently producing an incorrect profit estimate.
Daily Reporting
After a successful synchronization, the reporting workflow can generate and persist a daily operational snapshot.

The report includes areas such as:
- Store health
- Orders
- Financial performance
- Inventory state
- Open alerts
- Recent store changes
- Synchronization health
Reporting is isolated from the successful synchronization transaction so a reporting failure does not retroactively convert an otherwise successful Shopify synchronization into a failed one.
Database Integrity
Database hardening is available through:
python -m database.integrity
The integrity layer protects important invariants such as:
- Valid synchronization states
- Valid alert states
- Non-negative numeric business values
- Historical snapshot immutability
- Foreign-key relationships
Release Candidate Audit
Run:
python scripts/release_candidate_audit.py
The audit evaluates:
- Preflight readiness
- Required V1 module footprint
- CI definition
- CI secret safety
- Automated test footprint
- Git cleanliness
- Tracked secret/local-data hygiene
- .env.example
- README operability
- Architecture/CI documentation
- License presence
Possible statuses:
READY
READY WITH WARNINGS
NOT READY
Current Release Warning
A repository license has not yet been selected.

This does not block local V1 validation, but a license should be chosen deliberately before public distribution or reuse by third parties.
V1 Scope Boundary
V1 is intentionally a single-store backend automation system.

The following are outside the current V1 scope:
- Supplier synchronization
- Automated fulfillment/tracking updates
- Multi-tenant store management
- Public Shopify app installation flow
- SaaS billing
- AI product research/scoring
- Web dashboard
Those capabilities belong to later versions after V1 has been fully accepted and proven on the initial store.
Development Philosophy
The project is intentionally built one verified feature at a time.

Core principles:
- Prefer small, testable modules over large scripts
- Validate configuration before live execution
- Keep secrets outside source control
- Preserve the original exception during secondary failure handling
- Treat the database as a protected consistency boundary
- Keep orchestration separate from domain implementation
- Make changes observable through tests and audit tooling
- Complete and verify V1 before expanding heavily into later versions