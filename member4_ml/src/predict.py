"""Phase 10 — Model Inference & Backend Integration (Member 4).

Reusable prediction interface. The backend does not need to understand
training internals. Provides:

  - load_model() — load a saved model + preprocessor + metadata
  - preprocess_event(event) — transform a normalized event into model features
  - predict_event(event) — run inference and return a structured result
  - explain_prediction(event) — explain a single prediction
  - get_model_metadata() — model name, version, feature names

The interface accepts a normalized event dict (aligned with Member 3's
events.jsonl schema) and returns a structured result suitable for Member 1
backend and Member 5 dashboard.

Run self-check:
  $env:PYTHONPATH = "src;member4_ml/src"
  python member4_ml/src/predict.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import joblib
import numpy as np
import pandas as pd

if __package__:
    from .preprocessing import (
        build_preprocessor,
        fit_preprocessor,
        transform_preprocessor,
        get_feature_names,
        TARGET_BINARY,
    )
    from .explainability import explain_prediction as _explain_prediction
else:
    from preprocessing import (
        build_preprocessor,
        fit_preprocessor,
        transform_preprocessor,
        get_feature_names,
        TARGET_BINARY,
    )
    from explainability import explain_prediction as _explain_prediction


# ---------------------------------------------------------------------------
# Model container
# ---------------------------------------------------------------------------

class ModelBundle:
    """Holds a fitted model, preprocessor, and metadata together.

    Keeps model and preprocessing versions synchronized.
    """

    def __init__(
        self,
        model: Any,
        preprocessor: Any,
        metadata: dict[str, Any],
    ):
        self.model = model
        self.preprocessor = preprocessor
        self.metadata = metadata

    @property
    def model_name(self) -> str:
        return self.metadata.get("model_name", "unknown")

    @property
    def model_version(self) -> str:
        return self.metadata.get("model_version", "v1")

    @property
    def task(self) -> str:
        return self.metadata.get("task", "unknown")

    @property
    def feature_names(self) -> list[str]:
        return self.metadata.get("feature_names", [])

    @property
    def target(self) -> str:
        return self.metadata.get("target", TARGET_BINARY)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_model(
    model_path: str | Path,
    preprocessor_path: str | Path | None = None,
    metadata_path: str | Path | None = None,
) -> ModelBundle:
    """Load a saved model, preprocessor, and metadata.

    Parameters
    ----------
    model_path : str | Path
        Path to the saved model (.joblib).
    preprocessor_path : str | Path, optional
        Path to the saved preprocessor (.joblib). If None, inferred by
        replacing "model" with "preprocessor" in the filename.
    metadata_path : str | Path, optional
        Path to the metadata JSON. If None, inferred as
        <model_dir>/<model_name>_metadata.json.

    Returns
    -------
    ModelBundle
    """
    model_path = Path(model_path)
    if not model_path.is_file():
        raise FileNotFoundError(f"Model file not found: {model_path}")

    model = joblib.load(model_path)

    if preprocessor_path is None:
        preprocessor_path = model_path.with_name(
            model_path.name.replace("model", "preprocessor")
        )
    preprocessor_path = Path(preprocessor_path)
    if not preprocessor_path.is_file():
        raise FileNotFoundError(f"Preprocessor file not found: {preprocessor_path}")

    preprocessor = joblib.load(preprocessor_path)

    if metadata_path is None:
        metadata_path = model_path.parent / (
            model_path.stem.replace("model", "model_metadata") + ".json"
        )
    metadata_path = Path(metadata_path)
    if metadata_path.is_file():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    else:
        metadata = {
            "model_name": model_path.stem,
            "model_version": "v1",
            "task": "unknown",
            "target": TARGET_BINARY,
            "feature_names": [],
        }

    return ModelBundle(model=model, preprocessor=preprocessor, metadata=metadata)


# ---------------------------------------------------------------------------
# Event preprocessing
# ---------------------------------------------------------------------------

def preprocess_event(
    bundle: ModelBundle,
    event: dict[str, Any],
) -> np.ndarray:
    """Transform a single normalized event dict into model-ready features.

    Parameters
    ----------
    bundle : ModelBundle
        Loaded model bundle (contains fitted preprocessor).
    event : dict
        A single event record. Expected to include the raw feature columns
        (matching Member 3's events.jsonl schema after flattening). The
        `event_id` and `is_synthetic` fields are preserved as metadata but
        excluded from model features via the preprocessor.

    Returns
    -------
    np.ndarray
        2D array of shape (1, n_features) ready for model.predict.

    Raises
    ------
    ValueError
        If required feature columns are missing from the event.
    RuntimeError
        If the preprocessor is not fitted.
    """
    preprocessor = bundle.preprocessor
    feature_names = bundle.feature_names

    # Build a single-row DataFrame from the event dict.
    event_df = pd.DataFrame([event])

    # Reindex to the columns the preprocessor was fit on, filling missing
    # columns with NaN so the imputer can handle them.
    expected_input_cols = getattr(preprocessor, "feature_names_in_", None)
    if expected_input_cols is not None:
        event_df = event_df.reindex(columns=list(expected_input_cols))

    # Coerce known-numeric columns to numeric dtype (invalid values -> NaN)
    # so the median imputer can handle them instead of crashing on strings.
    numeric_input_cols = _get_numeric_input_cols(preprocessor)
    for col in numeric_input_cols:
        if col in event_df.columns:
            event_df[col] = pd.to_numeric(event_df[col], errors="coerce")

    # Transform using the fitted preprocessor.
    try:
        X = transform_preprocessor(preprocessor, event_df)
    except Exception as exc:
        raise RuntimeError(
            "Failed to preprocess event. Ensure the preprocessor is fitted "
            f"and the event contains the expected feature columns. Error: {exc}"
        ) from exc

    return X


def _get_numeric_input_cols(preprocessor: Any) -> list[str]:
    """Extract the names of input columns routed to the numeric pipeline.

    After fitting, ColumnTransformer.transformers_ contains
    (name, transformer, columns) tuples. The numeric pipeline's columns
    are the ones that should be coerced to numeric before transform.
    """
    numeric_cols: list[str] = []
    transformers = getattr(preprocessor, "transformers_", None)
    if transformers is None:
        return numeric_cols
    for name, transformer, columns in transformers:
        # The numeric pipeline is the one whose first step is SimpleImputer
        # followed by StandardScaler (or just SimpleImputer).
        if name == "numeric" or "numeric" in str(name).lower():
            numeric_cols.extend(list(columns))
    return numeric_cols


# ---------------------------------------------------------------------------
# Prediction
# ---------------------------------------------------------------------------

def predict_event(
    bundle: ModelBundle,
    event: dict[str, Any],
    threshold: float = 0.5,
) -> dict[str, Any]:
    """Run inference on a single normalized event and return a structured result.

    The output contract aligns with the prediction-response contract shared
    with Member 1 (backend) and Member 5 (dashboard).

    Parameters
    ----------
    bundle : ModelBundle
        Loaded model bundle.
    event : dict
        A single normalized event record (must include `event_id`).
    threshold : float
        Decision threshold for binary classification (default 0.5).
        Only used for binary tasks; multiclass uses argmax.

    Returns
    -------
    dict with keys: event_id, entity_id, prediction, attack_category,
    risk_score, confidence, top_features, model_version, explanation,
    evidence_status, is_synthetic, limitations.
    """
    event_id = event.get("event_id", "unknown")
    entity_id = event.get("source_record_id", event_id)
    is_synthetic = bool(event.get("is_synthetic", False))

    # Preprocess the event.
    X = preprocess_event(bundle, event)

    # Predict.
    model = bundle.model
    prediction = model.predict(X)[0]

    # Confidence / probability.
    confidence = None
    attack_category = None
    if hasattr(model, "predict_proba"):
        try:
            probs = model.predict_proba(X)[0]
            confidence = float(np.max(probs))
            # For multiclass, map the predicted class index to a label.
            classes = getattr(model, "classes_", None)
            if classes is not None:
                pred_index = int(model.predict(X)[0])
                attack_category = str(classes[pred_index])
        except Exception:
            confidence = None

    if attack_category is None:
        attack_category = str(prediction)

    # Risk score: 0-100 scaled from confidence (for binary) or max probability.
    risk_score = None
    if confidence is not None:
        risk_score = int(round(confidence * 100))

    # Explanation.
    explanation_result = _explain_prediction(
        model=model,
        preprocessor=bundle.preprocessor,
        feature_names=bundle.feature_names,
        event_df=pd.DataFrame([event]),
        top_k=5,
        model_version=bundle.model_version,
    )

    top_features = explanation_result.get("top_features", [])
    explanation_text = explanation_result.get("explanation", [])

    # Build structured result.
    result = {
        "event_id": str(event_id),
        "entity_id": str(entity_id),
        "prediction": str(prediction),
        "attack_category": attack_category,
        "risk_score": risk_score,
        "confidence": confidence,
        "top_features": top_features,
        "model_version": bundle.model_version,
        "explanation": explanation_text,
        "evidence_status": "model_generated_signal",
        "is_synthetic": is_synthetic,
        "limitations": explanation_result.get("limitations", []),
        "graph_context": {
            "note": "Graph context requires Member 2 Neo4j integration (Phase 8).",
        },
    }

    return result


def predict_batch(
    bundle: ModelBundle,
    events: list[dict[str, Any]],
    threshold: float = 0.5,
) -> list[dict[str, Any]]:
    """Run inference on a list of events.

    Returns a list of structured results (same shape as predict_event).
    """
    return [predict_event(bundle, event, threshold=threshold) for event in events]


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

def get_model_metadata(bundle: ModelBundle) -> dict[str, Any]:
    """Return model metadata for dashboard/backend display."""
    return {
        "model_name": bundle.model_name,
        "model_version": bundle.model_version,
        "task": bundle.task,
        "target": bundle.target,
        "feature_count": len(bundle.feature_names),
        "feature_names": bundle.feature_names,
    }


# ---------------------------------------------------------------------------
# Self-check
# ---------------------------------------------------------------------------

def _build_synthetic_bundle() -> ModelBundle:
    """Build a ModelBundle from synthetic data for self-check."""
    import sys
    from pathlib import Path as _P

    sys.path.insert(0, str(_P(__file__).resolve().parents[1]))
    from data_loader import load_member3_events
    from preprocessing import (
        build_preprocessor,
        fit_preprocessor,
        transform_preprocessor,
        get_feature_names,
        identify_feature_columns,
    )
    from train_binary import get_binary_models

    TRUST_ROOT = _P(__file__).resolve().parents[2]
    EVENTS_PATH = TRUST_ROOT / "data" / "demo-run" / "processed" / "events.jsonl"

    df = load_member3_events(EVENTS_PATH)
    df[TARGET_BINARY] = (df["event_type"] == "network_flow").astype(int)

    feature_columns = identify_feature_columns(df, TARGET_BINARY, task_type="binary")
    X = df[feature_columns]
    y = df[TARGET_BINARY]

    preprocessor = build_preprocessor(df, TARGET_BINARY, task_type="binary")
    preprocessor = fit_preprocessor(preprocessor, X)
    X_t = transform_preprocessor(preprocessor, X)
    feature_names = get_feature_names(preprocessor)

    model = get_binary_models()["random_forest"]
    model.fit(X_t, y)

    metadata = {
        "model_name": "random_forest",
        "model_version": "v1",
        "task": "binary_intrusion_detection",
        "target": TARGET_BINARY,
        "feature_names": feature_names,
    }

    return ModelBundle(model=model, preprocessor=preprocessor, metadata=metadata)


if __name__ == "__main__":
    print("=" * 60)
    print("Phase 10 Inference Interface — self-check")
    print("=" * 60)

    bundle = _build_synthetic_bundle()
    meta = get_model_metadata(bundle)
    print(f"\nModel: {meta['model_name']} {meta['model_version']}")
    print(f"Task: {meta['task']}, Target: {meta['target']}")
    print(f"Features: {meta['feature_count']}")

    # A single synthetic event (network_flow).
    event = {
        "event_id": "EVT-TEST-001",
        "event_type": "network_flow",
        "event_time": "2026-01-15T10:22:00Z",
        "event_type_original": "network_flow",
        "severity": None,
        "description": None,
        "evidence_id": "EVD-TEST-001",
        "evidence_status": "observed",
        "ingested_at": "2026-01-15T10:22:00Z",
        "is_synthetic": True,
        "source_record_id": "demo-flow-test",
        "source_system": "trustrail_synthetic_generator",
        "timestamp_semantics": "iso8601",
        "attr_DstBytes": 8192,
        "attr_DstPackets": 11,
        "attr_DstPort": 443,
        "attr_Duration": 12,
        "attr_Protocol": 6,
        "attr_SrcBytes": 2048,
        "attr_SrcPackets": 14,
        "attr_SrcPort": 53000,
    }

    result = predict_event(bundle, event, threshold=0.5)
    print(f"\nPrediction result for event {result['event_id']}:")
    for key in (
        "prediction",
        "attack_category",
        "risk_score",
        "confidence",
        "model_version",
        "is_synthetic",
    ):
        print(f"  {key}: {result[key]}")
    print(f"  top_features ({len(result['top_features'])}):")
    for feat in result["top_features"]:
        print(f"    - {feat['feature']}: importance={feat['importance_mean']:.4f}")
    print(f"  explanation: {' | '.join(result['explanation'])}")

    print("\nInference interface self-check complete.")
