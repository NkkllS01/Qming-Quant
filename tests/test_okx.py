import base64
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from exchanges.okx.gateway import OKXGateway
from exchanges.okx.mapper import map_funding_rate, map_instrument, map_okx_candles
from exchanges.okx.signer import sign_okx_request


def test_sign_okx_request_matches_hmac_sha256_base64() -> None:
    timestamp = "2020-12-08T09:08:57.715Z"
    method = "GET"
    request_path = "/api/v5/account/balance?ccy=BTC"
    body = ""
    secret = "22582BD0CFF14C41EDBF1AB98506286D"

    expected = base64.b64encode(
        hmac.new(
            secret.encode(),
            f"{timestamp}{method}{request_path}{body}".encode(),
            hashlib.sha256,
        ).digest()
    ).decode()

    assert sign_okx_request(timestamp, method, request_path, body, secret) == expected


def test_map_okx_candles_filters_unconfirmed_rows() -> None:
    rows = [
        ["1717200000000", "1", "2", "0.5", "1.5", "10", "1", "10", "1"],
        ["1717200060000", "2", "3", "1.5", "2.5", "20", "2", "20", "0"],
    ]

    candles = map_okx_candles("BTC-USDT-SWAP", "1m", rows, confirmed_only=True)

    assert len(candles) == 1
    assert candles[0].confirmed is True


def test_map_instrument_keeps_contract_precision_fields() -> None:
    instrument = map_instrument(
        {
            "instId": "BTC-USDT-SWAP",
            "instType": "SWAP",
            "baseCcy": "BTC",
            "quoteCcy": "USDT",
            "settleCcy": "USDT",
            "tickSz": "0.1",
            "lotSz": "0.01",
            "minSz": "0.01",
            "ctVal": "0.01",
            "state": "live",
        }
    )

    assert instrument.symbol == "BTC-USDT-SWAP"
    assert instrument.tick_size == Decimal("0.1")
    assert instrument.lot_size == Decimal("0.01")


def test_map_funding_rate_history_row_to_model() -> None:
    funding_rate = map_funding_rate(
        {
            "instId": "BTC-USDT-SWAP",
            "fundingRate": "0.0001",
            "realizedRate": "0.00008",
            "fundingTime": "1717200000000",
        }
    )

    assert funding_rate.symbol == "BTC-USDT-SWAP"
    assert funding_rate.funding_rate == Decimal("0.0001")
    assert funding_rate.realized_rate == Decimal("0.00008")
    assert funding_rate.funding_time.year == 2024


def test_okx_gateway_history_candles_range_paginates_until_start_is_covered() -> None:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows_by_after = {
        str(int((start + timedelta(minutes=5)).timestamp() * 1000)): [
            _okx_candle_row(start + timedelta(minutes=4), "104"),
            _okx_candle_row(start + timedelta(minutes=3), "103"),
        ],
        str(int((start + timedelta(minutes=3)).timestamp() * 1000)): [
            _okx_candle_row(start + timedelta(minutes=2), "102"),
            _okx_candle_row(start + timedelta(minutes=1), "101"),
        ],
    }
    rest = FakeRest(rows_by_after)
    gateway = OKXGateway(rest)

    candles = gateway.history_candles_range(
        "BTC-USDT-SWAP",
        "1m",
        start + timedelta(minutes=1),
        start + timedelta(minutes=5),
    )

    assert [candle.close for candle in candles] == [
        Decimal("101"),
        Decimal("102"),
        Decimal("103"),
        Decimal("104"),
    ]
    assert [call["after"] for call in rest.calls] == [
        str(int((start + timedelta(minutes=5)).timestamp() * 1000)),
        str(int((start + timedelta(minutes=3)).timestamp() * 1000)),
    ]


class FakeRest:
    def __init__(self, rows_by_after: dict[str, list[list[str]]]) -> None:
        self.rows_by_after = rows_by_after
        self.calls: list[dict] = []

    def get(self, path: str, params: dict | None = None, *, private: bool = False) -> dict:
        assert path == "/api/v5/market/history-candles"
        assert private is False
        assert params is not None
        self.calls.append(params)
        return {"data": self.rows_by_after.get(params["after"], [])}


def _okx_candle_row(timestamp: datetime, close: str) -> list[str]:
    return [
        str(int(timestamp.timestamp() * 1000)),
        close,
        close,
        close,
        close,
        "10",
        "1",
        "10",
        "1",
    ]
