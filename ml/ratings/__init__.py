"""STRATAI-owned team ratings, computed from STRATAI's own canonical data.

ml.ratings.epa is the pure EPA engine core (docs/ratings/epa_specification.md,
docs/ratings/data_contract.md); ml.ratings.provider is the source-selection
boundary future consumers will ask through. Nothing in this package reads the
database or calls an external API.
"""
