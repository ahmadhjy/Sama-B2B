import base64
import hashlib
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = Path(os.environ.get('HELLOSAMA_ENV_FILE', BASE_DIR / '.env'))
if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

def env(key, default=''):
    return os.environ.get(key, default)

def flag(key, default=False):
    return env(key, str(default)).lower() in ('true', '1', 'yes')

DEBUG = flag('DJANGO_DEBUG', True)
SECRET_KEY = env('DJANGO_SECRET_KEY', 'local-development-only-hellosama')
ALLOWED_HOSTS = env('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver').split(',')
PUBLIC_URL = env('PUBLIC_URL', 'http://127.0.0.1:8000').rstrip('/')
CSRF_TRUSTED_ORIGINS = [PUBLIC_URL]
INSTALLED_APPS = ['django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions',
                  'django.contrib.messages', 'django.contrib.staticfiles', 'portal.apps.PortalConfig']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware',
              'django.middleware.common.CommonMiddleware', 'django.middleware.csrf.CsrfViewMiddleware',
              'django.contrib.auth.middleware.AuthenticationMiddleware', 'django.contrib.messages.middleware.MessageMiddleware',
              'django.middleware.clickjacking.XFrameOptionsMiddleware', 'portal.middleware.AccessMiddleware']
ROOT_URLCONF = 'hellosama.urls'
WSGI_APPLICATION = 'hellosama.wsgi.application'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [BASE_DIR / 'templates'],
              'APP_DIRS': True, 'OPTIONS': {'context_processors': ['django.template.context_processors.request',
              'django.contrib.auth.context_processors.auth', 'django.contrib.messages.context_processors.messages',
              'portal.context.portal_context']}}]
AUTH_USER_MODEL = 'portal.User'
AUTHENTICATION_BACKENDS = ['portal.auth.CompanyBackend', 'portal.auth.LocalBackend']
AUTH_PASSWORD_VALIDATORS = [{'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 10}},
                           {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
                           {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
                           {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'}]
if env('DB_NAME'):
    DATABASES = {'default': {'ENGINE': 'django.db.backends.postgresql', 'NAME': env('DB_NAME'),
        'USER': env('DB_USER'), 'PASSWORD': env('DB_PASSWORD'), 'HOST': env('DB_HOST'), 'PORT': env('DB_PORT', '5432'),
        'CONN_MAX_AGE': 60, 'OPTIONS': {'sslmode': env('DB_SSLMODE', 'prefer')}}}
else:
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3', 'OPTIONS': {'timeout': 20}}}
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Beirut'
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
SESSION_COOKIE_NAME = 'hellosama_session'
CSRF_COOKIE_NAME = 'hellosama_csrf'
SESSION_COOKIE_AGE = 43200
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_ROOT = Path(env('PRIVATE_UPLOAD_DIR', str(BASE_DIR / 'private_uploads')))
FILE_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
DATA_ENCRYPTION_KEY = env('DATA_ENCRYPTION_KEY', base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode()).digest()).decode())
ACCOUNTING_BASE_URL = env('ACCOUNTING_BASE_URL').rstrip('/')
ACCOUNTING_SHARED_SECRET = env('ACCOUNTING_SHARED_SECRET')
ACCOUNTING_ENABLED = bool(ACCOUNTING_BASE_URL and ACCOUNTING_SHARED_SECRET)
ACCOUNTING_STATUS_TTL = 60
OPENAI_API_KEY = env('OPENAI_API_KEY')
OPENAI_MODEL = env('OPENAI_MODEL', 'gpt-6-luna')
AI_MONTHLY_LIMIT_USD = min(float(env('AI_MONTHLY_LIMIT_USD', '20')), 20)
AI_ENABLED = flag('AI_ENABLED', False)
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = env('EMAIL_HOST', 'smtp.ionos.com')
EMAIL_PORT = int(env('EMAIL_PORT', '587'))
EMAIL_USE_TLS = True
EMAIL_TIMEOUT = 25
EMAIL_HOST_USER = env('EMAIL_HOST_USER', 'info@hellosama.com')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = f'HelloSama <{EMAIL_HOST_USER}>'
BUSINESS_EMAIL = env('BUSINESS_EMAIL', 'info@hellosama.com')
EMAIL_ENABLED = flag('EMAIL_ENABLED', False)
IMAP_ENABLED = flag('IMAP_ENABLED', False)
IMAP_HOST = env('IMAP_HOST', 'imap.ionos.com')
IMAP_PORT = 993
VAPID_PRIVATE_KEY = env('VAPID_PRIVATE_KEY')
VAPID_PUBLIC_KEY = env('VAPID_PUBLIC_KEY')
VAPID_SUBJECT = 'mailto:' + BUSINESS_EMAIL
SMS_ENABLED = flag('SMS_ENABLED', False)
SMS_BASE_URL = env('SMS_BASE_URL', 'http://smppa3.broadnet.me:8080/websmpp').rstrip('/')
SMS_USERNAME = env('SMS_USERNAME')
SMS_PASSWORD = env('SMS_PASSWORD')
SMS_SENDER_ID = env('SMS_SENDER_ID')
SMS_ALLOW_HTTP = flag('SMS_ALLOW_HTTP', False)
# Initial staging deployments may only notify explicitly listed test recipients.
NOTIFICATION_TEST_MODE = flag('NOTIFICATION_TEST_MODE', True)
NOTIFICATION_TEST_EMAILS = [v.strip().lower() for v in env('NOTIFICATION_TEST_EMAILS', 'info@hellosama.com').split(',') if v.strip()]
NOTIFICATION_TEST_PHONES = [v.strip() for v in env('NOTIFICATION_TEST_PHONES').split(',') if v.strip()]
ALLOW_SELF_APPROVAL = flag('ALLOW_SELF_APPROVAL', True)
if not DEBUG:
    if SECRET_KEY == 'local-development-only-hellosama' or len(SECRET_KEY) < 40:
        raise ValueError('Set a unique DJANGO_SECRET_KEY with at least 40 characters.')
    if not env('DATA_ENCRYPTION_KEY'):
        raise ValueError('Set DATA_ENCRYPTION_KEY and back it up separately.')
    if not env('DB_NAME'):
        raise ValueError('Production requires a separate PostgreSQL database (DB_NAME).')
    if not PUBLIC_URL.startswith('https://'):
        raise ValueError('Production PUBLIC_URL must use HTTPS.')
    if ACCOUNTING_ENABLED and not ACCOUNTING_BASE_URL.startswith('https://'):
        raise ValueError('The production accounting connection must use HTTPS.')
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
# HSTS applies to this app only. Do not impose it on IONOS/other domain services
# or enroll the entire domain in a browser preload list without the domain owner's decision.
SILENCED_SYSTEM_CHECKS = ['security.W005', 'security.W021']
LOGGING = {'version': 1, 'disable_existing_loggers': False,
           'handlers': {'console': {'class': 'logging.StreamHandler'}},
           'root': {'handlers': ['console'], 'level': 'INFO'}}
