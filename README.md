# Sukoon Health API

Saudi DTC COD ecommerce backend for [sukoonhealth.shop](https://sukoonhealth.shop).

## Stack

- **Python 3.11** + **FastAPI**
- **PostgreSQL** via SQLAlchemy 2 async + asyncpg
- **Alembic** migrations
- **Pydantic v2** validation
- **HTTPX** for outbound calls (Sheets, Meta/TikTok/Snap CAPI)
- **slowapi** rate limiting
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
