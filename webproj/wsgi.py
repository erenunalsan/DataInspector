"""WSGI giriş noktası. `waitress-serve --threads=8 webproj.wsgi:application`
gibi tam bir WSGI sunucusuyla çalıştırmak için kullanılır (bkz. LIVEDATA_WEB.md
-- TEK process ile çalıştırılmalıdır, çoklu process DEĞİL)."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "webproj.settings")

application = get_wsgi_application()
