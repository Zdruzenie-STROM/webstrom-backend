# pylint: disable=wildcard-import,unused-wildcard-import

from .settings import *

DEBUG = False

ALLOWED_HOSTS = [
    "test.strom.sk",
]

USE_X_FORWARDED_HOST = True

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'webstrom-test',
        'USER': 'webstrom',
    }
}

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

EMAIL_HOST = "smtp-relay.gmail.com"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_TIMEOUT = 10

SERVER_EMAIL = DEFAULT_FROM_EMAIL

ADMINS = [
    ("Martin Mihálik", "mihalik@strom.sk"),
    ("Peter Kovács", "kovacs@strom.sk"),
]
