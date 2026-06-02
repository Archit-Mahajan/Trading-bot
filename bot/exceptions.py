class TradingBotError(Exception):
    """Base class for all trading bot errors."""


class ValidationError(TradingBotError):
    """Raised when user input or order parameters fail validation."""


class OrderError(TradingBotError):
    """Raised when an order is rejected or fails on the exchange."""


class APIConnectionError(TradingBotError):
    """Raised when we cannot reach the Binance API (network/auth/etc.)."""
