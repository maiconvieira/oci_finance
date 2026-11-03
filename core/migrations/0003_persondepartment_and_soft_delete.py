# Generated migration for PersonDepartment (role per department) and Department.is_active
import django.db.models.deletion
from django.db import migrations, models


def migrate_existing_person_departments(apps, schema_editor):
    """
    Copia os vínculos existentes em core_person_departments para core_persondepartment
    com role='MANAGE', sem depender de ON CONFLICT antes da criação da constraint.
    """
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN ('core_person_departments', 'core_persondepartment');
        """)
        tables = {row[0] for row in cursor.fetchall()}

        if 'core_person_departments' in tables and 'core_persondepartment' in tables:
            cursor.execute("""
                INSERT INTO core_persondepartment (person_id, department_id, role)
                SELECT DISTINCT pd.person_id, pd.department_id, 'MANAGE'
                FROM core_person_departments pd
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM core_persondepartment existing
                    WHERE existing.person_id = pd.person_id
                      AND existing.department_id = pd.department_id
                );
            """)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_person_departments'),
    ]

    operations = [
        migrations.AddField(
            model_name='department',
            name='is_active',
            field=models.BooleanField(default=True, verbose_name='Ativo'),
        ),
        migrations.CreateModel(
            name='PersonDepartment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role', models.CharField(
                    choices=[('MANAGE', 'Acesso Total (Gerir)'), ('VIEW', 'Apenas Visualização')],
                    default='MANAGE',
                    max_length=15,
                    verbose_name='Nível de Atuação na Instância',
                )),
                ('department', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='person_links',
                    to='core.department',
                )),
                ('person', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='department_links',
                    to='core.person',
                )),
            ],
            options={
                'verbose_name': 'Vínculo de Instância da Pessoa',
                'verbose_name_plural': 'Vínculos de Instâncias das Pessoas',
                'unique_together': {('person', 'department')},
            },
        ),
        migrations.RunPython(migrate_existing_person_departments, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='person',
            name='departments',
        ),
        migrations.AddField(
            model_name='person',
            name='departments',
            field=models.ManyToManyField(
                help_text='Instâncias às quais a pessoa está associada.',
                related_name='people',
                through='core.PersonDepartment',
                to='core.department',
            ),
        ),
    ]
