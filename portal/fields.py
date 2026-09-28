from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models

def cipher():
    return Fernet(settings.DATA_ENCRYPTION_KEY.encode())

class EncryptedTextField(models.TextField):
    """Application-level encryption for passport data; deliberately not searchable."""
    def from_db_value(self, value, expression, connection):
        if not value:
            return ''
        try:
            return cipher().decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise ValueError('The configured data encryption key cannot read existing records.') from exc

    def get_prep_value(self, value):
        return cipher().encrypt(str(value).encode()).decode() if value else ''
