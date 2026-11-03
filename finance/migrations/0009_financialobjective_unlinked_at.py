from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0008_objectivecategory_use_notes'),
    ]

    operations = [
        migrations.AddField(
            model_name='financialobjective',
            name='unlinked_at',
            field=models.DateTimeField(
                blank=True,
                help_text='Registra o momento em que o lançamento deixou de estar ativo ou a pessoa foi desvinculada da instância, mantendo o vínculo histórico.',
                null=True,
                verbose_name='Desvinculado / Inativado em',
            ),
        ),
    ]

