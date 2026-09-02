from __future__ import annotations

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
if not DEBUG and (not os.environ.get("DJANGO_SECRET_KEY") or SECRET_KEY == "dev-only-change-me"):
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set to a strong non-default value when DJANGO_DEBUG=0.")

ALLOWED_HOSTS_RAW = os.environ.get("DJANGO_ALLOWED_HOSTS", "")
if not DEBUG and not ALLOWED_HOSTS_RAW:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must be set when DJANGO_DEBUG=0.")
ALLOWED_HOSTS = [h.strip() for h in ALLOWED_HOSTS_RAW.split(",") if h.strip()] if ALLOWED_HOSTS_RAW else ["*"]


CSRF_TRUSTED_ORIGINS = [
    "https://aurafoods.online",
    "https://www.aurafoods.online",
]

USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PORT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "erp",
    "frontend",
    "shop",
    "sales",
    "crm",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "erp.middleware.SecurityHeadersMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "aurafoods_erp.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "erp.middleware.csp_nonce",
            ],
        },
    },
]

WSGI_APPLICATION = "aurafoods_erp.wsgi.application"


def database_config() -> dict:
    url = os.environ.get("DATABASE_URL")
    if not url:
        if not DEBUG:
            raise ImproperlyConfigured("DATABASE_URL must be set in production.")
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": parsed.path.lstrip("/"),
            "USER": parsed.username or "",
            "PASSWORD": parsed.password or "",
            "HOST": parsed.hostname or "",
            "PORT": parsed.port or "",
        }
    if url.startswith("sqlite:"):
        if not DEBUG:
            raise ImproperlyConfigured("Production DATABASE_URL must not use SQLite.")
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}
    raise ImproperlyConfigured("Unsupported DATABASE_URL. Use postgresql:// for production.")


DATABASES = {"default": database_config()}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": str(BASE_DIR / "media"), "base_url": "/media/"},
    },
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
LOGIN_URL = "/admin/login/"

MEDIA_STORAGE_BACKEND = os.environ.get("MEDIA_STORAGE_BACKEND", "local").lower()
MEDIA_UPLOADS_ENABLED = DEBUG or MEDIA_STORAGE_BACKEND != "local"
if MEDIA_STORAGE_BACKEND in {"s3", "r2", "s3-compatible"}:
    required_media_env = ("AWS_STORAGE_BUCKET_NAME", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")
    missing_media_env = [name for name in required_media_env if not os.environ.get(name)]
    if missing_media_env and not DEBUG:
        raise ImproperlyConfigured("Production S3-compatible media storage is missing: " + ", ".join(missing_media_env))
    if not missing_media_env:
        STORAGES["default"] = {
            "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
            "OPTIONS": {
                "bucket_name": os.environ["AWS_STORAGE_BUCKET_NAME"],
                "access_key": os.environ["AWS_ACCESS_KEY_ID"],
                "secret_key": os.environ["AWS_SECRET_ACCESS_KEY"],
                "region_name": os.environ.get("AWS_S3_REGION_NAME", ""),
                "endpoint_url": os.environ.get("AWS_S3_ENDPOINT_URL") or None,
                "default_acl": "private",
                "file_overwrite": False,
            },
        }

SESSION_COOKIE_AGE = int(os.environ.get("DJANGO_SESSION_COOKIE_AGE", "1800" if not DEBUG else "1209600"))
SESSION_EXPIRE_AT_BROWSER_CLOSE = env_bool("DJANGO_SESSION_EXPIRE_AT_BROWSER_CLOSE", not DEBUG)
ADMIN_LOGIN_FAILURE_LIMIT = int(os.environ.get("ADMIN_LOGIN_FAILURE_LIMIT", "5"))
ADMIN_LOGIN_LOCKOUT_SECONDS = int(os.environ.get("ADMIN_LOGIN_LOCKOUT_SECONDS", "900"))
STAFF_MFA_REQUIRED = env_bool("STAFF_MFA_REQUIRED", not DEBUG)
MFA_SECRET_ENCRYPTION_KEY = os.environ.get("MFA_SECRET_ENCRYPTION_KEY", "")
if not DEBUG and STAFF_MFA_REQUIRED and not MFA_SECRET_ENCRYPTION_KEY:
    raise ImproperlyConfigured("MFA_SECRET_ENCRYPTION_KEY must be set when staff MFA is enabled.")
if DEBUG and not MFA_SECRET_ENCRYPTION_KEY:
    MFA_SECRET_ENCRYPTION_KEY = "s0f0H-WTod2GGbBDl220EItWk-_1YiivkcEk9503ZTg="

DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "Aura Foods <no-reply@aurafoods.pk>")
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend" if DEBUG else "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)

CORS_ALLOWED_ORIGINS = [item.strip() for item in os.environ.get("DJANGO_CORS_ORIGINS", "").split(",") if item.strip()]
CORS_ALLOW_ALL_ORIGINS = False
AURAFOODS_MAX_UPLOAD_BYTES = int(os.environ.get("AURAFOODS_MAX_UPLOAD_BYTES", str(3 * 1024 * 1024)))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

authentication_classes = ["rest_framework.authentication.SessionAuthentication"]
if env_bool("DJANGO_ENABLE_BASIC_AUTH", DEBUG):
    authentication_classes.append("rest_framework.authentication.BasicAuthentication")

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_AUTHENTICATION_CLASSES": authentication_classes,
    "EXCEPTION_HANDLER": "erp.exceptions.api_exception_handler",
}

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", False)
SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_SECURE_HSTS_SECONDS", "0" if DEBUG else "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
REFERRER_POLICY = os.environ.get("DJANGO_REFERRER_POLICY", "strict-origin-when-cross-origin")
PERMISSIONS_POLICY = os.environ.get("DJANGO_PERMISSIONS_POLICY", "geolocation=(), microphone=(), camera=()")
CONTENT_SECURITY_POLICY = os.environ.get(
    "DJANGO_CONTENT_SECURITY_POLICY",
    "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' data: https://fonts.gstatic.com; script-src 'self' 'nonce-{nonce}'; connect-src 'self'; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'",
)
CSP_REPORT_ONLY = env_bool("CSP_REPORT_ONLY", False)
DATA_UPLOAD_MAX_MEMORY_SIZE = int(os.environ.get("DJANGO_DATA_UPLOAD_MAX_MEMORY_SIZE", "2621440"))
FILE_UPLOAD_MAX_MEMORY_SIZE = int(os.environ.get("DJANGO_FILE_UPLOAD_MAX_MEMORY_SIZE", "2621440"))
ANALYTICS_ID = os.environ.get("ANALYTICS_ID", "")
