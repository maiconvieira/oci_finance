# Generated migration to wipe all test financial records (settlements, objectives, categories) from the DB
from django.db import migrations


def clear_all_test_financial_data(apps, schema_editor):
    ObjectiveSettlement = apps.get_model('finance', 'ObjectiveSettlement')
    FinancialObjective = apps.get_model('finance', 'FinancialObjective')
    ObjectiveCategory = apps.get_model('finance', 'ObjectiveCategory')

    ObjectiveSettlement.objects.all().delete()
    FinancialObjective.objects.all().delete()
    ObjectiveCategory.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0004_customizable_revenue_categories'),
    ]

    operations = [
        migrations.RunPython(clear_all_test_financial_data, migrations.RunPython.noop),
    ]

