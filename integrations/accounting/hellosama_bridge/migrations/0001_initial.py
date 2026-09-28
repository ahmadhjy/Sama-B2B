from django.db import migrations, models
class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [migrations.CreateModel(name='UsedNonce', fields=[
        ('nonce', models.CharField(max_length=64, primary_key=True, serialize=False)),
        ('created_at', models.DateTimeField(auto_now_add=True))])]
