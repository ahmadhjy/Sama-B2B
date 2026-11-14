from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import providers, service_credits as credits, service_suppliers as suppliers
from .models import CreditEntry, ServiceOffer, ServiceOrder
from . import tests as fixtures


@override_settings(DEBUG=False,ACCOUNTING_ENABLED=False,SECURE_SSL_REDIRECT=False,
    SERVICE_ESIM_CHECKOUT=True,SERVICE_HOTEL_CHECKOUT=True, SERVICE_INSURANCE_CHECKOUT=False,
    SWAN_IMS_SANDBOX=True,SWAN_IMS_API_BASE_URL='https://staging.cygnet-ims.com',
    SERVICE_CREDIT_USD_RATES='{"EUR":"1.25"}',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ManualServicesTests(TestCase):
    user=fixtures.PortalTests.user
    request=fixtures.PortalTests.request
    signin=fixtures.PortalTests.signin

    def setUp(self):
        fixtures.PortalTests.setUp(self)
        self.hr=self.user('humanresources','hr',self.company)
        company_check=patch('portal.middleware.check_company',return_value=True)
        company_check.start()
        self.addCleanup(company_check.stop)

    def credit(self,value='100.00'):
        credits.deposit(self.ceo,self.company.pk,Decimal(value),'Manual receipt',uuid4())

    def make_offer(self,kind,search,reference,price='25.00',currency='USD'):
        import json
        sandbox=kind=='insurance'
        return ServiceOffer.objects.create(actor=self.hr,company=self.company,kind=kind,label='Supplier offer',
            currency=currency,price=Decimal(price),credits=credits.credits_for(price,currency,sandbox),
            expires=timezone.now()+timedelta(minutes=10),sandbox=sandbox,
            payload=json.dumps({'row':{'provider_reference':reference},'search':search}))

    def test_roles_and_company_isolation(self):
        for actor in (self.owner,self.hr,self.requester,self.accountant,self.sales):
            self.signin(actor)
            result=self.client.get(reverse('service_catalog',args=['hotel']))
            self.assertEqual(result.status_code,200 if actor in (self.owner,self.hr) else 403)
        offer=self.make_offer('esim',{}, {'bundle_code':'A'})
        self.signin(self.outsider)
        self.assertEqual(self.client.get(reverse('service_checkout',args=[offer.pk])).status_code,404)
        self.signin(self.hr)
        self.assertEqual(self.client.get(reverse('service_admin_wallet',args=[self.company.pk])).status_code,403)
        self.assertContains(self.client.get(reverse('dashboard')),'Your AI travel assistant is coming soon')

    def test_deposit_replay_only_credits_once(self):
        self.signin(self.ceo)
        url=reverse('service_admin_wallet',args=[self.company.pk])
        self.assertContains(self.client.get(url),'Record deposit')
        data={'deposit_id':str(uuid4()),'amount':'82.45','note':'Receipt 51'}
        self.assertEqual(self.client.post(url,data).status_code,302)
        self.assertEqual(self.client.post(url,data).status_code,302)
        self.assertEqual(credits.wallet_balance(self.company.pk),Decimal('82.45'))
        self.assertEqual(CreditEntry.objects.filter(kind='deposit').count(),1)

    @patch('portal.service_suppliers.esim_catalog')
    @patch('portal.providers.call')
    def test_esim_reprices_and_charges_once(self, call, catalog):
        self.credit()
        self.signin(self.hr)
        offer=self.make_offer('esim',{'page':1},{'bundle_code':'A'},currency='EUR')
        catalog.return_value=([{'price_min':'25.00','currency':'EUR','provider_reference':{'bundle_code':'A'}}],1)
        call.return_value={'order_id':'esim-test-id'}
        url=reverse('service_checkout',args=[offer.pk])
        data={'email':'demo@example.invalid','name':'Test Person','accept':'on','price':'0.01'}
        first=self.client.post(url,data)
        self.assertEqual(first.status_code,302)
        self.assertEqual(self.client.post(url,data).url,first.url)
        self.assertEqual(credits.wallet_balance(self.company.pk),Decimal('68.75'))
        call.assert_called_once()
        self.assertEqual(call.call_args.args,('monty','POST','/Bundles'))
        order=ServiceOrder.objects.get(offer=offer)
        self.assertEqual(order.status,'confirmed')
        self.assertEqual(call.call_args.kwargs['json']['order_reference'],str(order.pk))
        self.signin(self.outsider)
        self.assertEqual(self.client.get(reverse('service_document',args=[order.pk])).status_code,404)

    @patch('portal.service_suppliers.esim_catalog')
    @patch('portal.providers.call')
    def test_changed_price_and_insufficient_credits_do_not_purchase(self, call, catalog):
        self.signin(self.hr)
        offer=self.make_offer('esim',{}, {'bundle_code':'A'})
        catalog.return_value=([{'price_min':'26.00','currency':'USD','provider_reference':{'bundle_code':'A'}}],1)
        url=reverse('service_checkout',args=[offer.pk])
        data={'email':'demo@example.invalid','name':'Test Person','accept':'on'}
        self.assertContains(self.client.post(url,data),'price or exchange rate changed')
        catalog.return_value[0][0]['price_min']='25.00'
        self.assertContains(self.client.post(url,data),'does not have enough credits')
        call.assert_not_called()
        self.assertFalse(ServiceOrder.objects.exists())

    @patch('portal.service_suppliers.prepare',return_value=('25.00','USD',{'bundle_code':'A'}))
    @patch('portal.service_suppliers.fulfill',side_effect=providers.ProviderUnavailable)
    def test_ambiguous_purchase_reserves_credits_and_staff_can_reconcile(self, fulfill, prepare):
        self.credit()
        self.signin(self.hr)
        offer=self.make_offer('esim',{}, {'bundle_code':'A'})
        url=reverse('service_checkout',args=[offer.pk])
        data={'email':'demo@example.invalid','name':'Test Person','accept':'on'}
        first=self.client.post(url,data)
        self.assertEqual(self.client.post(url,data).url,first.url)
        fulfill.assert_called_once()
        order=ServiceOrder.objects.get(offer=offer)
        self.assertEqual(order.status,'review')
        self.assertEqual(credits.wallet_balance(self.company.pk),Decimal('75.00'))
        self.signin(self.ceo)
        resolution=reverse('service_reconcile',args=[order.pk])
        self.assertEqual(self.client.post(resolution,{'decision':'released','note':'Provider verified no charge','verified':'on'}).status_code,302)
        self.assertEqual(credits.wallet_balance(self.company.pk),Decimal('100.00'))

    @patch('portal.service_suppliers.insurance_quotes')
    @patch('portal.providers.call')
    def test_swan_sandbox_uses_requoted_ids_without_debit(self, call, quotes):
        self.signin(self.hr)
        start=timezone.localdate()+timedelta(days=10)
        offer=self.make_offer('insurance',dict(destination='ITA',residence='LBN',start=str(start),
            end=str(start+timedelta(days=4)),births=['1994-07-12']),{'plan_id':7,'deductible':'0','price_ids':[3]})
        quotes.return_value=[{'price_min':'25.00','currency':'USD','provider_reference':{'plan_id':7,'deductible':'0','price_ids':[42]}}]
        call.return_value={'status':'success','contract_id':'SANDBOX-FIXTURE'}
        data={'email':'test@example.invalid','phone':'+96170000000','address':'Fictional test address','accept':'on','test_only':'on',
            'traveller_0_first_name':'Test','traveller_0_last_name':'Person','traveller_0_passport':'TEST0000',
            'traveller_0_gender':'F','traveller_0_nationality':'LB','traveller_0_passport_expiry':str(start+timedelta(days=365))}
        response=self.client.post(reverse('service_checkout',args=[offer.pk]),data)
        self.assertEqual(response.status_code,302)
        self.assertEqual(ServiceOrder.objects.get(offer=offer).status,'confirmed')
        self.assertFalse(CreditEntry.objects.exists())
        self.assertEqual(call.call_args.kwargs['json']['travellers'][0]['plan_price_id'],42)

    @override_settings(SWAN_IMS_API_BASE_URL='https://production.example.invalid')
    def test_sandbox_flag_cannot_issue_free_production_policies(self):
        self.assertFalse(suppliers.enabled('insurance',sandbox=True))

    @patch('portal.providers.call')
    def test_hotel_prebooks_rechecks_and_books_on_provider_credit(self,call):
        self.credit()
        self.signin(self.hr)
        start=timezone.localdate()+timedelta(days=10)
        offer=self.make_offer('hotel',{'start':str(start),'rooms':[{'adults':1,'childrenAges':[]}]},
            {'srk':'search','hotel_index':100,'offer_id':'1','results_token':'result','package_token':'package','room_tokens':['room-search']})
        availability={'availabilityToken':'checked','package':{'complete':True,'price':{'selling':{'value':25,'currency':'USD'}},
            'packageRooms':[{'occupancy':{'adults':1},'roomReferences':[{'selected':True,'roomToken':'checked-room'}]}]},
            'paymentMethods':[{'code':'credit'}],'cancellationPolicy':{'policies':[{'type':'standard','date':'2030-01-01','charge':{'value':25,'currency':'USD'}}]}}
        call.side_effect=[availability,availability,{'id':12345,'status':'OK'}]
        url=reverse('service_checkout',args=[offer.pk])
        response=self.client.get(url)
        self.assertContains(response,'Cancellation terms')
        data={'email':'test@example.invalid','accept':'on','room_0_0_title':'ms','room_0_0_firstName':'Test','room_0_0_lastName':'Person',
            'review_token':response.context['review_token']}
        self.assertEqual(self.client.post(url,data).status_code,302)
        order=ServiceOrder.objects.get(offer=offer)
        self.assertEqual(order.status,'confirmed')
        self.assertEqual(credits.wallet_balance(self.company.pk),Decimal('75.00'))
        self.assertTrue(call.call_args.args[2].endswith('/book'))
        self.assertEqual(call.call_args.kwargs['json']['payment'],{'method':'credit'})
        self.assertEqual(call.call_args.kwargs['json']['rooms'][0]['packageRoomToken'],'checked-room')



    @patch('portal.service_suppliers.esim_catalog')
    @patch('portal.service_suppliers.regions',return_value=[('EU','Europe')])
    @patch('portal.providers.available',return_value={'esim':True})
    def test_manual_catalog_persists_supplier_offer_and_shows_credit_price(self,available,regions,catalog):
        self.signin(self.hr)
        catalog.return_value=([{'price_min':'12.00','currency':'USD','label':'Europe data','detail':'3 GB',
                                'provider_reference':{'bundle_code':'PRIVATE-BUNDLE'}}],51)
        response=self.client.post(reverse('service_catalog',args=['esim']),{
            'bundle_category':'region','region_code':'EU','sort_by':'price_asc','page':'1'})
        self.assertContains(response,'Europe data')
        self.assertContains(response,'12.00 credits')
        self.assertNotContains(response,'PRIVATE-BUNDLE')
        self.assertContains(response,'Next')
        self.assertEqual(ServiceOffer.objects.get().actor,self.hr)

    def test_cancelled_order_can_only_refund_verified_amount_once(self):
        self.credit()
        offer=self.make_offer('esim',{}, {'bundle_code':'A'})
        order,created=credits.reserve(self.hr,offer.pk)
        self.assertTrue(created)
        credits.finish(order.pk,'test-reference',True,{'email':'test@example.invalid'})
        self.signin(self.hr)
        self.assertEqual(self.client.post(reverse('service_cancel',args=[order.pk])).status_code,302)
        self.signin(self.ceo)
        self.assertContains(self.client.get(reverse('service_review_queue')),'Cancellation requested')
        url=reverse('service_reconcile',args=[order.pk])
        payload={'decision':'cancelled','refund':'30.00','verified':'on','note':'Verified partial refund'}
        self.assertContains(self.client.post(url,payload),'cannot exceed')
        payload['refund']='12.50'
        self.assertEqual(self.client.post(url,payload).status_code,302)
        self.assertEqual(credits.wallet_balance(self.company.pk),Decimal('87.50'))
        self.assertContains(self.client.post(url,payload),'cannot be reconciled')

    @patch('portal.providers.hotels')
    @patch('portal.providers.hotel_cities')
    def test_hotel_suggestions_bind_search_to_the_selected_city(self,cities,hotels):
        cities.return_value=[
            {'id':17,'name':'Paris','country':'FR','country_name':'France','exact':True},
            {'id':55,'name':'Paris','country':'US','country_name':'United States','exact':True},
        ]
        hotels.return_value=[]
        self.signin(self.hr)
        with override_settings(IRIX_USERNAME='mock',IRIX_PASSWORD='mock'):
            places=self.client.get(reverse('hotel_destinations'),{'q':'Par'}).json()['places']
            start=timezone.localdate()+timedelta(days=10)
            data={'city':'Paris','destination':'US','city_choice':places[1]['choice'],'nationality':'LB',
                  'start':start.isoformat(),'end':(start+timedelta(days=2)).isoformat(),'count':'1','adults_0':'2'}
            url=reverse('service_catalog',args=['hotel'])
            self.assertEqual(self.client.post(url,data).status_code,200)
            self.assertEqual(hotels.call_args.args[0],55)
            hotels.reset_mock()
            self.assertContains(self.client.post(url,dict(data,destination='FR')),'Choose your destination from the suggestions.')
            hotels.assert_not_called()
            self.assertEqual(cities.call_count,1)
        self.signin(self.requester)
        self.assertEqual(self.client.get(reverse('hotel_destinations'),{'q':'Par'}).status_code,403)

    @patch('portal.providers.call')
    def test_hotel_photos_are_company_scoped_and_supplier_only(self,call):
        from django.core import signing
        self.signin(self.hr)
        token=signing.dumps({'company':str(self.company.pk),'hotel':7261},salt='hotel-photo')
        url=reverse('hotel_photo',args=[token])
        photo='https://www.ebookingcenter.com/tbs/reseller/assets/thumbnail?src=hotel:7261/demo.jpg'
        call.return_value={'_embedded':{'gallery':[{'url':'https://example.invalid/image.jpg'},{'url':photo}]}}
        self.assertRedirects(self.client.get(url),photo,fetch_redirect_response=False)
        self.signin(self.outsider)
        self.assertEqual(self.client.get(url).status_code,404)
        call.assert_called_once()


    @patch('portal.service_suppliers.prebook')
    @patch('portal.hotel_content.hotel_profile')
    @patch('portal.hotel_content.room_content')
    def test_property_details_are_grouped_and_terms_work_without_supplier_credit(self, rooms, profile, prebook):
        from .service_views import save_offers

        self.signin(self.hr)
        search = {'start': '2032-01-12', 'end': '2032-01-15', 'rooms': [{'adults': 2, 'childrenAges': []}]}
        row = providers.option('hotel', 'Garden Hotel', 'Double room', '180.00', 'USD',
                               {'hotel_index': 161, 'results_token': 'PRIVATE-TOKEN'})
        second = dict(row, price_min='210.00')
        another_hotel = dict(row, label='Other Hotel', provider_reference={'hotel_index': 162})
        items = save_offers(self.hr, 'hotel', [row, second, another_hotel], search)
        save_offers(self.hr, 'hotel', [dict(row, price_min='99.99')], search)
        offer = items[0]['offer']
        profile.return_value = {'address': '12 Test Street', 'overview': 'Hotel overview',
                                'photos': [{'url': 'https://i.travelapi.com/lodging/room.jpg'}]}
        detail = reverse('hotel_detail', args=[offer.pk])
        terms = reverse('hotel_terms', args=[offer.pk])
        response = self.client.get(detail)
        self.assertContains(response, 'Hotel overview')
        self.assertContains(response, '210.00')
        self.assertNotContains(response, '99.99')
        self.assertNotContains(response, 'Other Hotel')
        self.assertNotContains(response, 'PRIVATE-TOKEN')
        self.assertIn('https://i.travelapi.com/lodging/', response['Content-Security-Policy'])

        prebook.return_value = {'price': {'selling': {'value': 180, 'currency': 'USD'}}, 'paymentMethods': [],
                                'taxes': [{'name': 'City tax', 'amount': '4.00', 'currency': 'EUR', 'isIncluded': False}]}
        result = self.client.get(terms)
        self.assertContains(result, 'City tax')
        self.assertContains(result, 'paid separately')
        self.assertContains(result, 'credit payment available')
        self.assertNotContains(result, 'Continue to booking')
        self.assertFalse(ServiceOrder.objects.exists())
        self.assertFalse(CreditEntry.objects.exists())

        for user in (self.owner, self.outsider):
            self.signin(user)
            self.assertEqual(self.client.get(detail).status_code, 404)
            self.assertEqual(self.client.get(terms).status_code, 404)
