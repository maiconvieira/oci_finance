# test_hierarchy.py
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'setup.settings')
django.setup()

from django.db import connection
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from core.models import (
    Department,
    Person,
    PersonDepartment,
    GROUP_ADMIN,
    GROUP_SECRETARIO,
    GROUP_FINANCEIRO,
    GROUP_MILITANTE,
    GROUP_CONTRIBUINTE,
    GROUP_CONTATO,
)

User = get_user_model()

print("--- 1. LIMPANDO BASE DE DADOS COMPLETA ---")
tables = [
    'finance_objectivesettlement',
    'finance_financialobjective',
    'finance_objectivecategory_target_departments',
    'finance_objectivecategory',
    'core_persondepartment',
    'core_person_groups',
    'core_person',
    'core_user_groups',
    'core_user_user_permissions',
    'auth_group_permissions',
    'auth_group',
    'core_user',
    'core_department',
]

with connection.cursor() as cursor:
    cursor.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
          AND table_name = ANY(%s);
    """, [tables])
    existing_tables = [row[0] for row in cursor.fetchall()]

    if existing_tables:
        cursor.execute(f"TRUNCATE TABLE {', '.join(existing_tables)} RESTART IDENTITY CASCADE;")
        print(f"[OK] {len(existing_tables)} tabelas truncadas e IDs reiniciados para 1.")
    else:
        print("[AVISO] Nenhuma das tabelas alvo existia no banco para truncar.")

print("\n--- 2. CRIANDO AS INSTÂNCIAS (d1 a d5 CORRIGIDAS) ---")
d1 = Department.objects.create(name="Administração Geral", code="ADMIN")
d2 = Department.objects.create(name="Comitê Central", code="CC", parent=d1)

# Nível d3 (Subordinados ao Comitê Central - d2)
d3_sc = Department.objects.create(name="Santa Catarina", code="CR-SC", parent=d2)
d3_sp = Department.objects.create(name="São Paulo", code="CR-SP", parent=d2)
d3_rj = Department.objects.create(name="Rio de Janeiro", code="CR-RJ", parent=d2)
d3_pr = Department.objects.create(name="Paraná", code="CR-PR", parent=d2)
d3_rs = Department.objects.create(name="Rio Grande do Sul", code="CR-RS", parent=d2)

# Nível d4 (Setores subordinados ao CR de Santa Catarina - d3_sc)
d4_sind = Department.objects.create(name="Sindical", code="SETOR-Sind", parent=d3_sc)
d4_juv = Department.objects.create(name="Juventude", code="SETOR-Juv", parent=d3_sc)

# Nível d5 (Células Sinsej 1 e Sinsej 2 subordinadas ao Setor Sindical - d4_sind)
d5_sinsej1 = Department.objects.create(name="Sinsej 1", code="CEL-SINSEJ1", parent=d4_sind)
d5_sinsej2 = Department.objects.create(name="Sinsej 2", code="CEL-SINSEJ2", parent=d4_sind)

print(f"[OK] {Department.objects.count()} Instâncias criadas com sucesso.")

print("\n--- 3. CONFIGURANDO OS 6 GRUPOS / PERFIS (00 a 05) ---")
# 00 - Administração: permissão total
g00_admin = Group.objects.create(name=GROUP_ADMIN)
g00_admin.permissions.set(Permission.objects.all())

# 01 - Secretário: todas as permissões de pessoas, objetivos/metas e liquidações/pagamentos
g01_sec = Group.objects.create(name=GROUP_SECRETARIO)
sec_codenames = [
    'view_person', 'add_person', 'change_person', 'delete_person',
    'view_financialobjective', 'add_financialobjective', 'change_financialobjective', 'delete_financialobjective',
    'view_objectivesettlement', 'add_objectivesettlement', 'change_objectivesettlement', 'delete_objectivesettlement',
    'view_objectivecategory', 'add_objectivecategory', 'change_objectivecategory', 'delete_objectivecategory',
]
g01_sec.permissions.set(Permission.objects.filter(codename__in=sec_codenames))

# 02 - Financeiro: Visualizar Cadastro de Pessoas + todas as permissões de objetivos/metas e liquidações/pagamentos
g02_fin = Group.objects.create(name=GROUP_FINANCEIRO)
fin_codenames = [
    'view_person',
    'view_financialobjective', 'add_financialobjective', 'change_financialobjective', 'delete_financialobjective',
    'view_objectivesettlement', 'add_objectivesettlement', 'change_objectivesettlement', 'delete_objectivesettlement',
    'view_objectivecategory', 'add_objectivecategory', 'change_objectivecategory', 'delete_objectivecategory',
]
g02_fin.permissions.set(Permission.objects.filter(codename__in=fin_codenames))

# 03 - Militante, 04 - Contribuinte e 05 - Contato: sem nenhuma permissão
g03_mil = Group.objects.create(name=GROUP_MILITANTE)
g04_contrib = Group.objects.create(name=GROUP_CONTRIBUINTE)
g05_contato = Group.objects.create(name=GROUP_CONTATO)

print("[OK] Grupos criados: 00 - Administração, 01 - Secretário, 02 - Financeiro, 03 - Militante, 04 - Contribuinte, 05 - Contato.")

print("\n--- 4. CRIANDO USUÁRIO ADMINISTRADOR E PESSOAS SOLICITADAS ---")
# Usuário Master do Sistema (para login inicial de administração)
admin_user = User.objects.create_superuser("admin", "admin@teste.com", "admin")
admin_person = Person.objects.create(name="Administrador", user=admin_user)
admin_person.groups.set([g00_admin])
admin_person.sync_user_groups()


def create_person_with_depts(name, groups_list, department, role='MANAGE', responsible=None, username=None, password=None):
    user = None
    if username and password:
        user = User.objects.create_user(username=username, password=password)

    person = Person.objects.create(
        name=name,
        user=user,
        responsible_militant=responsible,
        is_active=True,
    )
    person.groups.set(groups_list)
    if user:
        person.sync_user_groups()
    if department:
        PersonDepartment.objects.create(person=person, department=department, role=role)
    return person


# Militantes da Célula Sinsej 1 (com permissão de visualização na célula)
mara = create_person_with_depts("Mara Lúcia Tavares", [g03_mil], d5_sinsej1, role='VIEW')
flavia = create_person_with_depts("Flávia Antunes", [g03_mil], d5_sinsej1, role='VIEW')
gilmara = create_person_with_depts("Gilmara Martins", [g03_mil], d5_sinsej1, role='VIEW')
veneranda = create_person_with_depts("Veneranda Alexandre", [g03_mil], d5_sinsej1, role='VIEW')
maciel = create_person_with_depts("Maciel Frigoto", [g03_mil], d5_sinsej1, role='VIEW')
jonathan = create_person_with_depts("Jonathan Vitorio", [g03_mil], d5_sinsej1, role='VIEW')

# Militante da Célula Sinsej 2 (com permissão de visualização na célula)
dartagnan = create_person_with_depts("D'Artagnan Júlifer Borges", [g03_mil], d5_sinsej2, role='VIEW')

# Militantes + Secretários
# Felippe: Acesso Total na Célula Sinsej 1 e Apenas Visualização no Setor Sindical (d4_sind)
felippe = create_person_with_depts(
    "Felippe Michel Veiga", [g03_mil, g01_sec], d5_sinsej1, role='MANAGE',
    username="veiga", password="senha123"
)
PersonDepartment.objects.create(person=felippe, department=d4_sind, role='VIEW')

welington = create_person_with_depts(
    "Welington Laufer", [g03_mil, g01_sec], d5_sinsej2, role='MANAGE',
    username="welington", password="senha123"
)

# Militantes + Financeiros
maicon = create_person_with_depts(
    "Maicon Rodrigo Vieira", [g03_mil, g02_fin], d5_sinsej1, role='VIEW',
    username="maicon", password="senha123"
)
edson = create_person_with_depts(
    "Edson Luiz Tavares", [g03_mil, g02_fin], d5_sinsej2, role='VIEW',
    username="edson", password="senha123"
)

# Contribuinte da Célula Sinsej 1 vinculada à Mara Lúcia Tavares
karlinne = create_person_with_depts(
    "Karlinne Lisandra Devegili",
    [g04_contrib],
    d5_sinsej1,
    role='VIEW',
    responsible=mara,
)

print(f"[OK] {Person.objects.count()} Pessoas cadastradas com sucesso!")
print("\n=== BASE DE DADOS CONFIGURADA E PRONTA PARA USO ===")
