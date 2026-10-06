from __future__ import annotations
from .orchestrator import run_dictionary_agent

def run_dictionary_candidate_batch(candidates, *, apply=False, model=None, verbose=True, stop_on_error=False):
    results=[]; failed=[]
    unique=[]; seen=set()
    for x in candidates:
        x=str(x or "").strip()
        if x and x.casefold() not in seen: seen.add(x.casefold()); unique.append(x)
    for i,c in enumerate(unique,1):
        if verbose: print(f"\n[{i}/{len(unique)}] {c}")
        try: results.append(run_dictionary_agent(term=c,apply=apply,model=model,verbose=verbose))
        except Exception as e:
            failed.append({"candidate":c,"error":f"{type(e).__name__}: {e}"})
            if verbose: print(f"FAILED | {c} | {type(e).__name__}: {e}")
            if stop_on_error: raise
    return {"total":len(unique),"success":len(results),"failed":len(failed),"results":results,"failures":failed}
