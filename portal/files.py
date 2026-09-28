from io import BytesIO
from pathlib import Path
from PIL import Image
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from .fields import cipher
from .models import Attachment

def read_upload(upload):
    if upload.size > settings.MAX_UPLOAD_BYTES:
        raise ValidationError('Each file must be 10 MB or smaller.')
    data=upload.read(settings.MAX_UPLOAD_BYTES+1)
    upload.seek(0)
    ext=Path(upload.name).suffix.lower()
    if len(data)>settings.MAX_UPLOAD_BYTES or not data:
        raise ValidationError('The attachment is empty or too large.')
    if ext=='.pdf' and data.startswith(b'%PDF-'):
        content_type='application/pdf'
    elif ext in ('.jpg','.jpeg','.png'):
        try:
            image=Image.open(BytesIO(data)); image.verify()
            if image.format not in ('JPEG','PNG'):
                raise ValueError()
            content_type='image/jpeg' if image.format=='JPEG' else 'image/png'
        except Exception as exc:
            raise ValidationError('This image file could not be verified.') from exc
    else:
        raise ValidationError('Attach a PDF, JPG or PNG file.')
    return data, content_type

def save_attachment(upload, user, *, req=None, message=None, passport_owner=None, internal=False, sensitive=False):
    data, content_type=read_upload(upload)
    name=Path(upload.name.replace('\\','/')).name[:255]
    attachment=Attachment(request=req, message=message, passport_owner=passport_owner, uploaded_by=user,
        name=name, size=len(data), content_type=content_type, internal=internal, sensitive=sensitive or bool(passport_owner))
    attachment.file.save('encrypted.bin',ContentFile(cipher().encrypt(data)),save=True)
    return attachment
