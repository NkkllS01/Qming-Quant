from __future__ import annotations

import argparse

from app.commands import register_all
from app.services import AppServices, build_services


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trade", description="OKX contract quant trading CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    register_all(subparsers)
    return parser


def run_command(args: argparse.Namespace, services: AppServices) -> str:
    return args.handler(args, services)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    print(run_command(args, build_services()))


if __name__ == "__main__":
    main()
