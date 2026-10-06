from __future__ import annotations

import re
from collections import Counter, defaultdict

from apps.core.models import DictionaryTerm, ProductSource, TermAlias

from .repository import norm


# ============================================================
# Constants
# ============================================================

TOKEN_RE = re.compile(
    r"[A-Za-z가-힣][A-Za-z가-힣0-9+&./-]*"
)

NOISE = {
    "기획",
    "단독",
    "신상",
    "추천",
    "인기",
    "베스트",
    "무료배송",
    "빠른배송",
    "빠른교환",
    "빠른환불",
    "정품",
    "공식",
    "특가",
    "할인",
    "세일",
    "쿠폰",
    "증정",
    "당일",
    "예약",
    "컬러",
    "color",
    "colors",
    "size",
    "사이즈",
}

NOISE_NORMALIZED = {
    norm(value)
    for value in NOISE
}


# ============================================================
# Known dictionary
# ============================================================

def _known_norms() -> set[str]:
    """
    현재 FEEDIT 패션 사전에서 이미 알고 있는 표현을 반환한다.

    포함:
    - DictionaryTerm.canonical_name
    - DictionaryTerm.english_name
    - TermAlias.alias

    LLM 호출 없음.
    """

    known: set[str] = set()

    terms = (
        DictionaryTerm.objects
        .filter(status="ACTIVE")
        .values_list(
            "canonical_name",
            "english_name",
        )
    )

    for canonical_name, english_name in terms.iterator(
        chunk_size=5000
    ):
        if canonical_name:
            known.add(norm(canonical_name))

        if english_name:
            known.add(norm(english_name))

    aliases = (
        TermAlias.objects
        .values_list(
            "alias",
            flat=True,
        )
    )

    for alias in aliases.iterator(
        chunk_size=5000
    ):
        if alias:
            known.add(norm(alias))

    known.discard("")

    return known


# ============================================================
# Tokenizer
# ============================================================

def _tokens(text: str | None) -> list[str]:
    """
    상품명에서 패션 용어 후보 토큰을 추출한다.

    여기서는 ontology 판정을 하지 않는다.
    Candidate discovery만 수행한다.
    """

    if not text:
        return []

    tokens: list[str] = []

    for token in TOKEN_RE.findall(str(text)):
        token = token.strip("-./")

        normalized = norm(token)

        if not normalized:
            continue

        if len(normalized) < 2:
            continue

        if normalized in NOISE_NORMALIZED:
            continue

        tokens.append(token)

    return tokens


def _ngrams(
    tokens: list[str],
    *,
    max_words: int = 3,
):
    """
    1~N 어절 후보 생성.

    예:
        ["빈티지", "링거", "티셔츠"]

    ->
        빈티지
        링거
        티셔츠
        빈티지 링거
        링거 티셔츠
        빈티지 링거 티셔츠
    """

    if not tokens:
        return

    max_n = min(
        max_words,
        len(tokens),
    )

    for n in range(1, max_n + 1):
        for i in range(
            len(tokens) - n + 1
        ):
            yield " ".join(
                tokens[i:i + n]
            )


# ============================================================
# Candidate validation
# ============================================================

def _is_noise_phrase(
    phrase: str,
    *,
    known: set[str],
) -> bool:
    normalized = norm(phrase)

    if not normalized:
        return True

    # 이미 사전에 존재
    if normalized in known:
        return True

    # 마케팅/커머스 노이즈
    if normalized in NOISE_NORMALIZED:
        return True

    # 숫자만 존재
    if normalized.isdigit():
        return True

    # 너무 짧은 표현
    if len(normalized) < 2:
        return True

    parts = _tokens(phrase)

    if not parts:
        return True

    # --------------------------------------------------------
    # 이미 알고 있는 개념들의 단순 조합은
    # 신규 Term 후보로 만들지 않는다.
    #
    # 예:
    # 울 + 니트
    # 블랙 + 팬츠
    # 라운드넥 + 티셔츠
    # --------------------------------------------------------

    if (
        len(parts) > 1
        and all(
            norm(part) in known
            for part in parts
        )
    ):
        return True

    return False


# ============================================================
# Discovery
# ============================================================

