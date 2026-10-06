from __future__ import annotations
from .llm import DictionaryReviewer
from .schemas import DictionaryDecisionBatch
from .prompts import BATCH_CURATOR_PROMPT
from .repository import candidate_payload
from .policy import looks_marketing, validate_decision
from .writer import apply_decision
from .orchestrator import _print_decision

def _unique_candidates(candidates):
    out=[]; seen=set()
    for x in candidates:
        x=str(x or "").strip(); key=x.casefold()
        if x and key not in seen: seen.add(key); out.append(x)
    return out

def run_dictionary_candidate_batch(candidates, *, apply=False, model=None, verbose=True, stop_on_error=False, batch_size=15, client=None):
    """True LLM batching: up to batch_size candidates per API call."""
    unique=_unique_candidates(candidates); results=[]; failed=[]; reviewer=DictionaryReviewer(model=model,client=client)
    for start in range(0,len(unique),batch_size):
        chunk=unique[start:start+batch_size]
        if verbose: print(f"\nMIRANDA BATCH | {start+1}-{start+len(chunk)}/{len(unique)} | API CALL 1")
        try:
            payloads=[]
            for c in chunk:
                p=candidate_payload(c); p["marketing_pattern_flag"]=looks_marketing(c); payloads.append(p)
            parsed=reviewer.review(prompt=BATCH_CURATOR_PROMPT,payload={"candidates":payloads},schema=DictionaryDecisionBatch)
            by_name={d.candidate.casefold():d for d in parsed.decisions}
            for c in chunk:
                d=by_name.get(c.casefold())
                if d is None:
                    failed.append({"candidate":c,"error":"LLM batch omitted candidate"}); continue
                errors=validate_decision(d)
                if errors and d.action not in {"KEEP","HOLD","REJECT"}:
                    d.action="HOLD"; d.warnings.extend(errors); d.reason=f"{d.reason} | POLICY HOLD: {'; '.join(errors)}"
                if verbose: _print_decision(d)
                write_result=apply_decision(d) if apply else None
                results.append({"candidate":c,"decision":d.model_dump(),"applied":bool(apply),"write_result":write_result})
        except Exception as e:
            for c in chunk: failed.append({"candidate":c,"error":f"{type(e).__name__}: {e}"})
            if verbose: print(f"BATCH FAILED | {type(e).__name__}: {e}")
            if stop_on_error: raise
    return {"total":len(unique),"success":len(results),"failed":len(failed),"llm_calls":(len(unique)+batch_size-1)//batch_size if unique else 0,"batch_size":batch_size,"results":results,"failures":failed}
