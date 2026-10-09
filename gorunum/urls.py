from django.urls import path

from . import views

urlpatterns = [
    path("", views.ana_sayfa, name="ana_sayfa"),
    path("api/gozat", views.gozat, name="gozat"),
    path("api/son-dosyalar", views.son_dosyalar_liste, name="son_dosyalar_liste"),
    path("api/son-dosyalar/temizle", views.son_dosyalar_temizle, name="son_dosyalar_temizle"),
    path("api/ac", views.ac, name="ac"),

    path("api/oturum/<str:oid>/kapat", views.kapat, name="kapat"),
    path("api/oturum/<str:oid>/satirlar", views.satirlar, name="satirlar"),
    path("api/oturum/<str:oid>/durum", views.durum, name="durum"),
    path("api/oturum/<str:oid>/satira-git", views.satira_git, name="satira_git"),
    path("api/oturum/<str:oid>/indeksle", views.indeksle, name="indeksle"),

    path("api/oturum/<str:oid>/ara", views.ara, name="ara"),
    path("api/oturum/<str:oid>/arama-durdur", views.arama_durdur, name="arama_durdur"),

    path("api/oturum/<str:oid>/sirala", views.sirala, name="sirala"),
    path("api/oturum/<str:oid>/sirala-durdur", views.sirala_durdur, name="sirala_durdur"),
    path("api/oturum/<str:oid>/sirala-sifirla", views.sirala_sifirla, name="sirala_sifirla"),

    path("api/oturum/<str:oid>/secim", views.secim_liste, name="secim_liste"),
    path("api/oturum/<str:oid>/secim/satirlar", views.secim_satirlar, name="secim_satirlar"),
    path("api/oturum/<str:oid>/secim/degistir", views.secim_degistir, name="secim_degistir"),
    path("api/oturum/<str:oid>/secim/sayfa-sec", views.secim_sayfa_sec, name="secim_sayfa_sec"),
    path("api/oturum/<str:oid>/secim/temizle", views.secim_temizle, name="secim_temizle"),
    path("api/oturum/<str:oid>/secim/disa-aktar/<str:bicim>",
        views.disa_aktar_baslat, name="disa_aktar_baslat"),

    path("api/disa-aktar/<str:token>/ilerleme", views.disa_aktar_ilerleme,
        name="disa_aktar_ilerleme"),
    path("api/disa-aktar/<str:token>/indir", views.disa_aktar_indir,
        name="disa_aktar_indir"),

    path("api/oturum/<str:oid>/base64", views.base64_coz, name="base64_coz"),
]
