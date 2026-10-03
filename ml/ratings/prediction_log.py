"""P5-M2 §8 prediction log: what determines an output, stored per response, and a bit-for-bit re-serve check.

Each entry records:
- as_of;
- snapshot_id;
- the STRATAI replay fingerprint;
- the model sha256s and the commit;
- the request;
- the response's canonical bytes (and their sha256).

``reserve_matches`` re-serves a logged request through a caller-supplied serve function and compares bytes.
The log is append-only JSON lines.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from ml.ratings.live_snapshots import canonical


@dataclass(frozen=True)
class LoggedPrediction:
    as_of: str
    snapshot_id: str
    stratai_fingerprint: str
    model_sha256: dict[str, str]
    commit: str
    request: dict[str, Any]
    response: dict[str, Any]

    @property
    def response_sha256(self) -> str:
        return hashlib.sha256(canonical(self.response)).hexdigest()

    def to_json(self) -> dict[str, Any]:
        return {"as_of": self.as_of, "snapshot_id": self.snapshot_id, "stratai_fingerprint": self.stratai_fingerprint,
                "model_sha256": self.model_sha256, "commit": self.commit, "request": self.request,
                "response": self.response, "response_sha256": self.response_sha256}


class PredictionLog:
    """Append-only JSON-lines log of LoggedPrediction entries."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def append(self, entry: LoggedPrediction) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry.to_json(), sort_keys=True) + "\n")

    def entries(self) -> list[LoggedPrediction]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            data = json.loads(line)
            entry = LoggedPrediction(data["as_of"], data["snapshot_id"], data["stratai_fingerprint"],
                                     data["model_sha256"], data["commit"], data["request"], data["response"])
            if entry.response_sha256 != data["response_sha256"]:
                raise ValueError(f"log entry at {data['as_of']} does not match its recorded response sha256")
            out.append(entry)
        return out


def reserve_matches(entry: LoggedPrediction,
                    serve: Callable[[dict[str, Any], datetime, str], dict[str, Any]]) -> bool:
    """Re-serve a logged request at its as_of and snapshot; True when the bytes are identical."""
    again = serve(entry.request, datetime.fromisoformat(entry.as_of), entry.snapshot_id)
    return canonical(again) == canonical(entry.response)
