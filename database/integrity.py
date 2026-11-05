import logging

from database.connection import get_db_connection


logger = logging.getLogger(__name__)


class DatabaseIntegrityError(RuntimeError):
    """
    Raised when existing database data violates an
    integrity rule required by the hardening layer.
    """


SYNC_RUN_INTEGRITY_SQL = """
CREATE TRIGGER IF NOT EXISTS
trg_sync_runs_terminal_immutable

BEFORE UPDATE ON sync_runs

WHEN OLD.status IN (
    'success',
    'failed'
)

BEGIN
    SELECT RAISE(
        ABORT,
        'terminal synchronization runs are immutable'
    );
END;


CREATE TRIGGER IF NOT EXISTS
trg_sync_runs_counts_insert

BEFORE INSERT ON sync_runs

WHEN
    NEW.products_seen IS NULL
    OR TYPEOF(NEW.products_seen) != 'integer'
    OR NEW.products_seen < 0
    OR NEW.variants_seen IS NULL
    OR TYPEOF(NEW.variants_seen) != 'integer'
    OR NEW.variants_seen < 0

BEGIN
    SELECT RAISE(
        ABORT,
        'synchronization counts must be non-negative integers'
    );
END;


CREATE TRIGGER IF NOT EXISTS
trg_sync_runs_counts_update

BEFORE UPDATE ON sync_runs

WHEN
    NEW.products_seen IS NULL
    OR TYPEOF(NEW.products_seen) != 'integer'
    OR NEW.products_seen < 0
    OR NEW.variants_seen IS NULL
    OR TYPEOF(NEW.variants_seen) != 'integer'
    OR NEW.variants_seen < 0

BEGIN
    SELECT RAISE(
        ABORT,
        'synchronization counts must be non-negative integers'
    );
END;
"""


ALERT_INTEGRITY_SQL = """
CREATE TRIGGER IF NOT EXISTS
trg_alerts_state_consistency_insert

BEFORE INSERT ON alerts

WHEN
    (
        NEW.status = 'open'
        AND NEW.resolved_at IS NOT NULL
    )
    OR
    (
        NEW.status = 'resolved'
        AND (
            NEW.resolved_at IS NULL
            OR TRIM(NEW.resolved_at) = ''
        )
    )

BEGIN
    SELECT RAISE(
        ABORT,
        'alert status and resolved_at are inconsistent'
    );
END;


CREATE TRIGGER IF NOT EXISTS
trg_alerts_state_consistency_update

BEFORE UPDATE ON alerts

WHEN
    (
        NEW.status = 'open'
        AND NEW.resolved_at IS NOT NULL
    )
    OR
    (
        NEW.status = 'resolved'
        AND (
            NEW.resolved_at IS NULL
            OR TRIM(NEW.resolved_at) = ''
        )
    )

BEGIN
    SELECT RAISE(
        ABORT,
        'alert status and resolved_at are inconsistent'
    );
END;
"""


VARIANT_COST_INTEGRITY_SQL = """
CREATE TRIGGER IF NOT EXISTS
trg_variant_costs_value_insert

BEFORE INSERT ON variant_costs

WHEN
    NEW.unit_cost IS NULL
    OR TRIM(NEW.unit_cost) = ''
    OR TRIM(NEW.unit_cost) NOT GLOB '*[0-9]*'
    OR TRIM(NEW.unit_cost) GLOB '*[^0-9.]*'
    OR (
        LENGTH(TRIM(NEW.unit_cost))
        - LENGTH(
            REPLACE(
                TRIM(NEW.unit_cost),
                '.',
                ''
            )
        )
    ) > 1
    OR NEW.currency_code IS NULL
    OR TRIM(NEW.currency_code) = ''

BEGIN
    SELECT RAISE(
        ABORT,
        'variant cost must use a non-negative decimal and currency'
    );
END;


CREATE TRIGGER IF NOT EXISTS
trg_variant_costs_value_update

BEFORE UPDATE ON variant_costs

WHEN
    NEW.unit_cost IS NULL
    OR TRIM(NEW.unit_cost) = ''
    OR TRIM(NEW.unit_cost) NOT GLOB '*[0-9]*'
    OR TRIM(NEW.unit_cost) GLOB '*[^0-9.]*'
    OR (
        LENGTH(TRIM(NEW.unit_cost))
        - LENGTH(
            REPLACE(
                TRIM(NEW.unit_cost),
                '.',
                ''
            )
        )
    ) > 1
    OR NEW.currency_code IS NULL
    OR TRIM(NEW.currency_code) = ''

BEGIN
    SELECT RAISE(
        ABORT,
        'variant cost must use a non-negative decimal and currency'
    );
END;
"""


