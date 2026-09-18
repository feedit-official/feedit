"""서버 시작 경로 회귀 테스트 (2026-09-18).

engine() 이 llm.DISABLED 를 쓰는데 server.py 맨 위에서 llm 을 import 하지 않아,
배포 컨테이너가 NameError 로 재시작을 반복했다(nginx 502 → 사이트는 데모 답).
import 만 확인하던 검사로는 안 잡혔다 — engine() 을 실제로 부르는 줄까지 본다.
"""
import server


def test_engine_uses_names_defined_at_module_level():
    # engine() 안에서 쓰는 전역 이름이 모두 모듈에 있어야 한다
    names = server.engine.__code__.co_names
    missing = [n for n in names if n not in vars(server) and n not in dir(__builtins__)
               and n not in ("DISABLED",)]
    assert missing == [], missing
    assert hasattr(server.llm, "DISABLED")
