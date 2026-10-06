from __future__ import annotations
from .llm import DictionaryReviewer
from .schemas import DictionaryDecision, AuditResult
from .prompts import CURATOR_PROMPT, AUDIT_PROMPT
from .repository import exact_matches, nearby_terms, product_evidence, audit_records
from .policy import looks_marketing, validate_decision
from .writer import apply_decision

def _print_decision(d):
    print("="*88); print(f"DICTIONARY AGENT | {d.candidate}"); print("="*88)
    print(f"ACTION     : {d.action}"); print(f"TYPE       : {d.term_type}"); print(f"CANONICAL  : {d.canonical_name}"); print(f"ENGLISH    : {d.english_name}"); print(f"CONFIDENCE : {d.confidence:.2f}"); print(f"REASON     : {d.reason}")
    if d.aliases: print(f"ALIASES    : {d.aliases}")
    if d.description: print(f"DESCRIPTION: {d.description}")
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

def run_dictionary_audit(*, limit=50, offset=0, apply=False, model=None, verbose=True, client=None):
    records=audit_records(limit=limit,offset=offset)
    reviewer=DictionaryReviewer(model=model,client=client)
    result=reviewer.review(prompt=AUDIT_PROMPT,payload={"records":records},schema=AuditResult)
    outputs=[]
    for f in result.findings:
        if verbose: print(f"AUDIT | TERM {f.term_id} | {f.action} | {f.confidence:.2f} | {f.reason}")
        outputs.append(f.model_dump())
    # Audit mutations deliberately require candidate-level rerun; prevents mass destructive edits.
    return {"scanned":len(records),"findings":outputs,"applied":False,"requested_apply":apply,"note":"Audit is recommendation-only. Re-run each candidate with run_dictionary_agent(..., apply=True) before mutation."}
