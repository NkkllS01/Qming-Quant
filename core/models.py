from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, Field


def utc_from_ms(value: str | int) -> datetime:
    return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)


class TradeLineage(BaseModel):
    account_id: str
    bot_id: str
    strategy_id: str
    symbol: str
    run_id: str


class Account(BaseModel):
    account_id: str
    exchange: str = "OKX"
    margin_currency: str = "USDT"
    margin_mode: str = "isolated"


class Bot(BaseModel):
    bot_id: str
    account_id: str
    mode: str = "simulation"


class StrategyInstance(BaseModel):
    account_id: str
    bot_id: str
    strategy_id: str
    symbol: str
    timeframe: str
    run_id: str
    status: str = "active"


class Instrument(BaseModel):
    symbol: str
    inst_type: str
    base_currency: str | None = None
    quote_currency: str | None = None
    settle_currency: str | None = None
    tick_size: Decimal
    lot_size: Decimal
    min_size: Decimal
    contract_value: Decimal | None = None
    state: str


class FundingRate(BaseModel):
    symbol: str
    funding_time: datetime
    funding_rate: Decimal
    realized_rate: Decimal | None = None


class Candle(BaseModel):
    symbol: str
    timeframe: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    confirmed: bool = True

    @classmethod
    def from_okx_row(cls, symbol: str, timeframe: str, row: list[str]) -> "Candle":
        return cls(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=utc_from_ms(row[0]),
            open=Decimal(row[1]),
            high=Decimal(row[2]),
            low=Decimal(row[3]),
            close=Decimal(row[4]),
            volume=Decimal(row[5]),
            confirmed=row[8] == "1",
        )


class CandleSyncState(BaseModel):
    symbol: str
    timeframe: str
    first_ts: datetime
    last_ts: datetime
    actual_count: int
    missing_ranges: list[tuple[datetime, datetime]] = []
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Signal(TradeLineage):
    action: str
    direction: str
    confidence: float
    timeframe: str
    reason: str
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RiskDecision(BaseModel):
    approved: bool
    reason: str
    original_size: Decimal = Decimal("0")
    adjusted_size: Decimal = Decimal("0")
    max_loss_usdt: Decimal = Decimal("0")
    leverage: int = 1


class OrderIntent(TradeLineage):
    side: str
    position_action: str
    order_type: str
    size: Decimal
    price: Decimal | None
    reduce_only: bool
    client_order_id: str


class Order(TradeLineage):
    order_id: str
    client_order_id: str
    side: str
    order_type: str
    size: Decimal
    filled_size: Decimal = Decimal("0")
    price: Decimal | None = None
    avg_fill_price: Decimal | None = None
    status: str = "pending"
    okx_order_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Fill(TradeLineage):
    fill_id: str
    client_order_id: str
    side: str
    size: Decimal
    price: Decimal
    fee: Decimal = Decimal("0")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Position(BaseModel):
    account_id: str
    symbol: str
    direction: str
    size: Decimal
    entry_price: Decimal
    mark_price: Decimal
    unrealized_pnl: Decimal = Decimal("0")
    liquidation_price: Decimal | None = None
    margin_mode: str = "isolated"
    leverage: int = 1
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BacktestTrade(BaseModel):
    symbol: str
    side: str
    entry_price: Decimal
    exit_price: Decimal | None = None
    size: Decimal
    pnl: Decimal = Decimal("0")
    fee: Decimal = Decimal("0")
    opened_at: datetime
    closed_at: datetime | None = None
    stop_loss_price: Decimal | None = None
    take_profit_price: Decimal | None = None
    exit_reason: str | None = None


class BacktestMetrics(BaseModel):
    total_trades: int
    win_rate: float
    max_drawdown: Decimal
    total_fees: Decimal
    gross_profit: Decimal = Decimal("0")
    gross_loss: Decimal = Decimal("0")
    profit_factor: Decimal = Decimal("0")
    average_win: Decimal = Decimal("0")
    average_loss: Decimal = Decimal("0")
    payoff_ratio: Decimal = Decimal("0")
    max_consecutive_losses: int = 0
    average_holding_seconds: Decimal = Decimal("0")


class EquityPoint(BaseModel):
    timestamp: datetime
    equity: Decimal


class BacktestResult(BaseModel):
    initial_equity: Decimal
    final_equity: Decimal
    trades: list[BacktestTrade]
    metrics: BacktestMetrics
    equity_curve: list[EquityPoint] = []


class PaperJournalEvent(BaseModel):
    event_type: str
    symbol: str
    strategy_id: str
    message: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PaperRunResult(BaseModel):
    initial_equity: Decimal
    final_equity: Decimal
    signals_count: int
    approved_count: int
    rejected_count: int
    fills_count: int
    positions_count: int
    journal: list[PaperJournalEvent]
    fills: list[Fill] = []
    positions: list[Position] = []
