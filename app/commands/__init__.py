from __future__ import annotations

import argparse

from app.commands import live_ops, market_data, operator, research


def register_all(subparsers: argparse._SubParsersAction) -> None:
    market_data.register(subparsers)
    research.register(subparsers)
    live_ops.register(subparsers)
    operator.register(subparsers)
