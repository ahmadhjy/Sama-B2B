from datetime import date

import pycountry
from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.utils import timezone

from . import providers

COUNTRIES = [(c['code'], c['name']) for c in providers.countries()]
PHONE = RegexValidator(r'^\+[1-9][0-9]{7,14}$', 'Use international format, such as +961…')


def iso3(code):
    return pycountry.countries.get(alpha_2=code).alpha_3


def date_field(**kwargs):
    return forms.DateField(widget=forms.DateInput(attrs={'type':'date'}, format='%Y-%m-%d'),
                           input_formats=['%Y-%m-%d'], **kwargs)


def years(born, on):
    return on.year-born.year-((on.month,on.day)<(born.month,born.day))


class Dates(forms.Form):
    destination = forms.ChoiceField(choices=COUNTRIES)
    start = date_field(label='Start date')
    end = date_field(label='End date')

    def clean(self):
        data = super().clean()
        start, end = data.get('start'), data.get('end')
        if start and end and (start < timezone.localdate() or end <= start):
            raise ValidationError('Choose a start date from today and a later end date.')
        return data


class HotelSearch(Dates):
    city = forms.CharField(max_length=100, label='City', widget=forms.TextInput(attrs={'placeholder':'e.g. Istanbul'}))
    nationality = forms.ChoiceField(choices=COUNTRIES, label='Lead guest nationality')
    landmark = forms.CharField(max_length=120, required=False, label='Near a landmark (optional)')
    radius = forms.DecimalField(required=False, min_value=0.1, max_value=50, decimal_places=1, label='Distance in km')
    hotel_name = forms.CharField(required=False, max_length=120)
    stars = forms.TypedMultipleChoiceField(choices=[(i,f'{i} star'+('s' if i!=1 else '')) for i in range(1,6)],coerce=int,required=False,widget=forms.CheckboxSelectMultiple)
    board = forms.ChoiceField(choices=[('any','Any meals'),('RO','Room only'),('BB','Breakfast'),
        ('HB','Half board'),('FB','Full board'),('AI','All inclusive'),('SC','Self catering')])
    refundability = forms.ChoiceField(choices=[('any','Any cancellation terms'),('refundable','Refundable'),
        ('non_refundable','Non-refundable')])
    sort = forms.ChoiceField(choices=[('price','Lowest price'),('stars','Highest rating'),
        ('recommended','Recommended'),('distance','Closest to landmark')])

    def __init__(self, *args, count=1, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['destination'].label='Hotel country'
        self.fields['start'].label='Check-in'
        self.fields['end'].label='Check-out'
        self.fields['board'].required=self.fields['refundability'].required=self.fields['sort'].required=False
        self.fields['radius'].help_text='Leave blank to search within 1 km of the landmark.'
        for i in range(count):
            self.fields[f'adults_{i}'] = forms.IntegerField(min_value=1,max_value=9,initial=1,label='Adults')
            self.fields[f'ages_{i}'] = forms.CharField(required=False,max_length=24,label='Children’s ages at check-in',
                widget=forms.TextInput(attrs={'placeholder':'e.g. 4, 9'}),
                help_text='Optional. Separate ages with commas. Use 0 for a baby under one.')

    def clean(self):
        data = super().clean()
        rooms = []
        for key in self.fields:
            if key.startswith('adults_'):
                age_key = 'ages_'+key.split('_')[1]
                try:
                    ages = [int(v.strip()) for v in (data.get(age_key) or '').split(',') if v.strip()]
                    if len(ages)>8 or any(not 0<=a<=17 for a in ages):
                        raise ValueError
                except ValueError:
                    self.add_error(age_key,'Enter up to eight ages between 0 and 17.')
                    continue
                rooms.append({'adults':data.get(key),'childrenAges':ages})
        data['rooms']=rooms
        return data


class InsuranceSearch(Dates):
    residence = forms.ChoiceField(choices=COUNTRIES)

    def __init__(self, *args, count=1, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['destination'].label='Destination country'
        self.fields['residence'].label='Country of residence'
        self.fields['start'].label='Departure date'
        self.fields['end'].label='Return date'
        for i in range(count):
            self.fields[f'birth_{i}'] = date_field(label='Date of birth')

    def clean(self):
        data = super().clean()
        births = [data.get(k) for k in self.fields if k.startswith('birth_')]
        if any(b and (b>timezone.localdate() or years(b,timezone.localdate())>120) for b in births):
            raise ValidationError('Check the travellers’ dates of birth.')
        data['births']=births
        return data


class EsimSearch(forms.Form):
    destination = forms.ChoiceField(required=False,label='Destination country',choices=[('','Choose a country')]+COUNTRIES)
    bundle_category = forms.ChoiceField(label='Coverage', choices=[('country','One country'),('region','One region'),('global','Worldwide')],initial='country',widget=forms.RadioSelect)
    region_code = forms.ChoiceField(required=False,label='Region')
    sort_by = forms.ChoiceField(label='Sort plans', required=False, choices=[('price_asc','Lowest price'),('price_desc','Highest price')],initial='price_asc')
    page = forms.IntegerField(required=False,min_value=1,max_value=200,widget=forms.HiddenInput,initial=1)

    def __init__(self,*args,regions=(),**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['region_code'].choices=[('','Choose a region')]+list(regions)

    def clean(self):
        data=super().clean()
        category=data.get('bundle_category')
        if category=='country' and not data.get('destination'):
            self.add_error('destination','Choose the country where you’ll use your eSIM.')
        elif category=='region' and not data.get('region_code'):
            self.add_error('region_code','Choose the region where you’ll use your eSIM.')
        return data


class PurchaseForm(forms.Form):
    email = forms.EmailField()
    phone = forms.CharField(required=False,validators=[PHONE],max_length=16)
    accept = forms.BooleanField(label='I accept the displayed price and supplier terms and authorize this purchase.')

    def __init__(self,*args,kind,sandbox=False,rooms=None,births=None,hotel_config=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.kind, self.rooms, self.births = kind, rooms or [], births or []
        if kind=='esim':
            self.fields['name']=forms.CharField(max_length=120,label='Recipient name')
        if kind=='insurance':
            self.fields['phone'].required=True
            self.fields['address']=forms.CharField(max_length=240)
            if sandbox:
                self.fields['test_only']=forms.BooleanField(label='This is a test policy, not valid cover. I am using fictional traveller data.')
            for i in range(len(self.births)):
                p=f'traveller_{i}_'
                for key,label in [('first_name','first name'),('last_name','last name'),('passport','passport number')]:
                    self.fields[p+key]=forms.CharField(max_length=60,label=f'Traveller {i+1}: {label}')
                self.fields[p+'gender']=forms.ChoiceField(choices=[('M','Male'),('F','Female')],label=f'Traveller {i+1}: gender')
                self.fields[p+'nationality']=forms.ChoiceField(choices=COUNTRIES,label=f'Traveller {i+1}: nationality')
                self.fields[p+'passport_expiry']=date_field(label=f'Traveller {i+1}: passport expiry')
        if kind=='hotel':
            config=(hotel_config or {}).get('offerConfiguration') or {}
            contact=config.get('contactDetails') or {}
            if (contact.get('phone') or {}).get('required'):
                self.fields['phone'].required=True
                self.fields['phone'].help_text='Enter the national number after the international prefix.'
                self.fields['phone'].validators=[RegexValidator(r'^[0-9]{5,15}$','Enter the national number without spaces.')]
                self.fields['phone_prefix']=forms.CharField(label='International dialling prefix',max_length=5,
                    validators=[RegexValidator(r'^\+[1-9][0-9]{0,2}$','Enter a prefix such as +961.')])
            for key in ('address','city','country','postalCode'):
                if (contact.get(key) or {}).get('required'):
                    self.fields['contact_'+key]=(forms.ChoiceField(choices=COUNTRIES,label='Lead guest country') if key=='country'
                        else forms.CharField(max_length=120,label='Lead guest '+('postal code' if key=='postalCode' else key)))
            for key in ('fiscalIdentificationNumber','personalIdentificationNumber'):
                if ((config.get('identificationDocument') or {}).get(key) or {}).get('required'):
                    self.fields['id_'+key]=forms.CharField(max_length=60,label=key.replace('IdentificationNumber',' identification number'))
            self.hotel_options={}
            for i,option in enumerate((hotel_config or {}).get('bookingOptions') or []):
                if not option.get('included') or not option.get('optionCode'):
                    continue
                values=option.get('options') or [{'value':option.get('value'),'label':option.get('title')}]
                choices=[(v['value'],v.get('label') or v['value']) for v in values if v.get('value') is not None]
                if choices:
                    key=f'hotel_option_{i}'
                    self.hotel_options[key]=option['optionCode']
                    self.fields[key]=forms.ChoiceField(choices=[('','No preference')]+choices,required=False,
                        label=option.get('title') or 'Hotel preference')
            self.supplier_fields={}
            supplier_form=config.get('supplierBookingForm') or {}
            for i,(key,descriptor) in enumerate(supplier_form.items()):
                rules=descriptor.get('restrictions') or {}
                required=bool(descriptor.get('required'))
                field_name=f'supplier_{i}'
                self.supplier_fields[field_name]=key
                label=descriptor.get('name') or 'Supplier information'
                typ=rules.get('type')
                if typ=='enum':
                    self.fields[field_name]=forms.ChoiceField(label=label,required=required,choices=[(v,v) for v in rules.get('options',[])])
                elif typ=='date':
                    self.fields[field_name]=date_field(label=label,required=required)
                elif typ=='email':
                    self.fields[field_name]=forms.EmailField(label=label,required=required)
                else:
                    self.fields[field_name]=forms.CharField(label=label,required=required,max_length=120,
                        validators=[RegexValidator(r'^[0-9]+$','Enter digits only.')] if typ=='numeric' else [])
            self.fields['notes']=forms.CharField(max_length=400,required=False,label='Hotel requests (not guaranteed)')
            for i,room in enumerate(self.rooms):
                for j in range(room['adults']+len(room['ages'])):
                    p=f'room_{i}_{j}_'
                    label=f'Room {i+1}, guest {j+1}'
                    self.fields[p+'title']=forms.ChoiceField(choices=[(x,x.title()) for x in ('mr','mrs','miss','ms','mstr')],label=label+': title')
                    self.fields[p+'firstName']=forms.CharField(max_length=60,label=label+': first name')
                    self.fields[p+'lastName']=forms.CharField(max_length=60,label=label+': last name')
                    self.fields[p+'birthDate']=date_field(required=j>=room['adults'] or bool((config.get('birthdate') or {}).get('adults')),label=label+': date of birth')

    def payload(self, search, checked_rooms):
        data = self.cleaned_data
        result = {k:data[k] for k in ('email','phone')}
        if self.kind=='esim':
            result['name']=data['name']
        elif self.kind=='insurance':
            result.update(address=data['address'],travellers=[])
            for i in range(len(self.births)):
                p=f'traveller_{i}_'
                person={k:data[p+k] for k in ('first_name','last_name','passport','gender','nationality','passport_expiry')}
                if person['passport_expiry'] < date.fromisoformat(search['end']):
                    raise ValidationError('Passports must be valid through the end of the trip.')
                person['passport_expiry']=person['passport_expiry'].isoformat()
                person['nationality']=iso3(person['nationality'])
                result['travellers'].append(person)
        else:
            result.update(notes=data['notes'],rooms=[],
                booking_options=[{'optionCode':code,'value':data[field]} for field,code in self.hotel_options.items() if data.get(field)],
                supplier_form={code:str(data[field]) for field,code in self.supplier_fields.items() if data.get(field)})

            start=date.fromisoformat(search['start'])
            if [(r['adults'],sorted(r['ages'])) for r in self.rooms] != [(r['adults'],sorted(r['ages'])) for r in checked_rooms]:
                raise ValidationError('The supplier changed the room occupancy. Review a new offer.')
            for i,room in enumerate(checked_rooms):
                adults,children=[],[]
                for j in range(room['adults']+len(room['ages'])):
                    p=f'room_{i}_{j}_'
                    person={k:data[p+k] for k in ('title','firstName','lastName')}
                    person.update(reference=f'r{i+1}g{j+1}',lead=(i==0 and j==0),type='adult')
                    if person['lead']:
                        person['email']=data['email']
                        if data.get('phone_prefix'):
                            person.update(phonePrefix=data['phone_prefix'],phone=data['phone'])
                        person.update({key.removeprefix('contact_'):value for key,value in data.items() if key.startswith('contact_') and value})
                        identifiers={key.removeprefix('id_'):value for key,value in data.items() if key.startswith('id_') and value}
                        if identifiers:
                            person['identificationNumbers']=identifiers
                    born=data[p+'birthDate']
                    age=years(born,start) if born else None
                    if born and (born>timezone.localdate() or age>120 or (j<room['adults'] and age<18)):
                        raise ValidationError('Check the hotel guests’ dates of birth.')
                    if born:
                        person['birthDate']=born.isoformat()
                    if j>=room['adults']:
                        person['type']='infant' if age<2 else 'child'
                        children.append((age,person))
                    else:
                        adults.append(person)
                ordered=[]
                for age in room['ages']:
                    index=next((n for n,(value,_) in enumerate(children) if value==age),None)
                    if index is None:
                        raise ValidationError('Child ages must match the ages in the hotel search on check-in day.')
                    ordered.append(children.pop(index)[1])
                result['rooms'].append({'packageRoomToken':room['token'],'travelers':adults+ordered})
        return result


class DepositForm(forms.Form):
    amount = forms.DecimalField(min_value=0.01,max_value=10_000_000,max_digits=10,decimal_places=2)
    note = forms.CharField(max_length=200,label='Deposit reference or note')
    deposit_id = forms.UUIDField(widget=forms.HiddenInput)


class ResolveForm(forms.Form):
    decision = forms.ChoiceField(choices=[('confirmed','Confirmed with provider'),('released','Verified not charged / fully refunded'),('cancelled','Supplier verified cancellation')])
    refund = forms.DecimalField(required=False,min_value=0,max_digits=12,decimal_places=2,label='Credits to refund (verified cancellations only)')
    reference = forms.CharField(max_length=160,required=False,label='Provider reference')
    note = forms.CharField(max_length=200,label='Evidence / reconciliation note')
    verified = forms.BooleanField(label='I verified this outcome with the supplier.')
