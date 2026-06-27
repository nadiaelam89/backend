# Sukoon Health API

Saudi DTC COD ecommerce backend for [sukoonhealth.shop](https://sukoonhealth.shop).

## Stack

- **Python 3.11** + **FastAPI**
- **PostgreSQL** via SQLAlchemy 2 async + asyncpg
- **Alembic** migrations
- **Pydantic v2** validation
- **HTTPX** for outbound calls (Sheets, Meta/TikTok/Snap CAPI)
- **slowapi** rate limiting
- **MaxMind minFraud** optional IP fraud screening
- **Docker** deployment

## Quick Start

### 1. Copy and fill environment variables

```bash
cp .env.example .env
# Edit .env with your credentials
```

### 2. Install dependencies

```bash
poetry install
```

### 3. Run database migrations

```bash
poetry run alembic upgrade head
```

### 4. Start the development server

```bash
poetry run uvicorn app.main:app --reload --port 8000
```

### 5. Run tests

```bash
poetry run pytest
```

## Docker

```bash
docker build -t sukoon-health-api .
docker run -p 8000:8000 --env-file .env sukoon-health-api
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/api/orders` | Create a new order |
| POST | `/api/orders/{order_id}/upsell` | Add upsell item to order |
| GET | `/api/orders/{order_id}/summary` | Get order summary (safe fields) |

## Products

| ID | Slug | Name (AR) |
|----|------|-----------|
| `sleep_gummies` | `sleep-melatonin-gummies` | علكة النوم بالميلاتونين ضد الأرق |
| `ashwagandha_tea` | `ashwagandha-tea` | شاي الأشواجندا ضد التوتر |
| `focus_coffee` | `l-theanine-focus-coffee` | قهوة التركيز بالإل-ثيانين ضد الخمول |

## Pricing

| Quantity | Price (SAR) |
|----------|-------------|
| 1 | 199 |
| 2 | 279 |
| 3 | 349 |
| Upsell | 99 |

## Optional MaxMind Fraud Screening

Set `ENABLE_IP_FRAUD_CHECK=true` to screen public client IPs with MaxMind minFraud before an order is saved. The check blocks clear non-allowed-country or high-risk-score results, but fails open if MaxMind is unavailable so normal COD checkout is not interrupted by provider downtime.

```env
MAXMIND_ACCOUNT_ID=
MAXMIND_LICENSE_KEY=
ENABLE_IP_FRAUD_CHECK=true
MAXMIND_RISK_SCORE_THRESHOLD=25
MAXMIND_ALLOWED_COUNTRY=SA
WHITELISTED_PHONES=+966550630222
```

Keep these values only in the backend environment. Never add MaxMind credentials to `frontend/.env`.

## Project Structure

```
backend/
  app/
    api/routes/     # FastAPI route handlers
    core/           # Config, logging
    db/             # SQLAlchemy models, session, migrations
    schemas/        # Pydantic request/response schemas
    services/       # Business logic (orders, pricing, phone, sheets, CAPI)
  tests/            # pytest test suite
```
