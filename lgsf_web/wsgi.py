"""
WSGI config for lgsf_web project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os
from pathlib import Path
from sys import path

import dotenv
from django.core.exceptions import ImproperlyConfigured
from django.core.wsgi import get_wsgi_application

SITE_ROOT = Path(__file__).resolve().parent.parent
path.append(str(SITE_ROOT))

dotenv.load_dotenv(SITE_ROOT / ".env")

if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    raise ImproperlyConfigured("You must explicitly set DJANGO_SETTINGS_MODULE")

application = get_wsgi_application()
