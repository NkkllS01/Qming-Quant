from datetime import datetime, timezone
from decimal import Decimal

from core.models import Fill, PaperJournalEvent, Position, SimulationJournalEvent
from storage.trade_repository import TradeRepository


def test_trade_repository_persists_fills_positions_and_journal_by_run_id() -> None:
    repo = TradeRepository("sqlite:///:memory:")
    fill = Fill(
        account_id="okx_sub_main",
        bot_id="okx_perp_bot_main",
        strategy_id="btc_trend_15m",
        symbol="BTC-USDT-SWAP",
        run_id="paper-run-1",
        fill_id="paper-1",
        client_order_id="client-1",
        side="buy",
        size=Decimal("0.1"),
        price=Decimal("100"),
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    position = Position(
        account_id="okx_sub_main",
        symbol="BTC-USDT-SWAP",
        direction="long",
        size=Decimal("0.1"),
        entry_price=Decimal("100"),
        mark_price=Decimal("101"),
    )
    event = SimulationJournalEvent(
        event_type="fill",
        symbol="BTC-USDT-SWAP",
        strategy_id="btc_trend_15m",
        message="buy 0.1 @ 100",
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    repo.save_simulation_run(
        run_id="paper-run-1",
        fills=[fill],
        positions=[position],
        journal=[event],
    )

    fills = repo.list_fills("paper-run-1")
    positions = repo.list_positions("paper-run-1")
    journal = repo.list_journal("paper-run-1")

    assert len(fills) == 1
    assert fills[0].client_order_id == "client-1"
    assert fills[0].price == Decimal("100.000000000000000000")
    assert len(positions) == 1
    assert positions[0].symbol == "BTC-USDT-SWAP"
    assert positions[0].size == Decimal("0.100000000000000000")
    assert len(journal) == 1
    assert journal[0].event_type == "fill"


def test_trade_repository_replaces_existing_paper_run_snapshot() -> None:
    repo = TradeRepository("sqlite:///:memory:")
    fill = Fill(
        account_id="okx_sub_main",
        bot_id="okx_perp_bot_main",
        strategy_id="btc_trend_15m",
        symbol="BTC-USDT-SWAP",
        run_id="paper-run-1",
        fill_id="paper-1",
        client_order_id="client-1",
        side="buy",
        size=Decimal("0.1"),
        price=Decimal("100"),
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    position = Position(
        account_id="okx_sub_main",
        symbol="BTC-USDT-SWAP",
        direction="long",
        size=Decimal("0.1"),
        entry_price=Decimal("100"),
        mark_price=Decimal("101"),
    )
    event = PaperJournalEvent(
        event_type="fill",
        symbol="BTC-USDT-SWAP",
        strategy_id="btc_trend_15m",
        message="buy 0.1 @ 100",
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    repo.save_paper_run(
        run_id="paper-run-1",
        fills=[fill],
        positions=[position],
        journal=[event],
    )

    repo.save_paper_run(
        run_id="paper-run-1",
        fills=[],
        positions=[],
        journal=[],
    )

    assert repo.list_fills("paper-run-1") == []
    assert repo.list_positions("paper-run-1") == []
    assert repo.list_journal("paper-run-1") == []


def test_trade_repository_paper_save_alias_remains_compatible() -> None:
    repo = TradeRepository("sqlite:///:memory:")
    event = PaperJournalEvent(
        event_type="fill",
        symbol="BTC-USDT-SWAP",
        strategy_id="btc_trend_15m",
        message="buy 0.1 @ 100",
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    repo.save_paper_run(
        run_id="paper-run-1",
        fills=[],
        positions=[],
        journal=[event],
    )

    assert repo.list_journal("paper-run-1")[0].event_type == "fill"
