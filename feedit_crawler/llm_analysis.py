"""OpenAI Responses API를 쓰는 패션 텍스트 분석기.

규칙 기반 필터를 없애지 않는다. 규칙은 수집 직후의 값싼 1차 판정이고,
이 모듈은 통과한 텍스트를 문맥까지 읽어 보강하는 2차 분석기다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import requests

MODEL = "gpt-5.6-luna"
PROMPT_VERSION = "feedit-text-v3-entity-opinion"
API = "https://api.openai.com/v1"
# intent.py와 플랫폼 intent_rule의 코드 6개를 그대로 쓴다. 이름이 다르면
# 규칙 결과와 LLM 결과를 비교할 수 없고 지표 집계도 둘로 갈라진다.
INTENTS = ["buy_done", "restock", "considering", "price_pain",
           "disappoint", "returned"]

FORMAT = {
    "type": "json_schema",
    "name": "feedit_text_analysis",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "fashion_relevance": {"type": "number", "minimum": 0, "maximum": 1},
            "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative", "mixed"]},
            "sentiment_score": {"type": "number", "minimum": -1, "maximum": 1},
            # OpenAI Structured Outputs의 JSON Schema 부분집합은 uniqueItems를
            # 허용하지 않는다. 중복 제거는 응답을 받은 뒤 아래에서 처리한다.
            "purchase_intents": {"type": "array", "items": {"type": "string", "enum": INTENTS}},
            "related_terms": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
            "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "entities": {"type": "array", "maxItems": 12, "items": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "canonical": {"type": "string"},
                    "facet": {"type": "string", "enum": ["style", "material", "item", "brand", "detail"]},
                    "surface": {"type": "string"},
                    "role": {"type": "string", "enum": ["target", "context"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "evidence": {"type": "string"},
                },
                "required": ["canonical", "facet", "surface", "role", "confidence", "evidence"],
            }},
            "entity_opinions": {"type": "array", "maxItems": 12, "items": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "canonical": {"type": "string"},
                    "facet": {"type": "string", "enum": ["style", "material", "item", "brand", "detail"]},
                    "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative", "mixed"]},
                    "sentiment_score": {"type": "number", "minimum": -1, "maximum": 1},
                    "purchase_intents": {"type": "array", "items": {"type": "string", "enum": INTENTS}},
                    "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["canonical", "facet", "sentiment", "sentiment_score",
                             "purchase_intents", "evidence", "confidence"],
            }},
            "unresolved_terms": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
            "no_signal_reason": {"type": "string"},
        },
        "required": ["fashion_relevance", "sentiment", "sentiment_score",
                     "purchase_intents", "related_terms", "evidence", "confidence",
                     "entities", "entity_opinions", "unresolved_terms", "no_signal_reason"],
    },
}

INSTRUCTIONS = """당신은 한국 패션 커머스 텍스트 분석기다. 입력이 패션과 실제로 관련 있는지 먼저 판정한다.
동음이의어(운동, 여행, 출근, 색, 골지, 와플 등)는 의류·코디·스타일 문맥이 있을 때만 관련 있다고 본다.
감성과 구매 의향은 구분한다. '예쁘다'는 긍정이지만 구매 의향이 아닐 수 있고, '비싸지만 사고 싶다'는
부정 감정과 구매 고려가 함께 있을 수 있다. related_terms에는 입력에 근거한 패션 개체/속성만 한국어
표준형으로 넣고 추측해서 만들지 않는다. evidence는 원문에서 판단 근거가 된 짧은 구절만 넣는다.
entities는 제공된 사전 후보 중 문맥상 실제 대상을 우선 선택한다. target은 감성·질문·구매 의향의 직접 대상,
context는 주변 착장이나 설명에 불과한 항목이다. 패션 정보가 없으면 entities와 unresolved_terms를 비우고
no_signal_reason에 이유를 쓴다. 패션 정보는 있으나 사전 후보로 확정할 수 없으면 unresolved_terms에 원문 표현을 넣는다.
entity_opinions에는 target 엔티티별 감성·구매 의향·직접 근거를 각각 적는다. 문서에 여러 대상이 있으면 서로
섞지 말고 해당 대상에 직접 연결되는 표현만 넣는다. 대상별 근거가 없으면 그 엔티티의 opinion은 만들지 않는다."""


class AnalysisError(RuntimeError):
    pass


@dataclass
class OpenAITextAnalyzer:
    api_key: str
    timeout: int = 60

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def test_connection(self) -> str:
        r = requests.get(f"{API}/models/{MODEL}", headers=self.headers, timeout=20)
        self._raise(r)
        return r.json().get("id") or MODEL

    def analyze(self, text: str, candidates: list[dict] | None = None) -> dict:
        body = {
            "model": MODEL,
            "store": False,
            "reasoning": {"effort": "low"},
            "instructions": INSTRUCTIONS,
            "input": json.dumps({"text": text, "dictionary_candidates": [
                {k: c.get(k) for k in ("canonical", "facet", "surface", "status", "confidence")}
                for c in (candidates or [])[:30]
            ]}, ensure_ascii=False),
            "text": {"format": FORMAT},
        }
        r = requests.post(f"{API}/responses", headers=self.headers, json=body,
                          timeout=self.timeout)
        self._raise(r)
        raw = r.json()
        output = raw.get("output_text") or self._output_text(raw)
        if not output:
            raise AnalysisError("모델 응답에 분석 결과가 없습니다.")
        try:
            result = json.loads(output)
        except (TypeError, json.JSONDecodeError) as e:
            raise AnalysisError("모델이 올바른 JSON 분석 결과를 보내지 않았습니다.") from e
        # 스키마 단계에서 uniqueItems를 쓸 수 없으므로 순서를 지키며 정리한다.
        result["purchase_intents"] = list(dict.fromkeys(result.get("purchase_intents") or []))
        result["related_terms"] = list(dict.fromkeys(result.get("related_terms") or []))
        result["evidence"] = list(dict.fromkeys(result.get("evidence") or []))
        result["unresolved_terms"] = list(dict.fromkeys(result.get("unresolved_terms") or []))
        for opinion in result.get("entity_opinions") or []:
            opinion["purchase_intents"] = list(dict.fromkeys(opinion.get("purchase_intents") or []))
            opinion["evidence"] = list(dict.fromkeys(opinion.get("evidence") or []))
        usage = raw.get("usage") or {}
        result.update({
            "model": raw.get("model") or MODEL,
            "prompt_version": PROMPT_VERSION,
            "response_id": raw.get("id"),
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
        })
        return result

    @staticmethod
    def _output_text(raw: dict) -> str:
        for item in raw.get("output") or []:
            for content in item.get("content") or []:
                if content.get("type") == "output_text" and content.get("text"):
                    return content["text"]
        return ""

    @staticmethod
    def _raise(response):
        if response.ok:
            return
        try:
            detail = (response.json().get("error") or {}).get("message")
        except ValueError:
            detail = None
        if response.status_code in (401, 403):
            raise AnalysisError("OpenAI API 키가 거부됐습니다. 키와 프로젝트 권한을 확인해 주세요.")
        if response.status_code == 429:
            raise AnalysisError("OpenAI 사용 한도 또는 호출 속도를 넘었습니다. 결제·한도를 확인해 주세요.")
        raise AnalysisError(detail or f"OpenAI API 호출 실패 ({response.status_code})")
