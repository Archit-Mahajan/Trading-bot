# Binance Futures Testnet Trading Bot

A command-line trading bot for the **Binance USD-M Futures Testnet** that supports:

* MARKET orders
* LIMIT orders
* STOP-LIMIT orders

The bot validates all orders against Binance exchange filters before submission, provides a clean terminal summary, and maintains a complete audit trail of requests, responses, and errors.

**Testnet only — no real funds are used.**

---

## Features

* Binance USD-M Futures Testnet integration
* MARKET, LIMIT, and STOP-LIMIT order support
* Exchange filter validation

  * LOT_SIZE
  * PRICE_FILTER
  * MIN_NOTIONAL
* Automatic quantity and price rounding
* Structured terminal output
* Detailed rotating log files
* Environment-based credential management
* Custom exception hierarchy
* Clear exit codes for automation and scripting

---

## Project Structure

```text
trading_bot/
├── bot/
│   ├── __init__.py
│   ├── client.py
│   ├── exceptions.py
│   ├── logging_config.py
│   ├── orders.py
│   └── validators.py
│
├── cli.py
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

### Module Overview

| File              | Purpose                                               |
| ----------------- | ----------------------------------------------------- |
| client.py         | Binance client wrapper configured for Futures Testnet |
| validators.py     | Exchange filter validation and parameter preparation  |
| orders.py         | Order creation and API submission                     |
| exceptions.py     | Custom exception hierarchy                            |
| logging_config.py | Console and rotating file logging                     |
| cli.py            | Command-line entry point                              |

---

## Installation

### 1. Clone Repository

```bash
git clone <your-repository-url>
cd trading_bot
```

### 2. Create Virtual Environment

```bash
python3 -m venv venv
```

Activate:

Linux / macOS

```bash
source venv/bin/activate
```

Windows

```cmd
venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

---

## Configure API Credentials

Copy the example file:

```bash
cp .env.example .env
```

Add your Binance Futures Testnet credentials:

```env
BINANCE_API_KEY=your_testnet_api_key
BINANCE_API_SECRET=your_testnet_api_secret
```

---

## Obtaining Binance Testnet Keys

1. Visit:

https://testnet.binancefuture.com

2. Sign in using GitHub or email.

3. Open the Futures Testnet trading interface.

4. Locate the API Management section.

5. Generate a new API key pair.

6. Copy the API Key and Secret Key.

7. Paste them into your `.env` file.

> The Binance Futures Testnet provides virtual USDT balances for testing. No real funds are involved.

---

# Usage

## MARKET Order

```bash
python cli.py \
  --symbol BTCUSDT \
  --side BUY \
  --type MARKET \
  --quantity 0.002
```

Example response:

```text
+------------------------------------------------------+
| ORDER REQUEST SUMMARY                                |
+------------------------------------------------------+
| Symbol   : BTCUSDT                                   |
| Side     : BUY                                       |
| Type     : MARKET                                    |
| Quantity : 0.002                                     |
+------------------------------------------------------+

+------------------------------------------------------+
| ORDER RESPONSE                                       |
+------------------------------------------------------+
| Order ID    : 1234567890                             |
| Status      : FILLED                                 |
| Executed Qty: 0.002                                  |
| Avg Price   : 105000.00                              |
+------------------------------------------------------+

SUCCESS
```

---

## LIMIT Order

Place a limit order away from the current market price so it rests on the order book.

```bash
python cli.py \
  --symbol BTCUSDT \
  --side BUY \
  --type LIMIT \
  --quantity 0.002 \
  --price 95000
```

Example response:

```text
Status      : NEW
Executed Qty: 0
Avg Price   : resting / not filled
```

---

## STOP-LIMIT Order

A STOP-LIMIT order becomes active only when the stop price is triggered.

```bash
python cli.py \
  --symbol BTCUSDT \
  --side BUY \
  --type STOP_LIMIT \
  --quantity 0.002 \
  --price 116000 \
  --stop-price 115000
```

Internally submitted as:

```text
type=STOP
timeInForce=GTC
```

Example response:

```text
Status      : NEW
Executed Qty: 0
Avg Price   : resting / not filled
Stop Price  : 115000.00
```

---

# Validation Rules

The bot validates all orders before submission.

### Quantity Validation

* Rounded down to exchange `stepSize`
* Must satisfy `minQty`
* Must satisfy `maxQty`

### Price Validation

* Rounded to nearest `tickSize`
* Must satisfy:

  * `minPrice`
  * `maxPrice`

### Notional Validation

LIMIT orders:

```text
notional = quantity × limit_price
```

MARKET orders:

```text
notional = quantity × current_mark_price
```

Both must satisfy Binance `MIN_NOTIONAL`.

### Symbol Validation

The symbol must:

* Exist
* Be active
* Have status = `TRADING`

---

# Logging

Logs are written to:

```text
logs/trading_bot.log
```

The log directory is created automatically.

### Logged Information

* CLI arguments
* Request parameters
* Exchange responses
* Validation failures
* API exceptions
* Full stack traces

### Rotation Policy

```text
Maximum size : 1 MB
Backups      : 3
```

Console output receives INFO-level logs and above.

The log file receives the complete DEBUG stream.

---

# Exit Codes

| Code | Meaning                                                       |
| ---- | ------------------------------------------------------------- |
| 0    | Order accepted (NEW, FILLED, PARTIALLY_FILLED)                |
| 1    | Validation, configuration, or connection failure              |
| 2    | Order reached exchange but was REJECTED, EXPIRED, or CANCELED |

---

# Design Assumptions

### Testnet Safety

The application is hard-wired to Binance Futures Testnet.

It:

* Enables `testnet=True`
* Overrides `FUTURES_URL`
* Forces all requests to the Futures Testnet endpoint

This prevents accidental submission to production environments.

### Supported Order Types

Supported:

* MARKET
* LIMIT
* STOP-LIMIT

Not Supported:

* STOP_MARKET
* TAKE_PROFIT
* TAKE_PROFIT_MARKET
* TRAILING_STOP_MARKET
* OCO

### Time In Force

```text
LIMIT      -> GTC
STOP_LIMIT -> GTC
```

### Retry Strategy

No automatic retries are performed.

Transient network failures raise:

```python
APIConnectionError
```

allowing operators or orchestration tools to implement their own retry policies.

---

# Troubleshooting

### Missing API Keys

```text
Configuration Error: API credentials not found
```

Ensure:

```env
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
```

exist in `.env`.

### Quantity Validation Failure

```text
Validation Error: Quantity below minimum lot size
```

Increase the order quantity.

### Notional Validation Failure

```text
Validation Error: Order value below minimum notional
```

Increase quantity or price.

### Network Failure

```text
APIConnectionError
```

Verify:

* Internet connection
* Binance Testnet availability
* API credentials

---

# Disclaimer

This project is intended solely for educational and testing purposes on the Binance USD-M Futures Testnet.

No real funds are used, and the software should not be considered investment advice or production-grade trading infrastructure.
