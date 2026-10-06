# Shopify Automation Lab

A modular Python automation project that connects to the Shopify Admin GraphQL API, retrieves store data, persists it locally with SQLite, tracks product changes, and records synchronization health.

This project is being built incrementally as a learning-focused backend automation system, with an emphasis on clean architecture, security, reliability, and future extensibility.

---

## Project Goals

Shopify Automation Lab is designed to explore how Python can be used to automate Shopify store operations.

The current V1 focuses on building a reliable backend foundation before adding more advanced automation.

Current goals include:

- Connect Python securely to Shopify
- Authenticate using Shopify client credentials
- Retrieve Shopify products and variants
- Handle GraphQL cursor pagination
- Store Shopify data locally
- Synchronize repeated API requests safely
- Track price and inventory changes
- Record synchronization success and failure
- Build a modular architecture that can expand later

Future versions may include:

- Supplier synchronization
- Inventory automation
- Order monitoring
- Fulfillment automation
- Profit and margin analysis
- Alerts
- Daily reports
- AI-assisted product analysis
- Dashboards
- Shopify app / SaaS architecture

---

# Current V1 Status

## Stage 0 — Project Foundation

Completed:

- Python virtual environment
- Project structure
- `.env` configuration
- Git repository
- Secure `.gitignore`

## Stage 1 — Shopify Connection

Completed:

- Shopify client-credentials authentication
- Reusable `ShopifyClient`
- Shopify Admin GraphQL API connection
- Environment-based credentials

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

## Stage 3 — SQLite Persistence

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
- Historical change tracking
- Synchronization run auditing
- Successful-run tracking
- Failed-run tracking
- Error persistence
- Recent synchronization history
- Data-integrity verification

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
      |
      v
ProductService
      |
      v
ProductRepository
      |
      +------> products
      |
      +------> variants
      |
      +------> variant_changes
                    |
                    v
                  SQLite


SyncRunRepository
      |
      +------> sync_runs

Project Structure
shopify-automation-lab/
|
|-- config/
|   |-- settings.py
|
|-- database/
|   |-- __init__.py
|   |-- connection.py
|   |-- schema.py
|
|-- repositories/
|   |-- __init__.py
|   |-- product_repository.py
|   |-- sync_run_repository.py
|
|-- services/
|   |-- __init__.py
|   |-- product_service.py
|
|-- shopify/
|   |-- __init__.py
|   |-- client.py
|   |
|   |-- queries/
|       |-- __init__.py
|       |-- products.py
|
|-- data/
|   |-- shopify.db
|
|-- .env
|-- .env.example
|-- .gitignore
|-- main.py
|-- README.md

The local SQLite database and .env file are intentionally excluded from Git.

Data Flow

The main synchronization flow currently works like this:

1. Start synchronization audit

2. Authenticate with Shopify

3. Retrieve products through GraphQL

4. Follow Shopify pagination cursors

5. Return product dictionaries to ProductService

6. Send products to ProductRepository

7. Read existing SQLite state

8. Detect price / inventory differences

9. Record meaningful changes

10. UPSERT the latest Shopify state

11. Verify Shopify and SQLite counts

12. Mark synchronization as successful

If an exception occurs:

13. Mark synchronization as failed

14. Save the error message

15. Re-raise the original exception
SQLite Tables
products

Stores the current product state.

Important fields include:

Shopify product ID
Product title
Last synchronization timestamp
variants

Stores the current Shopify variant state.

Important fields include:

Shopify variant ID
Parent product ID
Variant title
SKU
Price
Inventory quantity
Inventory item ID
Last synchronization timestamp
variant_changes

Stores historical price and inventory changes.

Example:

SKU: AUTO-Cap-001

price
17.50 -> 10.00

inventory_quantity
18 -> 14

inventory_quantity
14 -> 22

This allows the application to preserve previous values instead of simply overwriting them.

sync_runs

Tracks the health of each synchronization.

Example:

Run #11
Status: success
Products seen: 2
Variants seen: 3

Failed runs can also store an error message for debugging.

Important Backend Concepts Used

This project currently demonstrates:

Python
Classes
Functions
Modules
Packages
Dictionaries
Loops
Generator expressions
Context managers
yield
Exception handling
try / except
Exception propagation
Logging
Environment configuration
SQL / SQLite
CREATE TABLE
SELECT
INSERT
UPDATE
UPSERT
ON CONFLICT
JOIN
Primary keys
Foreign keys
Constraints
Indexes
Transactions
Commit / rollback
Software Architecture
API client layer
Service layer
Repository pattern
Separation of concerns
Single Responsibility Principle
Idempotent synchronization
Persistent state
Historical state
Audit trails
Observability
Security

Sensitive credentials are stored in a local .env file.

The following should never be committed to Git:

.env
.venv/
*.db
data/*.db
logs/
__pycache__/

An .env.example file may be committed as a template, but it must not contain real credentials.

Never commit:

Shopify client secrets
Shopify access tokens
Real .env files
Production database files
Environment Variables

Create a .env file based on .env.example.

Expected configuration includes variables for:

SHOPIFY_STORE_DOMAIN
SHOPIFY_CLIENT_ID
SHOPIFY_CLIENT_SECRET
SHOPIFY_API_VERSION

Real values must remain private.

Running the Project

Activate the virtual environment.

On Windows PowerShell:

.\.venv\Scripts\Activate.ps1

Initialize the SQLite schema:

python -m database.schema

Run the Shopify synchronization:

python main.py
Example Synchronization Result
Shopify products: 2
Database products: 2

Shopify variants: 3
Database variants: 3

Shopify -> SQLite persistence test: SUCCESS

Example audit:

Run #11 | success | Products: 2 | Variants: 3
Run #10 | success | Products: 2 | Variants: 3
Run #9  | success | Products: 2 | Variants: 3
Current Known Limitation

The current synchronization supports:

New products
Existing product updates
Price updates
Inventory updates
Repeated synchronization

Full deletion reconciliation has not yet been implemented.

For example, if a product is deleted from Shopify, the current application does not automatically remove or archive the corresponding SQLite record.

This behavior will be designed deliberately in a later stage.

Roadmap
V1 — Shopify Automation Foundation

Planned capabilities:

 Project setup
 Shopify authentication
 GraphQL API client
 Product retrieval
 Cursor pagination
 SQLite persistence
 Product / variant UPSERT
 Inventory change detection
 Price change detection
 Change history
 Synchronization auditing
 Additional V1 automation capabilities
 Alerts
 Logging improvements
 Daily reporting
 Final V1 testing
V2

Supplier synchronization.

V3

Fulfillment automation.

V4

AI product and business analysis.

V5

Dashboard / application interface.

Development Philosophy

This project is intentionally being developed one feature at a time.

Each major feature is:

Designed
Implemented
Tested independently
Integrated
Verified before continuing

The goal is not only to create working Shopify automation, but also to understand the Python, database, API, and software-engineering concepts behind the system.