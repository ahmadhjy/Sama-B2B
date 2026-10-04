from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('portal', '0003_delivery_provider_checked_at_and_more')]
    operations = [migrations.AddField(model_name='user', name='removed_at',
                                    field=models.DateTimeField(null=True, blank=True))]
