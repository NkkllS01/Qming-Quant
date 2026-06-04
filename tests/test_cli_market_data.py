from app.main import build_parser


def test_market_data_commands_parse_with_handlers() -> None:
    parser = build_parser()
    commands = [
        ["instruments"],
        ["sync-instruments"],
        ["sync-funding-rates", "--symbol", "BTC-USDT-SWAP"],
        ["sync-mark-prices"],
        ["sync-index-prices"],
        ["sync-candles", "--symbol", "BTC-USDT-SWAP"],
        ["sync-candles-range", "--symbol", "BTC-USDT-SWAP", "--start", "2024-01-01T00:00:00Z", "--end", "2024-01-01T01:00:00Z"],
        ["candle-state", "--symbol", "BTC-USDT-SWAP"],
        ["repair-missing", "--symbol", "BTC-USDT-SWAP"],
        ["aggregate-candles", "--symbol", "BTC-USDT-SWAP"],
    ]

    for argv in commands:
        args = parser.parse_args(argv)
        assert callable(args.handler)
