from __future__ import annotations

import asyncio
import importlib
import logging
import pickle
from pathlib import Path
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)


class DetectionEngineUnavailable(RuntimeError):
    pass


class DetectionInferenceError(RuntimeError):
    pass


def is_suspicious_prediction(prediction: Any) -> bool:
    normalized = str(prediction).strip().lower()
    return normalized not in {"0", "0.0", "normal", "benign", "false", "none", ""}


class Member4DetectionEngine:
    def __init__(self, project_root: Path | None = None):
        self.project_root = project_root or Path(__file__).resolve().parents[3]
        self.model_dir = self.project_root / "member4_ml" / "models"
        self._lock = Lock()
        self._bundle: Any = None
        self._predict_batch: Any = None
        self._compute_priority: Any = None
        self._recommendation: Any = None

    async def predict_events(
        self,
        events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not events:
            return []
        return await asyncio.to_thread(self._predict_events, events)

    def _predict_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self._load()
        try:
            predictions = self._predict_batch(self._bundle, events)
            if len(predictions) != len(events):
                raise DetectionInferenceError(
                    "Member 4 returned a different number of predictions than input events."
                )
            return [
                self._score_prediction(event, prediction)
                for event, prediction in zip(events, predictions)
            ]
        except (DetectionEngineUnavailable, DetectionInferenceError):
            raise
        except (RuntimeError, ValueError, TypeError) as exc:
            logger.error("Member 4 inference failed: %s", type(exc).__name__)
            raise DetectionInferenceError("Member 4 inference failed.") from exc

    def _load(self) -> None:
        if self._bundle is not None:
            return
        with self._lock:
            if self._bundle is not None:
                return

            model_path = self.model_dir / "perf_binary_model.joblib"
            preprocessor_path = self.model_dir / "perf_binary_preprocessor.joblib"
            if not model_path.is_file() or not preprocessor_path.is_file():
                raise DetectionEngineUnavailable(
                    "Member 4 model artifacts are missing from member4_ml/models."
                )

            try:
                predict_module = importlib.import_module("member4_ml.src.predict")
                scoring_module = importlib.import_module("member4_ml.src.risk_scoring")
            except ImportError as exc:
                logger.error("Member 4 dependencies are unavailable: %s", type(exc).__name__)
                raise DetectionEngineUnavailable(
                    "Install Member 4 dependencies with "
                    "pip install -r member4_ml/requirements.txt."
                ) from exc

            try:
                bundle = predict_module.load_model(model_path, preprocessor_path)
            except (
                AttributeError,
                ImportError,
                OSError,
                pickle.UnpicklingError,
                ValueError,
            ) as exc:
                logger.error("Member 4 model could not be loaded: %s", type(exc).__name__)
                raise DetectionEngineUnavailable(
                    "Member 4 model artifacts could not be loaded."
                ) from exc

            self._bundle = bundle
            self._predict_batch = predict_module.predict_batch
            self._compute_priority = scoring_module.compute_investigation_priority
            self._recommendation = scoring_module.priority_to_recommendation

    def _score_prediction(
        self,
        event: dict[str, Any],
        prediction: dict[str, Any],
    ) -> dict[str, Any]:
        confidence = prediction.get("confidence")
        model_confidence_percent = prediction.get("risk_score")
        event_time = event.get("event_time")
        priority = self._compute_priority(
            prediction=prediction.get("prediction", "unknown"),
            confidence=confidence,
            severity=event.get("severity"),
            event_time=str(event_time) if event_time is not None else None,
        )
        limitations = list(prediction.get("limitations", []))
        limitations.extend([
            "The bundled model was evaluated on a small synthetic dataset; real-world detection performance is unverified.",
            "The investigation-priority score does not include graph context in this integration.",
        ])
        return {
            **prediction,
            "model_name": self._bundle.model_name,
            "entity_id": event.get(
                "source_entity_id",
                prediction.get("entity_id"),
            ),
            "model_confidence_percent": model_confidence_percent,
            "risk_score": priority["score"],
            "risk_level": priority["level"],
            "investigation_priority": priority,
            "recommended_investigation_steps": self._recommendation(priority["level"]),
            "limitations": limitations,
        }
