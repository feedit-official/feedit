import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.modules.setdefault("requests", Mock())

from app import vton


class VirtualFittingTests(unittest.TestCase):
    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    @patch("app.vton.requests.post")
    def test_sends_model_and_all_items_as_image_array(self, post):
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = {"data": [{"b64_json": "result"}]}

        result = vton.generate(
            model_id="woman",
            items=[
                {"image": "data:image/png;base64,eA==", "category": "상의"},
                {"image": "data:image/png;base64,eQ==", "category": "하의"},
            ],
        )

        files = post.call_args.kwargs["files"]
        # 기준 사진 7장(마스터 6 + 포즈 1) + 상품 2장
        self.assertEqual([field for field, _file in files],
                         ["image[]"] * (vton.REFERENCE_COUNT + 2))
        self.assertEqual(post.call_args.kwargs["data"]["model"],
                         "gpt-image-2.5-sunburst")
        self.assertEqual(result["image"],
                         "data:" + vton.MIME[vton.OUTPUT_FORMAT] + ";base64,result")
        self.assertEqual(result["item_count"], 2)
        self.assertEqual(result["categories"], ["상의", "하의"])

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    @patch("app.vton.requests.post")
    def test_keeps_legacy_single_item_contract(self, post):
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = {"data": [{"b64_json": "result"}]}

        result = vton.generate(
            image_data_url="data:image/png;base64,eA==",
            model_id="man",
            category="아우터",
        )

        self.assertEqual(result["categories"], ["아우터"])

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    @patch("app.vton.requests.post")
    def test_supports_socks_and_auto_classification_prompt(self, post):
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = {"data": [{"b64_json": "result"}]}

        result = vton.generate(model_id="woman", items=[
            {"image": "data:image/png;base64,eA==", "category": "양말"},
            {"image": "data:image/png;base64,eQ==", "category": "자동 분류"},
        ])

        sent = post.call_args.kwargs["data"]["prompt"]
        self.assertIn("양말", sent)
        # 모자·벨트·안경이 칸에 들어오면서 "의류" 라고 못 박지 않는다 (2026-09-14)
        self.assertIn("종류를 먼저 판별", sent)
        self.assertEqual(result["categories"], ["양말", "자동 분류"])

    # ── 2026-09-14 추가 칸 · 착장 옵션 ─────────────────────────
    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    @patch("app.vton.requests.post")
    def test_accessory_slots_carry_their_own_wear_guide(self, post):
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = {"data": [{"b64_json": "result"}]}

        result = vton.generate(model_id="woman", items=[
            {"image": "data:image/png;base64,eA==", "category": "모자"},
            {"image": "data:image/png;base64,eQ==", "category": "벨트"},
            {"image": "data:image/png;base64,eg==", "category": "안경"},
        ])

        sent = post.call_args.kwargs["data"]["prompt"]
        self.assertIn(vton.WEAR_GUIDE["모자"], sent)
        self.assertIn(vton.WEAR_GUIDE["벨트"], sent)
        self.assertIn(vton.WEAR_GUIDE["안경"], sent)
        self.assertEqual(result["categories"], ["모자", "벨트", "안경"])

    def test_options_off_keeps_the_old_prompt(self):
        """전부 꺼진 상태가 기존 동작이다 — 켜지 않은 연출이 새면 안 된다."""
        base = vton.prompt(["상의"])
        self.assertEqual(base, vton.prompt(["상의"], {}))
        self.assertEqual(base, vton.prompt(["상의"], {k: False for k in vton.OPTION_LINES}))

    def test_option_lines_are_added_and_conflicts_dropped(self):
        got = vton.prompt(["아우터"], {"outer_layered": True, "outer_open": True,
                                       "top_open": True, "top_closed": True})
        self.assertIn(vton.OPTION_LINES["outer_layered"], got)
        self.assertIn(vton.OPTION_LINES["outer_open"], got)
        # 열기·닫기를 둘 다 켜 보내면 어느 쪽도 쓰지 않는다 (모순된 지시를 막는다)
        self.assertNotIn(vton.OPTION_LINES["top_open"], got)
        self.assertNotIn(vton.OPTION_LINES["top_closed"], got)

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    @patch("app.vton.requests.post")
    def test_generate_reports_the_options_it_used(self, post):
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = {"data": [{"b64_json": "result"}]}

        result = vton.generate(
            model_id="woman",
            items=[{"image": "data:image/png;base64,eA==", "category": "아우터"}],
            options={"outer_layered": True, "top_closed": True},
        )

        self.assertEqual(result["options"], ["outer_layered", "top_closed"])


