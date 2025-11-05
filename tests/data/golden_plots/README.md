# Golden plot baselines

This directory contains PNG images generated with Matplotlib's ``Agg`` backend. The
images serve as regression baselines for ``tests/plots/test_golden.py``; update them
only when the intended visual output changes. To regenerate for new behaviour:

```bash
PYTHONPATH=src python3 tests/plots/test_golden.py
```

or run the helper snippet in ``tests/plots/test_golden.py`` that mirrors these figures.

To refresh the event-labels v2 comparison, opt in to the feature flag and allow pytest
to rewrite the golden:

```bash
UPDATE_GOLDENS=1 VA_FEATURES=event_labels_v2 PYTHONPATH=src pytest tests/plots/test_event_labels_v2.py -q
```
