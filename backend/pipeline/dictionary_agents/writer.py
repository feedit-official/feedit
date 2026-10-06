from __future__ import annotations
import re
from django.db import transaction
from apps.core.models import DictionaryTerm, TermAlias
from .policy import validate_decision

def _slug(v):
    s=re.sub(r"[^0-9A-Za-z가-힣]+","_",str(v or "").strip()).strip("_").upper()
    return s[:100] or "TERM"
def _unique_code(term_type,name):
    base=f"{term_type}_{_slug(name)}"[:145]; code=base; i=2
    while DictionaryTerm.objects.filter(term_code=code).exists(): code=f"{base[:140]}_{i}"; i+=1
    return code

@transaction.atomic
def apply_decision(d):
    errors=validate_decision(d)
    if errors: raise ValueError("; ".join(errors))
    if d.action in {"KEEP","HOLD","REJECT"}: return {"action":d.action,"changed":False}
    if d.action=="ADD_TERM":
        t=DictionaryTerm.objects.create(term_code=_unique_code(d.term_type,d.canonical_name),term_type=d.term_type,canonical_name=d.canonical_name,english_name=d.english_name,description=d.description,status="ACTIVE")
        for a in d.aliases:
            if a.strip() and a.strip()!=t.canonical_name: TermAlias.objects.get_or_create(term=t,alias=a.strip(),source=None,defaults={"alias_type":"SYNONYM"})
        return {"action":d.action,"changed":True,"term_id":t.pk}
    t=DictionaryTerm.objects.select_for_update().get(pk=d.existing_term_id)
    if d.action=="ADD_ALIAS":
        added=[]
        for a in d.aliases or [d.candidate]:
            obj,created=TermAlias.objects.get_or_create(term=t,alias=a.strip(),source=None,defaults={"alias_type":"SYNONYM"});
            if created: added.append(obj.alias)
        return {"action":d.action,"changed":bool(added),"term_id":t.pk,"aliases":added}
    if d.action in {"UPDATE_TERM","RECLASSIFY"}:
        if d.canonical_name: t.canonical_name=d.canonical_name
        if d.english_name is not None: t.english_name=d.english_name
        if d.description: t.description=d.description
        if d.term_type: t.term_type=d.term_type
        t.save(); return {"action":d.action,"changed":True,"term_id":t.pk}
    if d.action=="DEACTIVATE_TERM":
        t.status="INACTIVE"; t.save(update_fields=["status","updated_at"]); return {"action":d.action,"changed":True,"term_id":t.pk}
    if d.action=="MERGE_TERM":
        target=DictionaryTerm.objects.select_for_update().get(pk=d.merge_target_term_id)
        if t.pk==target.pk: raise ValueError("cannot merge term into itself")
        for a in list(t.aliases.all()): TermAlias.objects.get_or_create(term=target,alias=a.alias,source=a.source,defaults={"alias_type":a.alias_type})
        TermAlias.objects.get_or_create(term=target,alias=t.canonical_name,source=None,defaults={"alias_type":"SYNONYM"})
        t.status="MERGED"; t.save(update_fields=["status","updated_at"]); return {"action":d.action,"changed":True,"term_id":t.pk,"merge_target_term_id":target.pk,"warning":"ProductTerm FK migration is intentionally not automatic; review usages before DB-level merge."}
    if d.action in {"ADD_RELATION","REMOVE_RELATION"}:
        return {"action":"HOLD","changed":False,"warning":"Dictionary relation model is project-version dependent; relation write intentionally held."}
    raise ValueError(f"unsupported action: {d.action}")
