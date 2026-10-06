# FEEDIT Fashion Dictionary Agent v3 — Enrichment

v3 keeps the v2 FAST/batch architecture and changes the meaning of `KEEP`:

- `KEEP` = canonical concept/type are correct.
- Missing aliases can still be added.
- Weak descriptions can still be improved.
- Relation proposals are surfaced but held from automatic writes.
- Alias/relation deletion remains recommendation-only.

## Test

```python
from pipeline.dictionary_agents import run_dictionary_candidate_batch

result = run_dictionary_candidate_batch(
    ["피코트", "럭비", "모직"],
    apply=False,
    batch_size=15,
    model="gpt-5.4-mini",
    verbose=True,
)
```

Look for `ALIAS ADD`, `DESC UPDATE`, and relation proposals.

Then apply:

```python
result = run_dictionary_candidate_batch(
    ["피코트", "럭비", "모직"],
    apply=True,
    batch_size=15,
    model="gpt-5.4-mini",
    verbose=True,
)
```

Only missing aliases and approved description improvements are written for KEEP decisions.

## v4 Automatic Discovery

No manual candidate list is required.

```python
from pipeline.dictionary_agents import run_dictionary_pipeline

result = run_dictionary_pipeline(
    apply=False,
    product_limit=30000,
    discovery_limit=80,
    audit_limit=40,
    batch_size=20,
    model="gpt-5.4-mini",
    verbose=True,
)
```

Pipeline: ProductSource discovery (0 LLM) -> known term/alias filtering -> frequency/brand/platform ranking -> existing dictionary fast audit (0 LLM) -> Miranda batch review -> safe enrichment writes when apply=True.

Start with `apply=False`. Candidate discovery is intentionally conservative, but product naming contains commerce noise and must be reviewed before first production apply.
