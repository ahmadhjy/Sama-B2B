from django.db import models

class UsedNonce(models.Model):
    nonce = models.CharField(max_length=64, primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
