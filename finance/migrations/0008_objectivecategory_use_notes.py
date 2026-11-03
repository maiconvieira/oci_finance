from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0007_objectivecategory_notes'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='objectivecategory',
            name='notes',
        ),
        migrations.AddField(
            model_name='objectivecategory',
            name='use_notes',
            field=models.BooleanField(default=False, verbose_name='Utilizar campo Observação'),
        ),
        migrations.AddField(
            model_name='objectivecategory',
            name='notes_required',
            field=models.BooleanField(default=False, verbose_name='Observação é obrigatória?'),
        ),
    ]

