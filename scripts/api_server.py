"""
Step 4 (Backend): Simple Flask API for MRR data
=================================================
Serves BigQuery MRR data as JSON for the React frontend.

Usage:
    pip install flask flask-cors google-cloud-bigquery python-dotenv
    export GOOGLE_APPLICATION_CREDENTIALS=path/to/service-account.json
    export GCP_PROJECT_ID=your-project-id
    export BQ_DATASET=mrr_dashboard
    python scripts/api_server.py
"""

import os
from flask import Flask, jsonify
from flask_cors import CORS
from google.cloud import bigquery
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)  # Allow React dev server to call this API

GCP_PROJECT = os.environ.get("GCP_PROJECT_ID")
BQ_DATASET = os.environ.get("BQ_DATASET", "mrr_dashboard")

bq_client = bigquery.Client(project=GCP_PROJECT)


@app.route("/api/mrr", methods=["GET"])
def get_mrr():
    """Return monthly MRR data as JSON."""
    query = f"""
    WITH month_spine AS (
        SELECT month_start
        FROM UNNEST(
            GENERATE_DATE_ARRAY(
                DATE_TRUNC(
                    (SELECT DATE(MIN(created_at)) FROM `{GCP_PROJECT}.{BQ_DATASET}.subscriptions`),
                    MONTH
                ),
                DATE_TRUNC(CURRENT_DATE(), MONTH),
                INTERVAL 1 MONTH
            )
        ) AS month_start
    ),
    subscription_windows AS (
        SELECT
            subscription_id,
            customer_id,
            DATE(created_at) AS start_date,
            COALESCE(
                DATE(ended_at),
                CASE WHEN status = 'canceled' THEN DATE(canceled_at) END,
                CASE WHEN cancel_at_period_end = TRUE THEN DATE(current_period_end) END
            ) AS end_date,
            CASE
                WHEN plan_interval = 'year' THEN
                    CAST(ROUND(plan_amount * quantity / (12.0 * COALESCE(plan_interval_count, 1))) AS INT64)
                WHEN plan_interval = 'month' THEN
                    CAST(ROUND(plan_amount * quantity / COALESCE(plan_interval_count, 1)) AS INT64)
                ELSE CAST(plan_amount * quantity AS INT64)
            END AS monthly_amount_cents
        FROM `{GCP_PROJECT}.{BQ_DATASET}.subscriptions`
        WHERE status IN ('active', 'past_due', 'canceled')
    )
    SELECT
        FORMAT_DATE('%Y-%m', m.month_start) AS month,
        COUNT(DISTINCT s.subscription_id) AS active_subscriptions,
        COUNT(DISTINCT s.customer_id) AS active_customers,
        ROUND(SUM(s.monthly_amount_cents) / 100.0, 2) AS mrr_amount
    FROM month_spine m
    CROSS JOIN subscription_windows s
    WHERE s.start_date <= DATE_ADD(m.month_start, INTERVAL 1 MONTH)
      AND (s.end_date IS NULL OR s.end_date >= m.month_start)
    GROUP BY m.month_start
    ORDER BY m.month_start
    """

    try:
        results = bq_client.query(query).result()
        data = []
        for row in results:
            data.append({
                "month": row.month,
                "active_subscriptions": row.active_subscriptions,
                "active_customers": row.active_customers,
                "mrr_amount": float(row.mrr_amount),
            })
        return jsonify({"data": data, "status": "ok"})

    except Exception as e:
        return jsonify({"error": str(e), "status": "error"}), 500


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("API_PORT", 5001))
    print(f"MRR API server starting on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