def discover_candidates(
    *,
    limit_products: int | None = 30000,
    min_frequency: int = 3,
    min_product_count: int = 3,
    max_candidates: int = 100,
    max_words: int = 3,
    source_codes: list[str] | tuple[str, ...] | None = None,
    only_unlinked: bool = False,
):
    """
    ProductSource 상품명에서 패션 사전 후보를 자동 발굴한다.

    IMPORTANT
    ---------
    이 단계에서는 LLM을 사용하지 않는다.

    역할:
        ProductSource
            ↓
        token / n-gram
            ↓
        DictionaryTerm / TermAlias 제거
            ↓
        반복 관찰 후보 집계
            ↓
        product / brand / platform evidence 기반 ranking

    Miranda Agent는 이 결과만 검수한다.
    """

    known = _known_norms()

    # --------------------------------------------------------
    # ProductSource query
    #
    # source_brand는 BrandSource FK.
    #
    # 여기서는 BrandSource 객체 자체가 필요 없다.
    # source_brand_id만 읽으면 되므로
    # select_related("source_brand")도 필요 없음.
    #
    # 불필요한 JOIN 제거.
    # --------------------------------------------------------

    qs = (
        ProductSource.objects
        .select_related("source")
        .order_by("-updated_at")
    )

    if source_codes:
        qs = qs.filter(
            source__code__in=source_codes
        )

    if only_unlinked:
        qs = qs.filter(
            product_id__isnull=True
        )

    if limit_products:
        qs = qs[:limit_products]

    # --------------------------------------------------------
    # Aggregation containers
    # --------------------------------------------------------

    frequency: Counter[str] = Counter()

    product_ids: dict[
        str,
        set[int],
    ] = defaultdict(set)

    brand_ids: dict[
        str,
        set[int],
    ] = defaultdict(set)

    source_codes_seen: dict[
        str,
        set[str],
    ] = defaultdict(set)

    examples: dict[
        str,
        list[dict],
    ] = defaultdict(list)

    # normalized candidate -> representative phrase
    representative: dict[
        str,
        str,
    ] = {}

    scanned = 0

    # --------------------------------------------------------
    # Scan
    # --------------------------------------------------------

    for product_source in qs.iterator(
        chunk_size=1000
    ):
        scanned += 1

        text = (
            getattr(
                product_source,
                "normalized_name",
                None,
            )
            or getattr(
                product_source,
                "source_name",
                None,
            )
            or ""
        ).strip()

        if not text:
            continue

        tokens = _tokens(text)

        if not tokens:
            continue

        # 같은 상품에서 동일 candidate가 여러 번 등장해도
        # product_count는 1회만 증가하도록 제어
        seen_in_product: set[str] = set()

        for phrase in _ngrams(
            tokens,
            max_words=max_words,
        ):
            normalized = norm(phrase)

            if _is_noise_phrase(
                phrase,
                known=known,
            ):
                continue

            if normalized in seen_in_product:
                continue

            seen_in_product.add(
                normalized
            )

            # ----------------------------------------------
            # 표기 차이 통합
            #
            # Pea Coat / pea coat 등의 빈도를
            # normalized key 하나로 집계한다.
            # ----------------------------------------------

            if normalized not in representative:
                representative[normalized] = phrase

            key = normalized

            frequency[key] += 1

            product_ids[key].add(
                product_source.pk
            )

            # ----------------------------------------------
            # Platform evidence
            # ----------------------------------------------

            source = getattr(
                product_source,
                "source",
                None,
            )

            source_code = getattr(
                source,
                "code",
                None,
            )

            if source_code:
                source_codes_seen[key].add(
                    source_code
                )

            # ----------------------------------------------
            # Brand evidence
            #
            # ProductSource.source_brand_id는
            # BrandSource PK이다.
            #
            # BrandSource 객체를 JOIN할 필요가 없다.
            #
            # 같은 FEEDIT Brand의 여러 BrandSource를
            # 하나로 합치고 싶다면 별도 단계에서
            # source_brand.brand_id를 사용하면 되지만,
            # Discovery ranking 용도로는 FK 자체로 충분.
            # ----------------------------------------------

            source_brand_id = getattr(
                product_source,
                "source_brand_id",
                None,
            )

            if source_brand_id:
                brand_ids[key].add(
                    source_brand_id
                )

            # ----------------------------------------------
            # Examples
            # ----------------------------------------------

            if len(examples[key]) < 4:
                examples[key].append(
                    {
                        "product_source_id":
                            product_source.pk,
                        "source":
                            source_code,
                        "source_brand_id":
                            source_brand_id,
                        "name":
                            text,
                    }
                )

    # ========================================================
    # Ranking
    # ========================================================

    rows: list[dict] = []

    for key, count in frequency.items():
        product_count = len(
            product_ids[key]
        )

        if count < min_frequency:
            continue

        if product_count < min_product_count:
            continue

        brand_count = len(
            brand_ids[key]
        )

        source_count = len(
            source_codes_seen[key]
        )

        phrase = representative.get(
            key,
            key,
        )

        # ----------------------------------------------------
        # Score
        #
        # 동일 상품 내 반복보다
        # 여러 상품 / 여러 브랜드 / 여러 플랫폼에서
        # 관찰되는 것을 중요하게 본다.
        # ----------------------------------------------------

        score = (
            product_count
            + min(
                brand_count,
                10,
            ) * 2
            + min(
                source_count,
                5,
            ) * 3
        )

        rows.append(
            {
                "candidate":
                    phrase,

                "normalized_candidate":
                    key,

                "frequency":
                    count,

                "product_count":
                    product_count,

                "brand_count":
                    brand_count,

                "source_count":
                    source_count,

                "score":
                    score,

                "examples":
                    examples[key],
            }
        )

    rows.sort(
        key=lambda row: (
            -row["score"],
            -row["product_count"],
            -row["brand_count"],
            -row["source_count"],
            len(row["candidate"]),
        )
    )

    selected = rows[
        :max_candidates
    ]

    return {
        "scanned_products":
            scanned,

        "known_dictionary_expressions":
            len(known),

        "raw_phrase_count":
            len(frequency),

        "eligible_candidate_count":
            len(rows),

        "selected_candidate_count":
            len(selected),

        "candidates":
            selected,
    }