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
