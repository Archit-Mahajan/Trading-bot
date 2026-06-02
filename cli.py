"""Command-line entry point for the Binance Futures Testnet trading bot.

Parses args, validates them against the symbol's exchange filters, places the
order, and prints a human-readable summary. Full details (raw API payloads,
stack traces, params) are written to ``logs/trading_bot.log``; the terminal
only ever sees the curated lines below.
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional

import requests

from bot.client import BinanceClient
from bot.exceptions import (
    APIConnectionError,
    OrderError,
    TradingBotError,
    ValidationError,
)
from bot.logging_config import get_logger
from bot.orders import place_order
from bot.validators import prepare_order

logger = get_logger(__name__)

BOX_WIDTH = 56


def _box(title: str, rows: list[tuple[str, str]]) -> str:
    border = "+" + "-" * (BOX_WIDTH - 2) + "+"
    inner = BOX_WIDTH - 4  # account for "| " ... " |"
    lines = [border, "| " + title.ljust(inner) + " |", border]
    key_width = max((len(k) for k, _ in rows), default=0)
    for key, value in rows:
        label = f"{key.ljust(key_width)} : {value}"
        if len(label) > inner:
            label = label[: inner - 1] + "…"
        lines.append("| " + label.ljust(inner) + " |")
    lines.append(border)
    return "\n".join(lines)


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="trading-bot",
        description=(
            "Place a MARKET, LIMIT, or STOP_LIMIT order on Binance Futures "
            "Testnet."
        ),
    )
    parser.add_argument(
        "--symbol",
        required=True,
        help="Trading pair, e.g. BTCUSDT.",
    )
    parser.add_argument(
        "--side",
        required=True,
        type=lambda s: s.upper(),
        choices=["BUY", "SELL"],
        help="Order side (case-insensitive).",
    )
    parser.add_argument(
        "--type",
        dest="order_type",
        required=True,
        type=lambda s: s.upper(),
        choices=["MARKET", "LIMIT", "STOP_LIMIT"],
        help="Order type.",
    )
    parser.add_argument(
        "--quantity",
        required=True,
        type=float,
        help="Order quantity (base asset).",
    )
    parser.add_argument(
        "--price",
        type=float,
        default=None,
        help=(
            "Limit price (required for --type LIMIT and --type STOP_LIMIT, "
            "forbidden for MARKET)."
        ),
    )
    parser.add_argument(
        "--stop-price",
        dest="stop_price",
        type=float,
        default=None,
        help=(
            "Stop trigger price (required for --type STOP_LIMIT, forbidden "
            "for MARKET and LIMIT)."
        ),
    )

    args = parser.parse_args(argv)

    if args.order_type == "LIMIT":
        if args.price is None:
            parser.error("--price is required when --type LIMIT.")
        if args.stop_price is not None:
            parser.error("--stop-price must not be provided when --type LIMIT.")
    elif args.order_type == "MARKET":
        if args.price is not None:
            parser.error("--price must not be provided when --type MARKET.")
        if args.stop_price is not None:
            parser.error(
                "--stop-price must not be provided when --type MARKET."
            )
    elif args.order_type == "STOP_LIMIT":
        if args.price is None:
            parser.error("--price is required when --type STOP_LIMIT.")
        if args.stop_price is None:
            parser.error("--stop-price is required when --type STOP_LIMIT.")

    return args


def _print_request_summary(cleaned: dict) -> None:
    rows = [
        ("Symbol", cleaned["symbol"]),
        ("Side", cleaned["side"]),
        ("Type", cleaned["type"]),
        ("Quantity", cleaned["quantity"]),
        ("Price", cleaned.get("price", "—")),
    ]
    if "stopPrice" in cleaned:
        rows.append(("Stop Price", cleaned["stopPrice"]))
    print(_box("ORDER REQUEST SUMMARY", rows))


def _print_response(response: dict) -> None:
    avg_price = response.get("avgPrice")
    if avg_price is None:
        avg_price_display = response.get("note") or "resting / not filled"
    else:
        avg_price_display = avg_price
    rows = [
        ("Order ID", str(response.get("orderId"))),
        ("Status", str(response.get("status"))),
        ("Executed Qty", str(response.get("executedQty"))),
        ("Avg Price", avg_price_display),
    ]
    if response.get("stopPrice") is not None:
        rows.append(("Stop Price", str(response.get("stopPrice"))))
    print(_box("ORDER RESPONSE", rows))


def _fail(message: str, code: int = 1) -> int:
    print(f"\nFAILED: {message}", file=sys.stderr)
    print("See logs/trading_bot.log for full details.", file=sys.stderr)
    return code


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)

    logger.info(
        "CLI invoked: symbol=%s side=%s type=%s qty=%s price=%s stop_price=%s",
        args.symbol,
        args.side,
        args.order_type,
        args.quantity,
        args.price,
        args.stop_price,
    )

    try:
        client = BinanceClient()
    except TradingBotError as exc:
        logger.error("Failed to initialize client: %s", exc)
        return _fail(f"Configuration error: {exc}")
    except Exception as exc:
        logger.exception("Unexpected error initializing client")
        return _fail(f"Unexpected error initializing client: {exc}")

    try:
        client.check_connection()
    except APIConnectionError as exc:
        logger.error("Connection check failed: %s", exc)
        return _fail(f"Cannot reach Binance Futures Testnet: {exc}")
    except Exception as exc:
        logger.exception("Unexpected error on connection check")
        return _fail(f"Unexpected error on connection check: {exc}")

    try:
        cleaned = prepare_order(
            client,
            args.symbol,
            args.side,
            args.order_type,
            args.quantity,
            args.price,
            args.stop_price,
        )
    except ValidationError as exc:
        logger.error("Validation failed: %s", exc)
        return _fail(f"Invalid order: {exc}")
    except APIConnectionError as exc:
        logger.error("Connection error during validation: %s", exc)
        return _fail(f"Network error during validation: {exc}")
    except Exception as exc:
        logger.exception("Unexpected error during validation")
        return _fail(f"Unexpected validation error: {exc}")

    _print_request_summary(cleaned)

    try:
        response = place_order(client, cleaned)
    except OrderError as exc:
        logger.error("Order rejected: %s", exc)
        return _fail(f"Order rejected: {exc}")
    except APIConnectionError as exc:
        logger.error("Network error placing order: %s", exc)
        return _fail(f"Network error placing order: {exc}")
    except requests.exceptions.RequestException as exc:
        logger.exception("Unhandled network error placing order")
        return _fail(f"Network error placing order: {exc}")
    except Exception as exc:
        logger.exception("Unexpected error placing order")
        return _fail(f"Unexpected error placing order: {exc}")

    _print_response(response)
    status = (response.get("status") or "").upper()
    if status in {"REJECTED", "EXPIRED", "CANCELED"}:
        print(f"\nFAILED: order ended in status={status}.", file=sys.stderr)
        return 2
    print("\nSUCCESS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