class PoseTests(unittest.TestCase):
    """포즈 풀 (2026-09-14).

    한 장짜리 모델일 땐 만들 때마다 같은 자세만 나왔다. 같은 모델의 포즈를
    여러 장 두고 뽑는다 — 여기서 보는 것은 '정말 여러 장에서 뽑는가' 와
    '이름을 집어 주면 그것이 나가는가' 둘이다.
    ★ 두 모델 다 본다. 여성만 보던 시절엔 남성 쪽 폴더가 비어도 초록이었다.
    """

    MODELS = ["woman", "man"]

    def test_every_model_has_a_pose_pool(self):
        for mid in self.MODELS:
            with self.subTest(model=mid):
                found = vton.poses(mid)
                self.assertGreater(len(found), 1, f"{mid} 포즈가 한 장뿐이다")
                for path in found:
                    self.assertTrue(path.is_file(), f"{path} 가 없다")

    def test_unknown_model_has_no_pose(self):
        self.assertEqual(vton.poses("robot"), [])
        with self.assertRaises(ValueError):
            vton.pick_pose("robot")

    def test_pick_pose_spreads_over_the_pool(self):
        for mid in self.MODELS:
            with self.subTest(model=mid):
                names = {vton.pick_pose(mid).name for _ in range(160)}
                self.assertGreater(len(names), 1, f"{mid} 은 늘 같은 포즈만 뽑힌다")

    def test_pick_pose_honours_a_named_pose(self):
        for mid in self.MODELS:
            with self.subTest(model=mid):
                first = vton.poses(mid)[0].name
                for _ in range(20):
                    self.assertEqual(vton.pick_pose(mid, first).name, first)

    def test_unknown_pose_name_falls_back_instead_of_failing(self):
        """없는 이름이 와도 실패시키지 않는다 — 파일이 갈린 옛 결과일 수 있다."""
        for mid in self.MODELS:
            with self.subTest(model=mid):
                self.assertIn(vton.pick_pose(mid, "nope.png"), vton.poses(mid))

    def test_pools_do_not_share_photos(self):
        """두 풀이 섞이면 여성 모델을 골랐는데 남성이 나온다."""
        woman = {p.name for p in vton.poses("woman")}
        man = {p.name for p in vton.poses("man")}
        self.assertEqual(woman & man, set(), "두 모델이 같은 파일을 쓴다")

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    @patch("app.vton.requests.post")
    def test_generate_reports_which_pose_it_used(self, post):
        for mid in self.MODELS:
            with self.subTest(model=mid):
                post.return_value = Mock(status_code=200)
                post.return_value.json.return_value = {"data": [{"b64_json": "result"}]}

                result = vton.generate(model_id=mid, items=[
                    {"image": "data:image/png;base64,eA==", "category": "상의"}])

                self.assertIn(result["pose"], [p.name for p in vton.poses(mid)])
                # 기준 사진 중 마지막이 그 포즈여야 한다 — 앞의 여섯은 마스터다
                names = [f[1][0] for f in post.call_args.kwargs["files"]]
                self.assertEqual(names[vton.REFERENCE_COUNT - 1], result["pose"])


