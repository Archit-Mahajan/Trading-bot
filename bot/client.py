import os

import requests
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceOrderException
from dotenv import load_dotenv

from .exceptions import APIConnectionError, OrderError, TradingBotError
from .logging_config import get_logger

logger = get_logger(__name__)


class BinanceClient:
    def __init__(self):
        load_dotenv()
        api_key = os.getenv("BINANCE_API_KEY")
        api_secret = os.getenv("BINANCE_API_SECRET")

        if not api_key or not api_secret:
            raise TradingBotError(
                "BINANCE_API_KEY and BINANCE_API_SECRET must be set in the "
                "environment or a .env file."
            )

        self.client = Client(api_key, api_secret, testnet=True)

        # Defensive fallback: some python-binance versions leave FUTURES_URL
        # pointing at production even when testnet=True. Force it to the
        # testnet fapi URL so any code path that reads FUTURES_URL directly
        # still hits the testnet.
        self.client.FUTURES_URL = self.client.FUTURES_TESTNET_URL

    def check_connection(self) -> None:
        logger.debug("futures_ping request")
        try:
            response = self.client.futures_ping()
        except (BinanceAPIException, BinanceOrderException) as exc:
            logger.error("Binance API error on futures_ping: %s", exc)
            raise APIConnectionError(f"Binance API error: {exc}") from exc
        except requests.exceptions.RequestException as exc:
            logger.error("Network error on futures_ping: %s", exc)
            raise APIConnectionError(f"Network error reaching Binance: {exc}") from exc
        logger.debug("futures_ping response: %s", response)

    def get_exchange_info(self, symbol: str) -> dict:
        params = {"symbol": symbol}
        logger.debug("futures_exchange_info request: %s", params)
        try:
            info = self.client.futures_exchange_info()
        except (BinanceAPIException, BinanceOrderException) as exc:
            logger.error("Binance API error on futures_exchange_info: %s", exc)
            raise APIConnectionError(f"Binance API error: {exc}") from exc
        except requests.exceptions.RequestException as exc:
            logger.error("Network error on futures_exchange_info: %s", exc)
            raise APIConnectionError(f"Network error reaching Binance: {exc}") from exc

        logger.debug("futures_exchange_info raw response keys: %s", list(info.keys()))
        for entry in info.get("symbols", []):
            if entry.get("symbol") == symbol.upper():
                return entry
        raise TradingBotError(f"Symbol not found in futures exchange info: {symbol}")

    def create_order(self, **params) -> dict:
        logger.debug("futures_create_order request: %s", params)
        try:
            response = self.client.futures_create_order(**params)
        except BinanceOrderException as exc:
            logger.error("Binance order rejected: %s | params=%s", exc, params)
            raise OrderError(f"Order rejected: {exc}") from exc
        except BinanceAPIException as exc:
            logger.error("Binance API error on create_order: %s | params=%s", exc, params)
            raise OrderError(f"Binance API error: {exc}") from exc
        except requests.exceptions.RequestException as exc:
            logger.error("Network error on create_order: %s | params=%s", exc, params)
            raise APIConnectionError(f"Network error reaching Binance: {exc}") from exc

        logger.debug("futures_create_order response: %s", response)
        return response
