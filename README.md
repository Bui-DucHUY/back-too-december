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
# Edit .env with your Stripe and GCP credentials
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Set up Stripe

1. Sign up at [dashboard.stripe.com](https://dashboard.stripe.com) (Developer/Test mode).
2. Copy your **test secret key** (`sk_test_...`) into `.env`.

### 4. Set up Google Cloud / BigQuery

1. Create a GCP project at [console.cloud.google.com](https://console.cloud.google.com).
2. Enable the **BigQuery API**.
3. Create a service account with **BigQuery Data Editor** and **BigQuery Job User** roles.
4. Download the JSON key file and set the path in `.env` (`GOOGLE_APPLICATION_CREDENTIALS`).
5. Set `GCP_PROJECT_ID` in `.env`.

### 5. Generate test data (Step 1)

```bash
python scripts/generate_data.py
```

This creates ~75 customers with subscriptions across 5 Stripe Test Clocks and advances them through 6 months of billing history. Takes ~10-15 minutes due to test clock advancement.

**What it does:**
- Creates 6 subscription plans (Starter $29/mo, Pro $79/mo, Business $199/mo, Enterprise $499/mo, plus annual variants)
- Distributes customers across plans with realistic weighting
- Simulates churn (~15%) and payment failures (~10%) across months
- Outputs a `data_manifest.json` for reference

### 6. Run ETL pipeline (Step 2)

```bash
python scripts/etl_stripe_to_bq.py
```

Extracts all subscriptions and invoices from Stripe, saves local JSON copies, and loads them into BigQuery tables (`mrr_dashboard.subscriptions` and `mrr_dashboard.invoices`).

### 7. Verify SQL logic (Step 3)

Open `sql/mrr_calculation.sql` in the [BigQuery Console](https://console.cloud.google.com/bigquery) and run it (replace `{PROJECT}` and `{DATASET}` with your values). You should see output like:

| month   | active_subscriptions | active_customers | mrr_amount |
|---------|---------------------|------------------|------------|
| 2025-09 | 52                  | 48               | 4,280      |
| 2025-10 | 58                  | 53               | 5,120      |
| ...     | ...                 | ...              | ...        |

Optionally, create the view for the API:
```sql
-- In BigQuery Console, run sql/create_mrr_view.sql
-- (replace {PROJECT} and {DATASET} placeholders)
```

### 8. Start the API server

```bash
python scripts/api_server.py
```

Runs on `http://localhost:5001`. Test it:
```bash
curl http://localhost:5001/api/mrr
```

### 9. Start the React frontend (Step 4)

```bash
cd frontend
npm install
npm start
```

Opens at `http://localhost:3000`. The React app proxies API requests to `localhost:5001`.

---

## Project Structure

```
mrr-dashboard/
├── scripts/
│   ├── generate_data.py       # Step 1: Stripe test data generator
│   ├── etl_stripe_to_bq.py   # Step 2: ETL pipeline (Stripe → BigQuery)
│   ├── api_server.py          # Flask API serving BigQuery data
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
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

---

## MRR Calculation Logic

MRR is **not** just revenue — it's the **normalized monthly value of active recurring subscriptions**.

The SQL logic:

1. **Generates a month spine** covering the full date range of the data.
2. **Determines each subscription's active window** — from `created_at` to `ended_at` / `canceled_at`.
3. **Normalizes plan amounts to monthly values:**
   - Monthly plans: `plan_amount × quantity`
   - Annual plans: `plan_amount × quantity ÷ 12`
4. **Joins subscriptions × months** to count which subs were active during each month.
5. **Aggregates** to get total MRR per month, with MoM change.

Only subscriptions with status `active`, `past_due`, or `canceled` (before their end date) are counted. Trialing subscriptions are excluded since they don't generate revenue.

---

## Design Decisions

- **Test Clocks over manual timestamps**: Using Stripe's Test Clock API ensures invoices, charges, and subscription lifecycle events are generated authentically by Stripe, not mocked.
- **Full-refresh ETL**: The pipeline truncates and reloads tables on each run. For production, incremental loading with event-based triggers would be better.
- **Simple schema**: Two tables (`subscriptions`, `invoices`) rather than a fully normalized data model. The focus is on correct MRR logic, not schema design.
- **Flask API layer**: Decouples the React frontend from BigQuery directly. In production, this could be a Cloud Function or Cloud Run service.
- **Demo fallback data**: The React app includes hardcoded demo data so the frontend can be evaluated even without a live API connection.

---

## Interview Prep Notes

**Accuracy Check:** The SQL-calculated MRR should closely match Stripe's built-in analytics for active subscriptions. Discrepancies can arise from: (a) timing of test clock advancement vs. subscription period boundaries, (b) prorations from mid-cycle changes, (c) how "past due" subs are counted.

**Verification:** Cross-reference the SQL output against Stripe Dashboard → Billing → MRR. Also validate by manually summing active subscription amounts for a given month.

**Architecture (Production):** Use Stripe webhooks to trigger incremental updates — a Cloud Function listens for `invoice.paid`, `customer.subscription.updated`, etc., and upserts into BigQuery. Supplement with a daily batch reconciliation job.

**Retrospective:** For a production system handling millions: use Stripe's event stream (webhooks + Events API) for real-time data, partition BigQuery tables by month, add data quality checks and alerting, and implement idempotent processing to handle webhook retries.
