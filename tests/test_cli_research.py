from app.main import build_parser


def test_research_commands_parse_with_handlers() -> None:
    parser = build_parser()

    for argv in [["backtest"], ["sim-run"]]:
        args = parser.parse_args(argv)
        assert callable(args.handler)
