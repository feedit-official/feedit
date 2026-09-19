from django.db import models


class AppUser(models.Model):
    """
    FEEDIT 서비스 사용자.
    Django auth.User와 1:1로 연결해서 쓰는 구조.
    """

    user = models.OneToOneField(
        "auth.User",
        on_delete=models.CASCADE,
        related_name="feedit_profile",
        verbose_name="사용자",
    )

    nickname = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="닉네임",
    )

    gender = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        verbose_name="성별",
    )

    birth_year = models.IntegerField(
        null=True,
        blank=True,
        verbose_name="출생연도",
    )

    body_type = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name="체형",
    )

    profile_metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="추가 프로필 정보",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="가입일시",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="수정일시",
    )

    class Meta:
        db_table = '"app"."app_user"'
        verbose_name = "사용자"
        verbose_name_plural = "사용자"

    def __str__(self):
        return self.nickname or self.user.username


class UserTaste(models.Model):
    """
    사용자의 관심 스타일 / 아이템 / 브랜드 / 용어.
    """

    class TasteType(models.TextChoices):
        TERM = "TERM", "용어"
        BRAND = "BRAND", "브랜드"
        CATEGORY = "CATEGORY", "카테고리"

    user = models.ForeignKey(
        AppUser,
        on_delete=models.CASCADE,
        related_name="tastes",
        verbose_name="사용자",
    )

    taste_type = models.CharField(
        max_length=20,
        choices=TasteType.choices,
        verbose_name="취향 유형",
    )

    term = models.ForeignKey(
        "core.DictionaryTerm",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="user_tastes",
        verbose_name="용어",
    )

    brand = models.ForeignKey(
        "core.Brand",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="user_tastes",
        verbose_name="브랜드",
    )

    category = models.ForeignKey(
        "core.Category",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="user_tastes",
        verbose_name="카테고리",
    )

    weight = models.DecimalField(
        max_digits=6,
        decimal_places=5,
        default=1,
        verbose_name="관심 가중치",
    )

    source = models.CharField(
        max_length=30,
        default="USER",
        verbose_name="취향 출처",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = '"app"."user_taste"'
        verbose_name = "사용자 취향"
        verbose_name_plural = "사용자 취향"

        indexes = [
            models.Index(
                fields=["user", "taste_type"],
                name="idx_taste_user_type",
            ),
        ]

    def __str__(self):
        if self.term:
            return f"{self.user} / {self.term}"
        if self.brand:
            return f"{self.user} / {self.brand}"
        if self.category:
            return f"{self.user} / {self.category}"

        return str(self.user)


class UserEvent(models.Model):
    """
    사용자의 행동 로그.
    클릭, 조회, 저장, 검색, 투표 등.
    """

    class EventType(models.TextChoices):
        VIEW = "VIEW", "조회"
        CLICK = "CLICK", "클릭"
        SAVE = "SAVE", "저장"
        SEARCH = "SEARCH", "검색"
        VOTE = "VOTE", "투표"
        CHAT = "CHAT", "챗봇"

    user = models.ForeignKey(
        AppUser,
        on_delete=models.CASCADE,
        related_name="events",
        verbose_name="사용자",
    )

    event_type = models.CharField(
        max_length=30,
        choices=EventType.choices,
        verbose_name="행동 유형",
    )

    content_item = models.ForeignKey(
        "core.ContentItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="user_events",
        verbose_name="콘텐츠",
    )

    product = models.ForeignKey(
        "core.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="user_events",
        verbose_name="상품",
    )

    term = models.ForeignKey(
        "core.DictionaryTerm",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="user_events",
        verbose_name="용어",
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="행동 추가 정보",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="발생일시",
    )

    class Meta:
        db_table = '"app"."user_event"'
        verbose_name = "사용자 행동"
        verbose_name_plural = "사용자 행동"

        indexes = [
            models.Index(
                fields=["user", "-created_at"],
                name="idx_event_user_time",
            ),
            models.Index(
                fields=["event_type", "-created_at"],
                name="idx_event_type_time",
            ),
        ]

    def __str__(self):
        return f"{self.user} / {self.get_event_type_display()}"


class UserSavedItem(models.Model):
    """
    사용자가 저장한 상품 또는 콘텐츠.
    """

    user = models.ForeignKey(
        AppUser,
        on_delete=models.CASCADE,
        related_name="saved_items",
        verbose_name="사용자",
    )

    product = models.ForeignKey(
        "core.Product",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="saved_by_users",
        verbose_name="상품",
    )

    content_item = models.ForeignKey(
        "core.ContentItem",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="saved_by_users",
        verbose_name="콘텐츠",
    )

    # ── 가격 하락 알림(1번)이 쓰는 기준값 ──────────────────────────
    # 찜한 순간의 가격을 여기에 박아 둔다. 스냅샷 시계열만으로는
    # '언제 대비 내렸는지'가 사람마다 달라 판정이 흔들린다.
    saved_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="찜 시점 가격",
    )

    # 그 가격을 읽은 판매처. 한 상품에 판매처가 여럿이면 비교 대상을 고정한다.
    saved_price_source = models.ForeignKey(
        "core.ProductSource",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="saved_price_items",
        verbose_name="가격 기준 판매처",
    )

    saved_price_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="찜 시점 가격 관측일시",
    )

    # 마지막으로 알린 가격. 같은 하락을 며칠 내리 알리지 않기 위해 남긴다.
    notified_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="마지막 알림 가격",
    )

    notified_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="마지막 알림 시각",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="저장일시",
    )

    class Meta:
        db_table = '"app"."user_saved_item"'
        verbose_name = "저장 항목"
        verbose_name_plural = "저장 항목"

        constraints = [
            models.UniqueConstraint(
                fields=["user", "product"],
                condition=models.Q(product__isnull=False),
                name="uq_saved_user_product",
            ),
            models.UniqueConstraint(
                fields=["user", "content_item"],
                condition=models.Q(content_item__isnull=False),
                name="uq_saved_user_content",
            ),
        ]

        indexes = [
            models.Index(
                fields=["user", "-created_at"],
                name="idx_saved_user_time",
            ),
        ]

    def __str__(self):
        return f"{self.user} / 저장"


