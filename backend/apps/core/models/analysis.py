from django.db import models


class TextDocument(models.Model):
    class DocumentType(models.TextChoices):
        TRANSCRIPT = "TRANSCRIPT", "자막"
        COMMENT = "COMMENT", "댓글"
        REVIEW = "REVIEW", "리뷰"
        DESCRIPTION = "DESCRIPTION", "설명"
        ARTICLE = "ARTICLE", "본문"

    class AnalysisStatus(models.TextChoices):
        PENDING = "PENDING", "대기"
        PROCESSING = "PROCESSING", "분석 중"
        DONE = "DONE", "완료"
        FAILED = "FAILED", "실패"

    source = models.ForeignKey(
        "core.Source",
        on_delete=models.PROTECT,
        related_name="text_documents",
        verbose_name="플랫폼",
    )

    content_item = models.ForeignKey(
        "core.ContentItem",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="text_documents",
        verbose_name="콘텐츠",
    )

    document_type = models.CharField(
        max_length=30,
        choices=DocumentType.choices,
        verbose_name="문서 유형",
    )

    external_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="플랫폼 문서 ID",
    )

    body = models.TextField(
        verbose_name="분석 텍스트",
    )

    language = models.CharField(
        max_length=10,
        default="ko",
        verbose_name="언어",
    )

    sentiment_score = models.DecimalField(
        max_digits=6,
        decimal_places=5,
        null=True,
        blank=True,
        verbose_name="감성 점수",
    )

    intent_code = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name="의도 코드",
    )

    # 상세 분석 결과
    extracted_terms = models.JSONField(
        default=list,
        blank=True,
        verbose_name="추출 용어",
    )

    analysis_metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="분석 추가 정보",
    )

    analysis_status = models.CharField(
        max_length=20,
        choices=AnalysisStatus.choices,
        default=AnalysisStatus.PENDING,
        verbose_name="분석 상태",
    )

    analyzed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="분석일시",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="생성일시",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="수정일시",
    )

    class Meta:
        db_table = '"analysis"."text_document"'
        verbose_name = "분석 문서"
        verbose_name_plural = "분석 문서"

        indexes = [
            models.Index(
                fields=["content_item", "document_type"],
                name="idx_text_doc_content",
            ),
            models.Index(
                fields=["analysis_status"],
                name="idx_text_doc_status",
            ),
            models.Index(
                fields=["-created_at"],
                name="idx_text_doc_created",
            ),
        ]

    def __str__(self):
        if self.content_item:
            return f"{self.get_document_type_display()} / {self.content_item}"

        return f"{self.get_document_type_display()} / {self.id}"


