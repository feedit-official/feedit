"""YouTube 댓글과 커머스 리뷰를 같은 방식으로 분석하는 텍스트 신호 파이프라인."""


def run_text_signal_pipeline(*args, **kwargs):
    from .service import run_text_signal_pipeline as implementation
    return implementation(*args, **kwargs)


def sync_product_reviews(*args, **kwargs):
    from .service import sync_product_reviews as implementation
    return implementation(*args, **kwargs)


__all__ = ["run_text_signal_pipeline", "sync_product_reviews"]