class VoteCard(models.Model):
    """
    '살!말?' 카드.
    """

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "진행 중"
        CLOSED = "CLOSED", "종료"

    user = models.ForeignKey(
        AppUser,
        on_delete=models.CASCADE,
        related_name="vote_cards",
        verbose_name="작성자",
    )

    product = models.ForeignKey(
        "core.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vote_cards",
        verbose_name="상품",
    )

    product_source = models.ForeignKey(
        "core.ProductSource",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vote_cards",
        verbose_name="상품 출처",
    )

    seed_key = models.CharField(
        max_length=160,
        null=True,
        blank=True,
        unique=True,
        verbose_name="시드 식별자",
    )

    gender_target = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        verbose_name="성별 타깃",
    )

    title = models.CharField(
        max_length=300,
        verbose_name="제목",
    )

    description = models.TextField(
        null=True,
        blank=True,
        verbose_name="내용",
    )

    image_url = models.TextField(
        null=True,
        blank=True,
        verbose_name="이미지 URL",
    )

    tags = models.JSONField(
        default=list,
        blank=True,
        verbose_name="태그",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        verbose_name="상태",
    )

    closes_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="마감일시",
    )

    source_metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="출처 메타데이터",
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
        db_table = '"app"."vote_card"'
        verbose_name = "살말 카드"
        verbose_name_plural = "살말 카드"

        indexes = [
            models.Index(
                fields=["status", "-created_at"],
                name="idx_vote_card_status",
            ),
            models.Index(
                fields=["gender_target", "status"],
                name="idx_vote_gender_status",
            ),
        ]

    def __str__(self):
        return self.title


class VoteBallot(models.Model):
    """
    살 / 말 투표.
    """

    class Choice(models.TextChoices):
        BUY = "BUY", "살"
        PASS = "PASS", "말"

    card = models.ForeignKey(
        VoteCard,
        on_delete=models.CASCADE,
        related_name="ballots",
        verbose_name="살말 카드",
    )

    user = models.ForeignKey(
        AppUser,
        on_delete=models.CASCADE,
        related_name="vote_ballots",
        verbose_name="사용자",
    )

    choice = models.CharField(
        max_length=10,
        choices=Choice.choices,
        verbose_name="선택",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="투표일시",
    )

    class Meta:
        db_table = '"app"."vote_ballot"'
        verbose_name = "살말 투표"
        verbose_name_plural = "살말 투표"

        constraints = [
            models.UniqueConstraint(
                fields=["card", "user"],
                name="uq_vote_ballot",
            ),
        ]

    def __str__(self):
        return f"{self.card} / {self.get_choice_display()}"


