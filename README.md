# Binance Futures Testnet Trading Bot

A small command-line trading bot that places **MARKET**, **LIMIT**, and
**STOP_LIMIT** orders on the
[Binance USD-M Futures Testnet](https://testnet.binancefuture.com). It validates
inputs against the symbol's exchange filters (LOT_SIZE / PRICE_FILTER /
MIN_NOTIONAL), submits the order through `python-binance`, prints a clean
two-box summary to the terminal, and writes a full audit trail (raw API
payloads, parameters, stack traces) to `logs/trading_bot.log`.

The bot is intentionally scoped to the testnet — it does not touch real funds.

---

## Project structure

```
trading_bot/
├── bot/
│   ├── __init__.py
│   ├── client.py            # BinanceClient wrapper (forces testnet URL)
│   ├── exceptions.py        # TradingBotError, ValidationError, OrderError, APIConnectionError
│   ├── logging_config.py    # Rotating-file + console logger
│   ├── orders.py            # place_order(): builds params, calls API, normalizes response
│   └── validators.py        # validate_inputs() + prepare_order() (filter enforcement)
├── cli.py                   # argparse entry point
├── requirements.txt         # Pinned runtime dependencies
├── .env.example             # Template for API credentials (no real keys)
├── .gitignore               # Ignores .env, logs/, venv/, __pycache__
└── README.md
```

Logs are written to `logs/trading_bot.log` (auto-created on first run, rotated
at 1 MB with 3 backups).

---

## Setup

### 1. Clone and create a virtual environment

```bash
git clone <your-repo-url> trading_bot
cd trading_bot

python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
```

### 2. Install pinned dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure testnet API credentials

Copy the template and fill in your testnet keys:

```bash
cp .env.example .env
```

Then edit `.env`:

```
BINANCE_API_KEY=your_testnet_api_key
BINANCE_API_SECRET=your_testnet_api_secret
```

### 4. Where to get testnet keys

1. Open <https://testnet.binancefuture.com> and log in with a GitHub or email
   account (separate from your real Binance login).
2. Scroll to the **API Key** panel at the bottom of the trading screen.
3. Click **Generate** — copy the **API Key** and **Secret Key** immediately
   (the secret is only shown once).
4. Paste them into your `.env` file.

The testnet seeds your account with virtual USDT, so you can place orders
without any real money at risk.

---

## Running the bot

The CLI takes `--symbol`, `--side`, `--type`, `--quantity`, and (for LIMIT
and STOP_LIMIT orders) `--price`. STOP_LIMIT orders additionally require
`--stop-price`. Side and type are case-insensitive.

### Example 1 — MARKET order

```bash
python cli.py --symbol BTCUSDT --side BUY --type MARKET --quantity 0.002
```

Expected console output (the order fills immediately at the current mark
price, so `Avg Price` is populated):

```
+------------------------------------------------------+
| ORDER REQUEST SUMMARY                                |
+------------------------------------------------------+
| Symbol   : BTCUSDT                                   |
| Side     : BUY                                       |
| Type     : MARKET                                    |
| Quantity : 0.002                                     |
| Price    : —                                         |
+------------------------------------------------------+
+------------------------------------------------------+
| ORDER RESPONSE                                       |
+------------------------------------------------------+
| Order ID    : 1234567890                             |
| Status      : FILLED                                 |
| Executed Qty: 0.002                                  |
| Avg Price   : 68000.00                               |
+------------------------------------------------------+

SUCCESS
```

### Example 2 — LIMIT order (resting, well below market)

Place a buy roughly 10 % below current price so the order rests on the book
instead of filling. If BTC is around \$68 000, an entry of \$61 000 will sit
unmatched:

```bash
python cli.py --symbol BTCUSDT --side BUY --type LIMIT --quantity 0.002 --price 61000
```

Expected console output (status is `NEW`, no fill yet, so the avg-price slot
shows the resting note rather than a misleading `0`):

```
+------------------------------------------------------+
| ORDER REQUEST SUMMARY                                |
+------------------------------------------------------+
| Symbol   : BTCUSDT                                   |
| Side     : BUY                                       |
| Type     : LIMIT                                     |
| Quantity : 0.002                                     |
| Price    : 61000                                     |
+------------------------------------------------------+
+------------------------------------------------------+
| ORDER RESPONSE                                       |
+------------------------------------------------------+
| Order ID    : 1234567891                             |
| Status      : NEW                                    |
| Executed Qty: 0                                      |
| Avg Price   : resting / not filled                   |
+------------------------------------------------------+

SUCCESS
```

