"""Integrity pins for the PX-1b chain (G1/G2; approved by Kanav 2026-10-08).

**G1: model files.** `px1b-v1`, its seed-only comparator and the PX-2b v2 calibration base are pinned by the sha256
of their saved registry file (`ml.registry.model_file_sha256`, the same artifact identity P6-M10 pins). A run loads
a pinned model only after its file hashes to the pinned value.

**G2: slice content.** The 526-row PX-2b v2 calibration slice is pinned by its content, not only its keys.
- **Serialization:** `ml.playoffs.px1b.dataset_fingerprint`. For each row, sorted by `match_key`:
  `json.dumps(sort_keys=True)` of `{match_key, season, round, red_seed, blue_seed, red_win, red, blue, fields}`.
  `red` and `blue` list each member as `{team, values, score_scale, epa_scale}`, where `values` is the
  `TEAM_FEATURE_NAMES`-ordered vector with NaN as null and a scale is null unless present. Lines are joined with "\n",
  UTF-8 encoded and hashed with sha256.
- **Signature:** that serialization is identified by `serialization_signature()`, the sha256 of the source of
  every function and constant it depends on, with newlines normalized. If the signature differs from the pinned one,
  the serialization is ambiguous and the run refuses rather than comparing fingerprints made two different ways.

Pure: nothing here reads a database. Every failure is a `PinError`; nothing falls back to an unpinned artifact.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

PIN_RECORD = "p6_px1b_chain_pins.json"
PIN_VERSION = 1
SERIALIZATION_NAME = "px1b-dataset-fingerprint-v1"


class PinError(ValueError):
    """A pinned artifact is missing, differs from its pin, or cannot be compared unambiguously."""


def serialization_signature() -> str:
    """sha256 of the exact code that serializes a row for the content fingerprint (G2)."""
    from ml.models import team_vector
    from ml.playoffs import px1b

    parts = [inspect.getsource(obj) for obj in (px1b.dataset_fingerprint, px1b._team_record, px1b._number,
                                                team_vector.team_features_to_vector)]
    parts.append(repr(team_vector.TEAM_FEATURE_NAMES))
    text = "\n".join(p.replace("\r\n", "\n") for p in parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def slice_content_fingerprint(slice_rows: Sequence) -> str:
    from ml.playoffs.px1b import dataset_fingerprint

    return dataset_fingerprint(slice_rows)


def model_key(model_type: str, version_tag: str) -> str:
    return f"{model_type}/{version_tag}"


def read_pins(path: Path) -> dict[str, Any]:
    if not Path(path).exists():
        raise PinError(f"{path} (the PX-1b chain pin record) does not exist")
    pins = json.loads(Path(path).read_text(encoding="utf-8"))
    if pins.get("pin_version") != PIN_VERSION or "models" not in pins or "slice_content" not in pins:
        raise PinError(f"{path} is not a version-{PIN_VERSION} pin record")
    return pins


def require_model_pin(pins: dict[str, Any], model_type: str, version_tag: str, actual_sha256: str | None) -> None:
    """G1: the model file exists and hashes to its pin."""
    expected = pins["models"].get(model_key(model_type, version_tag))
    if not expected:
        raise PinError(f"no pin for {model_key(model_type, version_tag)}")
    if actual_sha256 is None:
        raise PinError(f"{model_key(model_type, version_tag)}: the registered model file is missing")
    if actual_sha256 != expected:
        raise PinError(f"{model_key(model_type, version_tag)}: file sha256 {actual_sha256} is not the pinned {expected}")


def require_slice_content(pins: dict[str, Any], slice_rows: Sequence) -> None:
    """G2: the same serialization, and the same content, as the pinned slice."""
    pinned = pins["slice_content"]
    if pinned.get("serialization", {}).get("name") != SERIALIZATION_NAME \
            or pinned["serialization"].get("signature_sha256") != serialization_signature():
        raise PinError("the slice-content serialization differs from the pinned one: the fingerprints are not "
                       "comparable, so the run refuses")
    if len(slice_rows) != pinned["rows"]:
        raise PinError(f"the slice has {len(slice_rows)} rows, the pin {pinned['rows']}")
    actual = slice_content_fingerprint(slice_rows)
    if actual != pinned["fingerprint"]:
        raise PinError(f"the slice content changed: fingerprint {actual} is not the pinned {pinned['fingerprint']}")
