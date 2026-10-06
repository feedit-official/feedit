from __future__ import annotations
from .llm import DictionaryReviewer
from .schemas import DictionaryDecision, AuditResult
from .prompts import CURATOR_PROMPT, FAST_AUDIT_PROMPT
from .repository import exact_matches, nearby_terms, product_evidence, fast_audit_scan
from .policy import looks_marketing, validate_decision
from .writer import apply_decision

def _print_decision(d):
    print("="*88); print(f"DICTIONARY AGENT | {d.candidate}"); print("="*88)
    print(f"ACTION     : {d.action}"); print(f"TYPE       : {d.term_type}"); print(f"CANONICAL  : {d.canonical_name}"); print(f"ENGLISH    : {d.english_name}"); print(f"CONFIDENCE : {d.confidence:.2f}"); print(f"REASON     : {d.reason}")
    if d.aliases: print(f"ALIASES    : {d.aliases}")
    if d.changes.add_aliases: print(f"ALIAS ADD  : {d.changes.add_aliases}")
    if d.changes.remove_aliases: print(f"ALIAS DROP : {d.changes.remove_aliases} (recommendation only)")
    if d.description:
        print(f"DESCRIPTION: {d.description}")
        print(f"DESC UPDATE: {d.changes.update_description}")
    if d.changes.add_relations: print(f"REL ADD    : {d.changes.add_relations} (write held)")
    if d.warnings: print(f"WARNINGS   : {d.warnings}")

def run_dictionary_agent(*, term, apply=False, model=None, verbose=True, client=None):
    candidate=str(term or "").strip()
    if not candidate: raise ValueError("term is required")
    exact=exact_matches(candidate); nearby=nearby_terms(candidate); evidence=product_evidence(candidate)
    payload={"candidate":candidate,"marketing_pattern_flag":looks_marketing(candidate),"exact_matches":exact,"nearby_terms":nearby,"product_evidence":evidence}
    reviewer=DictionaryReviewer(model=model,client=client)
    d=reviewer.review(prompt=CURATOR_PROMPT,payload=payload,schema=DictionaryDecision)
    errors=validate_decision(d)
    if errors and d.action not in {"KEEP","HOLD","REJECT"}:
        d.action="HOLD"; d.warnings.extend(errors); d.reason=f"{d.reason} | POLICY HOLD: {'; '.join(errors)}"
    if verbose: _print_decision(d)
    write_result=None
    if apply: write_result=apply_decision(d); print(f"APPLY      : {write_result}") if verbose else None
    return {"candidate":candidate,"decision":d.model_dump(),"applied":bool(apply),"write_result":write_result,"evidence_count":len(evidence)}

def run_dictionary_fast_scan(*, limit=None, offset=0, verbose=True):
    result=fast_audit_scan(limit=limit,offset=offset)
    if verbose:
        print("="*88); print("DICTIONARY FAST SCAN | LLM CALLS: 0"); print("="*88)
        print(f"SCANNED    : {result['scanned']}"); print(f"SUSPICIOUS : {len(result['suspicious'])}")
        counts={}
        for row in result['suspicious']:
            for flag in row['fast_flags']: counts[flag['kind']]=counts.get(flag['kind'],0)+1
        for k,v in sorted(counts.items()): print(f"{k:<30}: {v}")
    return result

def run_dictionary_audit(*, limit=None, offset=0, apply=False, model=None, verbose=True, client=None, batch_size=20, max_candidates=None):
    """Fast DB scan first, then LLM only for suspicious terms in chunks."""
    scan=fast_audit_scan(limit=limit,offset=offset); suspects=scan["suspicious"]
    if max_candidates is not None: suspects=suspects[:max_candidates]
    if verbose:
        print(f"FAST SCAN | scanned={scan['scanned']} suspicious={len(scan['suspicious'])} selected={len(suspects)} | LLM so far=0")
    if not suspects:
        return {"scanned":scan["scanned"],"suspicious":0,"reviewed":0,"findings":[],"llm_calls":0,"applied":False,"requested_apply":apply}
    reviewer=DictionaryReviewer(model=model,client=client); outputs=[]; calls=0
    for start in range(0,len(suspects),batch_size):
        chunk=suspects[start:start+batch_size]; calls+=1
        if verbose: print(f"MIRANDA AUDIT | {start+1}-{start+len(chunk)}/{len(suspects)} | API CALL {calls}")
        result=reviewer.review(prompt=FAST_AUDIT_PROMPT,payload={"records":chunk},schema=AuditResult)
        for f in result.findings:
            if verbose: print(f"AUDIT | TERM {f.term_id} | {f.action} | {f.confidence:.2f} | {f.reason}")
            outputs.append(f.model_dump())
    return {"scanned":scan["scanned"],"suspicious":len(scan["suspicious"]),"reviewed":len(suspects),"findings":outputs,"llm_calls":calls,"applied":False,"requested_apply":apply,"note":"Audit remains recommendation-only. Apply destructive changes through candidate-level review."}
