"""Order placement layer.

Builds the Binance Futures order params, calls the client, and normalizes the
response into a small dict the CLI can print or persist. Input validation
(sides, lot/tick/notional filters, etc.) belongs in ``validators`` — by the
time we get here the params are already clean.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Optional

import requests
from binance.exceptions import BinanceAPIException, BinanceOrderException

from .client import BinanceClient
from .exceptions import APIConnectionError, OrderError
from .logging_config import get_logger

logger = get_logger(__name__)

DEFAULT_TIME_IN_FORCE = "GTC"


def _build_params(cleaned: dict) -> dict:
    """Assemble the kwargs we pass to ``futures_create_order``.

    ``cleaned`` is the dict returned by ``validators.prepare_order``:
        {symbol, side, type, quantity[, price][, stopPrice]}
    ``type`` is the Binance wire value (STOP_LIMIT enters here as ``STOP``).
    Both LIMIT and STOP carry a limit ``price`` and default to GTC. STOP
    additionally requires ``stopPrice``.
    """
    params = {
        "symbol": cleaned["symbol"],
        "side": cleaned["side"],
        "type": cleaned["type"],
        "quantity": cleaned["quantity"],
    }
    if cleaned["type"] in ("LIMIT", "STOP"):
        params["price"] = cleaned["price"]
        params["timeInForce"] = cleaned.get("timeInForce", DEFAULT_TIME_IN_FORCE)
    if cleaned["type"] == "STOP":
        params["stopPrice"] = cleaned["stopPrice"]
    return params


def _is_meaningful_price(raw) -> bool:
    if raw is None:
        return False
    try:
        return Decimal(str(raw)) > 0
    except (InvalidOperation, ValueError, TypeError):
        return False


def _normalize_response(response: dict, requested: dict) -> dict:
    """Project the raw Binance payload into the small shape the CLI consumes.

    avgPrice is '0.00000' on a resting LIMIT order; surface that as None plus
    a human-readable note rather than a misleading zero. STOP orders on
    Futures Testnet come back through the conditional/algo endpoint with
    ``algoId``/``algoStatus`` instead of ``orderId``/``status`` — fall back
    to those so the normalized shape stays uniform.
    """
    order_id = response.get("orderId") or response.get("algoId")
    status = response.get("status") or response.get("algoStatus")
    executed_qty = response.get("executedQty")
    if executed_qty is None and "algoStatus" in response:
        executed_qty = "0"  # resting algo order — nothing executed yet

    avg_price_raw = response.get("avgPrice")
    avg_price: Optional[str]
    note: Optional[str]
    if _is_meaningful_price(avg_price_raw):
        avg_price = str(avg_price_raw)
        note = None
    else:
        avg_price = None
        note = f"No fill price yet (status={status})."

    normalized = {
        "orderId": order_id,
        "status": status,
        "executedQty": executed_qty,
        "avgPrice": avg_price,
        "symbol": requested.get("symbol"),
        "side": requested.get("side"),
        "type": requested.get("type"),
        "quantity": requested.get("quantity"),
        "price": requested.get("price"),
        "stopPrice": requested.get("stopPrice"),
    }
    if note is not None:
        normalized["note"] = note
    return normalized


def _raise_order_error(exc: Exception, params: dict) -> "OrderError":
    """Build an OrderError that preserves Binance's structured code/message."""
    code = getattr(exc, "code", None)
    message = getattr(exc, "message", None) or str(exc)
    logger.error(
        "Binance rejected order (code=%s, message=%s) | params=%s",
        code,
        message,
        params,
    )
    err = OrderError(f"Binance order error [code={code}]: {message}")
    err.code = code
    err.message = message
    return err


def place_order(client: BinanceClient, cleaned: dict) -> dict:
    """Place ``cleaned`` (already-validated params) on Binance Futures.

    Returns a normalized response dict. Raises OrderError on a rejection (with
    the Binance error code/message attached) or APIConnectionError on a
    network failure.
    """
    params = _build_params(cleaned)
    price_suffix = f" @ {params['price']}" if "price" in params else ""
    if "stopPrice" in params:
        price_suffix += f" stop={params['stopPrice']}"
    logger.info(
        "Submitting %s %s order: %s qty=%s%s",
        params["type"],
        params["side"],
        params["symbol"],
        params["quantity"],
        price_suffix,
    )
    logger.debug("Order params: %s", params)

    try:
        response = client.client.futures_create_order(**params)
    except BinanceOrderException as exc:
        raise _raise_order_error(exc, params) from exc
    except BinanceAPIException as exc:
        raise _raise_order_error(exc, params) from exc
    except requests.exceptions.RequestException as exc:
        logger.error("Network error placing order: %s | params=%s", exc, params)
        raise APIConnectionError(
            f"Network error reaching Binance while placing order: {exc}"
        ) from exc

    logger.debug("Raw order response: %s", response)
    normalized = _normalize_response(response, params)
    logger.info(
        "Order accepted: id=%s status=%s executedQty=%s avgPrice=%s",
        normalized["orderId"],
        normalized["status"],
        normalized["executedQty"],
        normalized["avgPrice"],
    )
    return normalized
