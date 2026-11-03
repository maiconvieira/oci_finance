# Generated migration to create the 6 standard groups and remove Person.status
from django.db import migrations, models
import django.db.models.deletion


def setup_six_groups_and_migrate_status(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    Person = apps.get_model('core', 'Person')

    # Renomeia grupos antigos caso existam para evitar duplicação
    rename_map = {
        'Perfil Administração': '01 - Administração',
        'Perfil Secretaria': '02 - Secretário',
        'Perfil Finanças': '03 - Financeiro',
    }
    for old_name, new_name in rename_map.items():
        if not Group.objects.filter(name=new_name).exists():
            Group.objects.filter(name=old_name).update(name=new_name)
        else:
            Group.objects.filter(name=old_name).delete()

    # Garante a existência dos 6 grupos padronizados
    g01, _ = Group.objects.get_or_create(name='01 - Administração')
    g02, _ = Group.objects.get_or_create(name='02 - Secretário')
    g03, _ = Group.objects.get_or_create(name='03 - Financeiro')
    g04, _ = Group.objects.get_or_create(name='04 - Militante')
    g05, _ = Group.objects.get_or_create(name='05 - Contribuinte')
    g06, _ = Group.objects.get_or_create(name='06 - Contato')

    # Configura permissões padrão se existirem no banco
    all_perms = Permission.objects.all()
    if all_perms.exists():
        g01.permissions.set(all_perms)
        g02.permissions.set(Permission.objects.filter(content_type__app_label='core', content_type__model='person'))
        g03.permissions.set(Permission.objects.filter(content_type__app_label='finance'))
        g04.permissions.set(
            Permission.objects.filter(
                codename__in=['view_department', 'view_person', 'view_financialobjective', 'view_objectivesettlement']
            )
        )

    # Converte o campo status antigo de cada Person no respectivo grupo (04, 05 ou 06)
    status_to_group = {
        'MILITANTE': g04,
        'CONTRIBUINTE': g05,
        'CONTATO': g06,
    }
    for person in Person.objects.all():
        old_status = getattr(person, 'status', None)
        target_group = status_to_group.get(old_status, g06)
        person.groups.add(target_group)
        if person.user_id:
            person.user.groups.set(person.groups.all())


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_persondepartment_and_soft_delete'),
    ]

    operations = [
        migrations.RunPython(setup_six_groups_and_migrate_status, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='person',
            name='status',
        ),
        migrations.AlterField(
            model_name='person',
            name='groups',
            field=models.ManyToManyField(
                help_text='Perfis de funções, classificação e permissões que esta pessoa possui.',
                related_name='people',
                to='auth.group',
            ),
        ),
        migrations.AlterField(
            model_name='person',
            name='responsible_militant',
            field=models.ForeignKey(
                blank=True,
                help_text='Militante responsável pelo acompanhamento.',
                limit_choices_to={'groups__name': '04 - Militante', 'is_active': True},
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='assigned_people',
                to='core.person',
            ),
        ),
    ]

