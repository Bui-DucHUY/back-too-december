"""
Step 1: Stripe Test Data Generator
===================================
Creates ~50-100 customers with subscriptions using Stripe Test Clocks
to simulate 6 months of billing history.

Key constraints (from Stripe docs):
  - Test clocks can only advance forward in time
  - Max advance = 2 intervals from the shortest subscription
    (for monthly subs, that means max 2 months per advance call)
  - Each customer must be attached to a test clock at creation time
  - Clock status must be "ready" before the next advance

Usage:
    pip install stripe python-dotenv
    export STRIPE_SECRET_KEY=sk_test_...
    python scripts/generate_data.py
"""

import stripe
import os
import time
import random
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
if not stripe.api_key:
    raise ValueError("STRIPE_SECRET_KEY environment variable is required")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
NUM_CUSTOMERS = 75          # Target ~50-100 customers
NUM_TEST_CLOCKS = 5         # Spread customers across clocks (Stripe limits objects per clock)
MONTHS_TO_SIMULATE = 6
CUSTOMERS_PER_CLOCK = NUM_CUSTOMERS // NUM_TEST_CLOCKS

# Subscription plans
PLAN_CONFIG = [
    {"name": "Starter",          "amount": 2900,   "interval": "month"},  # $29/mo
    {"name": "Pro",              "amount": 7900,   "interval": "month"},  # $79/mo
    {"name": "Business",         "amount": 19900,  "interval": "month"},  # $199/mo
    {"name": "Enterprise",       "amount": 49900,  "interval": "month"},  # $499/mo
    {"name": "Pro Annual",       "amount": 79000,  "interval": "year"},   # $790/yr
    {"name": "Business Annual",  "amount": 199000, "interval": "year"},   # $1990/yr
]

PLAN_WEIGHTS = [30, 25, 15, 5, 15, 10]  # Distribution (Starter-heavy)
CHURN_RATE = 0.15       # ~15% cancel during the 6-month window
PAST_DUE_RATE = 0.10    # ~10% will have payment failures

