"""Phase 6 strategy track (P6-M9 … P6-M13, docs/P6Milestones.md).

- `representation`: the one strategy type both the optimizer and coaches use, and coach observations (P6-M9).
- `coach_inputs`: raw-first storage and validation of coach-entered strategies and observations (P6-M9).
- `outcome`: the single strategy-conditional outcome model both paths are evaluated by (P6-M10).
- `display`: the one odds-presentation rule both paths use (P6-A5, P6-Q10).
- `engine`: the AI recommender and the coach-scenario assessment, both calling `outcome` (P6-M11).
"""
