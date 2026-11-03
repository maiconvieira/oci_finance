# Generated migration to update groups (00 to 05), department tree (d1 to d5), and initial people
from django.db import migrations, models
import django.db.models.deletion


def update_groups_departments_and_people(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    Department = apps.get_model('core', 'Department')
    Person = apps.get_model('core', 'Person')
    PersonDepartment = apps.get_model('core', 'PersonDepartment')

    # 1. Renomeia grupos antigos (01..06) para a nova numeração (00..05) em ordem reversa para evitar conflito de unique
    rename_pairs = [
        ('01 - Administração', '00 - Administração'),
        ('02 - Secretário', '01 - Secretário'),
        ('03 - Financeiro', '02 - Financeiro'),
        ('04 - Militante', '03 - Militante'),
        ('05 - Contribuinte', '04 - Contribuinte'),
        ('06 - Contato', '05 - Contato'),
    ]
    for old_name, new_name in rename_pairs:
        old_grp = Group.objects.filter(name=old_name).first()
        new_grp = Group.objects.filter(name=new_name).first()
        if old_grp and not new_grp:
            old_grp.name = new_name
            old_grp.save(update_fields=['name'])
        elif old_grp and new_grp:
            old_grp.delete()

    g00, _ = Group.objects.get_or_create(name='00 - Administração')
    g01, _ = Group.objects.get_or_create(name='01 - Secretário')
    g02, _ = Group.objects.get_or_create(name='02 - Financeiro')
    g03, _ = Group.objects.get_or_create(name='03 - Militante')
    g04, _ = Group.objects.get_or_create(name='04 - Contribuinte')
    g05, _ = Group.objects.get_or_create(name='05 - Contato')

    # Configura exatamente as permissões solicitadas para cada grupo
    all_perms = Permission.objects.all()
    if all_perms.exists():
        # 00 - Administração: permissão total
        g00.permissions.set(all_perms)

        # 01 - Secretário: todas as permissões de pessoas, objetivos/metas e liquidações/pagamentos
        sec_codenames = [
            'view_person', 'add_person', 'change_person', 'delete_person',
            'view_financialobjective', 'add_financialobjective', 'change_financialobjective', 'delete_financialobjective',
            'view_objectivesettlement', 'add_objectivesettlement', 'change_objectivesettlement', 'delete_objectivesettlement',
            'view_objectivecategory', 'add_objectivecategory', 'change_objectivecategory', 'delete_objectivecategory',
        ]
        g01.permissions.set(Permission.objects.filter(codename__in=sec_codenames))

        # 02 - Financeiro: Visualizar Cadastro de Pessoas + todas as permissões de objetivos/metas e liquidações/pagamentos
        fin_codenames = [
            'view_person',
            'view_financialobjective', 'add_financialobjective', 'change_financialobjective', 'delete_financialobjective',
            'view_objectivesettlement', 'add_objectivesettlement', 'change_objectivesettlement', 'delete_objectivesettlement',
            'view_objectivecategory', 'add_objectivecategory', 'change_objectivecategory', 'delete_objectivecategory',
        ]
        g02.permissions.set(Permission.objects.filter(codename__in=fin_codenames))

        # 03 - Militante, 04 - Contribuinte e 05 - Contato: sem nenhuma permissão
        g03.permissions.clear()
        g04.permissions.clear()
        g05.permissions.clear()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_replace_status_with_groups'),
    ]

    operations = [
        migrations.RunPython(update_groups_departments_and_people, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='person',
            name='responsible_militant',
            field=models.ForeignKey(
                blank=True,
                help_text='Militante responsável pelo acompanhamento.',
                limit_choices_to={'groups__name': '03 - Militante', 'is_active': True},
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='assigned_people',
                to='core.person',
            ),
        ),
    ]