FIRST_NAMES = [
    "Alice", "Bob", "Carol", "Dave", "Eve", "Frank", "Grace", "Hank",
    "Iris", "Jack", "Kate", "Leo", "Mia", "Nick", "Olivia", "Pete",
    "Quinn", "Rosa", "Sam", "Tina", "Uma", "Victor", "Wendy", "Xander",
]
LAST_NAMES = [
    "Smith", "Johnson", "Lee", "Brown", "Garcia", "Wilson", "Chen",
    "Taylor", "Anderson", "Thomas", "Martinez", "Davis", "Lopez", "Park",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def wait_for_clock_ready(clock_id: str, timeout: int = 180):
    """Poll until a test clock's status is 'ready'."""
    for _ in range(timeout // 3):
        clock = stripe.test_helpers.TestClock.retrieve(clock_id)
        if clock.status == "ready":
            return True
        if clock.status == "internal_failure":
            print(f"    WARN: Clock {clock_id} hit internal_failure, retrying...")
            return False
        time.sleep(3)
    print(f"    WARN: Clock {clock_id} timed out waiting for 'ready' status.")
    return False


# ---------------------------------------------------------------------------
# Step 1: Create Products & Prices
# ---------------------------------------------------------------------------

def create_products_and_prices():
    """Create Stripe Products + Prices for each plan."""
    print("\n--- Creating products and prices ---")
    prices = []

    for plan in PLAN_CONFIG:
        product = stripe.Product.create(name=f"MRR Dashboard - {plan['name']}")
        price = stripe.Price.create(
            product=product.id,
            unit_amount=plan["amount"],
            currency="usd",
            recurring={"interval": plan["interval"]},
        )
        prices.append({
            "price_id": price.id,
            "product_id": product.id,
            "name": plan["name"],
            "amount": plan["amount"],
            "interval": plan["interval"],
        })
        print(f"  {plan['name']}: ${plan['amount']/100:.2f}/{plan['interval']} (price={price.id})")

    return prices


# ---------------------------------------------------------------------------
# Step 2: Create Test Clocks + Customers with Subscriptions
# ---------------------------------------------------------------------------

def create_customer_on_clock(clock_id: str, prices: list, index: int):
    """
    Create a customer attached to a test clock, attach a test card,
    and start a subscription.
    """
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    email = f"{first.lower()}.{last.lower()}.{index}@example.com"

    # 1. Create customer attached to the test clock
    customer = stripe.Customer.create(
        name=f"{first} {last}",
        email=email,
        test_clock=clock_id,
    )

    # 2. Attach a test card as the default payment method
    #    (pm_card_visa is a reusable test PaymentMethod in test mode)
    pm = stripe.PaymentMethod.attach("pm_card_visa", customer=customer.id)
    stripe.Customer.modify(
        customer.id,
        invoice_settings={"default_payment_method": pm.id},
    )

    # 3. Pick a random plan
    chosen_price = random.choices(prices, weights=PLAN_WEIGHTS, k=1)[0]

    # 4. Create the subscription — charge_automatically with the attached card
    subscription = stripe.Subscription.create(
        customer=customer.id,
        items=[{"price": chosen_price["price_id"]}],
    )

    print(f"    Customer #{index + 1}: {first} {last} → {chosen_price['name']} "
          f"(sub={subscription.id}, status={subscription.status})")

    return {
        "customer_id": customer.id,
        "subscription_id": subscription.id,
        "plan": chosen_price["name"],
        "amount": chosen_price["amount"],
        "interval": chosen_price["interval"],
        "clock_id": clock_id,
        "status": "active",
    }


# ---------------------------------------------------------------------------
# Step 3: Simulate Churn & Payment Failures
# ---------------------------------------------------------------------------

def simulate_churn(customers_info: list, month: int):
    """Cancel some subscriptions and break payment methods for others."""
    active = [c for c in customers_info if c.get("status") == "active"]
    if not active:
        return

    # How many to churn/fail this month
    num_churn = max(1, int(len(active) * CHURN_RATE / MONTHS_TO_SIMULATE))
    num_fail = max(1, int(len(active) * PAST_DUE_RATE / MONTHS_TO_SIMULATE))

    # --- Cancellations ---
    to_cancel = random.sample(active, min(num_churn, len(active)))
    for c in to_cancel:
        try:
            stripe.Subscription.modify(c["subscription_id"], cancel_at_period_end=True)
            c["status"] = "canceling"
            print(f"    Canceling: {c['customer_id']} ({c['plan']})")
        except Exception as e:
            print(f"    Cancel error {c['customer_id']}: {e}")

    # --- Payment failures (switch to a declining card) ---
    still_active = [c for c in customers_info if c.get("status") == "active"]
    to_fail = random.sample(still_active, min(num_fail, len(still_active)))
    for c in to_fail:
        try:
            # Attach a card that always declines
            pm = stripe.PaymentMethod.attach("pm_card_chargeDeclined", customer=c["customer_id"])
            stripe.Customer.modify(
                c["customer_id"],
                invoice_settings={"default_payment_method": pm.id},
            )
            c["status"] = "past_due_pending"
            print(f"    Declining card set: {c['customer_id']} ({c['plan']})")
        except Exception as e:
            print(f"    Payment fail setup error {c['customer_id']}: {e}")


# ---------------------------------------------------------------------------
# Step 4: Advance Clocks Month-by-Month
# ---------------------------------------------------------------------------

def advance_all_clocks(clock_ids: list, target_ts: int):
    """Advance all clocks to a target timestamp, waiting for each to be ready."""
    for clock_id in clock_ids:
        print(f"  Advancing clock {clock_id}...")
        try:
            stripe.test_helpers.TestClock.advance(clock_id, frozen_time=target_ts)
        except stripe.error.InvalidRequestError as e:
            print(f"    Advance error: {e}")
            continue

    # Wait for all clocks to be ready before proceeding
    print("  Waiting for clocks to finish advancing...")
    for clock_id in clock_ids:
        ready = wait_for_clock_ready(clock_id)
        if ready:
            print(f"    Clock {clock_id}: ready")
        else:
            print(f"    Clock {clock_id}: NOT ready (may need manual check)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  MRR Dashboard — Stripe Test Data Generator")
    print("=" * 60)

    # 1. Create products + prices
    prices = create_products_and_prices()

    with open("scripts/price_config.json", "w") as f:
        json.dump(prices, f, indent=2)

    # 2. Calculate time window
    now = datetime.utcnow()
    start_time = now - timedelta(days=MONTHS_TO_SIMULATE * 30)
    start_ts = int(start_time.timestamp())
    print(f"\nSimulation start: {start_time.strftime('%Y-%m-%d')} (frozen time)")
    print(f"Simulation end:   ~{now.strftime('%Y-%m-%d')} (today)")

    # 3. Create test clocks
    print("\n--- Creating test clocks ---")
    clock_ids = []
    for i in range(NUM_TEST_CLOCKS):
        clock = stripe.test_helpers.TestClock.create(
            frozen_time=start_ts,
            name=f"MRR-Sim-{i + 1}",
        )
        clock_ids.append(clock.id)
        print(f"  Clock {i + 1}: {clock.id}")

    # 4. Create customers + subscriptions on each clock
    all_customers = []
    for clock_idx, clock_id in enumerate(clock_ids):
        print(f"\n--- Clock {clock_idx + 1}/{NUM_TEST_CLOCKS}: Creating customers ---")
        for i in range(CUSTOMERS_PER_CLOCK):
            global_idx = clock_idx * CUSTOMERS_PER_CLOCK + i
            try:
                info = create_customer_on_clock(clock_id, prices, global_idx)
                all_customers.append(info)
            except Exception as e:
                print(f"    ERROR creating customer #{global_idx + 1}: {e}")
            time.sleep(0.3)  # Gentle rate limiting

    print(f"\nTotal customers created: {len(all_customers)}")

    # 5. Advance month by month
    for month in range(1, MONTHS_TO_SIMULATE + 1):
        target_time = start_time + timedelta(days=month * 30)
        target_ts = int(target_time.timestamp())

        print(f"\n{'=' * 60}")
        print(f"  MONTH {month}/{MONTHS_TO_SIMULATE} → {target_time.strftime('%Y-%m-%d')}")
        print(f"{'=' * 60}")

        # Simulate churn starting from month 2
        if month >= 2:
            simulate_churn(all_customers, month)

        advance_all_clocks(clock_ids, target_ts)

    # 6. Save manifest
    manifest = {
        "generated_at": now.isoformat(),
        "start_date": start_time.isoformat(),
        "months_simulated": MONTHS_TO_SIMULATE,
        "num_customers": len(all_customers),
        "clock_ids": clock_ids,
        "customers": all_customers,
        "prices": prices,
    }
    with open("scripts/data_manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\n{'=' * 60}")
    print("  DATA GENERATION COMPLETE")
    print(f"  Customers: {len(all_customers)}")
    print(f"  Clocks:    {len(clock_ids)}")
    print(f"  Months:    {MONTHS_TO_SIMULATE}")
    print(f"  Manifest:  scripts/data_manifest.json")
    print(f"{'=' * 60}")
    print("\nNext step: python scripts/etl_stripe_to_bq.py")


if __name__ == "__main__":
    main()
