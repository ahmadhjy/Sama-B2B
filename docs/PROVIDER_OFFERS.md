# Provider offers in the chat

The concierge starts with service cards, then asks for the route, departure, return date or number of nights, and adult/child/infant counts. Only one question card appears at a time. Each chosen service gets its own short flow, with provider offers shown in the conversation. Selecting an offer moves to the next service; users can also ask Sama to find options for them.

After the final optional note, a review pop-up opens automatically. It shows the route, dates, travellers, services and saved options as a request card, with small Edit actions. The client sends that reviewed request to Sama with one button. A receipt and request reference appear only after the server confirms submission. Draft answers survive reloads, and the question cards also work when the AI is unavailable. No separate summary-generation step or full trip form is shown in the normal chat flow.

## What is connected

- **Hotels:** IRIX/eBookingCenter OAuth client credentials, Mapping API countries/cities/nationalities/hotels, and Hotels API synchronous search. Searches up to the first 100 mapped properties in the chosen city and displays up to six complete room packages. The selling price comes from the package, not the hotel's minimum or net price. Room names, meal basis and non-refundable flags are shown when returned. This is a selection of provider inventory, not an exhaustive city search.
- **eSIM:** Monty reseller login and GET /Bundles. Country codes are ISO3. Shows up to six plans from the first 50 results sorted by provider price. Price is for **one eSIM**, not automatically multiplied by passengers. Quantity and compatibility remain for Sama to confirm.
- **Insurance:** Swan IMS v5 login and POST /api/v5/travel/plans. Quotes use the exact dates, residence, destination and birth date for every traveller. Only complete deductible tiers are shown. Provider currencies remain unchanged. Sandbox quotes are visibly marked and cannot be selected for submission.

There are no purchase, contract creation, payment, hotel prebook/booking or Amadeus endpoints in this integration. Staff still confirms the quotation and completes bookings through the established approval process.

## Deploy on PythonAnywhere

Add the provider settings to `/home/Samatours2026/HelloSama/.env` privately. The supplied local values were verified from the handoff and credential notes, and are stored only in the ignored local `.env`. Git does **not** upload environment credentials.

```env
IRIX_API_BASE_URL=https://www.ebookingcenter.com/tbs/reseller
IRIX_USERNAME=YOUR_API_CLIENT_ID
IRIX_PASSWORD=YOUR_API_CLIENT_TOKEN
MONTY_ESIM_API_BASE_URL=https://resellerapi.montyesim.com/api/v0
MONTY_ESIM_USERNAME=YOUR_USERNAME
MONTY_ESIM_PASSWORD=YOUR_PASSWORD
MONTY_ESIM_CURRENCY=USD
SWAN_IMS_API_BASE_URL=https://staging.cygnet-ims.com
SWAN_IMS_USERNAME=YOUR_USERNAME
SWAN_IMS_PASSWORD=YOUR_PASSWORD
SWAN_IMS_SANDBOX=True
```

Use the existing approved account values. For real insurance offers, obtain the production base URL/account permissions from Swan, set that production URL and `SWAN_IMS_SANDBOX=False`, and test the resulting quote currencies/products. Changing the flag alone does not turn a staging account into production.

Then run:

```bash
bash /home/Samatours2026/HelloSama/deploy/update.sh
```

The script installs the added country-code dependency, checks the app, collects static files and reloads the web app. No new migrations are needed. Readiness reports provider configuration without displaying credentials.

## Validation and privacy

- Credentials and upstream authentication tokens stay on the server. Provider bodies/errors are not returned to the browser.
- Birth dates are used transiently for the insurance quote and are not stored in draft messages, sent to OpenAI or included in the saved offer. The browser clears them after a successful search.
- Selections use the server's saved offer, never a client-supplied price or label. Provider references and prices are retained in the request for staff follow-up; booking tokens are omitted.
- Quotes expire after 15 minutes. Changes to route, dates, service or passenger count invalidate selections. A fresh search also expires earlier quotes for that service, including different room/age criteria.
- Expired quotes must be searched and selected again before submission. This does not replace staff repricing before booking.
- Search and city lookup are authenticated, owned-draft scoped, rate limited and protected against concurrent edits/submission. Existing all-approver rules are unchanged.

## Checks performed

Provider sign-in succeeded for all three supplied accounts. Read-only live checks returned Monty plans, Swan staging plans, and IRIX packages from the provider-designated test city/property in Lebanon. No purchase or policy creation was called. Automated tests cover price parsing, currencies, exact occupancy/tier matching, stale quotes, ownership, failure recovery, selection snapshots and submission. Browser tests use explicitly fictional fixtures.
