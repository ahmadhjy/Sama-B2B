# Manual services launch

Hotels, eSIM and travel insurance have independent form-based tabs. The customer AI workspace stays on Coming Soon in production. Assign **Human resources** from Company users to grant service access; owners already have it. Requesters and company accountants cannot use the service routes. HR can see its own orders, and company owners can see their company's orders.

## Company credits

- In the Sama CEO account, open **Company accounts → Manage credits** and record an externally received USD deposit with its receipt reference. 1 credit is 1 USD. There is no online deposit or card form.
- Wallet updates and ledger entries are committed together. A quote can create only one order. Credits are reserved before the supplier write; successful purchases retain the debit.
- A timeout or unclear supplier outcome moves the order to **Service review**. Do not submit another provider booking. Check the supplier using the portal order UUID/client reference. Record confirmation or release credits only when the supplier verifies that no charge remains. Orders stuck in Processing can be reconciled after 15 minutes.
- A customer may request cancellation. Sama verifies or performs it in the provider portal and records the actual approved refund in credits. Cancellation is not automatic and a request does not void a booking or policy.
- Non-USD quotes are displayed in their own currency. For checkout, set `SERVICE_CREDIT_USD_RATES` to a JSON map of approved USD-per-unit rates for the applicable currencies. Leave a currency out to prevent checkout in it. USD always uses 1. A changed supplier price or conversion requires a fresh quote.

## Hotel photos, details and rate conditions

- The hotel and room galleries use property-specific photos returned by IRIX. The sample included images hosted by Ebookingcenter and TravelAPI. The photos in the destination cards are separately credited destination photography.
- Hotel pages use IRIX extended hotel details plus the mapping catalogue for descriptions, amenities, property policies and photos. The room endpoint supplies room descriptions, facilities and photos. The page displays room size when the supplier text includes it. Coordinates power the OpenStreetMap view. Hotel content varies by property.
- **View rate & conditions** checks current availability and price. It shows the returned cancellation charges, taxes, supplier notes and itemized prices or meals when supplied. It does not place an order or deduct credits.
- IRIX's documentation describes reviews and nearby points of interest, but the extended responses sampled with this account did not contain structured guest reviews, rating breakdowns or a structured list of nearby attractions and transport. Supplier area descriptions and exact coordinates did come back. Ask IRIX which content products, hotels and account permissions expose the extra fields before promising parity with TBrooms.
- The portal displays a bounded selection of returned properties and rates. Refine the city, hotel name or landmark to narrow it. The content also depends on the dates and occupancy. Blank supplier sections are omitted.

## Deployment and supplier commissioning

Run `bash /home/Samatours2026/HelloSama/deploy/update.sh`. The migrations add wallets, credit entries, offers, service orders and the HR role. Keep the worker running to remove expired quotes and scrub their private data.

- **Monty:** live catalogue works with the existing account. Verify reseller wallet, corporate retail prices and supported currencies; set `SERVICE_ESIM_CHECKOUT=True` in the server's private environment when ready for paid orders. Purchase and top-up calls are billable. The portal supports installation QR PDF, resend, usage and compatible top-ups. A paid transaction was not used as a connectivity test.
- **IRIX:** search and prebook work. The sampled prebook responses returned no supplier credit payment method. Ask IRIX to enable B2B credit payment, verify the account's credit line and enable the `write:hotels-book`, `read:reservations` and `read:reservations-documents` permissions. Set `SERVICE_HOTEL_CHECKOUT=True` once IRIX confirms. Only complete, freshly priced supplier-credit rates can book. The portal does not handle third-party card/payment gateways or separately priced hotel extras. The supplier can return a pending reservation.
- **Swan IMS:** the configured endpoint is staging. Test policies use fictional data, cost zero credits and provide no cover. Staging issuance and PDF retrieval were verified. Obtain production URL and credentials, agency/tenant access and enabled plans, settlement currencies, cancellation terms and any IP allowlist requirement. In the private environment use the production endpoint and credentials, set `SWAN_IMS_SANDBOX=False`, and set `SERVICE_INSURANCE_CHECKOUT=True` only after verifying live access. Do not use test-policy references with production credentials.

After editing the server environment, reload the application (or run the update script again). Never put credentials in Git. The provider consoles remain the place for supplier wallet management, cancellation/refund execution, and reseller administration.
