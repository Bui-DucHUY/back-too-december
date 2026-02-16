-- =============================================================================
-- MRR View — Create this as a BigQuery view for the API to query
-- =============================================================================
-- Run once:
--   CREATE OR REPLACE VIEW `{PROJECT}.{DATASET}.v_monthly_mrr` AS (...)
-- =============================================================================

CREATE OR REPLACE VIEW `{PROJECT}.{DATASET}.v_monthly_mrr` AS

WITH month_spine AS (
    SELECT month_start
    FROM UNNEST(
        GENERATE_DATE_ARRAY(
            DATE_TRUNC(
                (SELECT DATE(MIN(created_at)) FROM `{PROJECT}.{DATASET}.subscriptions`),
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
                CAST(ROUND(plan_amount * quantity / (12.0 * plan_interval_count)) AS INT64)
            WHEN plan_interval = 'month' THEN
                CAST(ROUND(plan_amount * quantity / plan_interval_count) AS INT64)
            ELSE CAST(plan_amount * quantity AS INT64)
        END AS monthly_amount_cents
    FROM `{PROJECT}.{DATASET}.subscriptions`
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
ORDER BY m.month_start;
