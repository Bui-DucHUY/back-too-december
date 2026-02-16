"""
Step 2: ETL Pipeline — Stripe → BigQuery
==========================================
Extracts subscriptions and invoices from Stripe using the data manifest,
and loads into BigQuery tables.

Compatible with Stripe Python SDK v14+ (attribute access changes).

Usage:
    pip install stripe google-cloud-bigquery python-dotenv
    python scripts/etl_stripe_to_bq.py
"""

import stripe
import os
import json
from datetime import datetime, timezone
from google.cloud import bigquery
from dotenv import load_dotenv

load_dotenv()

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
GCP_PROJECT = os.environ.get("GCP_PROJECT_ID")
BQ_DATASET = os.environ.get("BQ_DATASET", "mrr_dashboard")

if not stripe.api_key:
    raise ValueError("STRIPE_SECRET_KEY is required")
if not GCP_PROJECT:
    raise ValueError("GCP_PROJECT_ID is required")

bq_client = bigquery.Client(project=GCP_PROJECT)

SUBSCRIPTIONS_SCHEMA = [
    bigquery.SchemaField("subscription_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("customer_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("customer_email", "STRING"),
    bigquery.SchemaField("customer_name", "STRING"),
    bigquery.SchemaField("status", "STRING"),
    bigquery.SchemaField("price_id", "STRING"),
    bigquery.SchemaField("product_id", "STRING"),
    bigquery.SchemaField("plan_amount", "INTEGER"),
    bigquery.SchemaField("plan_interval", "STRING"),
    bigquery.SchemaField("plan_interval_count", "INTEGER"),
    bigquery.SchemaField("currency", "STRING"),
    bigquery.SchemaField("quantity", "INTEGER"),
    bigquery.SchemaField("created_at", "TIMESTAMP"),
    bigquery.SchemaField("current_period_start", "TIMESTAMP"),
    bigquery.SchemaField("current_period_end", "TIMESTAMP"),
    bigquery.SchemaField("canceled_at", "TIMESTAMP"),
    bigquery.SchemaField("cancel_at_period_end", "BOOLEAN"),
    bigquery.SchemaField("ended_at", "TIMESTAMP"),
    bigquery.SchemaField("trial_start", "TIMESTAMP"),
    bigquery.SchemaField("trial_end", "TIMESTAMP"),
    bigquery.SchemaField("extracted_at", "TIMESTAMP", mode="REQUIRED"),
]

INVOICES_SCHEMA = [
    bigquery.SchemaField("invoice_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("customer_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("subscription_id", "STRING"),
    bigquery.SchemaField("status", "STRING"),
    bigquery.SchemaField("amount_due", "INTEGER"),
    bigquery.SchemaField("amount_paid", "INTEGER"),
    bigquery.SchemaField("currency", "STRING"),
    bigquery.SchemaField("period_start", "TIMESTAMP"),
    bigquery.SchemaField("period_end", "TIMESTAMP"),
    bigquery.SchemaField("created_at", "TIMESTAMP"),
    bigquery.SchemaField("paid_at", "TIMESTAMP"),
    bigquery.SchemaField("hosted_invoice_url", "STRING"),
    bigquery.SchemaField("extracted_at", "TIMESTAMP", mode="REQUIRED"),
]


def ensure_dataset_and_tables():
    dataset_ref = bigquery.DatasetReference(GCP_PROJECT, BQ_DATASET)
    dataset = bigquery.Dataset(dataset_ref)
    dataset.location = "US"
    try:
        bq_client.create_dataset(dataset, exists_ok=True)
        print(f"Dataset '{BQ_DATASET}' is ready.")
    except Exception as e:
        print(f"Dataset creation error: {e}")

    for table_name, schema in [("subscriptions", SUBSCRIPTIONS_SCHEMA),
                                ("invoices", INVOICES_SCHEMA)]:
        table_ref = dataset_ref.table(table_name)
        table = bigquery.Table(table_ref, schema=schema)
        table = bq_client.create_table(table, exists_ok=True)
        print(f"Table '{BQ_DATASET}.{table_name}' is ready.")


def load_manifest() -> dict | None:
    manifest_path = "scripts/data_manifest.json"
    if not os.path.exists(manifest_path):
        print(f"  WARNING: {manifest_path} not found")
        return None
    with open(manifest_path) as f:
        return json.load(f)


def _ts_to_iso(ts) -> str | None:
    if ts is None:
        return None
    if isinstance(ts, str):
        return ts
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _safe_get(obj, key, default=None):
    """Safely get an attribute from a Stripe object, handling v14+ changes."""
    # Try attribute access
    try:
        val = getattr(obj, key, None)
        if val is not None:
            return val
    except Exception:
        pass

    # Try dict-style access
    try:
        val = obj.get(key, None)
        if val is not None:
            return val
    except Exception:
        pass

    # Try bracket access
    try:
        val = obj[key]
        if val is not None:
            return val
    except (KeyError, TypeError, IndexError):
        pass

    return default


# ---------------------------------------------------------------------------
# Extract subscriptions
# ---------------------------------------------------------------------------
def extract_subscriptions_via_manifest(manifest: dict) -> list[dict]:
    """Fetch each subscription directly by ID, with safe attribute access."""
    print("Extracting subscriptions by ID from manifest...")
    subscriptions = []
    now = datetime.now(timezone.utc).isoformat()

    # First, let's inspect one subscription to see its actual structure
    test_sub_id = manifest["customers"][0]["subscription_id"]
    print(f"\n  Inspecting subscription structure ({test_sub_id})...")
    try:
        test_sub = stripe.Subscription.retrieve(test_sub_id)
        # Print all available keys
        sub_dict = dict(test_sub)
        print(f"  Available keys: {list(sub_dict.keys())}")
    except Exception as e:
        print(f"  Inspect error: {e}")

    for entry in manifest["customers"]:
        sub_id = entry["subscription_id"]
        cust_id = entry["customer_id"]

        try:
            sub = stripe.Subscription.retrieve(sub_id)
            cust = stripe.Customer.retrieve(cust_id)

            # Convert to dict for safe access
            sub_dict = dict(sub)

            # Get subscription item and price
            items_data = sub_dict.get("items", {})
            if hasattr(items_data, "data"):
                item_list = items_data.data
            elif isinstance(items_data, dict):
                item_list = items_data.get("data", [])
            else:
                item_list = []

            item = item_list[0] if item_list else None
            price = None
            plan_amount = None
            plan_interval = None
            plan_interval_count = None
            price_id = None
            product_id = None
            quantity = 1

            if item:
                item_dict = dict(item) if hasattr(item, '__iter__') else {}
                price = _safe_get(item, "price")
                quantity = _safe_get(item, "quantity", 1)

                if price:
                    price_id = _safe_get(price, "id")
                    product_id = _safe_get(price, "product")
                    plan_amount = _safe_get(price, "unit_amount")
                    recurring = _safe_get(price, "recurring")
                    if recurring:
                        plan_interval = _safe_get(recurring, "interval")
                        plan_interval_count = _safe_get(recurring, "interval_count", 1)

            row = {
                "subscription_id": sub_dict.get("id", sub_id),
                "customer_id": cust.id,
                "customer_email": _safe_get(cust, "email"),
                "customer_name": _safe_get(cust, "name"),
                "status": sub_dict.get("status"),
                "price_id": price_id,
                "product_id": product_id,
                "plan_amount": plan_amount,
                "plan_interval": plan_interval,
                "plan_interval_count": plan_interval_count,
                "currency": sub_dict.get("currency"),
                "quantity": quantity,
                "created_at": _ts_to_iso(sub_dict.get("created")),
                "current_period_start": _ts_to_iso(sub_dict.get("current_period_start")),
                "current_period_end": _ts_to_iso(sub_dict.get("current_period_end")),
                "canceled_at": _ts_to_iso(sub_dict.get("canceled_at")),
                "cancel_at_period_end": sub_dict.get("cancel_at_period_end", False),
                "ended_at": _ts_to_iso(sub_dict.get("ended_at")),
                "trial_start": _ts_to_iso(sub_dict.get("trial_start")),
                "trial_end": _ts_to_iso(sub_dict.get("trial_end")),
                "extracted_at": now,
            }
            subscriptions.append(row)
            print(f"  OK: {sub_id} status={sub_dict.get('status')} ({_safe_get(cust, 'name')})")

        except Exception as e:
            print(f"  ERROR {sub_id}: {type(e).__name__}: {e}")

    print(f"\n  Extracted {len(subscriptions)} subscriptions")
    return subscriptions


# ---------------------------------------------------------------------------
# Extract invoices
# ---------------------------------------------------------------------------
def extract_invoices_via_manifest(manifest: dict) -> list[dict]:
    """Fetch invoices for each customer in the manifest."""
    print("\nExtracting invoices by customer from manifest...")
    invoices = []
    now = datetime.now(timezone.utc).isoformat()
    seen_ids = set()

    # Inspect one invoice first
    test_cust_id = manifest["customers"][0]["customer_id"]
    print(f"  Inspecting invoice structure for {test_cust_id}...")
    try:
        test_invs = stripe.Invoice.list(customer=test_cust_id, limit=1)
        if test_invs.data:
            inv_dict = dict(test_invs.data[0])
            print(f"  Available keys: {list(inv_dict.keys())}")
    except Exception as e:
        print(f"  Inspect error: {e}")

    for entry in manifest["customers"]:
        cust_id = entry["customer_id"]
        try:
            result = stripe.Invoice.list(customer=cust_id, limit=100)
            for inv in result.data:
                inv_dict = dict(inv)

                if inv_dict.get("id") in seen_ids:
                    continue
                seen_ids.add(inv_dict.get("id"))

                # Safe access for status_transitions
                paid_at = None
                st = inv_dict.get("status_transitions")
                if st:
                    if hasattr(st, "paid_at"):
                        paid_at = st.paid_at
                    elif isinstance(st, dict):
                        paid_at = st.get("paid_at")

                row = {
                    "invoice_id": inv_dict.get("id"),
                    "customer_id": inv_dict.get("customer"),
                    "subscription_id": inv_dict.get("subscription"),
                    "status": inv_dict.get("status"),
                    "amount_due": inv_dict.get("amount_due"),
                    "amount_paid": inv_dict.get("amount_paid"),
                    "currency": inv_dict.get("currency"),
                    "period_start": _ts_to_iso(inv_dict.get("period_start")),
                    "period_end": _ts_to_iso(inv_dict.get("period_end")),
                    "created_at": _ts_to_iso(inv_dict.get("created")),
                    "paid_at": _ts_to_iso(paid_at),
                    "hosted_invoice_url": inv_dict.get("hosted_invoice_url"),
                    "extracted_at": now,
                }
                invoices.append(row)

            if len(result.data) > 0:
                print(f"  {cust_id}: {len(result.data)} invoices")

        except Exception as e:
            print(f"  ERROR {cust_id}: {type(e).__name__}: {e}")

    print(f"\n  Extracted {len(invoices)} invoices")
    return invoices


def load_to_bigquery(table_name: str, rows: list[dict], schema: list):
    if not rows:
        print(f"  No rows to load for {table_name}.")
        return

    table_ref = f"{GCP_PROJECT}.{BQ_DATASET}.{table_name}"
    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    )
    job = bq_client.load_table_from_json(rows, table_ref, job_config=job_config)
    job.result()
    print(f"  Loaded {len(rows)} rows into {table_ref}.")


def main():
    print("=" * 60)
    print("MRR Dashboard — ETL: Stripe → BigQuery")
    print("=" * 60)
    print(f"\nStripe API key: {stripe.api_key[:12]}...{stripe.api_key[-4:]}")
    print(f"GCP Project: {GCP_PROJECT}")
    print(f"BQ Dataset: {BQ_DATASET}")

    manifest = load_manifest()
    if not manifest:
        print("\nERROR: No data_manifest.json found. Run generate_data.py first.")
        return

    print(f"Manifest: {manifest['num_customers']} customers, {len(manifest['clock_ids'])} clocks\n")

    ensure_dataset_and_tables()

    subscriptions = extract_subscriptions_via_manifest(manifest)
    invoices = extract_invoices_via_manifest(manifest)

    os.makedirs("scripts/extracts", exist_ok=True)
    with open("scripts/extracts/subscriptions.json", "w") as f:
        json.dump(subscriptions, f, indent=2, default=str)
    with open("scripts/extracts/invoices.json", "w") as f:
        json.dump(invoices, f, indent=2, default=str)
    print("  Local extracts saved to scripts/extracts/")

    load_to_bigquery("subscriptions", subscriptions, SUBSCRIPTIONS_SCHEMA)
    load_to_bigquery("invoices", invoices, INVOICES_SCHEMA)

    print(f"\n{'=' * 60}")
    print("ETL complete!")
    print(f"  Subscriptions loaded: {len(subscriptions)}")
    print(f"  Invoices loaded:      {len(invoices)}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