class VoteComment(models.Model):
    """살말 카드에 사용자가 남긴 댓글."""

    card = models.ForeignKey(
        VoteCard,
        on_delete=models.CASCADE,
        related_name="comments",
        verbose_name="살말 카드",
    )
    user = models.ForeignKey(
        AppUser,
        on_delete=models.CASCADE,
        related_name="vote_comments",
        verbose_name="작성자",
    )
    seed_key = models.CharField(
        max_length=190,
        null=True,
        blank=True,
        unique=True,
        verbose_name="시드 식별자",
    )
    choice = models.CharField(
        max_length=10,
        choices=[("BUY", "살"), ("PASS", "말"), ("NEUTRAL", "중립")],
        null=True,
        blank=True,
        verbose_name="댓글 의견",
    )
    content = models.TextField(verbose_name="댓글 내용")
    source_metadata = models.JSONField(default=dict, blank=True, verbose_name="출처 메타데이터")
    is_deleted = models.BooleanField(default=False, db_index=True, verbose_name="삭제 여부")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="작성일시")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="수정일시")

    class Meta:
        db_table = '"app"."vote_comment"'
        verbose_name = "살말 댓글"
        verbose_name_plural = "살말 댓글"
        indexes = [
            models.Index(fields=["card", "-created_at"], name="idx_vote_comment_card"),
            models.Index(fields=["user", "-created_at"], name="idx_vote_comment_user"),
        ]

    def __str__(self):
        return f"{self.card} / {self.user}"


class VoteReport(models.Model):
    """살말 카드 또는 댓글에 접수된 사용자 신고 기록."""

    class TargetType(models.TextChoices):
        CARD = "CARD", "카드"
        COMMENT = "COMMENT", "댓글"

    class Status(models.TextChoices):
        PENDING = "PENDING", "검토 대기"
        REVIEWED = "REVIEWED", "검토 완료"
        DISMISSED = "DISMISSED", "기각"

    reporter = models.ForeignKey(
        AppUser,
        on_delete=models.SET_NULL,
        null=True,
        related_name="vote_reports",
        verbose_name="신고자",
    )
    target_type = models.CharField(max_length=10, choices=TargetType.choices, verbose_name="신고 대상")
    target_id = models.PositiveBigIntegerField(verbose_name="신고 대상 ID")
    card = models.ForeignKey(
        VoteCard,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports",
        verbose_name="대상 카드",
    )
    comment = models.ForeignKey(
        VoteComment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports",
        verbose_name="대상 댓글",
    )
    reason = models.CharField(max_length=500, blank=True, default="", verbose_name="신고 사유")
    target_snapshot = models.JSONField(default=dict, blank=True, verbose_name="대상 스냅샷")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name="처리 상태",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="신고일시")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="수정일시")

    class Meta:
        db_table = '"app"."vote_report"'
        verbose_name = "살말 신고"
        verbose_name_plural = "살말 신고"
        indexes = [
            models.Index(fields=["target_type", "target_id"], name="idx_vote_report_target"),
            models.Index(fields=["status", "-created_at"], name="idx_vote_report_status"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["reporter", "target_type", "target_id"],
                name="uq_vote_report_target",
            ),
        ]

    def __str__(self):
        return f"{self.get_target_type_display()} #{self.target_id} / {self.get_status_display()}"


class VoteFeedback(models.Model):
    """살!말? 사후 피드백 — 투표가 마감된 뒤 글쓴이가 남기는 결과 (2026-09-19).

    글쓴이만, 카드당 하나. 투표자들의 '적중'(내 판단이 맞았나)은 이 값으로 계산한다
    (apps/api/badges.py — 연속 적중 · 여론 조력자 · 성실 피드백러).
    """

    class Purchase(models.TextChoices):
        BOUGHT = "BOUGHT", "샀어요"
        SKIPPED = "SKIPPED", "안 샀어요"
        UNDECIDED = "UNDECIDED", "아직 고민 중"

    card = models.OneToOneField(
        VoteCard,
        on_delete=models.CASCADE,
        related_name="feedback",
        verbose_name="카드",
    )
    user = models.ForeignKey(
        AppUser,
        on_delete=models.CASCADE,
        related_name="vote_feedbacks",
        verbose_name="작성자",
    )
    purchase = models.CharField(max_length=20, choices=Purchase.choices, verbose_name="구매 여부")
    satisfaction = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name="만족도(1~5)",
        help_text="샀으면 '사길 잘했나', 안 샀으면 '안 사길 잘했나'. 고민 중이면 비워 둔다.",
    )
    helpful = models.BooleanField(null=True, blank=True, verbose_name="투표가 도움이 됐나")
    comment = models.CharField(max_length=300, blank=True, default="", verbose_name="한 줄 후기")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="작성일시")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="수정일시")

    class Meta:
        db_table = '"app"."vote_feedback"'
        verbose_name = "살말 피드백"
        verbose_name_plural = "살말 피드백"
        indexes = [
            models.Index(fields=["user", "-created_at"], name="idx_vote_feedback_user"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(satisfaction__isnull=True)
                | models.Q(satisfaction__gte=1, satisfaction__lte=5),
                name="ck_vote_feedback_satisfaction",
            ),
        ]

    def __str__(self):
        return f"#{self.card_id} {self.get_purchase_display()} · {self.satisfaction or '-'}"


