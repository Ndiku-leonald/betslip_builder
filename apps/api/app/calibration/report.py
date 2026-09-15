"""Print reliability buckets from a JSON list of {probability, outcome} rows."""
import argparse
import json
from app.evaluation.metrics import reliability_buckets

parser = argparse.ArgumentParser(); parser.add_argument("input", help="JSON file containing probability/outcome rows")
args = parser.parse_args()
items = json.loads(open(args.input, encoding="utf-8").read())
print(json.dumps(reliability_buckets([item["probability"] for item in items], [item["outcome"] for item in items]), indent=2))
