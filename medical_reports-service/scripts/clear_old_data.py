#!/usr/bin/env python3
"""
Clear all old report/note data for a fresh run.

Deletes:
  - All objects in the reports S3 bucket (old PDFs + old placeholder images)
  - All items in patient-results DynamoDB table (old reports)
  - All items in patient-notes DynamoDB table (old notes)

Does NOT touch:
  - patient-master table (keeps the 100 seeded patients)
  - medical-images bucket (already has 240 real images)

Usage:
    python scripts/clear_old_data.py
"""

import boto3
import time

ACCOUNT_ID = "<your-aws-account-id>"
REPORTS_BUCKET = f"medgemma-challenge-reports-{ACCOUNT_ID}"
RESULTS_TABLE = "medgemma-challenge-patient-results"
NOTES_TABLE = "medgemma-challenge-patient-notes"


def clear_s3_bucket(bucket_name):
    """Delete all objects in an S3 bucket."""
    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")
    deleted = 0

    for page in paginator.paginate(Bucket=bucket_name):
        contents = page.get("Contents", [])
        if not contents:
            continue
        objects = [{"Key": obj["Key"]} for obj in contents]
        s3.delete_objects(Bucket=bucket_name, Delete={"Objects": objects})
        deleted += len(objects)

    return deleted


def clear_dynamodb_table(table_name, key_schema):
    """Delete all items from a DynamoDB table using batch_writer."""
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)
    deleted = 0

    # Scan and delete in batches
    scan_kwargs = {"ProjectionExpression": ", ".join(k["AttributeName"] for k in key_schema)}
    done = False

    while not done:
        response = table.scan(**scan_kwargs)
        items = response.get("Items", [])

        if not items:
            break

        with table.batch_writer() as batch:
            for item in items:
                key = {k["AttributeName"]: item[k["AttributeName"]] for k in key_schema}
                batch.delete_item(Key=key)
                deleted += 1

        if deleted % 100 == 0 and deleted > 0:
            print(f"    ... deleted {deleted} items so far")

        if "LastEvaluatedKey" not in response:
            done = True
        else:
            scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

    return deleted


def main():
    print("=" * 60)
    print("CLEARING ALL OLD DATA FOR FRESH RUN")
    print("=" * 60)

    # 1. Clear reports S3 bucket
    print(f"\n1. Clearing S3 bucket: {REPORTS_BUCKET}")
    print("   (old PDFs + old placeholder image copies)")
    count = clear_s3_bucket(REPORTS_BUCKET)
    print(f"   Deleted {count} objects")

    # 2. Clear patient-results table
    print(f"\n2. Clearing DynamoDB table: {RESULTS_TABLE}")
    print("   (old reports with garbage images)")
    key_schema = [
        {"AttributeName": "patient_id", "KeyType": "HASH"},
        {"AttributeName": "report_id", "KeyType": "RANGE"},
    ]
    count = clear_dynamodb_table(RESULTS_TABLE, key_schema)
    print(f"   Deleted {count} items")

    # 3. Clear patient-notes table
    print(f"\n3. Clearing DynamoDB table: {NOTES_TABLE}")
    print("   (old patient notes)")
    key_schema = [
        {"AttributeName": "patient_id", "KeyType": "HASH"},
        {"AttributeName": "note_id", "KeyType": "RANGE"},
    ]
    count = clear_dynamodb_table(NOTES_TABLE, key_schema)
    print(f"   Deleted {count} items")

    # 4. Verify medical-images bucket is untouched
    s3 = boto3.client("s3")
    images_bucket = f"medgemma-challenge-medical-images-{ACCOUNT_ID}"
    paginator = s3.get_paginator("list_objects_v2")
    image_count = 0
    for page in paginator.paginate(Bucket=images_bucket):
        image_count += len(page.get("Contents", []))

    print(f"\n4. Medical images bucket (UNTOUCHED): {image_count} real images")

    # 5. Verify patient-master table is untouched
    dynamodb = boto3.resource("dynamodb")
    master_table = dynamodb.Table("medgemma-challenge-patient-master")
    patient_count = master_table.scan(Select="COUNT")["Count"]
    print(f"5. Patient master table (UNTOUCHED): {patient_count} patients")

    print()
    print("=" * 60)
    print("ALL CLEAR! Ready for a fresh run.")
    print("=" * 60)
    print()
    print("Next steps:")
    print("  1. Generate new reports:  curl -X POST <API_URL>/reports/generate")
    print("  2. Generate new notes:    curl -X POST <API_URL>/notes/generate")
    print("  3. Start the scheduler on DGX Spark to process them")


if __name__ == "__main__":
    main()
