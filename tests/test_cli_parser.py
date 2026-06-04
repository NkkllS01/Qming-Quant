from app.main import build_parser


COMMANDS = [
    ["instruments"],
    ["sync-instruments"],
    ["sync-funding-rates", "--symbol", "BTC-USDT-SWAP"],
    ["sync-fills"],
    ["sync-mark-prices"],
    ["sync-index-prices"],
    ["sync-candles", "--symbol", "BTC-USDT-SWAP"],
    ["sync-candles-range", "--symbol", "BTC-USDT-SWAP", "--start", "2024-01-01T00:00:00Z", "--end", "2024-01-01T01:00:00Z"],
    ["candle-state", "--symbol", "BTC-USDT-SWAP"],
    ["repair-missing", "--symbol", "BTC-USDT-SWAP"],
    ["aggregate-candles", "--symbol", "BTC-USDT-SWAP"],
    ["backtest"],
    ["sim-run"],
    ["live-sync"],
    ["live-bot-once"],
    ["live-reconcile"],
    ["trading-gate"],
    ["operator-status"],
    ["live-order-check", "--symbol", "BTC-USDT-SWAP", "--side", "buy", "--position-action", "open", "--size", "0.1"],
    ["prelive-readiness"],
    ["emergency-pause"],
    ["emergency-resume"],
    ["run-log-tail"],
]


def test_public_cli_commands_register_handlers() -> None:
    parser = build_parser()

    for argv in COMMANDS:
        args = parser.parse_args(argv)

        assert callable(args.handler), f"{args.command} should register a command handler"