class ChatSession(models.Model):
    """
    사용자와 AI 챗봇의 대화 세션.
    """

    user = models.ForeignKey(
        AppUser,
        on_delete=models.CASCADE,
        related_name="chat_sessions",
        verbose_name="사용자",
    )

    title = models.CharField(
        max_length=300,
        null=True,
        blank=True,
        verbose_name="대화 제목",
    )

    context = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="세션 컨텍스트",
    )

    started_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="시작일시",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="최근 대화일시",
    )

    class Meta:
        db_table = '"app"."chat_session"'
        verbose_name = "챗봇 세션"
        verbose_name_plural = "챗봇 세션"

        indexes = [
            models.Index(
                fields=["user", "-updated_at"],
                name="idx_chat_session_user",
            ),
        ]

    def __str__(self):
        return self.title or f"대화 {self.id}"


class ChatMessage(models.Model):
    """
    챗봇 세션 안의 개별 메시지.
    """

    class Role(models.TextChoices):
        USER = "USER", "사용자"
        ASSISTANT = "ASSISTANT", "AI"
        SYSTEM = "SYSTEM", "시스템"

    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name="대화",
    )

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        verbose_name="메시지 역할",
    )

    content = models.TextField(
        verbose_name="내용",
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="추가 정보",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="생성일시",
    )

    class Meta:
        db_table = '"app"."chat_message"'
        verbose_name = "챗봇 메시지"
        verbose_name_plural = "챗봇 메시지"

        indexes = [
            models.Index(
                fields=["session", "created_at"],
                name="idx_chat_msg_session",
            ),
        ]

    def __str__(self):
        return f"{self.get_role_display()} / {self.created_at}"


class Notification(models.Model):
    """사용자에게 보낼 알림 한 건.

    만드는 규칙은 apps/api/notifications.py(순수 계산),
    실제 생성은 apps/api/notification_service.py 가 맡는다.

    ★ dedup_key 가 이 모델의 핵심이다.
      '하루 한 번 묶어서', '10표 도달했을 때 한 번', '주 1회' 는 전부
      같은 키로 두 번 만들지 않는 것으로 지킨다. 배치가 여러 번 돌아도
      결과가 같아야 한다.
    """

    class Kind(models.TextChoices):
        PRICE_DROP = "PRICE_DROP", "찜한 상품 가격 하락"
        VOTE_RESULT = "VOTE_RESULT", "살!말? 투표 결과"
        WEEKLY_REPORT = "WEEKLY_REPORT", "주간 트렌드 리포트"
        BADGE = "BADGE", "뱃지 달성"
        TERM_ADDED = "TERM_ADDED", "용어 사전 등재"
        JOB_REVIEW = "JOB_REVIEW", "직업 인증 결과"
        VOTE_COMMENT = "VOTE_COMMENT", "살!말? 새 댓글"

    user = models.ForeignKey(
        AppUser,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="사용자",
    )

    kind = models.CharField(
        max_length=30,
        choices=Kind.choices,
        verbose_name="알림 종류",
    )

    title = models.CharField(
        max_length=200,
        verbose_name="제목",
    )

    body = models.CharField(
        max_length=500,
        blank=True,
        default="",
        verbose_name="본문",
    )

    # 눌렀을 때 갈 화면. 프런트의 화면 이름 그대로다 (goView 가 받는 값 —
    # "mypage" · "salmal" · "trend"). 있지도 않은 깊은 주소를 적지 않는다.
    link = models.CharField(
        max_length=200,
        blank=True,
        default="",
        verbose_name="이동 화면",
    )

    payload = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="알림 근거",
    )

    dedup_key = models.CharField(
        max_length=200,
        verbose_name="중복 방지 키",
    )

    read_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="읽은 시각",
    )

    # 사용자가 지운 알림. 행은 남긴다 — dedup_key 가 사라지면
    # 배치나 다음 투표가 같은 알림을 다시 만들어 버린다.
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="지운 시각",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="생성일시",
    )

    class Meta:
        db_table = '"app"."notification"'
        verbose_name = "알림"
        verbose_name_plural = "알림"

        constraints = [
            models.UniqueConstraint(
                fields=["user", "dedup_key"],
                name="uq_notification_user_key",
            ),
        ]

        indexes = [
            models.Index(
                fields=["user", "-created_at"],
                name="idx_noti_user_time",
            ),
            models.Index(
                fields=["user", "read_at"],
                name="idx_noti_user_read",
            ),
        ]

    def __str__(self):
        return f"{self.user} / {self.get_kind_display()}"


