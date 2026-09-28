"""Add an offline, repeatable local demonstration without changing existing requests."""
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from portal.files import save_attachment
from portal.models import Approval, Company, Draft, Message, Quote, TravelRequest, User
from portal.pdf import document


PEOPLE = [
    ('demo.ceo', 'Sama', 'Admin', 'ceo', None, False),
    ('demo.sales', 'Maya', 'Salem', 'sales', None, False),
    ('demo.sales2', 'Omar', 'Nassar', 'sales', None, False),
    ('demo.finance', 'Jad', 'Hanna', 'finance', None, False),
    ('demo.owner', 'Nour', 'Haddad', 'owner', 0, True),
    ('demo.requester', 'Rami', 'Khoury', 'requester', 0, False),
    ('demo.approver', 'Karim', 'Mansour', 'accountant', 0, True),
    ('demo.manager', 'Yara', 'Azar', 'requester', 0, True),
    ('demo.accountant', 'Lea', 'Saab', 'accountant', 0, False),
    ('demo.horizon.owner', 'Layla', 'Farah', 'owner', 1, True),
    ('demo.horizon.sales', 'Jad', 'Maalouf', 'requester', 1, False),
    ('demo.horizon.hr', 'Dalia', 'Aoun', 'requester', 1, True),
    ('demo.atlas.owner', 'Rana', 'Saleh', 'owner', 2, True),
    ('demo.atlas.sales', 'Tarek', 'Mouawad', 'requester', 2, False),
    ('demo.atlas.finance', 'Mira', 'Fares', 'accountant', 2, True),
]
# title, destination, status, requester, assignee, days until travel, nights, people, price
TRIPS = [
    ('Bangkok team retreat', 'Bangkok', 'awaiting_approval', 'demo.requester', 'demo.sales', 32, 6, 8, '11840.00'),
    ('Dubai partnership meetings', 'Dubai', 'confirmed', 'demo.requester', 'demo.sales', 12, 3, 3, '4260.00'),
    ('Istanbul leadership offsite', 'Istanbul', 'in_progress', 'demo.owner', 'demo.sales', 23, 4, 6, None),
    ('Paris technology conference', 'Paris', 'quote_sent', 'demo.requester', 'demo.sales', 45, 4, 2, '3680.00'),
    ('Doha client presentation', 'Doha', 'pending', 'demo.owner', None, 18, 2, 2, None),
    ('London annual strategy week', 'London', 'approved', 'demo.manager', 'demo.sales2', 56, 5, 4, '7920.00'),
    ('Athens supplier workshop', 'Athens', 'awaiting_client', 'demo.requester', 'demo.sales', 28, 3, 3, None),
    ('Rome board meeting', 'Rome', 'booking', 'demo.owner', 'demo.sales2', 38, 3, 2, '3240.00'),
    ('Barcelona design summit', 'Barcelona', 'closed', 'demo.requester', 'demo.sales', -18, 4, 2, '3480.00'),
    ('Singapore regional roadshow', 'Singapore', 'awaiting_approval', 'demo.horizon.sales', 'demo.sales2', 50, 6, 4, '9480.00'),
    ('Amsterdam customer workshop', 'Amsterdam', 'pending', 'demo.horizon.sales', None, 36, 3, 3, None),
    ('Abu Dhabi executive visit', 'Abu Dhabi', 'quote_sent', 'demo.horizon.owner', 'demo.sales', 21, 2, 2, '2760.00'),
    ('Vienna medical congress', 'Vienna', 'awaiting_approval', 'demo.atlas.sales', 'demo.sales', 42, 4, 5, '7250.00'),
    ('Milan distributor meetings', 'Milan', 'in_progress', 'demo.atlas.sales', 'demo.sales2', 24, 3, 2, None),
    ('Geneva research delegation', 'Geneva', 'confirmed', 'demo.atlas.owner', 'demo.sales2', 61, 4, 3, '6840.00'),
    ('Madrid incentive proposal', 'Madrid', 'rejected', 'demo.manager', 'demo.sales', 70, 5, 6, '10860.00'),
    ('Lisbon team getaway', 'Lisbon', 'expired', 'demo.owner', 'demo.sales2', 80, 4, 4, '5960.00'),
    ('Cairo site visit', 'Cairo', 'cancelled', 'demo.horizon.sales', 'demo.sales2', 25, 2, 2, None),
]


