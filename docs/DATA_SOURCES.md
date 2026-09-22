# Data sources

## Synthetic baseline

Phase 3D uses only the deterministic offline generator in `fdp.extract`.

- generator version: recorded in `dataset_manifest.json`;
- seed and exact requested row count: explicit;
- timestamp unit: UTC Unix seconds;
- timestamp granularity: 60 seconds;
- values: fixed-point integers at scale `10^-6`;
- live network dependency: none.

The generated values exist to test data-system correctness. They are not intended to model or
support conclusions about financial markets.

## Future real-data fixture

A fixed, attributable ECB reference-rate snapshot may be added in Phase 3E after its source,
retrieval date, reuse conditions, raw hash, transformation, and normalized hash are recorded.
It is not part of this P0 baseline.