PROFIT_SNAPSHOT_IMMUTABILITY_SQL = """
CREATE TRIGGER IF NOT EXISTS
trg_profit_snapshots_immutable_update

BEFORE UPDATE ON order_line_item_profit_snapshots

BEGIN
    SELECT RAISE(
        ABORT,
        'historical profit snapshots are immutable'
    );
END;


CREATE TRIGGER IF NOT EXISTS
trg_profit_snapshots_immutable_delete

BEFORE DELETE ON order_line_item_profit_snapshots

BEGIN
    SELECT RAISE(
        ABORT,
        'historical profit snapshots are immutable'
    );
END;
"""


DAILY_REPORT_IMMUTABILITY_SQL = """
CREATE TRIGGER IF NOT EXISTS
trg_daily_reports_immutable_update

BEFORE UPDATE ON daily_reports

BEGIN
    SELECT RAISE(
        ABORT,
        'historical daily reports are immutable'
    );
END;


CREATE TRIGGER IF NOT EXISTS
trg_daily_reports_immutable_delete

BEFORE DELETE ON daily_reports

BEGIN
    SELECT RAISE(
        ABORT,
        'historical daily reports are immutable'
    );
END;
"""


VARIANT_CHANGE_IMMUTABILITY_SQL = """
CREATE TRIGGER IF NOT EXISTS
trg_variant_changes_immutable_update

BEFORE UPDATE ON variant_changes

BEGIN
    SELECT RAISE(
        ABORT,
        'historical variant changes are immutable'
    );
END;


CREATE TRIGGER IF NOT EXISTS
trg_variant_changes_immutable_delete

BEFORE DELETE ON variant_changes

BEGIN
    SELECT RAISE(
        ABORT,
        'historical variant changes are immutable'
    );
END;
"""


def apply_database_integrity_hardening() -> None:
    """
    Apply idempotent SQLite integrity protections.

    Each protection is installed only when its target table
    exists. This keeps the hardening module compatible with
    partial test databases and staged schema creation.

    Protections currently include:

    1. Completed synchronization runs are immutable.
    2. Synchronization counters are non-negative integers.
    3. Alert status and resolved_at must agree.
    4. Variant costs use non-negative plain-decimal text
       and a non-blank currency code.
    5. Historical profit snapshots cannot be updated
       or deleted after creation.
    6. Historical daily reports cannot be updated or
       deleted after creation.
    7. Historical variant-change records cannot be updated
       or deleted after creation.
    """

    with get_db_connection() as connection:
        if _table_exists(
            connection,
            "alerts",
        ):
            alert_violation_count = (
                _count_alert_state_violations(
                    connection
                )
            )

            if alert_violation_count > 0:
                raise DatabaseIntegrityError(
                    "Cannot apply alert-state hardening: "
                    f"{alert_violation_count} existing alert row(s) "
                    "have inconsistent status/resolved_at values."
                )

        if _table_exists(
            connection,
            "sync_runs",
        ):
            sync_count_violation_count = (
                _count_sync_run_count_violations(
                    connection
                )
            )

            if sync_count_violation_count > 0:
                raise DatabaseIntegrityError(
                    "Cannot apply sync-count hardening: "
                    f"{sync_count_violation_count} existing "
                    "sync run row(s) contain invalid counters."
                )

        if _table_exists(
            connection,
            "variant_costs",
        ):
            cost_violation_count = (
                _count_variant_cost_violations(
                    connection
                )
            )

            if cost_violation_count > 0:
                raise DatabaseIntegrityError(
                    "Cannot apply variant-cost hardening: "
                    f"{cost_violation_count} existing variant "
                    "cost row(s) contain invalid values."
                )

        if _table_exists(
            connection,
            "sync_runs",
        ):
            connection.executescript(
                SYNC_RUN_INTEGRITY_SQL
            )

        if _table_exists(
            connection,
            "alerts",
        ):
            connection.executescript(
                ALERT_INTEGRITY_SQL
            )

        if _table_exists(
            connection,
            "variant_costs",
        ):
            connection.executescript(
                VARIANT_COST_INTEGRITY_SQL
            )

        if _table_exists(
            connection,
            "order_line_item_profit_snapshots",
        ):
            connection.executescript(
                PROFIT_SNAPSHOT_IMMUTABILITY_SQL
            )

        if _table_exists(
            connection,
            "daily_reports",
        ):
            connection.executescript(
                DAILY_REPORT_IMMUTABILITY_SQL
            )

        if _table_exists(
            connection,
            "variant_changes",
        ):
            connection.executescript(
                VARIANT_CHANGE_IMMUTABILITY_SQL
            )

    logger.info(
        "Database integrity hardening applied."
    )


