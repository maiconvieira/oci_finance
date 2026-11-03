# Generated migration for extended FinancialObjective, ObjectiveCategory, and ObjectiveSettlement
import django.db.models.deletion
from django.db import migrations, models


def seed_default_objective_categories(apps, schema_editor):
    ObjectiveCategory = apps.get_model('finance', 'ObjectiveCategory')
    defaults = [
        ('CONTRIB_MENSAL', 'Contribuição Mensal', 'CONTRIBUTION'),
        ('ASSINATURA_JORNAL', 'Assinatura de Jornal', 'SUBSCRIPTION'),
        ('JORNAL_AVULSO', 'Jornais Avulsos', 'EDITION_SALE'),
        ('REVISTA', 'Revistas', 'EDITION_SALE'),
        ('RIFA', 'Rifas', 'RAFFLE'),
        ('OUTRAS_RECEITAS', 'Outras Receitas', 'OTHER'),
    ]
    for code, name, cat_type in defaults:
        obj = ObjectiveCategory.objects.filter(code=code).first()
        if not obj:
            obj = ObjectiveCategory.objects.filter(name=name).first()
        if obj:
            obj.category_type = cat_type
            obj.save(update_fields=['category_type'])
        else:
            ObjectiveCategory.objects.create(code=code, name=name, category_type=cat_type, is_active=True)


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0002_alter_objectivesettlement_collected_by'),
    ]

    operations = [
        migrations.AddField(
            model_name='objectivecategory',
            name='category_type',
            field=models.CharField(
                choices=[
                    ('CONTRIBUTION', 'Contribuição / Cota'),
                    ('SUBSCRIPTION', 'Assinatura de Jornal (Edição Inicial e Final)'),
                    ('EDITION_SALE', 'Jornais Avulsos / Revistas (Qtd por Edição × Valor Unitário)'),
                    ('RAFFLE', 'Rifa'),
                    ('OTHER', 'Outras Receitas'),
                ],
                default='OTHER',
                max_length=20,
                verbose_name='Comportamento do Lançamento',
            ),
        ),
        migrations.AddField(
            model_name='objectivecategory',
            name='default_unit_price',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Opcional: preenche automaticamente o valor por unidade em jornais, revistas ou rifas.',
                max_digits=12,
                null=True,
                verbose_name='Valor Unitário Padrão (R$)',
            ),
        ),
        migrations.AddField(
            model_name='objectivecategory',
            name='is_active',
            field=models.BooleanField(default=True, verbose_name='Ativo'),
        ),
        migrations.AlterField(
            model_name='objectivecategory',
            name='name',
            field=models.CharField(max_length=120, unique=True, verbose_name='Nome da Categoria / Produto'),
        ),
        migrations.AlterField(
            model_name='objectivecategory',
            name='code',
            field=models.CharField(max_length=30, unique=True, verbose_name='Código / Sigla'),
        ),
        migrations.AddField(
            model_name='financialobjective',
            name='reference_month',
            field=models.DateField(
                blank=True,
                help_text='Primeiro dia do mês de competência (ex: 2026-11-01 para Novembro/2026).',
                null=True,
                verbose_name='Mês de Referência (Ciclo Mensal)',
            ),
        ),
        migrations.AddField(
            model_name='financialobjective',
            name='parent_objective',
            field=models.ForeignKey(
                blank=True,
                help_text='Preenche automaticamente quando o objetivo é herdado de CC, CR ou Setor.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='inherited_objectives',
                to='finance.financialobjective',
                verbose_name='Objetivo de Origem (Instância Superior)',
            ),
        ),
        migrations.AddField(
            model_name='financialobjective',
            name='initial_edition',
            field=models.PositiveIntegerField(
                blank=True,
                help_text='Número da edição inicial (para assinaturas de jornais).',
                null=True,
                verbose_name='Edição Inicial',
            ),
        ),
        migrations.AddField(
            model_name='financialobjective',
            name='final_edition',
            field=models.PositiveIntegerField(
                blank=True,
                help_text='Número da edição final (para assinaturas de jornais).',
                null=True,
                verbose_name='Edição Final',
            ),
        ),
        migrations.AddField(
            model_name='financialobjective',
            name='edition_number',
            field=models.CharField(
                blank=True,
                help_text='Ex: Edição 952, Nº 45 (para jornais avulsos ou revistas).',
                max_length=50,
                verbose_name='Nº / Identificação da Edição',
            ),
        ),
        migrations.AddField(
            model_name='financialobjective',
            name='target_quantity',
            field=models.PositiveIntegerField(
                blank=True,
                help_text='Meta de quantidade por edição (jornais, revistas, bilhetes).',
                null=True,
                verbose_name='Quantidade (Unidades / Exemplares)',
            ),
        ),
        migrations.AddField(
            model_name='financialobjective',
            name='unit_price',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Valor unitário de cada jornal, revista ou bilhete.',
                max_digits=12,
                null=True,
                verbose_name='Valor por Unidade (R$)',
            ),
        ),
        migrations.AddField(
            model_name='financialobjective',
            name='is_active',
            field=models.BooleanField(default=True, verbose_name='Ativo (Visível)'),
        ),
        migrations.AlterField(
            model_name='financialobjective',
            name='target_person',
            field=models.ForeignKey(
                blank=True,
                help_text='Pessoa que assumiu a meta/contribuição (ou deixe em branco para meta geral da instância).',
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='financial_objectives',
                to='core.person',
                verbose_name='Pessoa Vinculada',
            ),
        ),
        migrations.AddField(
            model_name='objectivesettlement',
            name='quantity_paid',
            field=models.PositiveIntegerField(
                blank=True,
                help_text='Opcional: quantidade efetiva de exemplares pagos nesta liquidação',
                null=True,
                verbose_name='Quantidade Paga / Vendida',
            ),
        ),
        migrations.AddField(
            model_name='objectivesettlement',
            name='is_active',
            field=models.BooleanField(default=True, verbose_name='Ativo'),
        ),
        migrations.RunPython(seed_default_objective_categories, migrations.RunPython.noop),
    ]

