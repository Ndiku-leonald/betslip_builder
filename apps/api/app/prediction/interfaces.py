from typing import Protocol

from app.features.common import FeatureRow


class PredictionModel(Protocol):
    name: str
    sport: str

    def fit(self, rows: list[FeatureRow]) -> "PredictionModel": ...
    def predict(self, row: FeatureRow) -> dict: ...
    def metadata(self) -> dict: ...
