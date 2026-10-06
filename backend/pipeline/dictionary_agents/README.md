# FEEDIT Fashion Dictionary Agent

Conservative fashion ontology curator for DictionaryTerm / TermAlias.

## Single candidate
```python
from pipeline.dictionary_agents import run_dictionary_agent
result = run_dictionary_agent(term="피코트", apply=False, verbose=True)
```
Review, then set `apply=True`.

## Candidate batch
```python
from pipeline.dictionary_agents import run_dictionary_candidate_batch
result = run_dictionary_candidate_batch(["링거", "피코트", "럭비", "착시핏"], apply=False)
```

## Dictionary audit
```python
from pipeline.dictionary_agents import run_dictionary_audit
result = run_dictionary_audit(limit=50, offset=0, apply=False)
```
Audit is intentionally recommendation-only. Destructive mass changes are not automatically applied.

Environment: OPENAI_API_KEY and optionally FEEDIT_DICTIONARY_AGENT_MODEL.
