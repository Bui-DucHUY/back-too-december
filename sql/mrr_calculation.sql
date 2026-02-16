-- =============================================================================
-- MRR Calculation — BigQuery SQL
-- =============================================================================
-- MRR (Monthly Recurring Revenue) is the normalized monthly value of all
-- active recurring subscriptions. This means:
--   - Monthly plans: plan_amount * quantity
--   - Yearly plans:  (plan_amount * quantity) / 12
--   - Only count subscriptions that were ACTIVE during each month
--
-- Output: month | mrr_amount (in dollars)
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. Generate a month spine covering our data range
-- ---------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------
-- 2. Determine each subscription's active window
--    A subscription contributes to MRR for any month where it was active
--    at some point during that month.
-- ---------------------------------------------------------------------------
subscription_windows AS (
    SELECT
        subscription_id,
        customer_id,
        plan_amount,
        plan_interval,
        plan_interval_count,
        quantity,
        currency,
        status,
        DATE(created_at) AS start_date,
        -- End date: use ended_at if fully ended, canceled_at if canceled,
        -- or current_period_end if cancel_at_period_end is true.
        -- NULL means still active.
        COALESCE(
            DATE(ended_at),
            CASE WHEN status = 'canceled' THEN DATE(canceled_at) END,
            CASE WHEN cancel_at_period_end = TRUE THEN DATE(current_period_end) END
        ) AS end_date,

        -- Calculate the normalized monthly amount (in cents)
        CASE
            WHEN plan_interval = 'year' THEN
                CAST(ROUND(plan_amount * quantity / (12.0 * plan_interval_count)) AS INT64)
            WHEN plan_interval = 'month' THEN
                CAST(ROUND(plan_amount * quantity / plan_interval_count) AS INT64)
            WHEN plan_interval = 'week' THEN
                CAST(ROUND(plan_amount * quantity * (52.0 / 12.0) / plan_interval_count) AS INT64)
            WHEN plan_interval = 'day' THEN
                CAST(ROUND(plan_amount * quantity * (365.25 / 12.0) / plan_interval_count) AS INT64)
            ELSE
                CAST(plan_amount * quantity AS INT64)
        END AS monthly_amount_cents

    FROM `{PROJECT}.{DATASET}.subscriptions`
    -- Only count subscriptions that were/are in a revenue-generating state
    WHERE status IN ('active', 'past_due', 'canceled', 'trialing')
),

-- ---------------------------------------------------------------------------
-- 3. Join subscriptions × months to figure out which subs were active each month
-- ---------------------------------------------------------------------------
mrr_by_sub_month AS (
    SELECT
        m.month_start,
        s.subscription_id,
        s.customer_id,
        s.monthly_amount_cents,
        s.status,
        s.plan_interval
    FROM month_spine m
    CROSS JOIN subscription_windows s
    WHERE
        -- Subscription started on or before the end of this month
        s.start_date <= DATE_ADD(m.month_start, INTERVAL 1 MONTH)
        -- Subscription hadn't ended before this month started
        AND (s.end_date IS NULL OR s.end_date >= m.month_start)
        -- Exclude trialing subs that haven't converted (no revenue yet)
        AND s.status != 'trialing'
),

-- ---------------------------------------------------------------------------
-- 4. Aggregate to monthly MRR
-- ---------------------------------------------------------------------------
monthly_mrr AS (
    SELECT
        month_start                                     AS month,
        COUNT(DISTINCT subscription_id)                 AS active_subscriptions,
        COUNT(DISTINCT customer_id)                     AS active_customers,
        SUM(monthly_amount_cents)                       AS mrr_cents,
        ROUND(SUM(monthly_amount_cents) / 100.0, 2)    AS mrr_amount
    FROM mrr_by_sub_month
    GROUP BY month_start
)

-- ---------------------------------------------------------------------------
-- 5. Final output with MoM change
-- ---------------------------------------------------------------------------
SELECT
    FORMAT_DATE('%Y-%m', month) AS month,
    active_subscriptions,
    active_customers,
    mrr_amount,
    mrr_cents,
    LAG(mrr_amount) OVER (ORDER BY month)                           AS prev_month_mrr,
    ROUND(mrr_amount - COALESCE(LAG(mrr_amount) OVER (ORDER BY month), 0), 2) AS mrr_change,
    CASE
        WHEN LAG(mrr_amount) OVER (ORDER BY month) IS NULL THEN NULL
        WHEN LAG(mrr_amount) OVER (ORDER BY month) = 0 THEN NULL
        ELSE ROUND(
            (mrr_amount - LAG(mrr_amount) OVER (ORDER BY month))
            / LAG(mrr_amount) OVER (ORDER BY month) * 100, 1
        )
    END AS mrr_change_pct
FROM monthly_mrr
ORDER BY month;
