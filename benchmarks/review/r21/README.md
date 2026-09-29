# R2.1 offline review cases

Generate and check the eight synthetic cases without network access:

```sh
python3 benchmarks/review/r21/generate.py --selftest
python3 benchmarks/review/r21/generate.py /tmp/review-cases /tmp/review-oracles
```

The first output directory contains a manifest and one Git bundle per case. Clone a bundle with
`git clone -b review-head CASE.bundle CHECKOUT`, and use its exact base/head commit IDs and
committed `requirements.md` as the review input. Give both comparison arms the same bundle,
requirements, public tests, tools and time limit. The second directory is private: it contains
the expected behavior, direct witness, human rubric and any repaired commit bundle. Keep the
generator and private output outside reviewer checkout, prompt, history and mounted input package.

The set includes normal controls, defects, an unchanged-caller regression, and a case with a known
blocker plus unavailable platform evidence. Case labels and the public manifest do not identify
their classifications. The selftest checks the witness against each applicable state and verifies
that repaired commits and oracle material are absent from the public bundle.

`quality_comparison` is `NOT_RUN`. Fixture checks establish the examples and their packaging;
they do not measure review accuracy, recall, false positives or time. A later comparison must
record its actual inputs, results and unavailable evidence without changing these expected states.
