# Phase 4 — Milestone 10 Acceptance: Model Registry, Versioning & Reproducibility

## Completed Milestone

Milestone 10 of `docs/P4Milestones.md`'s 13-milestone plan: `ml/registry.py`'s
`register_model`/`load_registered_model`/`list_registered_versions` and
`ModelManifest`.

**Accepted in full.** Like M8/M9, this milestone's own "Success looks like"/"What to
test" criteria are entirely mechanical (save/load equivalence, mismatch rejection,
manifest completeness) and need no real Statbotics/EPA data or real backtest numbers.

## Files Modified/Created

- `ml/registry.py` (new) — `ModelManifest`, `register_model`, `load_registered_model`,
  `list_registered_versions`.
- `tests/test_ml_registry.py` (new) — 13 tests.

## Architectural Decisions

1. **The registry's own feature-list guard is independent of, and in addition to,
   whatever check the underlying model class does internally.** `RankingXGBModel.load`
   and `WinProbXGBModel.load` already refuse a feature-list mismatch baked into their
   own save file (M5/M6's own registry-guarantee head start); `load_registered_model`
   separately compares the manifest's own recorded `feature_list` against whatever the
   caller passes as `current_feature_list`. This is deliberate defense in depth: a
   future model class that forgets its own internal check is still caught here,
   because the comparison lives in the registry, not delegated entirely to the model.
2. **Storage is one write-once directory per (model_type, version_tag)** —
   `registry_dir/<model_type>/<version_tag>/{model.json, manifest.json}` —
   `register_model` raises `FileExistsError` on a duplicate tag rather than silently
   overwriting an artifact an already-running API process might be pinned to.
3. **`created_at` is a required, caller-supplied, timezone-aware timestamp, not
   computed internally** — mirrors `ml.dataset.builder.DatasetManifest`'s own
   `build_date` precedent: a caller registering a model trained earlier can record
   when training actually happened, not merely when `register_model` was called.
4. **"Store artifacts outside the request path"** (the milestone's own wording) is
   satisfied structurally rather than by a runtime check: both functions are plain
   filesystem operations with no network or database access, meant to run offline
   (training time) and once at API startup (a pinned version loaded once) — there is
   nothing in this module an API request path could accidentally call per-request.

## Tests Added & Executed

`tests/test_ml_registry.py` — 13 tests:
- **Round-trip save/load equivalence** (the milestone's own named test): a fixture
  model's predictions are identical before and after registering and reloading.
- Registration creates both files; duplicate `version_tag` is refused
  (`FileExistsError`); loading a never-registered entry raises `FileNotFoundError`.
- **Mismatch-rejection test** (the milestone's own named test): an altered
  `feature_list` at load time is refused with an error naming both the registered and
  current lists.
- A tampered manifest's own `model_type` disagreeing with the requested one is also
  refused (defensive consistency check).
- `list_registered_versions` returns `[]` for an unknown model type and a sorted list
  of real tags otherwise.
- **Manifest-completeness contract test** (the milestone's own named test): every
  field (`model_type`, `model_version`, `registry_version`, `training_dataset_hash`,
  `feature_list`, `random_seed`, `metrics`, `created_at`) round-trips exactly; an
  empty `feature_list` and a naive `created_at` are both refused by `ModelManifest`
  itself.
- **Two end-to-end tests against the real `RankingXGBModel`** (Milestone 5's actual
  production model, not just a fixture): a genuine fit-register-reload round trip
  gives identical `predict_rating` output, and a simulated feature-list drift (an
  extra field, standing in for a future season's assembler producing a different
  shape — the milestone's own named "2024<->2026 drift" scenario) is refused at load
  time with a clear error, never a silent mispredict.

## Terminal Verification Status

```
python -m pytest tests/test_ml_registry.py -v
13 passed in 1.70s
```

Full repository suite, isolated (no concurrent background job):

```
python -m pytest -q
1167 passed, 2 warnings in 357.37s
```

Zero regressions against the 1154-passed baseline immediately prior (1167 = 1154 + 13 new).

## Issues Found During Implementation

None requiring a fix — every test passed on first write.

## Remaining Known Risks

None new. Not affected by the Statbotics outage. This module registers whatever model
object it is handed; it does not itself decide WHEN a model is good enough to
register (that remains each milestone's own real-backtest acceptance gate) — a
caller could technically register an unaccepted model, which is intentional (the
registry is infrastructure, not a gate) but worth naming so a future API layer (M12)
knows to only load pinned, genuinely-accepted versions.

## Roadmap Satisfaction

- "Any served prediction traces to an exact model version + training dataset +
  feature list" — every field lives in `ModelManifest`, round-tripped exactly. ✅
- "A feature-schema mismatch fails loud at load time, never silently mispredicts" —
  pinned directly, including against a real production model class. ✅
- "Store artifacts outside the request path; the API loads a pinned version" —
  structurally true (plain filesystem I/O, no per-request computation). ✅

## Production Readiness

Ready for M12 (ML API endpoints) to load a pinned version at startup via
`load_registered_model`, and for a future training script to call `register_model`
once M4-M7's real backtest numbers exist (their `metrics` dict is exactly where those
real, dated numbers belong once Statbotics recovers).

## Readiness for Next Milestone

M10 is fully accepted. M11 (cross-season generalization guard) is next — its
feature-adapter half is buildable now against real synced 2024/2026 data (no
Statbotics dependency), though its full backtest-generalization test needs M5/M6
accepted first.
