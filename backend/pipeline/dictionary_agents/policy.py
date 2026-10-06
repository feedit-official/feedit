from __future__ import annotations
import re
SUPPORTED_TYPES={"STYLE","ITEM","DETAIL","MATERIAL","COLOR","TPO","BRAND","PERSON","TARGET"}
MARKETING_PATTERNS=(r"인생.?핏",r"착시.?핏",r"여신",r"꾸안꾸.?필수",r"소장.?각",r"강력.?추천",r"대박",r"핫템",r"필수템",r"데일리.?필수")

def normalize_text(v): return re.sub(r"[^0-9a-z가-힣]+","",str(v or "").casefold())
def looks_marketing(v): return any(re.search(p,str(v or ""),re.I) for p in MARKETING_PATTERNS)
def validate_decision(d):
    errors=[]
    if d.term_type and d.term_type not in SUPPORTED_TYPES: errors.append("unsupported term_type")
    if d.action=="ADD_TERM" and (not d.canonical_name or not d.term_type): errors.append("ADD_TERM requires canonical_name and term_type")
    if d.action in {"UPDATE_TERM","RECLASSIFY","DEACTIVATE_TERM","ADD_ALIAS"} and not d.existing_term_id: errors.append(f"{d.action} requires existing_term_id")
    if d.action=="MERGE_TERM" and (not d.existing_term_id or not d.merge_target_term_id): errors.append("MERGE_TERM requires source/target")
    if d.confidence < .82 and d.action not in {"HOLD","KEEP","REJECT"}: errors.append("confidence below apply threshold")
    if looks_marketing(d.candidate) and d.action=="ADD_TERM": errors.append("marketing expression cannot be promoted automatically")
    return errors
