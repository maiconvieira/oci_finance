# Generated migration for customizable Revenue (ObjectiveCategory) and eliminar opções pré-definidas
from django.db import migrations, models


def clear_preset_categories(apps, schema_editor):
    """
    Remove as categorias pré-configuradas antigas caso não estejam vinculadas a nenhum objetivo,
    ou desativa-as para que o usuário cadastre apenas as suas receitas personalizadas.
    """
    ObjectiveCategory = apps.get_model('finance', 'ObjectiveCategory')
    FinancialObjective = apps.get_model('finance', 'FinancialObjective')

    for cat in ObjectiveCategory.objects.all():
        if not FinancialObjective.objects.filter(category_id=cat.id).exists():
            cat.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0003_financial_objectives_extended'),
    ]

    operations = [
        migrations.AddField(
            model_name='objectivecategory',
            name='default_frequency',
            field=models.CharField(
                choices=[('PONTUAL', 'Único (Pontual)'), ('MENSAL', 'Mensal (Ciclo Mensal)')],
                default='MENSAL',
                max_length=15,
                verbose_name='Periodicidade da Receita',
            ),
        ),
        migrations.AddField(
            model_name='objectivecategory',
            name='use_unit_price',
            field=models.BooleanField(default=True, verbose_name='Utilizar campo Valor Unitário'),
        ),
        migrations.AddField(
            model_name='objectivecategory',
            name='unit_price_required',
            field=models.BooleanField(default=False, verbose_name='Valor Unitário é obrigatório?'),
        ),
        migrations.AddField(
            model_name='objectivecategory',
            name='use_quantity',
            field=models.BooleanField(default=False, verbose_name='Utilizar campo Quantidade'),
        ),
        migrations.AddField(
            model_name='objectivecategory',
            name='quantity_required',
            field=models.BooleanField(default=False, verbose_name='Quantidade é obrigatória?'),
        ),
        migrations.AddField(
            model_name='objectivecategory',
            name='default_quantity',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='Quantidade Padrão'),
        ),
        migrations.AddField(
            model_name='objectivecategory',
            name='is_subscription',
            field=models.BooleanField(default=False, verbose_name='É uma Assinatura?'),
        ),
        migrations.AddField(
            model_name='objectivecategory',
            name='use_editions_count',
            field=models.BooleanField(default=False, verbose_name='Utilizar Quantidade de Edições'),
        ),
        migrations.AddField(
            model_name='objectivecategory',
            name='editions_count_required',
            field=models.BooleanField(default=False, verbose_name='Quantidade de Edições é obrigatória?'),
        ),
        migrations.AddField(
            model_name='objectivecategory',
            name='default_editions_count',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='Quantidade de Edições Padrão'),
        ),
        migrations.AddField(
            model_name='objectivecategory',
            name='use_initial_final_edition',
            field=models.BooleanField(default=False, verbose_name='Utilizar Edição Inicial e Edição Final'),
        ),
        migrations.AddField(
            model_name='objectivecategory',
            name='initial_final_edition_required',
            field=models.BooleanField(default=False, verbose_name='Edição Inicial e Final são obrigatórias?'),
        ),
        migrations.AddField(
            model_name='objectivecategory',
            name='default_initial_edition',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='Edição Inicial Padrão'),
        ),
        migrations.AddField(
            model_name='objectivecategory',
            name='default_final_edition',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='Edição Final Padrão'),
        ),
        migrations.AddField(
            model_name='objectivecategory',
            name='person_required',
            field=models.BooleanField(default=False, verbose_name='Pessoa Vinculada é obrigatória?'),
        ),
        migrations.AddField(
            model_name='objectivecategory',
            name='replication_level',
            field=models.PositiveSmallIntegerField(
                choices=[
                    (0, 'Não replicar automaticamente para instâncias inferiores'),
                    (2, 'A partir do Nível d2 (Comitê Central → inferiores)'),
                    (3, 'A partir do Nível d3 (Comitê Regional → inferiores)'),
                    (4, 'A partir do Nível d4 (Setor → Células d5)'),
                    (5, 'Apenas Nível d5 (Célula)'),
                ],
                default=0,
                help_text='Define a partir de qual nível hierárquico esta receita se replica para as instâncias subordinadas.',
                verbose_name='Nível de Replicação para Instâncias Inferiores',
            ),
        ),
        migrations.AlterField(
            model_name='objectivecategory',
            name='category_type',
            field=models.CharField(blank=True, default='CUSTOM', max_length=20),
        ),
        migrations.AddField(
            model_name='financialobjective',
            name='editions_count',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='Quantidade de Edições'),
        ),
        migrations.RunPython(clear_preset_categories, migrations.RunPython.noop),
    ]

