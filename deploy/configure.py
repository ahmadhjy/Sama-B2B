"""Create a private configuration without overwriting existing keys or passwords."""
import argparse
import base64
import os
import secrets
import re
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

def configure(local=False,domain=None):
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
        domain=(domain or os.environ.get('DEPLOY_DOMAIN') or 'hellosama.com').lower().strip()
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?',domain) or '.' not in domain:
            raise SystemExit('DEPLOY_DOMAIN must be a hostname, without https:// or a path.')
        replacements.update({'DJANGO_DEBUG':'False','PUBLIC_URL':'https://'+domain,'DJANGO_ALLOWED_HOSTS':domain})
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
    parser=argparse.ArgumentParser();parser.add_argument('--local',action='store_true');parser.add_argument('--domain')
    args=parser.parse_args();configure(args.local,args.domain)
