# P11A hardening research (2026-11-06)

`collapse_check.py` asks what the estimator's collapse check measures. Its protocol is declared in the file's
docstring, fixed before the run, and the run is seeded.

```bash
PYTHONPATH=. python research/p11a_hardening/collapse_check.py   # about 50 s; 20-minute budget
```

The result is in `results/collapse_check.json` and is summarised in
`.agent/phase11/decisions/P11A_HARDENING_2026-11-06.md` (H1). It is simulation evidence about the check, not
validation of any estimate.