class Command(BaseCommand):
    help = 'Create screenshot-ready local demo accounts, conversations, quotes and attachments. Calls no external APIs.'

    def handle(self, *args, **options):
        if not settings.DEBUG or settings.ACCOUNTING_ENABLED or settings.EMAIL_ENABLED or settings.IMAP_ENABLED:
            raise CommandError('Showcase data requires DEBUG with accounting, email and mailbox connections disabled.')
        access = settings.BASE_DIR / '.demo-access.txt'
        password = ''
        if access.exists():
            for line in access.read_text(encoding='utf-8-sig').splitlines():
                if line.startswith('Local demo password: '):
                    password = line.partition(': ')[2].strip()
        password = password or 'SamaDemo-' + secrets.token_hex(5) + '!'
        now, today = timezone.now(), timezone.localdate()
        with transaction.atomic():
            companies = []
            for number, name in [('DEMO-100', 'Cedar & Co.'), ('DEMO-200', 'Horizon Consulting'), ('DEMO-300', 'Atlas Medical')]:
                company, _ = Company.objects.get_or_create(account_number=number, defaults={'name': name})
                if company.erp_id or not company.active:
                    raise CommandError('A reserved demo company is linked to accounting or disabled.')
                companies.append(company)
            people = {}
            for i, (username, first, last, role, company_index, approve) in enumerate(PEOPLE):
                company = companies[company_index] if company_index is not None else None
                user, _ = User.objects.get_or_create(username=username, defaults={
                    'first_name': first, 'last_name': last, 'role': role, 'company': company,
                    'can_approve': approve, 'email': username + '@example.com', 'phone': f'+96170009{i:03d}',
                    'passport_number': f'DEMO{i:05d}', 'passport_expiry': today + timedelta(days=900),
                    'nationality': 'Lebanese', 'email_notifications': False,
                })
                if user.is_primary or user.company_id != (company.pk if company else None):
                    raise CommandError('A reserved demo login belongs to another account.')
                if not user.check_password(password):
                    user.set_password(password)
                    user.save(update_fields=['password'])
                people[username] = user
            count = sum(self.add_trip(index, trip, people, now, today) for index, trip in enumerate(TRIPS))
            for username in ('demo.owner', 'demo.requester', 'demo.horizon.sales', 'demo.atlas.sales'):
                self.add_draft(people[username], today)
        lines = ['HELLOSAMA CORPORATE PORTAL — LOCAL DEMO ONLY', 'http://127.0.0.1:8765/login/', '',
                 'Fictional companies and travel. No accounting login is needed.', '', 'Accounts:']
        for user in people.values():
            lines.append(f'{user.username} | {user.label} | {user.get_role_display()} | {user.company or "Sama Tours"}'
                         + (' | Can approve quotations' if user.can_approve else ''))
        lines.extend(['', 'Local demo password: ' + password])
        access.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        if __import__('os').name != 'nt':
            access.chmod(0o600)
        self.stdout.write(self.style.SUCCESS(f'Demo ready: 3 companies, {len(people)} logins, {count} new requests.'))
        self.stdout.write('Existing requests preserved. Credentials: .demo-access.txt. No external services called.')

    def add_trip(self, index, trip, people, now, today):
        title, destination, status, requester_login, assignee_login, days, nights, size, amount = trip
        reference = f'HS-DEMO-{101 + index:04d}'
        if TravelRequest.objects.filter(reference=reference).exists():
            return 0
        requester = people[requester_login]
        sales = people.get(assignee_login)
        req = TravelRequest.objects.create(reference=reference, company=requester.company, requester=requester,
            assignee=sales, title=title, origin='Beirut', destination=destination, status=status,
            departure=today + timedelta(days=days), return_date=today + timedelta(days=days+nights), travellers=size,
            budget=f'Approximately {size * 1500:,} USD total',
            requirements=f'{nights} nights in a central business hotel with breakfast. Include airport transfers, checked baggage and flexible flight options. Please show the full group price.',
            traveller_details=f'Fictional demo group of {size} travellers. Lead contact: {requester.label}. Names to be verified before ticketing.',
            booking_reference=f'DEMO-{destination[:3].upper()}-{index+101}' if status in ('confirmed', 'closed') else '')
        events = []

        def say(body, author=None, internal=False):
            message = Message.objects.create(request=req, author=author, body=body,
                kind='human' if author else 'system', internal=internal)
            events.append(message)
            return message

        say(f'{requester.label} submitted this request. Waiting for a Sama specialist.')
        say(f'Hello Sama! We are arranging our {title.lower()} for {size} colleagues. Could you compare central hotels with breakfast and airport transfers?', requester)
        if sales:
            say(f'{sales.label} took over this request. Status changed to In progress.')
            say(f'Hi {requester.first_name}, I will be your point of contact. Will everyone travel together from Beirut, and do you have a preferred arrival time?', sales)
            say('Yes, we will travel together. An afternoon arrival would be ideal. Please include checked baggage and keep the hotel close to our meetings.', requester)
            say('Thank you. I will compare a central business hotel with a quieter alternative and make the inclusions clear in the quotation.', sales)
            say('Internal handover: verify flight change conditions and hotel cancellation terms before confirming.', sales, internal=True)
        if amount:
            approved = status in ('approved', 'booking', 'confirmed', 'closed')
            submitted = approved or status in ('awaiting_approval', 'rejected')
            approvers = list(User.objects.filter(company=req.company, can_approve=True, is_active=True).order_by('id'))
            version = 2 if destination == 'Paris' else 1
            values = dict(request=req, currency='USD', created_by=sales,
                inclusions=f'Return economy flights with baggage\n{nights} hotel nights with breakfast\nPrivate airport transfers',
                exclusions='Visa fees, travel insurance and personal expenses.',
                payment_terms='50% deposit after supplier confirmation; balance seven days before travel.',
                valid_until=now + timedelta(days=-1 if status == 'expired' else 7))
            if version == 2:
                Quote.objects.create(**values, version=1, amount='4120.00', details='Initial demonstration offer with a premium hotel.', superseded=True)
                say('Quotation version 1 was shared. The client requested a lower-cost hotel option.')
                say('Could you reduce the hotel budget without changing the flight times?', requester)
            quote = Quote.objects.create(**values, version=version, amount=amount,
                details=f'Illustrative offer for {size} travellers: Beirut to {destination}, {nights} hotel nights and transfers. Fictional prices for this demonstration; no live inventory has been checked.',
                submitted_at=now - timedelta(hours=4) if submitted else None,
                approval_required_count=len(approvers) if submitted else 0)
            say(f'{sales.label} shared quotation {quote.reference} for {float(amount):,.2f} USD.')
            say('Your quotation is ready. Review the inclusions, download the PDF and submit it for company approval when you are happy with the details.', sales)
            if submitted:
                say(f'{requester.label} submitted quotation version {version} to {len(approvers)} approvers. Everyone must approve this same version.')
                for position, approver in enumerate(approvers):
                    decision = 'approved' if approved or position == 0 else 'pending'
                    if status == 'rejected':
                        decision = 'rejected' if position == len(approvers)-1 else 'approved'
                    comment = 'Please reduce the total to fit our budget and send a revised offer.' if decision == 'rejected' else ''
                    Approval.objects.create(quote=quote, user=approver, name_snapshot=approver.label, decision=decision,
                        comment=comment, decided_at=now - timedelta(hours=2) if decision != 'pending' else None)
                    if decision != 'pending':
                        say(f'{approver.label} {decision} quotation version {version}. {comment}'.strip())
                if status == 'awaiting_approval':
                    waiting = ', '.join(quote.approvals.filter(decision='pending').values_list('name_snapshot', flat=True))
                    say(f'1 of {len(approvers)} approvals received. Waiting for {waiting}.')
                elif approved:
                    say(f'All {len(approvers)} approvers approved. Sama can now arrange the booking.')
                else:
                    say('Quotation rejected. A revised quotation will require fresh approvals.')
            if status == 'expired':
                say('The quotation has expired. Ask Sama to refresh availability and pricing.')
        if status == 'awaiting_client':
            say('Could you confirm whether the workshop venue is in the city centre or near the airport? This will help us choose the hotel.', sales)
            say('Status changed to Awaiting client. Waiting for the workshop location.')
        elif status in ('booking', 'confirmed', 'closed'):
            say(f'{sales.label} started arranging the booking with the suppliers.')
            if status != 'booking':
                say(f'Booking confirmed. Reference: {req.booking_reference}.')
                say('Everything is confirmed. Please review the traveller details and let me know if you need any adjustments.', sales)
                say('Received, thank you! This makes it much easier to keep the team updated.', requester)
            if status == 'closed':
                say('Trip completed and request closed. The conversation remains in your travel history.')
        elif status == 'cancelled':
            say('Our meeting has moved online. Please cancel this enquiry.', requester)
            say('Request cancelled before any booking was confirmed.')
        if index in (0, 1, 3, 9, 12, 14):
            author = sales if status == 'confirmed' else requester
            message = say('I have attached the trip brief for everyone to review.', author)
            pdf = document('DEMONSTRATION TRAVEL BRIEF', f'{req.reference} | {req.company.name}', [
                ('Journey', f'{title}\nBeirut to {destination}\n{req.departure} to {req.return_date} | {size} travellers'),
                ('Requirements', req.requirements), ('Demonstration only', 'Fictional data. This document is not a ticket, reservation or live quotation.')])
            save_attachment(SimpleUploadedFile('Travel-brief.pdf', pdf.getvalue(), content_type='application/pdf'), author, req=req, message=message)
        end = now - timedelta(minutes=index)
        start = end - timedelta(minutes=35 * (len(events)-1))
        for position, message in enumerate(events):
            Message.objects.filter(pk=message.pk).update(created_at=start + timedelta(minutes=position*35))
        TravelRequest.objects.filter(pk=req.pk).update(created_at=start, updated_at=end)
        # Match the quotation and approval cards to the same conversation timeline.
        for quote in req.quotes.all():
            issued = req.messages.filter(body__contains=quote.reference).first()
            quote.created_at = issued.created_at if issued else start + timedelta(minutes=35)
            submitted_event = req.messages.filter(body__contains=f'submitted quotation version {quote.version}').first()
            if submitted_event:
                quote.submitted_at = submitted_event.created_at
            quote.save(update_fields=['created_at', 'submitted_at'])
            for approval in quote.approvals.exclude(decision='pending'):
                event = req.messages.filter(body__startswith=f'{approval.name_snapshot} {approval.decision} quotation').first()
                if event:
                    approval.decided_at = event.created_at
                    approval.save(update_fields=['decided_at'])
        return 1

    def add_draft(self, user, today):
        for draft in Draft.objects.filter(user=user, travelrequest__isnull=True):
            if any(item.get('demo_scenario') == 'bangkok-planner' for item in draft.messages):
                return
        date = today + timedelta(days=60)
        Draft.objects.create(user=user, messages=[
            {'role': 'user', 'content': 'We are planning a six-night team trip from Beirut to Bangkok for four people. What would you recommend?', 'demo_scenario': 'bangkok-planner'},
            {'role': 'assistant', 'content': 'For this illustrative demo itinerary, I would suggest a central base near public transport, two meeting days and a flexible sightseeing day. What dates and budget do you have in mind? Live flights and hotel availability have not been checked.'},
            {'role': 'user', 'content': f'We would like to leave on {date:%d %B %Y}, return six days later and spend around 6,000 USD in total. Include breakfast and airport transfers.'},
            {'role': 'assistant', 'content': 'Ask Sama to compare business hotels near Siam or Sukhumvit. A riverside evening and a temple visit could fit around your meetings. I will include flights, checked baggage, breakfast and transfers in the request for the sales team to price.'},
            {'role': 'user', 'content': 'Please prepare a summary so I can review it before sending.'},
            {'role': 'assistant', 'content': 'Your editable request summary is ready alongside this conversation. Check the dates and group size, add any preferences, then select Submit request when ready.'},
        ], summary={'title': 'Bangkok team discovery trip', 'origin': 'Beirut', 'destination': 'Bangkok',
            'departure': date.isoformat(), 'return_date': (date + timedelta(days=6)).isoformat(),
            'travellers': 4, 'budget': '6,000 USD total',
            'requirements': 'Central business hotel, breakfast, checked baggage and return airport transfers. Two meeting days. Compare suitable options and confirm availability.'})
