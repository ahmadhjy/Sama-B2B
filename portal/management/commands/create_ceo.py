import getpass
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from portal.models import User

class Command(BaseCommand):
    help='Create the first Sama administrator. Password is entered privately and never printed.'
    def add_arguments(self,parser):
        parser.add_argument('--username',default='sama.admin')
        parser.add_argument('--email',required=True)
        parser.add_argument('--first-name',required=True)
        parser.add_argument('--last-name',required=True)
    def handle(self,*args,**options):
        if User.objects.filter(username__iexact=options['username']).exists():
            raise CommandError('This login already exists. No changes were made.')
        user=User(username=options['username'],email=options['email'],first_name=options['first_name'],last_name=options['last_name'],role='ceo')
        password=getpass.getpass('Choose an administrator password: ')
        if password!=getpass.getpass('Confirm password: '): raise CommandError('Passwords do not match.')
        try: validate_password(password,user)
        except ValidationError as exc: raise CommandError(' '.join(exc.messages))
        user.set_password(password);user.save()
        self.stdout.write(self.style.SUCCESS('Administrator created. Sign in with '+user.username))
