import logging
import time
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.utils import timezone
from portal.accounting import sync_companies
from portal.mailbox import fetch_mail
from portal.models import WorkerState, RateLimit
from portal.notifications import process_deliveries
from portal.workflow import expire_quotes

class Command(BaseCommand):
    help='Process durable notifications, account synchronization, incoming email and quotation expiry.'
    def add_arguments(self, parser):
        parser.add_argument('--once',action='store_true',help='Run a single pass for scheduled tasks or diagnostics.')
    def handle(self,*args,**options):
        import os
        lock_path=settings.BASE_DIR/'.worker.lock'
        with lock_path.open('a+') as lock:
            try:
                if os.name=='nt':
                    import msvcrt
                    lock.seek(0);lock.write('1');lock.flush();lock.seek(0)
                    msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError:
                raise CommandError('Another HelloSama worker is already running.')
            last_sync=0
            release=settings.BASE_DIR/'.release'
            release_version=release.stat().st_mtime_ns if release.exists() else None
            while True:
                current_version=release.stat().st_mtime_ns if release.exists() else None
                if current_version!=release_version:
                    self.stdout.write('New deployment detected. Exiting so the always-on supervisor can restart with the new code.')
                    break
                close_old_connections()
                issues=[]
                if time.monotonic()-last_sync>=60:
                    tasks=[('quote_expiry',expire_quotes)]
                    if settings.ACCOUNTING_ENABLED: tasks.append(('accounting_sync',sync_companies))
                    if settings.IMAP_ENABLED: tasks.append(('incoming_mail',fetch_mail))
                    for name,task in tasks:
                        try:
                            task();WorkerState.objects.update_or_create(name=name,defaults={'value':{'ok':True}})
                        except Exception as exc:
                            issues.append(name)
                            WorkerState.objects.update_or_create(name=name,defaults={'value':{'ok':False,'error_type':type(exc).__name__}})
                            logging.getLogger(__name__).warning('%s failed (%s)',name,type(exc).__name__)
                    RateLimit.objects.filter(expires__lt=timezone.now()).delete()
                    last_sync=time.monotonic()
                try: delivered=process_deliveries()
                except Exception as exc:
                    delivered=0;issues.append('notifications')
                    logging.getLogger(__name__).warning('Notification worker failed (%s)',type(exc).__name__)
                WorkerState.objects.update_or_create(name='worker',defaults={'value':{'ok':not issues,'issues':issues,'processed':delivered}})
                if options['once']:
                    self.stdout.write(f'Worker pass complete. Processed {delivered} deliveries; issues: {", ".join(issues) or "none"}.')
                    break
                time.sleep(10)
