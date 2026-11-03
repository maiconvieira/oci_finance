# Generated migration for Person.departments ManyToManyField
from django.db import migrations, models


def copy_department_to_departments(apps, schema_editor):
    Person = apps.get_model('core', 'Person')
    for person in Person.objects.all():
        if getattr(person, 'department_id', None):
            person.departments.add(person.department_id)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='person',
            name='departments',
            field=models.ManyToManyField(
                help_text='Instâncias às quais a pessoa está associada (herda acesso às subordinadas).',
                related_name='people',
                to='core.department',
            ),
        ),
        migrations.RunPython(copy_department_to_departments, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='person',
            name='department',
        ),
    ]

