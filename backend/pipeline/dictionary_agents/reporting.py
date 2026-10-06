def print_audit_summary(result):
    print("="*88); print("FEEDIT DICTIONARY AUDIT"); print("="*88)
    print("SCANNED :", result.get("scanned",0)); print("FINDINGS:", len(result.get("findings",[])))
    counts={}
    for f in result.get("findings",[]): counts[f["action"]]=counts.get(f["action"],0)+1
    for k,v in sorted(counts.items()): print(f"{k:18} {v}")