class OutputSettingsTests(unittest.TestCase):
    """출력 해상도·품질·형식 (2026-09-14).

    셋 다 눈에 안 보이는 설정이라 조용히 어긋나도 아무도 모른다. 값 자체보다
    '그 값이 실제로 요청에 실리는가' 와 'API 가 받아 주는 범위인가' 를 본다.
    """

    def test_size_fits_the_api_limits(self):
        w, h = (int(v) for v in vton.SIZE.split("x"))
        self.assertEqual(w % 16, 0, "가로가 16의 배수가 아니다")
        self.assertEqual(h % 16, 0, "세로가 16의 배수가 아니다")
        self.assertLessEqual(max(w, h), 3840, "긴 변이 3840px 를 넘는다")
        self.assertLessEqual(w * h, 8_294_400, "총 픽셀이 상한을 넘는다")
        self.assertLessEqual(max(w, h) / min(w, h), 3, "가로세로비가 3:1 을 넘는다")

    def test_size_keeps_the_model_photo_shape(self):
        """모델 사진이 3:4 다. 출력이 다른 비율이면 전신이 잘리거나 여백만 는다."""
        w, h = (int(v) for v in vton.SIZE.split("x"))
        self.assertAlmostEqual(h / w, 4 / 3, delta=0.02)

    def test_quality_is_one_the_model_accepts(self):
        self.assertIn(vton.QUALITY, {"low", "medium", "high", "xhigh", "max", "auto"})

    def test_output_format_is_small_enough_for_the_proxy(self):
        """★ PNG 으로 되돌리면 배포된 화면에서 4K 가 한 장도 안 나온다 —
        Vercel 함수 응답 상한 4.5MB 에 base64 4K PNG(13MB 쯤)이 걸린다."""
        self.assertIn(vton.OUTPUT_FORMAT, {"jpeg", "webp"},
                      "압축 포맷이 아니면 프록시 응답 한도를 넘는다")
        self.assertIn(vton.OUTPUT_FORMAT, vton.MIME)
        self.assertTrue(0 <= int(vton.OUTPUT_COMPRESSION) <= 100)

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    @patch("app.vton.requests.post")
    def test_settings_actually_ride_on_the_request(self, post):
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = {"data": [{"b64_json": "result"}]}

        result = vton.generate(model_id="woman", items=[
            {"image": "data:image/png;base64,eA==", "category": "상의"}])

        sent = post.call_args.kwargs["data"]
        self.assertEqual(sent["size"], vton.SIZE)
        self.assertEqual(sent["quality"], vton.QUALITY)
        self.assertEqual(sent["output_format"], vton.OUTPUT_FORMAT)
        self.assertEqual(sent["output_compression"], vton.OUTPUT_COMPRESSION)
        # 화면도 무엇으로 받았는지 알아야 한다 — 저장 파일 확장자가 여기서 나온다
        self.assertEqual(result["size"], vton.SIZE)
        self.assertEqual(result["quality"], vton.QUALITY)
        self.assertEqual(result["format"], vton.OUTPUT_FORMAT)
        self.assertTrue(result["image"].startswith(
            "data:" + vton.MIME[vton.OUTPUT_FORMAT] + ";base64,"))


