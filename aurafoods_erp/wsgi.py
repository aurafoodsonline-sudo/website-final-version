import os

from django.conf import settings
from django.core.wsgi import get_wsgi_application
from whitenoise import WhiteNoise


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "aurafoods_erp.settings")

application = get_wsgi_application()
application = WhiteNoise(
    application,
    root=str(settings.STATIC_ROOT),
    prefix=str(settings.STATIC_URL),
    autorefresh=settings.DEBUG,
)
application.add_files(str(settings.MEDIA_ROOT), prefix=str(settings.MEDIA_URL))