class NotificationSetting(models.Model):
    """알림 끄기 단위 — 전체 하나 + 종류마다 하나.

    행이 없으면 전부 켜진 것으로 본다(가입한 적 없는 사용자도 알림을 받는다).
    종류를 늘릴 때 칸을 추가한다. JSON 한 칸에 몰아넣지 않은 이유는
    '어떤 종류가 있는지'가 스키마에 드러나야 다음 사람이 읽을 수 있어서다.
    """

    user = models.OneToOneField(
        AppUser,
        on_delete=models.CASCADE,
        related_name="notification_setting",
        verbose_name="사용자",
    )

    enabled = models.BooleanField(
        default=True,
        verbose_name="전체 알림",
    )

    price_drop = models.BooleanField(
        default=True,
        verbose_name="찜한 상품 가격 하락",
    )

    vote_result = models.BooleanField(
        default=True,
        verbose_name="살!말? 투표 결과",
    )

    weekly_report = models.BooleanField(
        default=True,
        verbose_name="주간 트렌드 리포트",
    )

    badge = models.BooleanField(
        default=True,
        verbose_name="뱃지 달성",
    )

    term_added = models.BooleanField(
        default=True,
        verbose_name="용어 사전 등재",
    )

    job_review = models.BooleanField(
        default=True,
        verbose_name="직업 인증 결과",
    )

    vote_comment = models.BooleanField(
        default=True,
        verbose_name="살!말? 새 댓글",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = '"app"."notification_setting"'
        verbose_name = "알림 설정"
        verbose_name_plural = "알림 설정"

    def __str__(self):
        return f"{self.user} / 알림 설정"


class TermRequest(models.Model):
    """사용자가 '사전에 올려 달라'고 요청한 용어.

    dictionary.term_candidate 는 문서에서 자동으로 찾아낸 후보라 요청자가 없다.
    누가 무엇을 요청했는지는 여기에만 남는다 — 등재 알림(7번)의 근거다.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "검토 대기"
        ADDED = "ADDED", "등재됨"
        REJECTED = "REJECTED", "반려"

    user = models.ForeignKey(
        AppUser,
        on_delete=models.CASCADE,
        related_name="term_requests",
        verbose_name="요청자",
    )

    raw_term = models.CharField(
        max_length=100,
        verbose_name="요청 용어",
    )

    # 띄어쓰기·대소문자를 누른 비교용 이름. 등재 여부를 이 값으로 맞춘다.
    normalized_term = models.CharField(
        max_length=100,
        verbose_name="정규화 이름",
    )

    note = models.CharField(
        max_length=200,
        blank=True,
        default="",
        verbose_name="요청 메모",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name="처리 상태",
    )

    term = models.ForeignKey(
        "core.DictionaryTerm",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requests",
        verbose_name="등재된 용어",
    )

    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="처리 시각",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = '"app"."term_request"'
        verbose_name = "용어 등재 요청"
        verbose_name_plural = "용어 등재 요청"

        constraints = [
            models.UniqueConstraint(
                fields=["user", "normalized_term"],
                name="uq_term_request_user_term",
            ),
        ]

        indexes = [
            models.Index(
                fields=["status", "normalized_term"],
                name="idx_term_req_status",
            ),
        ]

    def __str__(self):
        return f"{self.user} / {self.raw_term}"
