from __future__ import annotations
from .discoverer import discover_candidates
from .orchestrator import run_dictionary_fast_scan
from .batch import run_dictionary_candidate_batch

def run_dictionary_pipeline(*, apply=False, model=None, verbose=True, client=None, product_limit=30000, discovery_limit=80, audit_limit=40, batch_size=20, min_frequency=3, min_product_count=3, source_codes=None):
    """Automatic FEEDIT dictionary loop: discover -> fast audit -> Miranda batch -> optional safe writes."""
    if verbose:
        print("="*88); print("FEEDIT FASHION DICTIONARY PIPELINE | MIRANDA"); print("="*88)
    discovery=discover_candidates(limit_products=product_limit,min_frequency=min_frequency,min_product_count=min_product_count,max_candidates=discovery_limit,source_codes=source_codes)
    if verbose:
        print(f"[1/3] DISCOVERY | products={discovery['scanned_products']} raw={discovery['raw_phrase_count']} selected={len(discovery['candidates'])} | LLM=0")
        for i,x in enumerate(discovery['candidates'][:20],1): print(f"  {i:>2}. {x['candidate']} | products={x['product_count']} brands={x['brand_count']} sources={x['source_count']} score={x['score']}")
    audit=run_dictionary_fast_scan(limit=None,offset=0,verbose=False)
    enrich=[]
    for row in audit["suspicious"]:
        flags={x["kind"] for x in row["fast_flags"]}
        if flags & {"MISSING_DESCRIPTION","VERY_SHORT_DESCRIPTION","DUPLICATE_CANONICAL","CANONICAL_EQUALS_OTHER_ALIAS","DUPLICATE_ENGLISH"}:
            enrich.append(row["canonical_name"])
        if len(enrich)>=audit_limit: break
    discovered=[x["candidate"] for x in discovery["candidates"]]
    candidates=[]; seen=set()
    for x in discovered+enrich:
        k=str(x).casefold().strip()
        if k and k not in seen: seen.add(k); candidates.append(x)
    if verbose: print(f"[2/3] FAST AUDIT | dictionary={audit['scanned']} suspicious={len(audit['suspicious'])} enrich_selected={len(enrich)} | LLM=0")
    review=run_dictionary_candidate_batch(candidates,apply=apply,model=model,verbose=verbose,batch_size=batch_size,client=client)
    if verbose:
        print("="*88); print("[3/3] DONE")
        print(f"CANDIDATES : {len(candidates)}"); print(f"LLM CALLS  : {review['llm_calls']}"); print(f"SUCCESS    : {review['success']}"); print(f"FAILED     : {review['failed']}"); print(f"APPLY      : {apply}")
    return {"discovery":discovery,"audit":{"scanned":audit["scanned"],"suspicious":len(audit["suspicious"]),"selected":len(enrich)},"review":review,"apply":apply}
