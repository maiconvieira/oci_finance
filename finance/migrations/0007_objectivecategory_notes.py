from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0006_alter_objectivesettlement_collected_by'),
    ]

    operations = [
        migrations.AddField(
            model_name='objectivecategory',
            name='notes',
            field=models.TextField(blank=True, verbose_name='Observação'),
        ),
    ]