class TermMetricDaily(models.Model):
    """
    용어별 하루 단위 트렌드 지표.

    ── 2026-09-07 보강 ──────────────────────────────────────
    크롤러가 이미 계산해 둔 값을 그대로 받을 수 있게 칸을 맞췄다.
    지표 정의의 원본은 `FEEDiT_지표계산_설계서.md` 이고, 계산은 크롤러가 한다.
    여기서 다시 계산하지 않는다 — 두 곳에서 계산하면 화면과 챗봇이
    서로 다른 숫자를 말하게 된다.

    ★ 왜 JSON 이 아니라 컬럼인가
      온도·모멘텀은 **정렬과 범위 조회에 쓰는 값**이다.
        · 화면 첫 진입   ORDER BY temp DESC LIMIT 20
        · 구간 필터      WHERE temp >= 75          (과열)
        · 챗봇 "뜨는 것" ORDER BY momentum DESC
      JSONB 도 표현식 인덱스로 가능하지만, 질의가 인덱스 표현식과 한 글자라도
      다르면 조용히 전체 훑기로 떨어진다. 게다가 JSON 안 숫자는 타입이 없어서
      "9" > "10" 같은 문자열 비교 사고가 난다 — 값이 틀려도 에러가 안 난다.
      그래서 **자주 정렬·필터하는 여섯 개만 컬럼**으로 빼고,
      나머지(raw_count·log_value·share_pct·실험값)는 `metrics` JSON 에 둔다.
    """

    term = models.ForeignKey(
        "core.DictionaryTerm",
        on_delete=models.CASCADE,
        related_name="daily_metrics",
        verbose_name="용어",
    )

    # ★★ 플랫폼별 지표를 담으려면 이 칸이 있어야 한다 ★★
    #   크롤러는 이미 (용어 × 플랫폼 × 날짜) 로 계산해 둔다.
    #   2026-09-07 실측: 12,484행 중 7,275행(58%)이 플랫폼별 행이다.
    #   이 칸이 없으면 그 58% 가 통째로 들어오지 못한다.
    #
    #   NULL = 전 플랫폼 합산 (크롤러의 `__all__`)
    #   값 있음 = 그 플랫폼만 (musinsa · youtube · naver · zigzag · ably · kream …)
    source = models.ForeignKey(
        "core.Source",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="term_metrics",
        verbose_name="플랫폼",
        help_text="비우면 전 플랫폼 합산",
    )

    metric_date = models.DateField(
        verbose_name="기준일",
    )

    # ★ 공식이 바뀌면 값의 뜻도 바뀐다.
    #   이 칸이 없으면 옛 공식으로 만든 행과 새 공식 행이 한 표에 섞여
    #   그래프가 어느 날 갑자기 튀는데 원인을 찾을 수가 없다.
    metric_version = models.CharField(
        max_length=64,
        default="",
        blank=True,
        db_index=True,
        verbose_name="지표 버전",
        help_text="예: feedit-l2-v2-shadow",
    )

    mention_count = models.BigIntegerField(
        default=0,
        verbose_name="언급 수",
    )

    document_count = models.BigIntegerField(
        default=0,
        verbose_name="문서 수",
    )

    source_count = models.IntegerField(
        default=0,
        verbose_name="플랫폼 수",
    )

    sentiment_avg = models.DecimalField(
        max_digits=6,
        decimal_places=5,
        null=True,
        blank=True,
        verbose_name="평균 감성",
    )

    growth_rate = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        verbose_name="증가율",
    )

    trend_score = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        verbose_name="트렌드 점수",
    )

    # ── 설계서 §1 의 값들 ─────────────────────────────────
    #   전부 크롤러가 계산해서 넘겨준다. 여기서 만들지 않는다.

    level = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        verbose_name="수준(0~100)",
        help_text="같은 축 안에서 이 용어가 어느 정도 위치인가",
    )

    momentum = models.DecimalField(
        max_digits=8, decimal_places=4, null=True, blank=True,
        verbose_name="가속(ma7/ma28)",
        help_text="1보다 크면 최근 7일이 28일 평균보다 뜨겁다",
    )

    temp = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        verbose_name="트렌드 온도(0~100)",
        help_text="수준 60% + 가속 40%. 구간: ~25 차가움 ~50 미지근 ~75 따뜻함 이상 과열",
    )

    ma7 = models.DecimalField(
        max_digits=14, decimal_places=4, null=True, blank=True,
        verbose_name="7일 이동평균",
    )

    ma28 = models.DecimalField(
        max_digits=14, decimal_places=4, null=True, blank=True,
        verbose_name="28일 이동평균",
    )

    pct_rank = models.DecimalField(
        max_digits=6, decimal_places=3, null=True, blank=True,
        verbose_name="백분위(0~100)",
        help_text="이름과 달리 0~1 이 아니라 0~100 이다. 크롤러 실측으로 확인했다.",
    )

    metrics = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="추가 지표",
        help_text="raw_count · log_value · share_pct 등 정렬에 안 쓰는 값",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = '"analysis"."term_metric_daily"'
        verbose_name = "용어 일별 지표"
        verbose_name_plural = "용어 일별 지표"

        constraints = [
            # ★ 예전 제약은 (용어, 날짜) 뿐이었다.
            #   그러면 플랫폼별 행이 서로 충돌한다 — 2026-09-07 실측으로
            #   12,484행 중 7,275행(58%)이 그 이유로 못 들어간다.
            #   플랫폼과 지표 버전까지 넣어야 한 칸씩 자리를 갖는다.
            #
            #   nulls_distinct=False 를 쓰는 이유: source 가 NULL(전체 합산)인
            #   행이 여러 번 들어오면 PostgreSQL 은 기본적으로 NULL 끼리 다르다고
            #   봐서 중복을 막지 못한다. 합산 행도 하루에 하나여야 한다.
            models.UniqueConstraint(
                fields=["term", "source", "metric_date", "metric_version"],
                name="uq_term_metric_day",
                nulls_distinct=False,
            ),
        ]

        indexes = [
            # 화면 첫 진입 — "오늘 온도 높은 순"
            models.Index(
                fields=["metric_date", "-temp"],
                name="idx_term_metric_temp",
            ),
            # 챗봇 "요즘 뜨는 것" — 가속 높은 순
            models.Index(
                fields=["metric_date", "-momentum"],
                name="idx_term_metric_mom",
            ),
            models.Index(
                fields=["metric_date", "-trend_score"],
                name="idx_term_metric_trend",
            ),
            # 용어 하나의 시계열
            models.Index(
                fields=["term", "-metric_date"],
                name="idx_term_metric_term",
            ),
            # 플랫폼별 온도 — "무신사에서는 뜨는데 지그재그에선 아직"
            models.Index(
                fields=["source", "metric_date"],
                name="idx_term_metric_source",
            ),
        ]

    def __str__(self):
        return f"{self.term} / {self.metric_date}"


class TermAssocDaily(models.Model):
    """
    용어 ↔ 용어 일별 연관도.
    """

    source_term = models.ForeignKey(
        "core.DictionaryTerm",
        on_delete=models.CASCADE,
        related_name="daily_assoc_sources",
        verbose_name="기준 용어",
    )

    target_term = models.ForeignKey(
        "core.DictionaryTerm",
        on_delete=models.CASCADE,
        related_name="daily_assoc_targets",
        verbose_name="연관 용어",
    )

    metric_date = models.DateField(
        verbose_name="기준일",
    )

    cooccurrence_count = models.BigIntegerField(
        default=0,
        verbose_name="동시 언급 수",
    )

    association_score = models.DecimalField(
        max_digits=10,
        decimal_places=5,
        null=True,
        blank=True,
        verbose_name="연관도",
    )

    confidence = models.DecimalField(
        max_digits=6,
        decimal_places=5,
        null=True,
        blank=True,
        verbose_name="신뢰도",
    )

    metrics = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="추가 지표",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = '"analysis"."term_assoc_daily"'
        verbose_name = "용어 일별 연관"
        verbose_name_plural = "용어 일별 연관"

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "source_term",
                    "target_term",
                    "metric_date",
                ],
                name="uq_term_assoc_day",
            ),
            models.CheckConstraint(
                condition=~models.Q(
                    source_term=models.F("target_term")
                ),
                name="ck_term_assoc_self",
            ),
        ]

        indexes = [
            models.Index(
                fields=["source_term", "-metric_date"],
                name="idx_assoc_src_day",
            ),
            models.Index(
                fields=["metric_date", "-association_score"],
                name="idx_assoc_score",
            ),
        ]

    def __str__(self):
        return (
            f"{self.source_term} ↔ "
            f"{self.target_term} / "
            f"{self.metric_date}"
        )