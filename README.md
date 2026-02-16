# MRR Dashboard

A functional Monthly Recurring Revenue (MRR) dashboard that calculates MRR from raw Stripe data, warehouses it in BigQuery, and visualizes the trend in a React frontend.

**Tech Stack:** Stripe API (Python) → Google BigQuery (SQL) → React (Recharts)

---

## Architecture Overview

```
┌──────────────┐     ┌──────────────────┐     ┌───────────┐     ┌────────────┐
│  Stripe API  │────▶│  ETL (Python)    │────▶│  BigQuery │────▶│  React App │
│  (Test Data) │     │  extract + load  │     │  (SQL)    │     │  (Chart)   │
└──────────────┘     └──────────────────┘     └───────────┘     └────────────┘
       ▲                                            │                  ▲
       │                                            │                  │
  generate_data.py                          mrr_calculation.sql   Flask API
  (Test Clocks)                             (MRR logic)          api_server.py
```

## Prerequisites

- **Python 3.10+**
- **Node.js 18+** and npm
- **Stripe Account** (free test mode): [dashboard.stripe.com](https://dashboard.stripe.com)
- **Google Cloud Account** (free tier): [cloud.google.com](https://cloud.google.com)

---

## Quick Start

### 1. Clone and configure

```bash
git clone <repo-url>
cd mrr-dashboard
cp .env.example .env
```

Edit `.env` with your credentials:

```
STRIPE_SECRET_KEY=sk_test_...
GCP_PROJECT_ID=your-project-id
GOOGLE_APPLICATION_CREDENTIALS=./service-account.json
BQ_DATASET=mrr_dashboard
API_PORT=5001
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
cd frontend && npm install && cd ..
```

### 3. Set up Stripe

1. Sign up at [dashboard.stripe.com](https://dashboard.stripe.com) (Developer/Test mode).
2. Copy your **test secret key** (`sk_test_...`) into `.env`.

### 4. Set up Google Cloud / BigQuery

1. Create a GCP project at [console.cloud.google.com](https://console.cloud.google.com).
2. Enable the **BigQuery API**.
3. Create a service account with **BigQuery Data Editor** and **BigQuery Job User** roles.
4. Download the JSON key file, place it in the project root as `service-account.json`.
5. Set `GCP_PROJECT_ID` in `.env`.

### 5. Run the pipeline

**Option A — One command (PowerShell):**

```powershell
.\run.ps1
```

Alternatively, open this file in Visual Studio Code and click "Run" (▶️). 
This runs all four steps in sequence: data generation, ETL, API server, and React frontend. Step 1 takes ~10–15 minutes due to Stripe test clock advancement.

**Option B — Step by step:**

```bash
# Step 1: Generate test data in Stripe (~10-15 min)
python scripts/generate_data.py

# Step 2: Extract from Stripe, load into BigQuery
python scripts/etl_stripe_to_bq.py

# Step 3: Start the API server
python scripts/api_server.py

# Step 4: In a new terminal, start the React frontend
cd frontend
npm start
```

The dashboard opens at `http://localhost:3000`. The API runs at `http://localhost:5001/api/mrr`.

### 6. Verify SQL logic (optional)

Open `sql/mrr_calculation.sql` in the [BigQuery Console](https://console.cloud.google.com/bigquery) and run it (replace `{PROJECT}` and `{DATASET}` with your values). The output should match what the dashboard displays.

---

## Project Structure

```
mrr-dashboard/
├── scripts/
│   ├── generate_data.py       # Step 1: Stripe test data generator
│   ├── etl_stripe_to_bq.py   # Step 2: ETL pipeline (Stripe → BigQuery)
│   ├── api_server.py          # Flask API serving BigQuery data
│   ├── data_manifest.json     # Generated: all customer/subscription IDs
│   └── price_config.json      # Generated: plan/price IDs
├── sql/
│   ├── mrr_calculation.sql    # Step 3: Full MRR query with MoM change
│   └── create_mrr_view.sql    # Optional: create a BQ view for the API
├── frontend/
│   ├── public/index.html
│   ├── src/
│   │   ├── App.js             # Step 4: React dashboard component
│   │   ├── App.css            # Dashboard styles
│   │   └── index.js           # React entry point
│   └── package.json
├── run.ps1                    # One-command pipeline runner (PowerShell)
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

---

## Data Generation

The generator script creates customers with subscriptions using Stripe Test Clocks to simulate 6 months of billing history. Test clocks allow Stripe to authentically generate invoices, charges, and subscription lifecycle events as if time had actually passed — no mocked data.

**Subscription plans:**

| Plan | Price | Interval |
|------|-------|----------|
| Starter | $29 | Monthly |
| Pro | $79 | Monthly |
| Business | $199 | Monthly |
| Enterprise | $499 | Monthly |
| Pro Annual | $790 | Yearly |
| Business Annual | $1,990 | Yearly |

Customers are distributed across plans with realistic weighting (heavier toward Starter/Pro). The script simulates ~15% churn and ~10% payment failures across months by canceling subscriptions and swapping payment methods to declining test cards.

**Note:** Stripe's free-tier test mode limits customers per test clock (3 on free accounts). The number of customers scales with the number of test clocks configured.

---

## ETL Pipeline

The ETL script (`etl_stripe_to_bq.py`) extracts subscriptions and invoices from Stripe's API and loads them into two BigQuery tables:

- `mrr_dashboard.subscriptions` — subscription ID, customer, plan, status, dates, cancellation info
- `mrr_dashboard.invoices` — invoice ID, customer, amounts, payment status, period dates

The pipeline uses full-refresh (`WRITE_TRUNCATE`) on each run. Local JSON copies of the extracted data are saved to `scripts/extracts/` for debugging.

---

## MRR Calculation Logic

MRR is **not** just revenue — it's the **normalized monthly value of active recurring subscriptions**.

The SQL logic:

1. **Generates a month spine** covering the full date range of the data.
2. **Determines each subscription's active window** — from `created_at` to `ended_at` / `canceled_at`. Subscriptions with `cancel_at_period_end = TRUE` remain active until their current period ends.
3. **Normalizes plan amounts to monthly values:** monthly plans use `plan_amount × quantity`, annual plans divide by 12, and arbitrary intervals (quarterly, etc.) are handled via `plan_interval_count`.
4. **Joins subscriptions × months** to determine which subscriptions were active during each month.
5. **Aggregates** to total MRR per month, with month-over-month change.

Only subscriptions with status `active`, `past_due`, or `canceled` (before their end date) are counted. Trialing subscriptions are excluded since they don't generate revenue.

---

## Design Decisions

- **Test Clocks over manual timestamps**: Stripe's Test Clock API generates authentic invoices, charges, and lifecycle events. The data is real Stripe data, not mocked.
- **Full-refresh ETL**: The pipeline truncates and reloads tables on each run. For production, incremental loading via webhooks would be more appropriate.
- **Simple schema**: Two tables (`subscriptions`, `invoices`) rather than a fully normalized data model. The focus is on correct MRR logic, not schema design.
- **Flask API layer**: Decouples the React frontend from BigQuery. In production, this could be a Cloud Function or Cloud Run service.
- **Demo fallback data**: The React app includes fallback demo data so the frontend renders even without a live API connection.
