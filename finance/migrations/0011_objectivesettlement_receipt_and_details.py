import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_update_groups_00_to_05'),
        ('finance', '0010_cell_replication_and_scope'),
    ]

    operations = [
        migrations.AddField(
            model_name='objectivesettlement',
            name='payment_time',
            field=models.TimeField(blank=True, null=True, verbose_name='Hora do Pagamento'),
        ),
        migrations.AddField(
            model_name='objectivesettlement',
            name='payer_name',
            field=models.CharField(blank=True, max_length=200, verbose_name='Nome do Responsável pelo Pagamento'),
        ),
        migrations.AddField(
            model_name='objectivesettlement',
            name='payer_account',
            field=models.CharField(blank=True, max_length=200, verbose_name='Conta que realizou o Pagamento'),
        ),
        migrations.AddField(
            model_name='objectivesettlement',
            name='receipt_total_amount',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=12,
                null=True,
                verbose_name='Valor Total do Comprovante (R$)',
            ),
        ),
        migrations.AddField(
            model_name='objectivesettlement',
            name='receipt_file',
            field=models.FileField(
                blank=True,
                null=True,
                upload_to='comprovantes/%Y/%m/',
                verbose_name='Comprovante de Pagamento (PDF, Imagem ou TXT)',
            ),
        ),
        migrations.AddField(
            model_name='objectivesettlement',
            name='notes',
            field=models.TextField(blank=True, verbose_name='Observações'),
        ),
        migrations.AlterField(
            model_name='objectivesettlement',
            name='collected_by',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='collected_settlements',
                to='core.person',
                verbose_name='Centralizado / Recolhido por (Militante)',
            ),
        ),
    ]

