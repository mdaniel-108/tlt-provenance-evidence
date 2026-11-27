r"""Export all server records (telemetry NDJSON, proxy JSON, source records/packs) of one test participant
from the LOCAL MinIO (http://127.0.0.1:9000) into D:\tlt\trace\export\<participant>\ (files kept as stored).

  python code/trace_driver/export_run.py <participant> [...]
"""
import sys
from pathlib import Path

import boto3

S3 = boto3.client("s3", endpoint_url="http://127.0.0.1:9000", aws_access_key_id="minioadmin",
                  aws_secret_access_key="minioadmin", region_name="us-east-1")
BUCKET = "llm-cp-experiment-raw"
OUT = Path(r"D:\tlt\trace\export")


def export(p):
    n = 0
    for page in S3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=f"raw/{p}/"):
        for o in page.get("Contents", []):
            dst = OUT / o["Key"][len("raw/"):]
            dst.parent.mkdir(parents=True, exist_ok=True)
            S3.download_file(BUCKET, o["Key"], str(dst))
            n += 1
    return n


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(p, export(p))
