import secrets
from datetime import timedelta
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from portal.models import User,Company,Draft,TravelRequest,Message,Quote,Approval
from portal.demo import ensure_demo_passport

class Command(BaseCommand):
    help='Create fictional local demonstration data. Refuses to run in production or send real notifications.'
    def add_arguments(self,parser):
        parser.add_argument('--password',help='Optional local demo password; omitted generates a random one.')
    def handle(self,*args,**options):
        if not settings.DEBUG or settings.EMAIL_ENABLED or settings.IMAP_ENABLED or settings.AI_ENABLED:
            raise CommandError('Demo data is only allowed in local development with external services disabled.')
        if User.objects.filter(username='demo.owner').exists():
            self.stdout.write('Demo already exists. No users or passwords were changed.');return
        password=options.get('password') or secrets.token_urlsafe(15)
        company=Company.objects.create(account_number='DEMO-100',name='Cedar & Co.')
        def user(username,first,last,role,company=None,approve=False):
            member = User.objects.create_user(username=username,password=password,first_name=first,last_name=last,
                email=username+'@example.com',phone='+96170000000',passport_number='DEMO12345',
                passport_expiry=timezone.localdate()+timedelta(days=900),nationality='Lebanese',
                role=role,company=company,can_approve=approve)
            ensure_demo_passport(member)
            return member
        owner=user('demo.owner','Nour','Haddad','owner',company,True)
        requester=user('demo.requester','Rami','Khoury','requester',company)
        approver=user('demo.approver','Karim','Mansour','accountant',company,True)
        user('demo.accountant','Lea','Saab','accountant',company)
        ceo=user('demo.ceo','Sama','Admin','ceo')
        sales=user('demo.sales','Maya','Salem','sales')
        user('demo.finance','Jad','Hanna','finance')
        trips=[('Bangkok team retreat','Beirut','Bangkok','awaiting_approval',21),('A few days in Istanbul','Beirut','Istanbul','in_progress',10),('Dubai partner meetings','Beirut','Dubai','confirmed',7),('Paris leadership summit','Beirut','Paris','pending',45)]
        for i,(title,origin,destination,status,days) in enumerate(trips,1):
            req=TravelRequest.objects.create(reference=f'HS-26-DEMO000{i}',company=company,requester=owner if i==2 else requester,
                assignee=None if status=='pending' else sales,title=title,origin=origin,destination=destination,
                departure=timezone.localdate()+timedelta(days=days),return_date=timezone.localdate()+timedelta(days=days+5),travellers=2,
                budget='Around 1,500 USD per person',requirements='Comfortable hotels, easy transfers and flexible flight options.',status=status)
            Message.objects.create(request=req,kind='system',body=f'{req.requester.label} submitted this request. Waiting for a Sama specialist.')
            if req.assignee:
                Message.objects.create(request=req,kind='system',body='Maya Salem took over this request.')
                Message.objects.create(request=req,author=sales,body=f'Hello {req.requester.first_name}! I’m looking into options for your trip to {destination}. I’ll put together a clear quotation for you here.')
                Message.objects.create(request=req,author=req.requester,body='Thank you, Maya. A centrally located hotel would be ideal. Please include airport transfers as well.')
            if status=='awaiting_approval':
                quote=Quote.objects.create(request=req,version=1,amount='2840.00',currency='USD',details='Return flights for two travellers, five nights in a centrally located hotel and private airport transfers. Demonstration quotation only.',
                    inclusions='Economy return flights\nFive nights with breakfast\nReturn airport transfers',exclusions='Personal expenses and optional tours',
                    payment_terms='Payment due after availability is confirmed.',valid_until=timezone.now()+timedelta(days=3),created_by=sales,submitted_at=timezone.now(),approval_required_count=2)
                Approval.objects.create(quote=quote,user=owner,name_snapshot=owner.label,decision='approved',decided_at=timezone.now())
                Approval.objects.create(quote=quote,user=approver,name_snapshot=approver.label)
                Message.objects.create(request=req,kind='system',body='Quotation sent for approval. Nour Haddad approved. 1 of 2 approvals received; waiting for Karim Mansour.')
        self.stdout.write(self.style.SUCCESS('Fictional demonstration data created.'))
        self.stdout.write('Logins: demo.ceo, demo.sales, demo.owner, demo.requester, demo.approver, demo.accountant, demo.finance')
        self.stdout.write('Local demo password: '+password)