def get_alert_state_violation_count() -> int:
    """
    Return the number of existing alert rows whose
    status/resolved_at values are inconsistent.

    Returns zero when the alerts table does not yet exist.
    """

    with get_db_connection() as connection:
        if not _table_exists(
            connection,
            "alerts",
        ):
            return 0

        return _count_alert_state_violations(
            connection
        )


def get_sync_run_count_violation_count() -> int:
    """
    Return the number of synchronization rows containing
    invalid product/variant counters.

    Returns zero when sync_runs does not yet exist.
    """

    with get_db_connection() as connection:
        if not _table_exists(
            connection,
            "sync_runs",
        ):
            return 0

        return _count_sync_run_count_violations(
            connection
        )


def get_variant_cost_violation_count() -> int:
    """
    Return the number of variant-cost rows containing
    invalid cost/currency values.

    Returns zero when variant_costs does not yet exist.
    """

    with get_db_connection() as connection:
        if not _table_exists(
            connection,
            "variant_costs",
        ):
            return 0

        return _count_variant_cost_violations(
            connection
        )


def get_integrity_trigger_names() -> list[str]:
    """
    Return user-created SQLite triggers.

    Useful for verification and future diagnostics.
    """

    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'trigger'
            ORDER BY name;
            """
        ).fetchall()

        return [
            row["name"]
            for row in rows
        ]


def _table_exists(
    connection,
    table_name: str,
) -> bool:
    """
    Return True when one SQLite table exists.
    """

    row = connection.execute(
        """
        SELECT 1

        FROM sqlite_master

        WHERE type = 'table'
          AND name = ?

        LIMIT 1;
        """,
        (table_name,),
    ).fetchone()

    return row is not None


def _count_alert_state_violations(
    connection,
) -> int:
    """
    Count impossible alert lifecycle states.

    Valid states are:

        open     -> resolved_at IS NULL
        resolved -> resolved_at contains a timestamp
    """

    row = connection.execute(
        """
        SELECT COUNT(*) AS count

        FROM alerts

        WHERE
            (
                status = 'open'
                AND resolved_at IS NOT NULL
            )
            OR
            (
                status = 'resolved'
                AND (
                    resolved_at IS NULL
                    OR TRIM(resolved_at) = ''
                )
            );
        """
    ).fetchone()

    return int(row["count"])


def _count_sync_run_count_violations(
    connection,
) -> int:
    """
    Count synchronization rows with invalid counters.
    """

    row = connection.execute(
        """
        SELECT COUNT(*) AS count

        FROM sync_runs

        WHERE
            products_seen IS NULL
            OR TYPEOF(products_seen) != 'integer'
            OR products_seen < 0
            OR variants_seen IS NULL
            OR TYPEOF(variants_seen) != 'integer'
            OR variants_seen < 0;
        """
    ).fetchone()

    return int(row["count"])


def _count_variant_cost_violations(
    connection,
) -> int:
    """
    Count invalid current product-cost records.

    V1 stores exact monetary values as text so Python can
    use Decimal without SQLite floating-point conversion.

    Accepted cost text uses plain non-negative decimal form,
    for example:

        0
        0.00
        4.25
        .50
        10.

    Negative values, alphabetic values, multiple decimal
    points, blank values, and blank currency codes are
    rejected.
    """

    row = connection.execute(
        """
        SELECT COUNT(*) AS count

        FROM variant_costs

        WHERE
            unit_cost IS NULL
            OR TRIM(unit_cost) = ''
            OR TRIM(unit_cost) NOT GLOB '*[0-9]*'
            OR TRIM(unit_cost) GLOB '*[^0-9.]*'
            OR (
                LENGTH(TRIM(unit_cost))
                - LENGTH(
                    REPLACE(
                        TRIM(unit_cost),
                        '.',
                        ''
                    )
                )
            ) > 1
            OR currency_code IS NULL
            OR TRIM(currency_code) = '';
        """
    ).fetchone()

    return int(row["count"])


if __name__ == "__main__":
    print(
        "Existing alert-state violations:",
        get_alert_state_violation_count(),
    )

    print(
        "Existing sync-count violations:",
        get_sync_run_count_violation_count(),
    )

    print(
        "Existing variant-cost violations:",
        get_variant_cost_violation_count(),
    )

    apply_database_integrity_hardening()

    print(
        "Database integrity hardening "
        "applied successfully."
    )

    print("Triggers:")

    for trigger_name in (
        get_integrity_trigger_names()
    ):
        print(
            f"  - {trigger_name}"
        )
