# Build and validation status

Updated 29 September 2026. Source repository: https://github.com/ahmadhjy/Sama-B2B. The application is prepared for a separate PythonAnywhere web app; it has not been deployed there yet.

## Included

- Responsive English corporate portal using the existing Sama branding.
- Owner creation from either dashboard through the accounting client code, shared sign-in, company users, individual permissions and complete profiles.
- Sales queue and exclusive assignment, private conversations, a grouped files/document library with protected previews, mandatory profile passport copies and request status history.
- Versioned PDF quotations, all-person approval tracking, rejection/expiry rules and booking confirmation.
- Public travel research assistant, editable summaries and a manual request path, with a $20 application allowance.
- Scoped accounting statements, invoices, receipts and attachments.
- Email outbox, reviewed incoming mail, opt-in push, and Broadnet GW3N SMS approval alerts with delivery reports.
- Private settings, encrypted passport numbers/documents and repeatable PostgreSQL deployment/update scripts.
- Temporary-domain notification restrictions and automatic suppression of real notifications from demo companies.

## Verified locally

- 83 portal tests passed locally; three PostgreSQL-only concurrency tests are skipped locally. GitHub Actions runs the full 86-test suite against PostgreSQL 16.
- 24 accounting/bridge tests passed, including a real signed HTTP roundtrip between separate Django applications and isolated databases.
- The roundtrip verified owner creation by the worker, unchanged account/password sign-in, password reset, idempotent sync, company disabling for owner/employees access restoration, and owner creation initiated in HelloSama that immediately creates the same working login in accounting.
- The live OpenAI model access check passed. Public research returned a Tourism Authority of Thailand citation and the generated summary passed the request form's validation with correct ISO dates and traveller count. The two calls totalled approximately $0.011369.
- IONOS SMTP STARTTLS and IMAP TLS authentication passed. No live email was sent; the mailbox was not modified.
- SMS authentication/balance passed (29,901 credits at the time checked). Submission formats, rejection handling, uncertain outcomes, short authenticated links, recipient restrictions and delivery-report transitions passed automated tests.
- Production Django checks for the temporary subdomain, migration consistency, Python compilation and deployment script syntax passed.
- The files library, image preview, return-to-message link, and company account screens passed desktop/mobile browser checks.
- The complete browser journey passed: request submission, sales claiming, quotation, three approvals, booking and confirmation; desktop/mobile checks reported no page JavaScript errors or horizontal overflow.
- PostgreSQL verification is recorded on each pushed commit in [GitHub Actions](https://github.com/ahmadhjy/Sama-B2B/actions).

The SMS HTTPS endpoints failed certificate/protocol checks. The documented HTTP endpoint works and is explicitly configurable; portal OTP does not secure that transport. A provider-approved sender and a controlled test mobile number are still required for handset delivery testing.

## Remaining on-host checks

Create the new web app, separate PostgreSQL database and always-on worker; configure the server's private `.env`; install/reload the accounting companion; and follow [LIVE_TESTING.md](LIVE_TESTING.md). Repeat connection checks from PythonAnywhere. Test actual email/SMS receipt and browser push with controlled recipients before disabling notification test mode.

The GitHub repository receives source and placeholder configuration only. Passwords, API keys, databases, uploaded documents and private demo credentials remain excluded.

See [the deployment guide](../DEPLOY_PYTHONANYWHERE.md) for the exact commands and temporary-domain setup.
