import argparse
from app.db import SessionLocal
from app.training.dataset import build_dataset, export_rows

if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--sport", choices=("football", "basketball"), required=True); parser.add_argument("--output", required=True)
    args = parser.parse_args()
    with SessionLocal() as db: rows = build_dataset(db, args.sport)
    print(export_rows(rows, args.output), len(rows))
