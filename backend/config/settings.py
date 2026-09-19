import os

from celery.schedules import crontab
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BASE_DIR.parent

load_dotenv(ROOT_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-secret-key")

DEBUG = os.getenv("DJANGO_DEBUG", "False").lower() == "true"

ALLOWED_HOSTS = [
    "127.0.0.1",
    "localhost",
    "15.164.151.62",
    "feedit-official.duckdns.org",
]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    "apps.core",
    "django.contrib.humanize",
    "apps.dashboard.apps.AdminDashboardConfig",
    "apps.api.apps.ApiConfig",
    "rest_framework",
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # 정적 파일(관리자 화면 CSS)을 gunicorn 에서도 내보내기 위함 — SecurityMiddleware 바로 다음이어야 함
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # /api/ 공유 토큰 검사 (FEEDIT_API_TOKEN 이 비어 있으면 검사하지 않음)
    'apps.api.middleware.ApiTokenMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME"),
        "USER": os.getenv("DB_USER"),
        "PASSWORD": os.getenv("DB_PASSWORD"),
        "HOST": os.getenv("DB_HOST"),
        "PORT": os.getenv("DB_PORT", "5432"),
        "OPTIONS": {
            "options": '-c search_path=dictionary,"$user",public',
        },
    }
}


AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_I18N = True
USE_TZ = True


STATIC_URL = 'static/'
# 원본 정적 폴더가 있을 때만 등록 (없으면 staticfiles.W004 경고가 뜸)
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
STATIC_ROOT = BASE_DIR / "staticfiles"    

MAILERS = {
    'default': {
        'BACKEND': 'django.core.mail.backends.console.EmailBackend',
    },
}

CELERY_BROKER_URL = os.getenv(
    "CELERY_BROKER_URL",
    "redis://127.0.0.1:6379/0",
)

CELERY_RESULT_BACKEND = os.getenv(
    "CELERY_RESULT_BACKEND",
    "redis://127.0.0.1:6379/1",
)

CELERY_BEAT_SCHEDULE = {
    "dispatch-due-crawl-targets": {
        "task": "core.dispatch_due_targets",

        # 60초마다 CrawlTarget 확인
        "schedule": 60.0,
    },
    # ── 알림 (apps/api/tasks.py) ──
    #   시간대는 app.conf.timezone = Asia/Seoul 이다.
    #   매일 10:00 — 찜한 상품 가격 하락(하루 한 번 묶어서) · 용어 사전 등재
    "notify-daily": {
        "task": "app.notify_daily",
        "schedule": crontab(hour=10, minute=0),
    },
    #   월요일 09:00 — 주간 트렌드 리포트 (주 1회)
    "notify-weekly": {
        "task": "app.notify_weekly",
        "schedule": crontab(hour=9, minute=0, day_of_week=1),
    },
}

AWS_STORAGE_BUCKET_NAME = os.getenv(
    "AWS_STORAGE_BUCKET_NAME"
)

AWS_REGION = os.getenv(
    "AWS_REGION",
    "ap-northeast-2",
)

YOUTUBE_API_KEY = os.getenv(
    "YOUTUBE_API_KEY"
)

# KURE candidates remain review-only unless both values are configured from a
# calibrated benchmark.  Environment variables keep deployment tuning out of
# the pipeline code.
KURE_HIGH_CONFIDENCE_THRESHOLD = (
    float(os.getenv("KURE_HIGH_CONFIDENCE_THRESHOLD"))
    if os.getenv("KURE_HIGH_CONFIDENCE_THRESHOLD")
    else None
)
KURE_HIGH_CONFIDENCE_MARGIN_THRESHOLD = (
    float(os.getenv("KURE_HIGH_CONFIDENCE_MARGIN_THRESHOLD"))
    if os.getenv("KURE_HIGH_CONFIDENCE_MARGIN_THRESHOLD")
    else None
)


# ══════════════════════════════════════════════════════════════
#  배포 설정 (feedit 프론트 연동용)
# ══════════════════════════════════════════════════════════════

# 정적 파일 — whitenoise 가 압축·해시해서 내보낸다.
#   배포 전에 한 번: python manage.py collectstatic --noinput
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# 앞단 프록시(Caddy/nginx)가 있을 때만 켠다.
if os.getenv("DJANGO_BEHIND_PROXY", "False").lower() == "true":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True

_LOCAL_FRONTEND_PORTS = (4173, 4174, *range(5173, 5184))
CSRF_TRUSTED_ORIGINS = list(dict.fromkeys([
    *(
        f"http://{host}:{port}"
        for host in ("localhost", "127.0.0.1")
        for port in _LOCAL_FRONTEND_PORTS
    ),
    *[
        o.strip()
        for o in os.getenv(
            "DJANGO_CSRF_TRUSTED_ORIGINS",
            "https://feedit-official.duckdns.org",
        ).split(",")
        if o.strip()
    ],
]))
