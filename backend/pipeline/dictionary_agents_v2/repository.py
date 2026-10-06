from __future__ import annotations
import re
from collections import defaultdict
from django.db.models import Count, Q
from apps.core.models import DictionaryTerm, TermAlias, ProductSource

def norm(v): return re.sub(r"[^0-9a-z가-힣]+","",str(v or "").casefold())

def serialize_term(t):
    detail=getattr(t,"detail",None)
    return {"term_id":t.pk,"term_code":t.term_code,"term_type":t.term_type,"canonical_name":t.canonical_name,"english_name":t.english_name,"description":t.description,"status":t.status,"detail_attribute_type":getattr(detail,"attribute_type",None),"aliases":[a.alias for a in t.aliases.all()]}

def exact_matches(candidate):
    n=norm(candidate); out=[]
    qs=DictionaryTerm.objects.prefetch_related("aliases").filter(status="ACTIVE")
    for t in qs:
        if n in {norm(t.canonical_name),norm(t.english_name),*(norm(a.alias) for a in t.aliases.all())}: out.append(serialize_term(t))
    return out

def nearby_terms(candidate, limit=30):
    tokens=[x for x in re.split(r"[^0-9A-Za-z가-힣]+",str(candidate)) if len(x)>1][:8]
    q=Q()
    for tok in tokens: q |= Q(canonical_name__icontains=tok)|Q(english_name__icontains=tok)|Q(aliases__alias__icontains=tok)
    qs=DictionaryTerm.objects.filter(q if tokens else Q(pk__lt=0)).filter(status="ACTIVE").prefetch_related("aliases").distinct()[:limit]
    return [serialize_term(t) for t in qs]

def product_evidence(candidate, limit=12):
    qs=ProductSource.objects.filter(Q(source_name__icontains=candidate)|Q(normalized_name__icontains=candidate)).select_related("source").order_by("-updated_at")[:limit]
    return [{"product_source_id":p.pk,"source":getattr(p.source,"code",None),"source_name":p.source_name,"normalized_name":p.normalized_name,"attributes":p.attributes} for p in qs]

def candidate_payload(candidate, nearby_limit=15, evidence_limit=8):
    return {"candidate":candidate,"exact_matches":exact_matches(candidate),"nearby_terms":nearby_terms(candidate, nearby_limit),"product_evidence":product_evidence(candidate,evidence_limit)}

def fast_audit_scan(*, limit=None, offset=0):
    """Pure DB/Python scan. Zero LLM calls. Returns only suspicious records."""
    qs=DictionaryTerm.objects.prefetch_related("aliases").annotate(product_usage=Count("product_terms")).order_by("pk")
    if offset: qs=qs[offset:]
    if limit is not None: qs=qs[:limit]
    rows=list(qs)
    canonical=defaultdict(list); english=defaultdict(list); aliases=defaultdict(list)
    for t in rows:
        if norm(t.canonical_name): canonical[norm(t.canonical_name)].append(t.pk)
        if norm(t.english_name): english[norm(t.english_name)].append(t.pk)
        for a in t.aliases.all():
            if norm(a.alias): aliases[norm(a.alias)].append(t.pk)
    suspicious=[]
    for t in rows:
        flags=[]; n=norm(t.canonical_name); en=norm(t.english_name)
        if n and len(canonical[n])>1: flags.append({"kind":"DUPLICATE_CANONICAL","term_ids":canonical[n]})
        if n and any(x!=t.pk for x in aliases.get(n,[])): flags.append({"kind":"CANONICAL_EQUALS_OTHER_ALIAS","term_ids":aliases[n]})
        if en and len(english[en])>1: flags.append({"kind":"DUPLICATE_ENGLISH","term_ids":english[en]})
        if not (t.description or "").strip(): flags.append({"kind":"MISSING_DESCRIPTION"})
        elif len((t.description or "").strip()) < 8: flags.append({"kind":"VERY_SHORT_DESCRIPTION"})
        if getattr(t,"status",None)=="ACTIVE" and getattr(t,"product_usage",0)==0: flags.append({"kind":"UNUSED_ACTIVE_TERM"})
        if flags:
            suspicious.append({**serialize_term(t),"product_usage":getattr(t,"product_usage",0),"fast_flags":flags})
    return {"scanned":len(rows),"suspicious":suspicious}
