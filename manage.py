#!/usr/bin/env python
"""livedata web arayüzü için Django yönetim betiği.

Çalıştırma:
    python manage.py runserver 0.0.0.0:8000 --noreload

`--noreload` ÖNEMLİDİR: oturum kaydı (`gorunum/kayit.py`) process-içi bir
sözlükte tutulur; Django'nun otomatik yeniden yükleyicisi ikinci bir alt
process açar ve bu iki process arasında oturumlar paylaşılamaz. Aynı sebeple
bu uygulama TEK worker/process ile çalıştırılmalıdır (bkz. LIVEDATA_WEB.md).
"""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "webproj.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Django içe aktarılamadı. Kurulu olduğundan ve etkin olduğundan "
            "emin olun (pip install django)."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
