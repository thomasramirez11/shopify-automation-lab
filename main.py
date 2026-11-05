import logging
import os

import application.bootstrap as bootstrap_module
from application.bootstrap import (
    build_core_dependencies,
    build_failure_safe_dependencies,
    build_shopify_client,
)
from application.failure_handler import (
    handle_synchronization_failure,
)
from application.reporting_workflow import (
    run_reporting_workflow,
)
from application.sync_workflow import (
    run_synchronization_workflow,
)
from config.logging_config import setup_logging
from presentation.terminal_presenter import (
    show_application_banner,
    show_shopify_authentication_started,
    show_shopify_authentication_success,
    show_sync_run_started,
)
from presentation.terminal_workflow_presenter import (
    TerminalWorkflowPresenter,
)


logger = logging.getLogger(__name__)


# Compatibility injection points for orchestration tests.
#
# main.py no longer constructs these classes directly. They are exposed
# here so the existing failure-orchestration tests can monkeypatch the
# same public seam they used before Stage 8.8B.2. main() passes the
# patched factories into application.bootstrap, preserving the new
# composition-root architecture without weakening test isolation.
SyncRunRepository = bootstrap_module.SyncRunRepository
AlertRepository = bootstrap_module.AlertRepository
AlertService = bootstrap_module.AlertService
ShopifyClient = bootstrap_module.ShopifyClient


def main():
    log_file = setup_logging()

    logger.info("Shopify Automation Lab synchronization starting.")

    show_application_banner()

    workflow_presenter = (
        TerminalWorkflowPresenter()
    )

    # --------------------------------------------------
    # Create failure-safe audit and alert dependencies
    # --------------------------------------------------

    failure_dependencies = (
        build_failure_safe_dependencies(
            sync_run_repository_factory=(
                SyncRunRepository
            ),
            alert_repository_factory=(
                AlertRepository
            ),
            alert_service_factory=(
                AlertService
            ),
        )
    )

    sync_run_repository = (
        failure_dependencies
        .sync_run_repository
    )

    alert_repository = (
        failure_dependencies
        .alert_repository
    )

    alert_service = (
        failure_dependencies
        .alert_service
    )

    sync_run_id = None

    try:
        # --------------------------------------------------
        # Create synchronization audit record
        # --------------------------------------------------

        sync_run_id = sync_run_repository.start_run()

        show_sync_run_started(
            sync_run_id
        )

        logger.info(
            "Synchronization run #%s started. Log file: %s",
            sync_run_id,
            log_file,
        )

        # Controlled Stage 6.8 failure hook.
        # Disabled by default and enabled only through the
        # current process environment during testing.
        if (
            os.getenv(
                "SHOPIFY_AUTOMATION_TEST_SYNC_FAILURE"
            )
            == "1"
        ):
            raise RuntimeError(
                "Intentional Stage 6.8 "
                "synchronization failure test"
            )

        # --------------------------------------------------
        # 1. Create Shopify client
        # --------------------------------------------------

        client = build_shopify_client(
            shopify_client_factory=(
                ShopifyClient
            ),
        )

        # --------------------------------------------------
        # 2. Authenticate with Shopify
        # --------------------------------------------------

        show_shopify_authentication_started()
        client.authenticate()
        show_shopify_authentication_success()

        logger.info("Shopify authentication successful.")

        # --------------------------------------------------
        # 3-5. Build authenticated application dependencies
        # --------------------------------------------------

        core_dependencies = (
            build_core_dependencies(
                client=client,
            )
        )

        product_service = (
            core_dependencies.product_service
        )

        order_service = (
            core_dependencies.order_service
        )

        product_repository = (
            core_dependencies
            .product_repository
        )

        order_repository = (
            core_dependencies
            .order_repository
        )

        profit_snapshot_repository = (
            core_dependencies
            .profit_snapshot_repository
        )

        financial_processing_service = (
            core_dependencies
            .financial_processing_service
        )

        sync_workflow_result = (
            run_synchronization_workflow(
                sync_run_id=sync_run_id,
                product_service=product_service,
                order_service=order_service,
                product_repository=(
                    product_repository
                ),
                order_repository=(
                    order_repository
                ),
                profit_snapshot_repository=(
                    profit_snapshot_repository
                ),
                financial_processing_service=(
                    financial_processing_service
                ),
                alert_repository=(
                    alert_repository
                ),
                alert_service=alert_service,
                sync_run_repository=(
                    sync_run_repository
                ),
                presenter=(
                    workflow_presenter
                ),
            )
        )

        logger.info(
            (
                "Authenticated synchronization workflow "
                "returned successfully. run_id=%s "
                "products=%s variants=%s orders=%s "
                "line_items=%s"
            ),
            sync_run_id,
            sync_workflow_result.products_seen,
            sync_workflow_result.variants_seen,
            sync_workflow_result.orders_seen,
            sync_workflow_result.line_items_seen,
        )

        # --------------------------------------------------
        # Post-success daily reporting
        # --------------------------------------------------
        #
        # Reporting is isolated inside its own application
        # workflow. A reporting failure cannot retroactively
        # turn this successful synchronization into a failure.
        # --------------------------------------------------

        run_reporting_workflow(
            sync_run_id=sync_run_id,
            product_repository=(
                product_repository
            ),
            order_repository=(
                order_repository
            ),
            alert_repository=(
                alert_repository
            ),
            sync_run_repository=(
                sync_run_repository
            ),
            profit_snapshot_repository=(
                profit_snapshot_repository
            ),
            presenter=(
                workflow_presenter
            ),
        )

    except Exception as exc:
        # --------------------------------------------------
        # Failure isolation + synchronization alerting
        # --------------------------------------------------
        #
        # Log the ORIGINAL traceback before any secondary
        # database work. The failure handler is deliberately
        # best-effort and must never replace this exception.
        # --------------------------------------------------

        logger.exception(
            "Synchronization run %s failed.",
            (
                f"#{sync_run_id}"
                if sync_run_id is not None
                else "before an audit ID was created"
            ),
        )

        handle_synchronization_failure(
            error=exc,
            sync_run_id=sync_run_id,
            sync_run_repository=(
                sync_run_repository
            ),
            alert_service=alert_service,
            presenter=(
                workflow_presenter
            ),
        )

        # Re-raise the ORIGINAL exception with its traceback.
        raise


if __name__ == "__main__":
    main()