import os
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
    "apps.dashboard.apps.DashboardConfig",
    "apps.api.apps.ApiConfig",
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # ★ gunicorn 은 정적 파일을 안 준다 — runserver 만 대신 해 주던 일이다.
    #   이게 없으면 admin CSS 가 404 로 통째로 깨진다.
    #   (2026-09-07 실측: gunicorn 단독 → /static/admin/css/base.css 404,
    #    whitenoise 를 넣으니 200 · 22,120 bytes · text/css)
    #   nginx 를 따로 세우는 대신 여기서 해결한다.
    #   ⚠ 반드시 SecurityMiddleware **바로 다음** 이어야 한다.
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
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

LLANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_I18N = True
USE_TZ = True


STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / "static"]        # 원본 (이미 있는 폴더)
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


# ══════════════════════════════════════════════════════════════
#  배포 설정 (2026-09-07)
# ══════════════════════════════════════════════════════════════

# 정적 파일 — whitenoise 가 압축·해시해서 내보낸다.
#   배포 전에 반드시 한 번:  python manage.py collectstatic --noinput
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# ★ 앞에 Caddy(또는 ALB)가 서면 Django 는 자기가 HTTP 로 불린 줄 안다.
#   그러면 request.is_secure() 가 False 라서 CSRF 검사와 리다이렉트가 엉킨다.
#   앞단이 붙여 주는 머리글을 믿으라고 알려 준다.
#
#   ⚠ 앞단이 **반드시 있을 때만** 켠다.
#     앞단 없이 켜면 누구나 이 머리글을 위조해 https 인 척할 수 있다.
if os.getenv("DJANGO_BEHIND_PROXY", "False").lower() == "true":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True

# admin 로그인 폼이 https 로 뜰 때 CSRF 를 통과시키려면 필요하다.
CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        "https://feedit-official.duckdns.org",
    ).split(",")
    if o.strip()
]
