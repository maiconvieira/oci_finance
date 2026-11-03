import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def migrate_zero_replication_level_to_five(apps, schema_editor):
    ObjectiveCategory = apps.get_model('finance', 'ObjectiveCategory')
    ObjectiveCategory.objects.filter(replication_level=0).update(replication_level=5)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_update_groups_00_to_05'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('finance', '0009_financialobjective_unlinked_at'),
    ]

    operations = [
        migrations.AlterField(
            model_name='objectivecategory',
            name='replication_level',
            field=models.PositiveSmallIntegerField(
                choices=[
                    (1, 'Nível d1 (Administração Geral → replica para todas as Células d5)'),
                    (2, 'Nível d2 (Comitê Central → replica para todas as Células d5)'),
                    (3, 'Nível d3 (Comitê Regional → selecionar CR(s) para replicar às Células d5)'),
                    (4, 'Nível d4 (Setor → selecionar Setor(es) para replicar às Células d5)'),
                    (5, 'Nível d5 (Célula → apenas para a(s) Célula(s) selecionada(s))'),
                ],
                default=5,
                help_text='Define o nível hierárquico a partir do qual esta receita será replicada para as Células (d5) subordinadas.',
                verbose_name='Nível de Replicação para as Células (d5)',
            ),
        ),
        migrations.AddField(
            model_name='objectivecategory',
            name='target_departments',
            field=models.ManyToManyField(
                blank=True,
                help_text='Instâncias do nível selecionado cujas Células (d5) subordinadas terão este lançamento.',
                related_name='revenue_categories',
                to='core.department',
                verbose_name='Instâncias Selecionadas para Replicação',
            ),
        ),
        migrations.AddField(
            model_name='objectivecategory',
            name='created_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='created_revenue_categories',
                to=settings.AUTH_USER_MODEL,
                verbose_name='Criado originalmente por',
            ),
        ),
        migrations.AlterField(
            model_name='financialobjective',
            name='department',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='financial_objectives',
                to='core.department',
                verbose_name='Célula / Instância do Lançamento',
            ),
        ),
        migrations.AddField(
            model_name='financialobjective',
            name='origin_department',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='originated_objectives',
                to='core.department',
                verbose_name='Instância de Origem (Replicação)',
            ),
        ),
        migrations.AddField(
            model_name='financialobjective',
            name='created_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='created_financial_objectives',
                to=settings.AUTH_USER_MODEL,
                verbose_name='Criado originalmente por',
            ),
        ),
        migrations.RunPython(migrate_zero_replication_level_to_five, migrations.RunPython.noop),
    ]

