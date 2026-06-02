"""Input and symbol-filter validation for orders.

``validate_inputs`` does the pure checks (side/type/quantity/price).
``prepare_order`` additionally consults the client's exchange info (and mark
price for MARKET orders) to enforce LOT_SIZE, PRICE_FILTER, and MIN_NOTIONAL,
returning cleaned strings ready to pass to ``BinanceClient.create_order``.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP
from typing import Optional

from .exceptions import APIConnectionError, TradingBotError, ValidationError
from .logging_config import get_logger

logger = get_logger(__name__)

VALID_SIDES = {"BUY", "SELL"}
VALID_ORDER_TYPES = {"MARKET", "LIMIT", "STOP_LIMIT"}

# Order types that carry a limit price (rounded to PRICE_FILTER tickSize).
_PRICED_TYPES = {"LIMIT", "STOP_LIMIT"}

# User-facing order_type -> Binance Futures wire ``type`` value.
_WIRE_TYPE = {"MARKET": "MARKET", "LIMIT": "LIMIT", "STOP_LIMIT": "STOP"}


def _to_decimal(name: str, value) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValidationError(f"{name} must be a number, got {value!r}.") from exc


def _format_decimal(d: Decimal) -> str:
    """Render a Decimal as a plain string with no scientific notation
    and no trailing zeros (so we don't send 0.10000000001 to the API)."""
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def _round_to_step(value: Decimal, step: Decimal, rounding) -> Decimal:
    """Round ``value`` to the nearest multiple of ``step`` using ``rounding``.
    The returned Decimal carries ``step``'s precision so trailing zeros are
    preserved until formatting."""
    if step <= 0:
        return value
    steps = (value / step).to_integral_value(rounding=rounding)
    return (steps * step).quantize(step)


def _filter_by_type(symbol_info: dict, filter_type: str) -> Optional[dict]:
    for f in symbol_info.get("filters", []):
        if f.get("filterType") == filter_type:
            return f
    return None


def validate_inputs(
    symbol,
    side,
    order_type,
    quantity,
    price=None,
    stop_price=None,
) -> dict:
    """Pure, client-independent validation.

    Returns a dict of normalized values:
        {symbol: str, side: str, order_type: str,
         quantity: Decimal, price: Optional[Decimal],
         stop_price: Optional[Decimal]}
    Raises ValidationError with a human-readable message on bad input.
    """
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValidationError("symbol is required and must be a non-empty string.")
    symbol_norm = symbol.strip().upper()

    if not isinstance(side, str):
        raise ValidationError(
            f"side must be a string, got {type(side).__name__}."
        )
    side_norm = side.strip().upper()
    if side_norm not in VALID_SIDES:
        raise ValidationError(f"side must be BUY or SELL (got {side!r}).")

    if not isinstance(order_type, str):
        raise ValidationError(
            f"order_type must be a string, got {type(order_type).__name__}."
        )
    order_type_norm = order_type.strip().upper()
    if order_type_norm not in VALID_ORDER_TYPES:
        raise ValidationError(
            f"order_type must be MARKET, LIMIT, or STOP_LIMIT "
            f"(got {order_type!r})."
        )

    qty_dec = _to_decimal("quantity", quantity)
    if qty_dec <= 0:
        raise ValidationError(f"quantity must be positive (got {quantity!r}).")

    price_dec: Optional[Decimal] = None
    if order_type_norm in _PRICED_TYPES:
        if price is None or (isinstance(price, str) and not price.strip()):
            raise ValidationError(
                f"price is required for {order_type_norm} orders."
            )
        price_dec = _to_decimal("price", price)
        if price_dec <= 0:
            raise ValidationError(f"price must be positive (got {price!r}).")
    else:  # MARKET
        if price is not None:
            logger.warning(
                "Ignoring price=%s supplied for MARKET order on %s.",
                price,
                symbol_norm,
            )

    stop_price_dec: Optional[Decimal] = None
    if order_type_norm == "STOP_LIMIT":
        if stop_price is None or (
            isinstance(stop_price, str) and not stop_price.strip()
        ):
            raise ValidationError("stop_price is required for STOP_LIMIT orders.")
        stop_price_dec = _to_decimal("stop_price", stop_price)
        if stop_price_dec <= 0:
            raise ValidationError(
                f"stop_price must be positive (got {stop_price!r})."
            )
    elif stop_price is not None:
        logger.warning(
            "Ignoring stop_price=%s supplied for %s order on %s.",
            stop_price,
            order_type_norm,
            symbol_norm,
        )

    return {
        "symbol": symbol_norm,
        "side": side_norm,
        "order_type": order_type_norm,
        "quantity": qty_dec,
        "price": price_dec,
        "stop_price": stop_price_dec,
    }


def _check_price_against_filter(
    original: Decimal,
    tick: Decimal,
    min_price: Decimal,
    max_price: Decimal,
    symbol_norm: str,
    label: str,
) -> Decimal:
    """Round ``original`` to the nearest ``tick`` and bounds-check it."""
    rounded = _round_to_step(original, tick, ROUND_HALF_UP)
    if rounded != original:
        logger.warning(
            "%s %s rounded to %s to match tickSize %s for %s.",
            label.capitalize(),
            _format_decimal(original),
            _format_decimal(rounded),
            _format_decimal(tick),
            symbol_norm,
        )
    if min_price > 0 and rounded < min_price:
        raise ValidationError(
            f"{label} {_format_decimal(rounded)} is below minPrice "
            f"{_format_decimal(min_price)} for {symbol_norm}."
        )
    if max_price > 0 and rounded > max_price:
        raise ValidationError(
            f"{label} {_format_decimal(rounded)} is above maxPrice "
            f"{_format_decimal(max_price)} for {symbol_norm}."
        )
    return rounded


def _get_mark_price(client, symbol: str) -> Decimal:
    """Fetch the current mark price via the underlying python-binance client."""
    try:
        data = client.client.futures_mark_price(symbol=symbol)
    except Exception as exc:
        raise APIConnectionError(
            f"Could not fetch mark price for {symbol}: {exc}"
        ) from exc

    if isinstance(data, list):
        for entry in data:
            if entry.get("symbol") == symbol:
                data = entry
                break
        else:
            raise APIConnectionError(f"No mark price entry returned for {symbol}.")

    mark = data.get("markPrice") if isinstance(data, dict) else None
    if mark is None:
        raise APIConnectionError(f"Mark price missing in response for {symbol}.")
    return _to_decimal("markPrice", mark)


def prepare_order(
    client,
    symbol,
    side,
    order_type,
    quantity,
    price=None,
    stop_price=None,
) -> dict:
    """Validate inputs and apply the symbol's LOT_SIZE / PRICE_FILTER /
    MIN_NOTIONAL filters.

    Returns a dict ready to splat into ``client.create_order``:
        {"symbol", "side", "type", "quantity"[, "price"][, "stopPrice"]}
    with quantity/price/stopPrice formatted as precise strings. ``type`` is
    the Binance wire value (STOP_LIMIT is translated to ``STOP``).
    Raises ValidationError on any filter violation.
    """
    cleaned = validate_inputs(
        symbol, side, order_type, quantity, price, stop_price
    )
    symbol_norm = cleaned["symbol"]

    try:
        info = client.get_exchange_info(symbol_norm)
    except TradingBotError as exc:
        raise ValidationError(
            f"Symbol {symbol_norm} not available on Binance Futures Testnet: {exc}"
        ) from exc

    status = info.get("status")
    if status and status != "TRADING":
        raise ValidationError(
            f"Symbol {symbol_norm} is not currently trading (status={status})."
        )

    lot = _filter_by_type(info, "LOT_SIZE")
    if lot is None:
        raise ValidationError(f"LOT_SIZE filter missing for {symbol_norm}.")
    min_qty = _to_decimal("minQty", lot["minQty"])
    max_qty = _to_decimal("maxQty", lot["maxQty"])
    step_size = _to_decimal("stepSize", lot["stepSize"])

    original_qty = cleaned["quantity"]
    rounded_qty = _round_to_step(original_qty, step_size, ROUND_DOWN)
    if rounded_qty != original_qty:
        logger.warning(
            "Quantity %s rounded DOWN to %s to match stepSize %s for %s.",
            _format_decimal(original_qty),
            _format_decimal(rounded_qty),
            _format_decimal(step_size),
            symbol_norm,
        )
    if rounded_qty < min_qty:
        raise ValidationError(
            f"quantity {_format_decimal(rounded_qty)} is below minQty "
            f"{_format_decimal(min_qty)} for {symbol_norm} "
            f"(after rounding to stepSize {_format_decimal(step_size)})."
        )
    if rounded_qty > max_qty:
        raise ValidationError(
            f"quantity {_format_decimal(rounded_qty)} is above maxQty "
            f"{_format_decimal(max_qty)} for {symbol_norm}."
        )

    rounded_price: Optional[Decimal] = None
    rounded_stop_price: Optional[Decimal] = None
    if cleaned["order_type"] in _PRICED_TYPES:
        price_filter = _filter_by_type(info, "PRICE_FILTER")
        if price_filter is None:
            raise ValidationError(f"PRICE_FILTER missing for {symbol_norm}.")
        tick = _to_decimal("tickSize", price_filter["tickSize"])
        min_price = _to_decimal("minPrice", price_filter["minPrice"])
        max_price = _to_decimal("maxPrice", price_filter["maxPrice"])

        rounded_price = _check_price_against_filter(
            cleaned["price"], tick, min_price, max_price, symbol_norm, "price"
        )
        if cleaned["order_type"] == "STOP_LIMIT":
            rounded_stop_price = _check_price_against_filter(
                cleaned["stop_price"],
                tick,
                min_price,
                max_price,
                symbol_norm,
                "stopPrice",
            )

    notional = _filter_by_type(info, "MIN_NOTIONAL")
    if notional is not None:
        # Futures payloads use 'notional'; spot-style payloads use 'minNotional'.
        min_notional_raw = notional.get("notional") or notional.get("minNotional")
        if min_notional_raw is not None:
            min_notional = _to_decimal("minNotional", min_notional_raw)
            if cleaned["order_type"] in _PRICED_TYPES:
                ref_price = rounded_price
                ref_label = "limit price"
            else:
                ref_price = _get_mark_price(client, symbol_norm)
                ref_label = "mark price"
            order_notional = ref_price * rounded_qty
            if order_notional < min_notional:
                raise ValidationError(
                    f"Order notional {_format_decimal(order_notional)} is below "
                    f"minNotional {_format_decimal(min_notional)} for "
                    f"{symbol_norm} ({ref_label} {_format_decimal(ref_price)} "
                    f"x quantity {_format_decimal(rounded_qty)})."
                )

    result = {
        "symbol": symbol_norm,
        "side": cleaned["side"],
        "type": _WIRE_TYPE[cleaned["order_type"]],
        "quantity": _format_decimal(rounded_qty),
    }
    if rounded_price is not None:
        result["price"] = _format_decimal(rounded_price)
    if rounded_stop_price is not None:
        result["stopPrice"] = _format_decimal(rounded_stop_price)
    return result
