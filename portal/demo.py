"""Fictional document fixtures; never resemble a real identity document."""
from django.core.files.uploadedfile import SimpleUploadedFile
from .files import save_attachment
from .pdf import document

def ensure_demo_passport(user):
    if user.company_id and not user.passport_files.exists():
        content = document('DEMO DOCUMENT — NOT A PASSPORT', user.label, [
            ('For local demonstrations only', 'This is a fictional placeholder for the profile passport upload. It is not an identity document and cannot be used for travel.'),
            ('Sample profile', f'{user.username}\nFictional passport number: {user.passport_number}')]).getvalue()
        save_attachment(SimpleUploadedFile('DEMO-passport-placeholder.pdf', content), user, passport_owner=user)