class ReferenceTests(unittest.TestCase):
    """기준 사진 (2026-09-14).

    포즈 한 장만 보내던 시절엔 그 한 장에 안 보이는 것을 모델이 지어냈다 —
    얼굴이 컷마다 딴사람이 되고 체형이 흔들렸다. 얼굴 셋·전신 셋을 같이 보낸다.
    ★ 여기서 지키는 것은 '순서' 다. prompt() 가 번호로 부르기 때문에,
      한 칸만 밀려도 모델은 신발 사진을 얼굴 기준으로 읽는다.
    """

    MODELS = ["woman", "man"]

    def test_every_model_has_the_six_masters(self):
        want = ["01_face_front.png", "02_face_right.png", "03_face_left.png",
                "04_body_front.png", "05_body_side.png", "06_body_back.png"]
        for mid in self.MODELS:
            with self.subTest(model=mid):
                self.assertEqual([p.name for p in vton.masters(mid)], want)
                for path in vton.masters(mid):
                    self.assertTrue(path.is_file())

    def test_references_are_masters_then_the_pose(self):
        for mid in self.MODELS:
            with self.subTest(model=mid):
                refs = vton.references(mid)
                self.assertEqual(len(refs), vton.REFERENCE_COUNT)
                self.assertEqual(refs[:vton.MASTER_COUNT], vton.masters(mid))
                self.assertIn(refs[-1], vton.poses(mid))

    def test_missing_masters_fail_loudly(self):
        """폴더가 비면 조용히 포즈 한 장으로 떨어지지 않고 말한다."""
        with self.assertRaises(ValueError):
            vton.references("robot")

    def test_errors_say_what_is_missing_and_where(self):
        """★ 예전에는 어느 경우든 "선택한 AI 모델을 찾을 수 없습니다." 한 줄이었다.

        사진 폴더를 옮긴 뒤 옛 코드를 물고 있던 서버가 그 문구를 뱉었는데,
        화면만 봐서는 이름이 틀린 건지 파일이 없는 건지 서버가 낡은 건지
        알 수 없었다. 셋을 구분해서 말하는지 본다.
        """
        with self.assertRaises(ValueError) as bad_id:
            vton.references("robot")
        self.assertIn("robot", str(bad_id.exception))

        folder = vton.MODELS["woman"]["dir"] / vton.POSE_DIR
        moved = folder.with_name("_poses_off")
        folder.rename(moved)
        try:
            with self.assertRaises(ValueError) as no_pose:
                vton.references("woman")
        finally:
            moved.rename(folder)
        said = str(no_pose.exception)
        self.assertIn("포즈", said)
        self.assertIn(vton.POSE_DIR, said, "어느 폴더인지 안 알려 준다")
        self.assertIn("다시 시작", said, "서버 재시작을 짚어 주지 않는다")
        # 고쳐 놓고 원래대로 돌아왔는지
        self.assertGreater(len(vton.poses("woman")), 1)

    def test_prompt_pins_the_leg_proportions(self):
        """★ 다리가 짧아 보인다는 말이 나왔던 자리 (2026-09-14).

        자세를 따라 그리다 보면 허리선과 다리 길이가 같이 눌린다. 비율만은
        체형 기준(4~6번)을 보라고 따로 적어 둔다 — 이 문장이 빠지면 다시 눌린다.
        """
        got = vton.prompt(["상의"])
        self.assertIn("다리 길이와 허리선 높이는 4~6번", got)
        self.assertIn("짧아 보이게 만들지 마세요", got)

    def test_prompt_numbers_match_the_image_order(self):
        """프롬프트의 번호와 실제로 보내는 순서가 어긋나면 안 된다."""
        got = vton.prompt(["상의", "하의"])
        self.assertIn(f"1번부터 {vton.REFERENCE_COUNT}번까지", got)
        self.assertIn("1~3번은 얼굴 기준", got)
        self.assertIn("4~6번은 체형 기준", got)
        self.assertIn(f"{vton.REFERENCE_COUNT}번은 이번 컷의 기준", got)
        # 상품은 기준 사진 바로 다음 번호부터
        self.assertIn(f"{vton.REFERENCE_COUNT + 1}번째 이미지는 상의", got)
        self.assertIn(f"{vton.REFERENCE_COUNT + 2}번째 이미지는 하의", got)

    def test_items_and_references_fit_in_one_request(self):
        """★ API 는 한 번에 16장이다. 칸을 늘리다 조용히 잘리면 사용자가 넣은
        사진이 사라진다 — 합이 상한을 넘지 않는지 여기서 붙잡는다."""
        self.assertLessEqual(vton.MAX_ITEMS + vton.REFERENCE_COUNT, vton.MAX_IMAGES)
        self.assertEqual(vton.MAX_ITEMS,
                         min(len(vton.SLOT_ORDER), vton.MAX_IMAGES - vton.REFERENCE_COUNT))

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    @patch("app.vton.requests.post")
    def test_masters_ride_ahead_of_the_items(self, post):
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = {"data": [{"b64_json": "result"}]}

        result = vton.generate(model_id="woman", items=[
            {"image": "data:image/png;base64,eA==", "category": "상의"}])

        names = [f[1][0] for f in post.call_args.kwargs["files"]]
        self.assertEqual(names[:vton.MASTER_COUNT],
                         [p.name for p in vton.masters("woman")])
        self.assertEqual(names[vton.REFERENCE_COUNT - 1], result["pose"])
        self.assertEqual(names[vton.REFERENCE_COUNT:], ["item-1.png"])
        self.assertEqual(result["references"], names[:vton.REFERENCE_COUNT])

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    @patch("app.vton.requests.post")
    def test_master_files_are_open_while_being_sent(self, post):
        """★ 보내는 그 순간에 봐야 한다.

        기준 사진은 파일 손잡이(handle)로 실린다. 한 장씩 열고 닫으면 requests 가
        읽을 때는 이미 닫혀 있어 빈 이미지가 올라간다 — 그런데 generate() 가
        끝난 뒤에 보면 정상이어도 닫혀 있다(보내고 나서 닫는 게 맞다).
        그래서 post 가 불린 그 자리에서 확인한다.
        """
        seen = {}

        def capture(*_args, **kwargs):
            for _field, (name, handle, _mime) in kwargs["files"]:
                if name.startswith("item-"):
                    continue
                seen[name] = (handle.closed, handle.read(8))
            return Mock(status_code=200,
                        json=lambda: {"data": [{"b64_json": "result"}]})

        post.side_effect = capture
        vton.generate(model_id="man", items=[
            {"image": "data:image/png;base64,eA==", "category": "상의"}])

        self.assertEqual(len(seen), vton.REFERENCE_COUNT, "기준 사진이 덜 실렸다")
        for name, (closed, head) in seen.items():
            self.assertFalse(closed, f"{name} 이 닫힌 채로 실렸다")
            self.assertTrue(head.startswith(b"\x89PNG"), f"{name} 이 비었다")


if __name__ == "__main__":
    unittest.main()
