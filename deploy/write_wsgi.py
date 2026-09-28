import os
from pathlib import Path
import sys
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
os.environ.setdefault('DJANGO_SETTINGS_MODULE','hellosama.settings')
from hellosama import settings
target_value=settings.env('PA_WSGI_FILE')
content=f'''# Managed by HelloSama deployment.
import os
import sys
project = {str(root)!r}
if project not in sys.path:
    sys.path.insert(0, project)
os.environ['HELLOSAMA_ENV_FILE'] = {str(root / '.env')!r}
os.environ['DJANGO_SETTINGS_MODULE'] = 'hellosama.settings'
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
'''
generated=root/'deploy/generated_wsgi.py'
generated.write_text(content,encoding='utf-8')
if target_value:
    target=Path(target_value).resolve()
    if target.parent!=Path('/var/www') or not target.name.endswith('_wsgi.py'):
        raise SystemExit('PA_WSGI_FILE must be the exact /var/www/..._wsgi.py path for HelloSama.')
    if not target.exists(): raise SystemExit('Create the HelloSama web app in PythonAnywhere first; WSGI file does not exist.')
    existing=target.read_text()
    if existing.strip() and '# Managed by HelloSama deployment.' not in existing:
        print('First deployment: paste deploy/generated_wsgi.py into the new HelloSama WSGI file, then rerun the update. Existing WSGI was preserved.')
    else:
        target.write_text(content,encoding='utf-8');target.touch()
        print('HelloSama WSGI updated and reload requested.')
else:
    print('Set PA_WSGI_FILE to the NEW HelloSama web app WSGI path for automatic reload.')
    print('Prepared deploy/generated_wsgi.py for first-time setup.')
