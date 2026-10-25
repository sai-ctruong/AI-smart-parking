"""Public, ground-truth-free inference result types."""

from dataclasses import dataclass
from typing import Literal

PredictionStatus = Literal["empty", "occupied", "unknown"]


@dataclass(frozen=True)
class SpotPrediction:
    spot_id: str
    predicted_status: PredictionStatus
    confidence: float | None
    class_probabilities: dict[str, float] | None
    model_version: str
    uncertainty_reason: str | None = None
    calibrated_confidence: float | None = None

    def to_dict(self) -> dict:
        """Return a JSON-serializable result without changing its meaning."""
        return {
            "spot_id": self.spot_id,
            "predicted_status": self.predicted_status,
            "confidence": self.confidence,
            "class_probabilities": self.class_probabilities,
            "model_version": self.model_version,
            "uncertainty_reason": self.uncertainty_reason,
            "calibrated_confidence": self.calibrated_confidence,
        }