### Example 3 — STOP_LIMIT order (resting, trigger above market)

A STOP_LIMIT order rests on the books with a trigger (`--stop-price`) and a
limit price (`--price`) that only activates once the trigger is hit. To park
one safely above market, pick a trigger comfortably above the current price
and a limit a bit above the trigger so the order has room to fill once
activated. If BTC is around \$110 000:

```bash
python cli.py --symbol BTCUSDT --side BUY --type STOP_LIMIT \
    --quantity 0.002 --price 116000 --stop-price 115000
```

Both `--price` and `--stop-price` are rounded to the symbol's `tickSize`
before submission. The order is sent as Binance Futures `type=STOP` with
`timeInForce=GTC`:

```
+------------------------------------------------------+
| ORDER REQUEST SUMMARY                                |
+------------------------------------------------------+
| Symbol     : BTCUSDT                                 |
| Side       : BUY                                     |
| Type       : STOP                                    |
| Quantity   : 0.002                                   |
| Price      : 116000                                  |
| Stop Price : 115000                                  |
+------------------------------------------------------+
+------------------------------------------------------+
| ORDER RESPONSE                                       |
+------------------------------------------------------+
| Order ID    : 1234567892                             |
| Status      : NEW                                    |
| Executed Qty: 0                                      |
| Avg Price   : resting / not filled                   |
| Stop Price  : 115000.00                              |
+------------------------------------------------------+

SUCCESS
```

Every run also appends to `logs/trading_bot.log`. The log captures CLI args,
request params, raw API responses, and any errors with full stack traces.

### Exit codes

- `0` — order accepted (FILLED, PARTIALLY_FILLED, or NEW).
- `1` — configuration / validation / network failure (nothing was sent or the
  exchange refused the request).
- `2` — order reached the exchange but ended in `REJECTED`, `EXPIRED`, or
  `CANCELED`.

---

## Assumptions

- **Testnet only.** The client always passes `testnet=True` to
  `python-binance` and additionally overrides `FUTURES_URL` with
  `FUTURES_TESTNET_URL` as a defensive belt-and-braces measure — some
  `python-binance` versions still point `FUTURES_URL` at production even when
  `testnet=True`. This bot will not place orders against production.
- **Order routing via `python-binance`.** All calls go through
  `binance.client.Client.futures_create_order` (USD-M Futures). Spot, COIN-M,
  and margin endpoints are not exercised.
- **Order types.** `MARKET`, `LIMIT`, and `STOP_LIMIT` are supported from the
  CLI. `STOP_LIMIT` maps to the Binance Futures wire `type=STOP` (a resting
  stop-with-limit order); STOP_MARKET, take-profit, trailing-stop, and OCO
  are intentionally out of scope.
- **`timeInForce` defaults to `GTC`** for LIMIT and STOP_LIMIT orders.
- **STOP_LIMIT requires both `--price` and `--stop-price`.** `--stop-price`
  is the trigger; `--price` is the limit that posts once the stop fires.
  Both are rounded to the symbol's `tickSize` (same `ROUND_HALF_UP` as the
  LIMIT price) and rejected if they fall outside `minPrice`/`maxPrice`.
- **Quantity rounding.** Quantities are rounded **DOWN** to the symbol's
  `stepSize` (`ROUND_DOWN`) so the bot never over-sizes an order. If the
  rounded quantity falls below `minQty`, the bot fails validation rather than
  submitting.
- **Price rounding.** Limit prices are rounded to the nearest multiple of
  `tickSize` (`ROUND_HALF_UP`). Out-of-band prices (below `minPrice` / above
  `maxPrice`) are rejected before submission.
- **MIN_NOTIONAL check.** For LIMIT orders, notional is computed against the
  rounded limit price. For MARKET orders, the bot fetches the live mark price
  via `futures_mark_price` and uses that as the reference.
- **Symbol must be `TRADING`.** Halted / break / auction-only symbols are
  refused up front.
- **Credentials come from `.env`** (loaded with `python-dotenv`) or process
  env vars. Missing keys raise a clear `Configuration error`.
- **Logging.** Console gets INFO-and-above lines. The full DEBUG stream —
  raw request params and raw exchange payloads — only ever lands in
  `logs/trading_bot.log`. The log file rotates at 1 MB (3 backups).
- **Network errors are not retried.** A single transient failure surfaces as
  an `APIConnectionError` and the CLI exits non-zero. Retries / backoff are
  left to the operator.
