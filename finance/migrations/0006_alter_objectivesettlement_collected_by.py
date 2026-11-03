# Generated migration to update ObjectiveSettlement.collected_by limit_choices_to '03 - Militante'
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_update_groups_00_to_05'),
        ('finance', '0005_clear_test_financial_records'),
    ]

    operations = [
        migrations.AlterField(
            model_name='objectivesettlement',
            name='collected_by',
            field=models.ForeignKey(
                limit_choices_to={'groups__name': '03 - Militante', 'is_active': True},
                on_delete=django.db.models.deletion.PROTECT,
                related_name='collected_settlements',
                to='core.person',
                verbose_name='Centralizado / Recolhido por (Militante)',
            ),
        ),
    ]

