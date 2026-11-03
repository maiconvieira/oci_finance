# Generated migration to update ObjectiveSettlement.collected_by limit_choices_to
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_replace_status_with_groups'),
        ('finance', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='objectivesettlement',
            name='collected_by',
            field=models.ForeignKey(
                help_text='Militante responsável que recolheu o dinheiro',
                limit_choices_to={'groups__name': '04 - Militante', 'is_active': True},
                on_delete=django.db.models.deletion.PROTECT,
                related_name='collected_settlements',
                to='core.person',
            ),
        ),
    ]