def test_cli_parser_rejects_removed_paper_run_alias() -> None:
    parser = build_parser()

    try:
        parser.parse_args(["paper-run", "--symbol", "BTC-USDT-SWAP", "--timeframe", "15m"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("paper-run should not be available in the clean early-stage CLI")


def test_cli_parser_supports_data_sync_and_backtest_commands() -> None:
    parser = build_parser()

    sync_args = parser.parse_args(
        ["sync-candles", "--symbol", "BTC-USDT-SWAP", "--timeframe", "1m", "--pages", "2"]
    )
    sync_range_args = parser.parse_args(
        [
            "sync-candles-range",
            "--symbol",
            "BTC-USDT-SWAP",
            "--timeframe",
            "1m",
            "--start",
            "2024-01-01T00:00:00Z",
            "--end",
            "2024-01-01T00:02:00Z",
        ]
    )
    candle_state_args = parser.parse_args(["candle-state", "--symbol", "BTC-USDT-SWAP", "--timeframe", "1m"])
    backtest_args = parser.parse_args(
        [
            "backtest",
            "--symbol",
            "ETH-USDT-SWAP",
            "--start",
            "2024-01-01T00:00:00Z",
            "--end",
            "2024-01-01T01:00:00Z",
            "--report-json",
            "reports/backtest.json",
            "--strategy",
            "ma-crossover",
        ]
    )
    aggregate_args = parser.parse_args(
        [
            "aggregate-candles",
            "--symbol",
            "BTC-USDT-SWAP",
            "--source-timeframe",
            "1m",
            "--target-timeframe",
            "15m",
        ]
    )
    sim_args = parser.parse_args(
        [
            "sim-run",
            "--symbol",
            "BTC-USDT-SWAP",
            "--timeframe",
            "15m",
            "--current-daily-loss",
            "30",
            "--current-drawdown",
            "0.08",
        ]
    )
    sync_instruments_args = parser.parse_args(["sync-instruments", "--inst-type", "SWAP"])
    sync_funding_args = parser.parse_args(
        ["sync-funding-rates", "--symbol", "BTC-USDT-SWAP", "--limit", "2"]
    )
    sync_fills_args = parser.parse_args(["sync-fills", "--symbol", "BTC-USDT-SWAP", "--limit", "10"])
    sync_mark_args = parser.parse_args(["sync-mark-prices", "--symbol", "BTC-USDT-SWAP"])
    sync_index_args = parser.parse_args(["sync-index-prices", "--quote-currency", "USDT"])
    live_sync_args = parser.parse_args(
        ["live-sync", "--symbol", "BTC-USDT-SWAP", "--max-messages", "1", "--public-only"]
    )
    live_order_check_args = parser.parse_args(
        [
            "live-order-check",
            "--symbol",
            "BTC-USDT-SWAP",
            "--side",
            "buy",
            "--position-action",
            "open",
            "--size",
            "0.1",
        ]
    )
    prelive_readiness_args = parser.parse_args(
        ["prelive-readiness", "--account-id", "okx_sub_main", "--symbol", "BTC-USDT-SWAP"]
    )
    run_log_tail_args = parser.parse_args(["run-log-tail", "--limit", "5"])
    operator_status_args = parser.parse_args(["operator-status", "--account-id", "okx_sub_main", "--skip-gate"])

    assert sync_args.command == "sync-candles"
    assert sync_args.symbol == "BTC-USDT-SWAP"
    assert sync_args.timeframe == "1m"
    assert sync_args.pages == 2
    assert sync_range_args.command == "sync-candles-range"
    assert sync_range_args.start == "2024-01-01T00:00:00Z"
    assert sync_range_args.end == "2024-01-01T00:02:00Z"
    assert candle_state_args.command == "candle-state"
    assert candle_state_args.symbol == "BTC-USDT-SWAP"
    assert backtest_args.command == "backtest"
    assert backtest_args.symbol == "ETH-USDT-SWAP"
    assert backtest_args.allow_gaps is False
    assert backtest_args.min_candles == 30
    assert backtest_args.start == "2024-01-01T00:00:00Z"
    assert backtest_args.end == "2024-01-01T01:00:00Z"
    assert backtest_args.report_json == "reports/backtest.json"
    assert backtest_args.strategy == "ma-crossover"
    assert aggregate_args.command == "aggregate-candles"
    assert aggregate_args.source_timeframe == "1m"
    assert aggregate_args.target_timeframe == "15m"
    assert sim_args.command == "sim-run"
    assert sim_args.symbol == "BTC-USDT-SWAP"
    assert sim_args.strategy == "trend"
    assert sim_args.current_daily_loss == "30"
    assert sim_args.current_drawdown == "0.08"
    assert sync_instruments_args.command == "sync-instruments"
    assert sync_instruments_args.inst_type == "SWAP"
    assert sync_funding_args.command == "sync-funding-rates"
    assert sync_funding_args.symbol == "BTC-USDT-SWAP"
    assert sync_funding_args.limit == 2
    assert sync_fills_args.command == "sync-fills"
    assert sync_fills_args.symbol == "BTC-USDT-SWAP"
    assert sync_fills_args.limit == 10
    assert sync_mark_args.command == "sync-mark-prices"
    assert sync_mark_args.inst_type == "SWAP"
    assert sync_mark_args.symbol == "BTC-USDT-SWAP"
    assert sync_index_args.command == "sync-index-prices"
    assert sync_index_args.quote_currency == "USDT"
    assert live_sync_args.command == "live-sync"
    assert live_sync_args.symbol == ["BTC-USDT-SWAP"]
    assert live_sync_args.max_messages == 1
    assert live_sync_args.public_only is True
    assert live_order_check_args.command == "live-order-check"
    assert live_order_check_args.symbol == "BTC-USDT-SWAP"
    assert prelive_readiness_args.command == "prelive-readiness"
    assert prelive_readiness_args.account_id == "okx_sub_main"
    assert prelive_readiness_args.symbol == ["BTC-USDT-SWAP"]
    assert run_log_tail_args.command == "run-log-tail"
    assert run_log_tail_args.limit == 5
    assert operator_status_args.command == "operator-status"
    assert operator_status_args.account_id == "okx_sub_main"
    assert operator_status_args.skip_gate is True
    assert operator_status_args.include_gate is False
    assert live_order_check_args.position_action == "open"
