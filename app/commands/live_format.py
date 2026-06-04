from __future__ import annotations


def live_sync_output(
    *,
    mode: str,
    symbols: list[str],
    public_messages: int,
    private_messages: int,
    tickers_count: int,
    balances_count: int,
    positions_count: int,
    orders_count: int,
    fills_count: int,
    fills_channel: bool,
    persisted: bool,
    trading_enabled: bool,
) -> str:
    return (
        f"live_sync mode={mode} symbols={','.join(symbols)} "
        f"public_messages={public_messages} "
        f"private_messages={private_messages} "
        f"tickers={tickers_count} "
        f"balances={balances_count} "
        f"positions={positions_count} "
        f"orders={orders_count} "
        f"fills={fills_count} "
        f"fills_channel={str(fills_channel).lower()} "
        f"persisted={str(persisted).lower()} "
        f"trading_enabled={str(trading_enabled).lower()}"
    )


def trading_gate_output(
    *,
    status: str,
    reason: str,
    manual_paused: bool,
    equity_risk: str,
    market_data: str,
    position_issues: int,
    missing_orders_on_exchange: int,
    missing_orders_locally: int,
    trading_allowed: bool,
) -> str:
    return (
        f"trading_gate status={status} reason={reason} "
        f"manual_paused={str(manual_paused).lower()} "
        f"equity_risk={equity_risk} "
        f"market_data={market_data} "
        f"position_issues={position_issues} "
        f"missing_orders_on_exchange={missing_orders_on_exchange} "
        f"missing_orders_locally={missing_orders_locally} "
        f"trading_allowed={str(trading_allowed).lower()}"
    )
