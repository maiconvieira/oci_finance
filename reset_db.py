# reset_db.py
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'setup.settings')
django.setup()

from django.db import connection

print("--- EXCLUINDO TODAS AS TABELAS DO BANCO REMOTO (AIVEN) ---")

with connection.cursor() as cursor:
    # Destrói o schema public inteiro (tabelas do Django, core, finance, migrações)
    cursor.execute("DROP SCHEMA public CASCADE;")
    cursor.execute("CREATE SCHEMA public;")
    cursor.execute("GRANT ALL ON SCHEMA public TO avnadmin;")
    cursor.execute("GRANT ALL ON SCHEMA public TO public;")

print("[SUCESSO] Todas as tabelas foram eliminadas. O banco está totalmente zerado.")