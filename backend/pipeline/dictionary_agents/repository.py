from __future__ import annotations
import re
from django.db.models import Count, Q
from apps.core.models import DictionaryTerm, TermAlias, ProductTerm, ProductSource

def norm(v): return re.sub(r"[^0-9a-z가-힣]+","",str(v or "").casefold())
def serialize_term(t):
    detail=getattr(t,"detail",None)
    return {"term_id":t.pk,"term_code":t.term_code,"term_type":t.term_type,"canonical_name":t.canonical_name,"english_name":t.english_name,"description":t.description,"status":t.status,"detail_attribute_type":getattr(detail,"attribute_type",None),"aliases":[a.alias for a in t.aliases.all()]}

def exact_matches(candidate):
    n=norm(candidate)
    out=[]
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

def product_evidence(candidate, limit=20):
    qs=ProductSource.objects.filter(Q(source_name__icontains=candidate)|Q(normalized_name__icontains=candidate)).select_related("source").order_by("-updated_at")[:limit]
    return [{"product_source_id":p.pk,"source":getattr(p.source,"code",None),"source_name":p.source_name,"normalized_name":p.normalized_name,"attributes":p.attributes} for p in qs]

def audit_records(limit=50, offset=0):
    qs=DictionaryTerm.objects.prefetch_related("aliases").annotate(product_usage=Count("product_terms")).order_by("pk")[offset:offset+limit]
    return [{**serialize_term(t),"product_usage":t.product_usage} for t in qs]
