import re
from django import forms
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from .models import User, Quote, TravelRequest

class LoginForm(forms.Form):
    username = forms.CharField(label='Account number or user ID', max_length=150, widget=forms.TextInput(attrs={'autocomplete':'username','autofocus':True}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={'autocomplete':'current-password'}), strip=False)

class ProfileForm(forms.ModelForm):
    passport_copy = forms.FileField(required=False, help_text='PDF, JPG or PNG. Up to 10 MB. Stored privately.')
    class Meta:
        model = User
        fields = ['first_name','last_name','email','phone','passport_number','passport_expiry','nationality','email_notifications']
        widgets = {'passport_number': forms.TextInput(), 'passport_expiry': forms.DateInput(attrs={'type':'date'})}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ['first_name','last_name','email']:
            self.fields[field].required = True
        if not self.instance.is_sama:
            for field in ['phone','passport_number','passport_expiry','nationality']:
                self.fields[field].required = True
            self.fields['passport_copy'].required = not self.instance.passport_files.exists()
        else:
            for field in ['passport_number','passport_expiry','nationality','passport_copy']:
                del self.fields[field]
    def clean_phone(self):
        value = re.sub(r'[\s()\-]', '', self.cleaned_data.get('phone',''))
        if value and not re.fullmatch(r'\+[1-9]\d{7,14}', value):
            raise forms.ValidationError('Use the country code, for example +96170123456.')
        return value
    def clean_passport_expiry(self):
        value = self.cleaned_data.get('passport_expiry')
        if value and value <= timezone.localdate():
            raise forms.ValidationError('Please enter an unexpired passport.')
        return value

class TeamForm(forms.ModelForm):
    password = forms.CharField(required=False, strip=False, widget=forms.PasswordInput(attrs={'autocomplete':'new-password'}), help_text='At least 10 characters. Leave blank to keep the existing password.')
    passport_copy = forms.FileField(required=False, help_text='Optional PDF, JPG or PNG; up to 10 MB.')
    class Meta:
        model = User
        fields = ['first_name','last_name','email','phone','passport_number','passport_expiry','nationality','role','can_approve','is_active']
        widgets = {'passport_number':forms.TextInput(),'passport_expiry':forms.DateInput(attrs={'type':'date'})}
        labels = {'can_approve': 'Can approve quotations', 'is_active':'Account enabled'}
    def __init__(self, *args, actor=None, **kwargs):
        self.actor = actor
        super().__init__(*args, **kwargs)
        self.fields['first_name'].required = self.fields['last_name'].required = True
        self.fields['password'].required = not self.instance.pk
        client_roles = [User.Role.OWNER, User.Role.REQUESTER, User.Role.ACCOUNTANT]
        staff_roles = [User.Role.CEO, User.Role.SALES, User.Role.FINANCE]
        choices = staff_roles if actor and actor.is_sama and not self.instance.company_id else client_roles
        self.fields['role'].choices = [(v, User.Role(v).label) for v in choices]
        if choices == staff_roles:
            self.fields.pop('can_approve')
            for key in ['passport_number','passport_expiry','nationality','passport_copy']:
                self.fields.pop(key)
        if self.instance.is_primary:
            for name in ['password','role','is_active']:
                self.fields.pop(name, None)
    def clean_password(self):
        value = self.cleaned_data.get('password','')
        if value:
            validate_password(value, self.instance)
        return value
    def clean_phone(self):
        value = re.sub(r'[\s()\-]', '', self.cleaned_data.get('phone',''))
        if value and not re.fullmatch(r'\+[1-9]\d{7,14}', value):
            raise forms.ValidationError('Include + and the country code.')
        return value
    def clean(self):
        data = super().clean()
        if self.instance.pk == getattr(self.actor, 'pk', None):
            if data.get('role', self.instance.role) != self.instance.role or data.get('is_active') is False:
                raise forms.ValidationError('Another administrator must change your own access.')
        return data

