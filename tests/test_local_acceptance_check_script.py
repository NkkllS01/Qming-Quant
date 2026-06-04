import scripts.local_acceptance_check as local_acceptance


def test_local_acceptance_check_script_runs() -> None:
    local_acceptance._run_check()


def test_local_acceptance_check_runs_checks_in_order(monkeypatch) -> None:
    calls: list[str] = []

    def make_check(name: str):
        def check() -> None:
            calls.append(name)

        return check

    monkeypatch.setattr(
        local_acceptance,
        "CHECKS",
        [
            ("first", make_check("first")),
            ("second", make_check("second")),
        ],
    )

    local_acceptance._run_check()

    assert calls == ["first", "second"]


def test_local_acceptance_check_main_exits_on_failure(monkeypatch) -> None:
    def fail() -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(local_acceptance, "CHECKS", [("fail", fail)])

    try:
        local_acceptance.main()
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("expected failing local acceptance check to exit")
