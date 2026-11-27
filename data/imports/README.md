# data/imports — local scouting exports (never committed)

Real scouting exports contain scouts' names and are personal data. Keep them here only on the machine that imports
them. `.gitignore` ignores everything in this folder except this README and the synthetic example. On 2026-11-26 the
exports that had been committed (and the scouts' names in a test fixture and a docstring) were removed from the
repository's history.

- **In the app (preferred):** an administrator uploads the export at **Admin → Import scouting CSV**
  (`/scouting/import`; docs/team_workspaces.md section 6.1). It shows a preview, then imports after confirmation.
- **By script:** `python -m scripts.import_2026mrcmp_scouting --csv <path to the export>`, run with `--dry-run`
  first.

`example_scoutradioz_export.csv` is **synthetic**: invented teams (99xx), an invented event (`2026synth`) and
invented scout labels. It shows the ScoutRadioz match-scouting export columns, with 2026's defense column
`qDefenseQuality` (0 = played no defense, 1–10 = a rating). It is not evidence about anything.
