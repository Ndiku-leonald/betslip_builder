"""Explicitly activate a reviewed candidate; training never auto-promotes."""
import argparse
from sqlalchemy import select
from app.db import SessionLocal
from app.models import ModelVersion

parser = argparse.ArgumentParser(); parser.add_argument("model_version_id")
args = parser.parse_args()
with SessionLocal() as db:
    selected = db.get(ModelVersion, args.model_version_id)
    if selected is None: raise SystemExit("model version not found")
    for item in db.scalars(select(ModelVersion).where(ModelVersion.sport == selected.sport, ModelVersion.status == "champion")): item.status = "retired"
    selected.status = "champion"; db.commit(); print(selected.id, selected.version, selected.status)
