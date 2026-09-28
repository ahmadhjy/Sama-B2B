"""Install/update only the HelloSama bridge and its two registration lines."""
import argparse
import shutil
from pathlib import Path

def install(root):
    root=Path(root).resolve()
    settings=root/'config/settings/base.py'; urls=root/'config/urls.py'
    if not (root/'manage.py').is_file() or not settings.is_file() or not urls.is_file():
        raise SystemExit('Choose the Sama Accounting project folder containing manage.py.')
    source=Path(__file__).resolve().parents[1]/'integrations/accounting/hellosama_bridge'
    destination=root/'hellosama_bridge'
    for path in source.rglob('*.py'):
        if '__pycache__' in path.parts: continue
        target=destination/path.relative_to(source);target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,target)
    content=settings.read_text(encoding='utf-8')
    if '"hellosama_bridge"' not in content and "'hellosama_bridge'" not in content:
        if 'INSTALLED_APPS = [' not in content: raise SystemExit('Cannot locate INSTALLED_APPS; register hellosama_bridge manually.')
        settings.write_text(content.replace('INSTALLED_APPS = [','INSTALLED_APPS = [\n    "hellosama_bridge",',1),encoding='utf-8')
    content=urls.read_text(encoding='utf-8')
    if 'hellosama_bridge.urls' not in content:
        if 'urlpatterns = [' not in content: raise SystemExit('Cannot locate urlpatterns; add the bridge URL manually.')
        urls.write_text(content.replace('urlpatterns = [','urlpatterns = [\n    path("hellosama-api/", include("hellosama_bridge.urls")),',1),encoding='utf-8')
    print('Bridge installed. Add HELLOSAMA_SHARED_SECRET to the accounting environment, run migrate, and reload accounting.')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('accounting_path');install(parser.parse_args().accounting_path)
