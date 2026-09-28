"""Create a private configuration without overwriting existing keys or passwords."""
import argparse
import base64
import os
import secrets
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

def configure(local=False):
    root=Path(__file__).resolve().parents[1]
    target=root/'.env'
    if target.exists():
        print('Private .env already exists; existing secrets were preserved.')
        return
    private=ec.generate_private_key(ec.SECP256R1())
    b64=lambda data:base64.urlsafe_b64encode(data).decode().rstrip('=')
    replacements={'DJANGO_SECRET_KEY':secrets.token_urlsafe(60),'DATA_ENCRYPTION_KEY':Fernet.generate_key().decode(),
        'ACCOUNTING_SHARED_SECRET':secrets.token_urlsafe(48),'VAPID_PRIVATE_KEY':b64(private.private_numbers().private_value.to_bytes(32,'big')),
        'VAPID_PUBLIC_KEY':b64(private.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint))}
    if not local:
        replacements.update({'DJANGO_DEBUG':'False','PUBLIC_URL':'https://hellosama.com','DJANGO_ALLOWED_HOSTS':'hellosama.com,www.hellosama.com'})
    lines=[]
    for line in (root/'.env.example').read_text().splitlines():
        key=line.split('=',1)[0]
        lines.append(f'{key}={replacements[key]}' if key in replacements else line)
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as handle: handle.write('\n'.join(lines)+'\n')
    print('Created private .env with unique application, encryption, integration and push keys.')
    print('Edit OPENAI_API_KEY and EMAIL_HOST_PASSWORD in .env; do not put credentials in source files.')
    if not local: print('Also fill in the PostgreSQL and accounting connection settings before deployment.')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--local',action='store_true');configure(parser.parse_args().local)
