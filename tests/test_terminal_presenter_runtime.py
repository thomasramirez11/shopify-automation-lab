from presentation.terminal_presenter import (
    show_application_banner,
    show_daily_report_failure,
    show_daily_report_success,
    show_order_database_verification,
    show_order_database_verification_success,
    show_order_persistence_started,
    show_order_persistence_success,
    show_product_database_verification,
    show_product_database_verification_success,
    show_product_persistence_started,
    show_product_persistence_success,
    show_recent_sync_runs,
    show_shopify_authentication_started,
    show_shopify_authentication_success,
    show_sync_audit,
    show_sync_failure,
    show_sync_run_started,
)


def test_application_banner(
    capsys,
):
    show_application_banner()

    assert (
        capsys.readouterr().out
        == (
            "Shopify Automation Lab\n"
            "----------------------\n"
        )
    )


def test_sync_run_started(
    capsys,
):
    show_sync_run_started(61)

    assert (
        capsys.readouterr().out
        == "Sync run started: #61\n\n"
    )


def test_authentication_output(
    capsys,
):
    show_shopify_authentication_started()
    show_shopify_authentication_success()

    assert (
        capsys.readouterr().out
        == (
            "Authenticating with Shopify...\n"
            "Authentication successful!\n\n"
        )
    )


def test_persistence_status_output(
    capsys,
):
    show_product_persistence_started()
    show_product_persistence_success()
    show_order_persistence_started()
    show_order_persistence_success()

    output = capsys.readouterr().out

    assert "Saving products to SQLite...\n" in output
    assert "Products saved successfully!\n\n" in output
    assert "Saving orders to SQLite...\n" in output
    assert "Orders saved successfully!\n\n" in output


def test_product_database_verification_output(
    capsys,
):
    show_product_database_verification(
        shopify_products=3,
        database_products=3,
        shopify_variants=4,
        database_variants=4,
    )

    show_product_database_verification_success()

    output = capsys.readouterr().out

    assert "Shopify products: 3\n" in output
    assert "Database products: 3\n" in output
    assert "Shopify variants: 4\n" in output
    assert "Database variants: 4\n" in output
    assert (
        "Shopify -> SQLite product "
        "persistence test: SUCCESS\n"
        in output
    )


def test_order_database_verification_output(
    capsys,
):
    show_order_database_verification(
        shopify_orders=4,
        database_orders=4,
        shopify_line_items=4,
        database_line_items=4,
    )

    show_order_database_verification_success()

    output = capsys.readouterr().out

    assert "Shopify orders: 4\n" in output
    assert "Database orders: 4\n" in output
    assert "Shopify line items: 4\n" in output
    assert "Database line items: 4\n" in output
    assert (
        "Shopify -> SQLite order "
        "persistence test: SUCCESS\n"
        in output
    )


def test_sync_audit_output(
    capsys,
):
    show_sync_audit(
        {
            "id": 60,
            "started_at": "start",
            "completed_at": "end",
            "status": "success",
            "products_seen": 3,
            "variants_seen": 4,
        }
    )

    output = capsys.readouterr().out

    assert "Run ID: 60\n" in output
    assert "Started: start\n" in output
    assert "Completed: end\n" in output
    assert "Status: success\n" in output
    assert "Products seen: 3\n" in output
    assert "Variants seen: 4\n" in output


def test_recent_sync_runs_output(
    capsys,
):
    show_recent_sync_runs(
        [
            {
                "id": 60,
                "status": "success",
                "products_seen": 3,
                "variants_seen": 4,
            }
        ]
    )

    output = capsys.readouterr().out

    assert (
        "Run #60 | success | Products: 3 | Variants: 4\n"
        in output
    )


def test_daily_report_success_output(
    capsys,
):
    show_daily_report_success(
        {
            "formatted_report": "REPORT BODY",
            "report_id": 7,
        }
    )

    assert (
        capsys.readouterr().out
        == (
            "\n"
            "REPORT BODY\n"
            "\n"
            "Daily report snapshot stored: #7\n"
            "\n"
        )
    )


def test_daily_report_failure_output(
    capsys,
):
    show_daily_report_failure()

    output = capsys.readouterr().out

    assert "Daily report generation failed.\n" in output
    assert (
        "Synchronization remains successful; "
        "review the application log for details.\n"
        in output
    )


def test_sync_failure_with_alert(
    capsys,
):
    show_sync_failure(
        sync_run_id=46,
        error_message="RuntimeError: test",
        sync_run_marked_failed=True,
        failure_alert={
            "id": 11,
            "alert_type": "sync_failure",
            "severity": "error",
            "status": "open",
        },
    )

    output = capsys.readouterr().out

    assert "Run ID: 46\n" in output
    assert "Status: failed\n" in output
    assert "Error: RuntimeError: test\n" in output
    assert "Audit marked failed: yes\n" in output
    assert "Synchronization failure alert\n" in output
    assert "Alert ID: 11\n" in output
    assert "Type: sync_failure\n" in output
    assert "Severity: error\n" in output


def test_sync_failure_before_audit_id(
    capsys,
):
    show_sync_failure(
        sync_run_id=None,
        error_message="RuntimeError: early",
        sync_run_marked_failed=False,
        failure_alert=None,
    )

    output = capsys.readouterr().out

    assert "Run ID: N/A\n" in output
    assert "Status: failed\n" in output
    assert "Audit marked failed:" not in output
    assert "Synchronization failure alert" not in output
