"""살!말? '나와 비슷한 사용자들'이 실제로 계산 가능한 상태인지 확인한다.

왜 필요한가
-----------
'나와 비슷한 사용자들' 비율은 **투표한 사람들의 프로필**로 계산한다
(성별 · 체형 · 출생연도 ±5년 · 취향 태그 중 둘 이상 일치).
그래서 다음 중 하나라도 비어 있으면 표본이 0명이 되고, 화면에는
비율 대신 "아직 나와 비슷한 사용자가 이 카드에 투표하지 않았습니다"가 뜬다.

  ① 테스트 사용자에게 gender / body_type / birth_year 가 없다
  ② 테스트 사용자에게 UserTaste(TERM) 가 없다
  ③ 테스트 사용자가 살!말? 카드에 투표(VoteBallot)하지 않았다

이 스크립트는 셋 중 무엇이 비어 있는지 세어서 알려 준다. 숫자를 고치지 않고
있는 그대로만 읽는다(읽기 전용).

쓰는 법 (EC2)
-------------
    docker compose --env-file .env -f docker/compose.api.yml \
      run --rm api python manage.py shell -c "$(cat tools/check_salmal_segment.py)"

  또는 로컬에서:
    cd backend && python3 manage.py shell < tools/check_salmal_segment.py
"""

from apps.core.models import AppUser, UserTaste, VoteBallot, VoteCard

users = list(AppUser.objects.all())
print(f"AppUser 총 {len(users)}명")
print(f"  성별 있음        {sum(1 for u in users if u.gender)}명")
print(f"  체형 있음        {sum(1 for u in users if u.body_type)}명")
print(f"  출생연도 있음    {sum(1 for u in users if u.birth_year)}명")

taste_users = set(
    UserTaste.objects.filter(taste_type=UserTaste.TasteType.TERM)
    .values_list("user_id", flat=True)
)
print(f"  취향(TERM) 있음  {len(taste_users)}명")

cards = VoteCard.objects.filter(seed_key__startswith="youtube:")
ballots = VoteBallot.objects.filter(card__in=cards)
voters = set(ballots.values_list("user_id", flat=True))
print(f"\n살!말? 카드 {cards.count()}장 · 투표 {ballots.count()}표 · 투표자 {len(voters)}명")

ready = [
    u for u in users
    if (u.gender or u.body_type or u.birth_year or u.id in taste_users)
    and u.id in voters
]
print(f"세그먼트 비교가 가능한 투표자: {len(ready)}명")

if not ready:
    print("\n→ 표본 0명입니다. 위 항목 중 비어 있는 것을 채워야 '나와 비슷한 사용자들'이 뜹니다.")
else:
    print("\n카드별 투표자 수 (상위 10장)")
    for card in cards.prefetch_related("ballots")[:10]:
        rows = list(card.ballots.all())
        print(f"  {card.title[:34]:<34} 투표 {len(rows):>3}표")
