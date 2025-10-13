# Golden plot baselines

This directory contains PNG images generated with Matplotlib's ``Agg`` backend. The
images serve as regression baselines for ``tests/plots/test_golden.py``; update them
only when the intended visual output changes. To regenerate for new behaviour:

```bash
PYTHONPATH=src python3 tests/plots/test_golden.py
```

or run the helper snippet in ``tests/plots/test_golden.py`` that mirrors these figures.
