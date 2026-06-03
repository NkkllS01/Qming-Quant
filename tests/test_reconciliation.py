from decimal import Decimal

from core.models import Position
from execution.reconciliation import Reconciliation, ReconciliationIssue, ReconciliationReport


def _position(symbol: str, direction: str, size: str) -> Position:
    return Position(
        account_id="okx_sub_main",
        symbol=symbol,
        direction=direction,
        size=Decimal(size),
        entry_price=Decimal("100"),
        mark_price=Decimal("101"),
    )


def test_compare_order_ids_reports_missing_ids() -> None:
    result = Reconciliation().compare_order_ids(
        local_ids={"local-only", "both"},
        exchange_ids={"exchange-only", "both"},
    )

    assert result == {
        "missing_on_exchange": {"local-only"},
        "missing_locally": {"exchange-only"},
    }


def test_compare_positions_returns_clean_report_for_matching_positions() -> None:
    report = Reconciliation().compare_positions(
        local_positions=[_position("BTC-USDT-SWAP", "long", "0.10")],
        exchange_positions=[{"symbol": "BTC-USDT-SWAP", "direction": "long", "size": "0.100"}],
    )

    assert isinstance(report, ReconciliationReport)
    assert report.is_clean is True
    assert report.issues == []


def test_compare_positions_reports_positions_missing_on_exchange_and_locally() -> None:
    report = Reconciliation().compare_positions(
        local_positions=[_position("BTC-USDT-SWAP", "long", "0.1")],
        exchange_positions=[{"symbol": "ETH-USDT-SWAP", "direction": "short", "size": "1"}],
    )

    assert report.is_clean is False
    assert report.issues == [
        ReconciliationIssue(
            kind="missing_on_exchange",
            symbol="BTC-USDT-SWAP",
            local_value="present",
            exchange_value=None,
            message="Local position BTC-USDT-SWAP is missing on exchange snapshot.",
        ),
        ReconciliationIssue(
            kind="missing_locally",
            symbol="ETH-USDT-SWAP",
            local_value=None,
            exchange_value="present",
            message="Exchange position ETH-USDT-SWAP is missing locally.",
        ),
    ]


def test_compare_positions_reports_size_and_direction_mismatches() -> None:
    report = Reconciliation().compare_positions(
        local_positions=[_position("BTC-USDT-SWAP", "long", "0.1")],
        exchange_positions=[{"symbol": "BTC-USDT-SWAP", "direction": "short", "size": "0.2"}],
    )

    assert report.issues == [
        ReconciliationIssue(
            kind="size_mismatch",
            symbol="BTC-USDT-SWAP",
            local_value=Decimal("0.1"),
            exchange_value=Decimal("0.2"),
            message="Position size mismatch for BTC-USDT-SWAP: local=0.1 exchange=0.2.",
        ),
        ReconciliationIssue(
            kind="direction_mismatch",
            symbol="BTC-USDT-SWAP",
            local_value="long",
            exchange_value="short",
            message="Position direction mismatch for BTC-USDT-SWAP: local=long exchange=short.",
        ),
    ]


def test_compare_positions_reports_duplicate_local_positions() -> None:
    report = Reconciliation().compare_positions(
        local_positions=[
            _position("BTC-USDT-SWAP", "long", "0.1"),
            _position("BTC-USDT-SWAP", "long", "0.2"),
        ],
        exchange_positions=[{"symbol": "BTC-USDT-SWAP", "direction": "long", "size": "0.1"}],
    )

    assert report.issues == [
        ReconciliationIssue(
            kind="duplicate_local_position",
            symbol="BTC-USDT-SWAP",
            local_value="duplicate",
            exchange_value=None,
            message="Local position BTC-USDT-SWAP appears more than once.",
        )
    ]


def test_compare_positions_reports_duplicate_exchange_positions() -> None:
    report = Reconciliation().compare_positions(
        local_positions=[_position("BTC-USDT-SWAP", "long", "0.1")],
        exchange_positions=[
            {"symbol": "BTC-USDT-SWAP", "direction": "long", "size": "0.1"},
            {"symbol": "BTC-USDT-SWAP", "direction": "long", "size": "0.2"},
        ],
    )

    assert report.issues == [
        ReconciliationIssue(
            kind="duplicate_exchange_position",
            symbol="BTC-USDT-SWAP",
            local_value=None,
            exchange_value="duplicate",
            message="Exchange position BTC-USDT-SWAP appears more than once.",
        )
    ]


def test_compare_positions_reports_malformed_exchange_positions_without_raising() -> None:
    malformed_positions = [
        {"direction": "long", "size": "0.1"},
        {"symbol": "", "direction": "long", "size": "0.1"},
        {"symbol": None, "direction": "long", "size": "0.1"},
        {"symbol": "ETH-USDT-SWAP", "size": "0.1"},
        {"symbol": "ETH-USDT-SWAP", "direction": "", "size": "0.1"},
        {"symbol": "ETH-USDT-SWAP", "direction": None, "size": "0.1"},
        {"symbol": "SOL-USDT-SWAP", "direction": "long"},
        {"symbol": "SOL-USDT-SWAP", "direction": "long", "size": ""},
        {"symbol": "SOL-USDT-SWAP", "direction": "long", "size": None},
        {"symbol": "SOL-USDT-SWAP", "direction": "long", "size": "not-decimal"},
    ]

    report = Reconciliation().compare_positions(
        local_positions=[],
        exchange_positions=malformed_positions,
    )

    assert [issue.kind for issue in report.issues] == ["malformed_exchange_position"] * len(malformed_positions)
    assert report.issues[0] == ReconciliationIssue(
        kind="malformed_exchange_position",
        symbol="<unknown>",
        local_value=None,
        exchange_value=malformed_positions[0],
        message="Exchange position row is malformed: missing symbol.",
    )
    assert report.issues[-1] == ReconciliationIssue(
        kind="malformed_exchange_position",
        symbol="SOL-USDT-SWAP",
        local_value=None,
        exchange_value=malformed_positions[-1],
        message="Exchange position SOL-USDT-SWAP has malformed size.",
    )
