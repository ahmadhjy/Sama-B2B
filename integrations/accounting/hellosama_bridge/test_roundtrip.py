"""Exercise real signed HTTP calls between independent Django apps and test databases."""
import os
import secrets
import subprocess
import tempfile
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch
from django.test import LiveServerTestCase, override_settings
from accounts_core.models import Client
from portal.accounts import sync_portal_account


@skipUnless(os.environ.get('HELLOSAMA_TEST_PORTAL_PATH'),'Set HELLOSAMA_TEST_PORTAL_PATH for the two-app roundtrip.')
@override_settings(ALLOWED_HOSTS=['localhost','127.0.0.1','testserver'],PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AccountingRoundtripTests(LiveServerTestCase):
    def test_creation_password_reset_disable_and_restore(self):
        root=Path(os.environ['HELLOSAMA_TEST_PORTAL_PATH'])
        python=root/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        secret=secrets.token_urlsafe(40)
        with tempfile.TemporaryDirectory(prefix='hellosama-roundtrip-') as folder, patch.dict(os.environ,{'HELLOSAMA_SHARED_SECRET':secret}):
            env=os.environ.copy()
            env.update({'ACCOUNTING_SHARED_SECRET':secret,'ACCOUNTING_BASE_URL':self.live_server_url,
                'HELLOSAMA_ROUNDTRIP_DB':str(Path(folder)/'portal.sqlite3')})
            def probe(stage):
                result=subprocess.run([str(python),str(root/'integrations/accounting/portal_probe.py'),stage],
                    cwd=root,env=env,capture_output=True,text=True,timeout=90)
                self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
                self.assertIn('"passed": true',result.stdout)
            company=Client.objects.create(client_code='ROUNDTRIP01',name_en='Isolated test company')
            self.assertEqual(sync_portal_account(company,enabled=True,password='RoundTripPass!2389'),[])
            probe('created')
            self.assertEqual(sync_portal_account(company,enabled=True,password='ChangedRoundTrip!7392'),[])
            probe('reset')
            self.assertEqual(sync_portal_account(company,enabled=False),[])
            probe('disabled')
            self.assertEqual(sync_portal_account(company,enabled=True),[])
            probe('restored')
            new_client=Client.objects.create(client_code='ROUNDTRIP02',name_en='Created from HelloSama')
            probe('portal_created')
            from accounts_core.models import UserProfile
            central=UserProfile.objects.get(client=new_client).user
            self.assertTrue(central.check_password('SharedHelloPass!7492'))
            self.assertEqual(central.username,'ROUNDTRIP02')
            self.assertFalse(central.is_staff or central.is_superuser)
