from app.main import build_parser


def test_operator_commands_parse_with_handlers() -> None:
    parser = build_parser()

    for argv in [["operator-status"], ["emergency-pause"], ["emergency-resume"], ["run-log-tail"]]:
        args = parser.parse_args(argv)
        assert callable(args.handler)
