from __future__ import annotations
import re
from django.db import transaction
from apps.core.models import DictionaryTerm, TermAlias
from .policy import validate_decision, normalize_text

def _slug(v):
    s=re.sub(r"[^0-9A-Za-z가-힣]+","_",str(v or "").strip()).strip("_").upper()
    return s[:100] or "TERM"

def _unique_code(term_type,name):
    base=f"{term_type}_{_slug(name)}"[:145]; code=base; i=2
    while DictionaryTerm.objects.filter(term_code=code).exists():
        code=f"{base[:140]}_{i}"; i+=1
    return code

def _resolve_existing(d):
    if d.existing_term_id:
        return DictionaryTerm.objects.select_for_update().prefetch_related("aliases").get(pk=d.existing_term_id)
    if d.canonical_name:
        n=normalize_text(d.canonical_name)
        for t in DictionaryTerm.objects.select_for_update().prefetch_related("aliases").filter(status="ACTIVE"):
            vals={normalize_text(t.canonical_name),normalize_text(t.english_name),*(normalize_text(a.alias) for a in t.aliases.all())}
            if n and n in vals:
                return t
    return None

def _alias_diff(t, proposed):
    existing={normalize_text(t.canonical_name),normalize_text(t.english_name)}
    existing.update(normalize_text(a.alias) for a in t.aliases.all())
    out=[]; seen=set()
    for raw in proposed:
        a=str(raw or "").strip(); key=normalize_text(a)
        if not a or not key or key in existing or key in seen: continue
        seen.add(key); out.append(a)
    return out

def _description_should_update(t,d):
    if not d.description or not d.changes.update_description: return False
    before=(t.description or "").strip(); after=d.description.strip()
    if not after or normalize_text(before)==normalize_text(after): return False
    # Avoid replacing a substantive description with a dramatically thinner one.
    if before and len(after) < max(12, int(len(before)*0.55)): return False
    return True

def _apply_enrichment(t,d):
    proposed=list(d.changes.add_aliases or [])
    # Backward compatibility: aliases from LLM can enrich too, but DB diff removes existing ones.
    proposed.extend(d.aliases or [])
    aliases_to_add=_alias_diff(t,proposed)
    added=[]
    for a in aliases_to_add:
        obj,created=TermAlias.objects.get_or_create(term=t,alias=a,source=None,defaults={"alias_type":"SYNONYM"})
        if created: added.append(obj.alias)
    desc_updated=False
    if _description_should_update(t,d):
        t.description=d.description.strip(); t.save(update_fields=["description","updated_at"]); desc_updated=True
    relation_hold=[]
    if d.changes.add_relations or d.changes.remove_relations:
        relation_hold=(d.changes.add_relations or [])+(d.changes.remove_relations or [])
    return {"aliases_added":added,"description_updated":desc_updated,"relations_held":relation_hold}

@transaction.atomic
def apply_decision(d):
    errors=validate_decision(d)
    if errors: raise ValueError("; ".join(errors))
    if d.action in {"HOLD","REJECT"}: return {"action":d.action,"changed":False}
    if d.action=="ADD_TERM":
        t=DictionaryTerm.objects.create(term_code=_unique_code(d.term_type,d.canonical_name),term_type=d.term_type,canonical_name=d.canonical_name,english_name=d.english_name,description=d.description,status="ACTIVE")
        proposed=list(d.changes.add_aliases or [])+list(d.aliases or [])
        enrich=_apply_enrichment(t,d.model_copy(update={"description":None}))
        return {"action":d.action,"changed":True,"term_id":t.pk,**enrich}

    t=_resolve_existing(d)
    if t is None:
        raise ValueError(f"{d.action} requires resolvable existing term")

    # KEEP is concept-level KEEP, but enrichment is still applied.
    if d.action=="KEEP":
        enrich=_apply_enrichment(t,d)
        changed=bool(enrich["aliases_added"] or enrich["description_updated"])
        return {"action":"KEEP","changed":changed,"term_id":t.pk,**enrich}

    if d.action=="ADD_ALIAS":
        if not d.changes.add_aliases and not d.aliases:
            d.changes.add_aliases=[d.candidate]
        enrich=_apply_enrichment(t,d)
        return {"action":d.action,"changed":bool(enrich["aliases_added"] or enrich["description_updated"]),"term_id":t.pk,**enrich}

    if d.action in {"UPDATE_TERM","RECLASSIFY"}:
        fields=[]
        if d.canonical_name and d.canonical_name!=t.canonical_name: t.canonical_name=d.canonical_name; fields.append("canonical_name")
        if d.english_name is not None and d.english_name!=t.english_name: t.english_name=d.english_name; fields.append("english_name")
        if d.term_type and d.term_type!=t.term_type: t.term_type=d.term_type; fields.append("term_type")
        if fields: fields.append("updated_at"); t.save(update_fields=fields)
        enrich=_apply_enrichment(t,d)
        return {"action":d.action,"changed":bool(fields or enrich["aliases_added"] or enrich["description_updated"]),"term_id":t.pk,"fields_updated":fields,**enrich}

    if d.action=="DEACTIVATE_TERM":
        t.status="INACTIVE"; t.save(update_fields=["status","updated_at"])
        return {"action":d.action,"changed":True,"term_id":t.pk}
    if d.action=="MERGE_TERM":
        target=DictionaryTerm.objects.select_for_update().get(pk=d.merge_target_term_id)
        if t.pk==target.pk: raise ValueError("cannot merge term into itself")
        for a in list(t.aliases.all()): TermAlias.objects.get_or_create(term=target,alias=a.alias,source=a.source,defaults={"alias_type":a.alias_type})
        TermAlias.objects.get_or_create(term=target,alias=t.canonical_name,source=None,defaults={"alias_type":"SYNONYM"})
        t.status="MERGED"; t.save(update_fields=["status","updated_at"])
        return {"action":d.action,"changed":True,"term_id":t.pk,"merge_target_term_id":target.pk,"warning":"ProductTerm FK migration is intentionally not automatic; review usages before DB-level merge."}
    if d.action in {"ADD_RELATION","REMOVE_RELATION"}:
        return {"action":"HOLD","changed":False,"warning":"Dictionary relation model is project-version dependent; relation write intentionally held."}
    raise ValueError(f"unsupported action: {d.action}")
