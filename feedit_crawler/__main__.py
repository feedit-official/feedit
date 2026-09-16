"""python -m feedit_crawler 로 관리자 화면을 띄운다."""
import argparse
import os

from .server import main

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="FEEDiT 관리자")
    # 컨테이너·클라우드는 보통 PORT 환경변수로 알려 준다.
    ap.add_argument("--port", type=int,
                    default=int(os.environ.get("PORT") or 8765))
    ap.add_argument("--no-browser", action="store_true",
                    help="브라우저를 자동으로 열지 않음 (서버에서는 이걸 씁니다)")
    a = ap.parse_args()
    # 안내 문구는 server.main() 이 찍는다 — 어디에 열렸는지(127.0.0.1 인지
    # 바깥인지)를 거기서만 알 수 있어서, 두 군데서 찍으면 서로 어긋난다.
    main(port=a.port, open_browser=not a.no_browser)
