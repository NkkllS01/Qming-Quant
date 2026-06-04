import scripts.config_check as config_check


OKX_ENV_NAMES = ("OKX_API_KEY", "OKX_SECRET_KEY", "OKX_PASSPHRASE")


def test_config_check_allows_missing_credentials(monkeypatch) -> None:
    for name in OKX_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)

    output = config_check._run_check()

    assert output.startswith("PASS config check")
    assert "okx_credentials=missing" in output
    assert "database=configured" in output


def test_config_check_can_require_credentials(monkeypatch) -> None:
    for name in OKX_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)

    try:
        config_check._run_check(require_okx_credentials=True)
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected missing OKX credentials to fail")

    assert "OKX_API_KEY" in message
    assert "OKX_SECRET_KEY" in message
    assert "OKX_PASSPHRASE" in message


def test_config_check_does_not_print_secrets(monkeypatch) -> None:
    monkeypatch.setenv("OKX_API_KEY", "test-api-key")
    monkeypatch.setenv("OKX_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("OKX_PASSPHRASE", "test-passphrase")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@localhost/qiming")

    output = config_check._run_check(require_okx_credentials=True)

    assert "okx_credentials=present" in output
    assert "test-api-key" not in output
    assert "test-secret-key" not in output
    assert "test-passphrase" not in output
    assert "password" not in output
