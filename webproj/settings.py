"""livedata web arayüzü — Django ayarları.

Bilinçli olarak MİNİMAL tutulmuştur: veritabanı, oturum çerçevesi (Django
session), kimlik doğrulama ve admin uygulaması YOKTUR. Bu proje bir CRUD
uygulaması değildir; tek işi büyük bir kaynak dosyayı `livedata` çekirdeği
üzerinden tarayıcıda göstermektir. Devre dışı bırakılan her Django alt
sistemi, "diske hiçbir şey yazılmaz" ilkesini de güçlendirir: burada asla
bir `db.sqlite3` oluşmaz.

Kullanım senaryosu: yerel makine / yerel ağ, TEK kullanıcı ya da birkaç
güvenilir yerel kullanıcı (bkz. LIVEDATA_WEB.md). Bu yüzden:
  - ALLOWED_HOSTS geniş tutulur (LAN IP'sinden erişim için).
  - CSRF ara katmanı YOKTUR; API görünümleri düz JSON döndürür/kabul eder.
    Bu, internete açık, çok kullanıcılı bir dağıtım için YETERSİZDİR --
    böyle bir senaryo için önce kimlik doğrulama eklenmelidir.
"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "livedata-web-yerel-arac-gizli-anahtar-degildir"
DEBUG = True

# Yerel ağdan (ör. 192.168.x.x) erişime izin ver. İnternete açık bir
# dağıtımda bu değer daraltılmalı ve kimlik doğrulama eklenmelidir.
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "gorunum",
]

# CsrfViewMiddleware BİLİNÇLİ OLARAK yok: API görünümleri form değil, düz
# JSON gövdesi kabul eder ve Django'nun csrf çerezi/token akışını
# kullanmaz. SessionMiddleware/AuthenticationMiddleware de yok -- hiçbir
# görünüm oturum ya da kullanıcı doğrulaması kullanmıyor.
MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "webproj.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    },
]

WSGI_APPLICATION = "webproj.wsgi.application"

# Veritabanı YOK: hiçbir model, hiçbir migrasyon, hiçbir db.sqlite3.
DATABASES = {}

LANGUAGE_CODE = "tr"
TIME_ZONE = "Europe/Istanbul"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Büyük seçim dışa aktarımlarında (Excel/Word/PDF) istek gövdesi küçüktür
# (yalnızca ayarlar), bu yüzden varsayılan sınırlar yeterlidir.
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10 MB (JSON gövdeler için)
