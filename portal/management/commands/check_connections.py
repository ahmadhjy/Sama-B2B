"""Non-delivery connection checks. Outputs never include passwords or API keys."""
import imaplib
import smtplib
import ssl
import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help='Verify accounting, OpenAI model access, IONOS authentication or SMS balance without sending messages.'

    def add_arguments(self,parser):
        for name in ('accounting','openai','email','sms'):
            parser.add_argument('--'+name,action='store_true')

    def handle(self,*args,**options):
        failures=[]
        def check(label,operation):
            try:
                result=operation();self.stdout.write(f'OK: {label}: {result}')
            except Exception as exc:
                failures.append(label)
                self.stdout.write(f'FAILED: {label} ({type(exc).__name__}). Credentials and provider response bodies are hidden.')
        if not any(options[k] for k in ('accounting','openai','email','sms')):
            raise CommandError('Choose --accounting, --openai, --email and/or --sms.')
        if options['accounting']:
            def accounting():
                from portal.accounting import bridge_call
                data=bridge_call('companies')
                if not data or 'companies' not in data:raise ValueError('Invalid bridge response')
                return f'{len(data["companies"])} company accounts available; no changes made'
            check('Accounting signed bridge',accounting)
        if options['openai']:
            def openai():
                response=requests.get('https://api.openai.com/v1/models/'+settings.OPENAI_MODEL,
                    headers={'Authorization':'Bearer '+settings.OPENAI_API_KEY},timeout=(5,15),allow_redirects=False)
                if response.status_code!=200:raise ValueError('Model access unavailable')
                return settings.OPENAI_MODEL+' accessible; no generation billed'
            check('OpenAI model',openai)
        if options['email']:
            def smtp():
                with smtplib.SMTP(settings.EMAIL_HOST,settings.EMAIL_PORT,timeout=15) as conn:
                    conn.ehlo();conn.starttls(context=ssl.create_default_context());conn.ehlo()
                    conn.login(settings.EMAIL_HOST_USER,settings.EMAIL_HOST_PASSWORD)
                return 'TLS authentication verified; no message sent'
            def imap():
                conn=imaplib.IMAP4_SSL(settings.IMAP_HOST,settings.IMAP_PORT,timeout=15)
                try:conn.login(settings.EMAIL_HOST_USER,settings.EMAIL_HOST_PASSWORD)
                finally:
                    try:conn.logout()
                    except Exception:pass
                return 'TLS authentication verified; mailbox unchanged'
            check('IONOS SMTP',smtp);check('IONOS IMAP',imap)
        if options['sms']:
            from portal.sms import balance
            check('SMS balance',lambda:balance()+' credits; no message sent')
        if failures:raise CommandError('Connection checks failed: '+', '.join(failures))
