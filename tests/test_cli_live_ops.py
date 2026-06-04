from app.main import build_parser


def test_live_ops_commands_parse_with_handlers() -> None:
    parser = build_parser()
    commands = [
        ["sync-fills"],
        ["live-sync"],
        ["live-bot-once"],
        ["live-reconcile"],
        ["trading-gate"],
        ["live-order-check", "--symbol", "BTC-USDT-SWAP", "--side", "buy", "--position-action", "open", "--size", "0.1"],
        ["prelive-readiness"],
    ]

    for argv in commands:
        args = parser.parse_args(argv)
        assert callable(args.handler)
