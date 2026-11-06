# Season scoring configurations (P11A B4)

**There are no configurations in this directory yet, and none is approved.** Until one is, every P11A plan for that
season is withheld with `scoring_config_not_approved`.

**What a configuration is.**
- One file per season, named `<season>.json`.
- Schema: `ml/alliance/scoring_config.py` `SeasonScoringConfig`.
- A configuration references the season's approved P5-M8 GameSpec by sha256, and never restates a point value. Every
  point value comes from a GameSpec scoring action.
- Each component rule (auto, teleop, endgame) cites the game manual.

**Approval.**
- A qualified reviewer verifies the file against the official manual.
- The reviewer's record (`review.verified_sha256`) must equal the content's sha256 (`content_sha256()`).
- Approval is a human act. No tool in this repository creates or approves a configuration.