class CompanyOwnerForm(forms.Form):
    account_number = forms.CharField(label='Accounting client code', max_length=64,
        help_text='The client code from Sama Accounting. For a new client, add their client record there first.')
    mode = forms.ChoiceField(label='Company login', choices=[
        ('create', 'Create a new company login'), ('link', 'Connect an existing accounting portal login')])
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    email = forms.EmailField(required=False, help_text='The owner can complete missing contact and passport details when signing in.')
    phone = forms.CharField(required=False, max_length=30)
    password = forms.CharField(strip=False, max_length=1024,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
        help_text='New login: choose a password of at least 10 characters. Existing login: enter its current password. This does not reset existing credentials.')

    clean_phone = TeamForm.clean_phone

    def clean(self):
        data = super().clean()
        if data.get('password') and data.get('mode') == 'create':
            password = data['password']
            user = User(username=data.get('account_number', ''), first_name=data.get('first_name', ''),
                        last_name=data.get('last_name', ''), email=data.get('email', ''))
            try:
                validate_password(password, user)
            except forms.ValidationError as exc:
                self.add_error('password', exc)
            if password != password.strip():
                self.add_error('password', 'Do not start or end the password with spaces.')
        return data

class RequestForm(forms.ModelForm):
    class Meta:
        model = TravelRequest
        fields = ['title','origin','destination','departure','return_date','travellers','budget','requirements','traveller_details']
        widgets = {'departure': forms.DateInput(attrs={'type':'date'}), 'return_date': forms.DateInput(attrs={'type':'date'}),
                   'requirements': forms.Textarea(attrs={'rows':4}), 'traveller_details': forms.Textarea(attrs={'rows':3})}
        labels = {'title':'Trip name', 'origin':'Travelling from', 'destination':'Travelling to',
                  'departure':'Departure date', 'return_date':'Return date (optional)',
                  'travellers':'Total passengers (including children and infants)', 'budget':'Budget (optional)',
                  'requirements':'Passenger breakdown and trip details',
                  'traveller_details':'Other travellers’ details (private, optional)'}
        help_texts = {'title':'For example: Beirut to Bangkok',
                      'requirements':'Include adults, children and infants, the number of days or nights, and any hotel or transfer needs.',
                      'traveller_details':'Your own passport is already in your profile. Add other travellers only when needed.'}
    def clean(self):
        data = super().clean()
        departure, returning = data.get('departure'), data.get('return_date')
        if departure and departure < timezone.localdate():
            self.add_error('departure','Choose today or a future date.')
        if departure and returning and returning < departure:
            self.add_error('return_date','Return date cannot be before departure.')
        if not 1 <= (data.get('travellers') or 0) <= 100:
            self.add_error('travellers','Enter between 1 and 100 travellers.')
        return data

class QuoteForm(forms.ModelForm):
    class Meta:
        model = Quote
        fields = ['amount','currency','details','inclusions','exclusions','payment_terms','valid_until']
        widgets = {'details':forms.Textarea(attrs={'rows':5}), 'inclusions':forms.Textarea(attrs={'rows':3}),
            'exclusions':forms.Textarea(attrs={'rows':3}), 'payment_terms':forms.Textarea(attrs={'rows':3}),
            'valid_until':forms.DateTimeInput(attrs={'type':'datetime-local'}, format='%Y-%m-%dT%H:%M')}
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for field in ('details','inclusions','exclusions','payment_terms'):
            self.fields[field].max_length=10000
            self.fields[field].widget.attrs['maxlength']=10000
    def clean_amount(self):
        value=self.cleaned_data['amount']
        if value <= 0:
            raise forms.ValidationError('Quotation total must be greater than zero.')
        return value
    def clean_currency(self):
        value=self.cleaned_data['currency'].upper()
        if value not in ('USD','EUR','GBP','LBP','AED','SAR'):
            raise forms.ValidationError('Choose USD, EUR, GBP, LBP, AED or SAR.')
        return value
    def clean_valid_until(self):
        value=self.cleaned_data['valid_until']
        if value <= timezone.now():
            raise forms.ValidationError('The quotation must expire in the future.')
        return value
