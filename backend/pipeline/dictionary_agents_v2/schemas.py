from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field

Action = Literal["KEEP","ADD_TERM","ADD_ALIAS","UPDATE_TERM","MERGE_TERM","DEACTIVATE_TERM","RECLASSIFY","ADD_RELATION","REMOVE_RELATION","HOLD","REJECT"]
TermType = Literal["STYLE","ITEM","DETAIL","MATERIAL","COLOR","TPO","BRAND","PERSON","TARGET"]

class DictionaryChanges(BaseModel):
    add_aliases: list[str] = Field(default_factory=list)
    remove_aliases: list[str] = Field(default_factory=list)
    update_description: bool = False
    add_relations: list[dict] = Field(default_factory=list)
    remove_relations: list[dict] = Field(default_factory=list)

class DictionaryDecision(BaseModel):
    action: Action
    candidate: str
    canonical_name: str | None = None
    english_name: str | None = None
    term_type: TermType | None = None
    detail_attribute_type: str | None = None
    description: str | None = None
    existing_term_id: int | None = None
    merge_target_term_id: int | None = None
    aliases: list[str] = Field(default_factory=list)  # compatibility; treated as proposed aliases
    changes: DictionaryChanges = Field(default_factory=DictionaryChanges)
    relation_type: str | None = None
    relation_target_term_id: int | None = None
    confidence: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)
    reason: str
    warnings: list[str] = Field(default_factory=list)

class DictionaryDecisionBatch(BaseModel):
    decisions: list[DictionaryDecision] = Field(default_factory=list)

class AuditFinding(BaseModel):
    term_id: int
    action: Action
    confidence: float = Field(ge=0, le=1)
    reason: str
    proposed_canonical_name: str | None = None
    proposed_english_name: str | None = None
    proposed_term_type: TermType | None = None
    proposed_description: str | None = None
    merge_target_term_id: int | None = None
    aliases_to_add: list[str] = Field(default_factory=list)

class AuditResult(BaseModel):
    findings: list[AuditFinding] = Field(default_factory=list)
