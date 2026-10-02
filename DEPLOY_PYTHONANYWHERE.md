# Deploy HelloSama on PythonAnywhere

Repository: https://github.com/ahmadhjy/Sama-B2B

HelloSama uses a separate web app, virtual environment and PostgreSQL database. Keep the existing accounting app and its database in place. The plan needs another web app and an always-on task slot.

## Runtime compatibility

HelloSama pins **Django 4.2.30** with Python 3.12 for this account's **PostgreSQL 12** server. This was explicitly selected by the project owner on 30 September 2026. Django 4.2 reached upstream end of security support on 7 April 2026, and PostgreSQL 12 on 21 November 2024. Compatibility does not imply ongoing security maintenance; plan to move this app to maintained versions when hosting permits. CI exercises both PostgreSQL 12 and 16.

The existing HelloSama web app can be reused. Its isolated virtual environment receives the pinned version through the update command; recreating the web app or changing the accounting environment is unnecessary. Initial `migrate` creates HelloSama's tables in its own new database, without moving existing accounting data.

References: [Django support lifecycle](https://www.djangoproject.com/download/), [PostgreSQL support lifecycle](https://www.postgresql.org/support/versioning/).

## 1. Start on a temporary subdomain

For the existing PythonAnywhere username `Samatours2026`, use:

**https://hellosama-samatours2026.pythonanywhere.com**

In the Web tab choose **Add a new web app → Your own domain**, enter `hellosama-samatours2026.pythonanywhere.com`, and choose manual configuration with Python 3.12. PythonAnywhere supports names of the form `something-yourusername.pythonanywhere.com`. For an EU account, use the equivalent `something-yourusername.eu.pythonanywhere.com` instead. Use the exact domain that the Web tab accepts.

Do not rename or replace the existing accounting web app. The new portal domain does not require changes to HelloSama's main-domain DNS or IONOS mail records.

## 2. Clone and run the setup command

In a Bash console:

```bash
cd /home/Samatours2026
git clone https://github.com/ahmadhjy/Sama-B2B.git HelloSama
cd HelloSama
DEPLOY_DOMAIN=hellosama-samatours2026.pythonanywhere.com bash deploy/update.sh
```

For a private GitHub repository, use your usual GitHub authentication or a read-only deploy key; do not put a token in the clone URL.

The first run creates `.venv` and a private `.env` with generated application, encryption, integration and push keys. It stops at validation until the database settings are supplied. Edit `.env` using PythonAnywhere's Files editor. An existing `.env` is always preserved; `DEPLOY_DOMAIN` only affects initial creation.

## 3. Private configuration

The following fields belong **only in the server's `.env`**, never in GitHub:

```dotenv
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=hellosama-samatours2026.pythonanywhere.com
PUBLIC_URL=https://hellosama-samatours2026.pythonanywhere.com
DB_NAME=your_separate_hellosama_database
DB_USER=your_postgresql_user
DB_PASSWORD=your_postgresql_password
DB_HOST=your_postgresql_host
DB_PORT=your_postgresql_port
DB_SSLMODE=prefer
ACCOUNTING_BASE_URL=https://samatours2026.pythonanywhere.com
OPENAI_API_KEY=your_OpenAI_project_key
AI_ENABLED=True
EMAIL_HOST_USER=info@hellosama.com
EMAIL_HOST_PASSWORD=the_mailbox_password
EMAIL_HOST=smtp.ionos.com
EMAIL_PORT=587
EMAIL_ENABLED=True
IMAP_HOST=imap.ionos.com
IMAP_ENABLED=True
BUSINESS_EMAIL=info@hellosama.com
SMS_BASE_URL=http://smppa3.broadnet.me:8080/websmpp
SMS_USERNAME=your_provider_username
SMS_PASSWORD=your_provider_password
SMS_SENDER_ID=your_provider_approved_sender
SMS_ENABLED=False
SMS_ALLOW_HTTP=True
NOTIFICATION_TEST_MODE=True
NOTIFICATION_TEST_EMAILS=info@hellosama.com
NOTIFICATION_TEST_PHONES=
```

Copy the current OpenAI, mailbox and SMS credentials from your local private configuration; deployment does not copy them through Git. Use the exact PostgreSQL host/port from the Databases tab, which may differ from port 5432. Create a separate database and set SSL mode according to its requirements. If accounting uses a different live domain, use that exact HTTPS address.

Keep the generated `DJANGO_SECRET_KEY`, `DATA_ENCRYPTION_KEY`, `ACCOUNTING_SHARED_SECRET`, `VAPID_PUBLIC_KEY` and `VAPID_PRIVATE_KEY`. Back up the encryption key permanently; existing encrypted documents cannot be recovered without it. Do not upload the local demo database, demo password file or test uploads.

`SMS_SENDER_ID` must be approved by the provider. After confirming a test mobile number, put it in `NOTIFICATION_TEST_PHONES` in international format and enable `SMS_ENABLED=True`. SMS sends only approval alerts, one per required approver. The provider documentation uses HTTP and the checked HTTPS endpoints failed. `SMS_ALLOW_HTTP=True` explicitly permits that transport; a portal OTP does not encrypt these API requests. Use a provider-confirmed HTTPS endpoint when available and then set this flag back to False.

Keep notification test mode on initially: only listed email addresses and phone numbers receive messages, and push delivery is suppressed. Demo-company requests never produce external messages. When all delivery checks pass, deliberately turn test mode off to enable real client recipients and opted-in push devices. Old blocked test deliveries are not automatically replayed.

## 4. Finish the web app configuration

Set these values in the new Web app:

- Source and working directory: `/home/Samatours2026/HelloSama`
- Virtualenv: `/home/Samatours2026/HelloSama/.venv`
- Static mapping `/static/` to `/home/Samatours2026/HelloSama/staticfiles`

Do not map `/media/` or `/private_uploads/`: private files require signed-in permission checks.

Copy the new app's exact WSGI file path from the Web tab into `PA_WSGI_FILE` in `.env`. Run:

```bash
bash /home/Samatours2026/HelloSama/deploy/update.sh
```

This applies migrations, collects static files, checks production settings and writes `deploy/generated_wsgi.py`. On the first setup, paste its contents into the **new HelloSama WSGI file**. Existing unmarked WSGI files are preserved. Future updates manage/reload only files bearing the HelloSama deployment marker. Enable HTTPS and confirm the site opens securely.

## 5. Connect accounting and automatic owner creation

```bash
cd /home/Samatours2026/HelloSama
.venv/bin/python deploy/install_accounting_bridge.py /home/Samatours2026/Sama-Acc
```

The installer copies only the included `hellosama_bridge` companion and adds one app registration plus one URL registration. Preserve those changes in the accounting repository as part of its next normal update.

Copy HelloSama's `ACCOUNTING_SHARED_SECRET` into the accounting project's root `.env` as:

```dotenv
HELLOSAMA_SHARED_SECRET=the_same_integration_secret
```

Run accounting's migration with its own virtual environment:

```bash
cd /home/Samatours2026/Sama-Acc
/home/Samatours2026/.virtualenvs/sama-accounting/bin/python manage.py migrate --noinput
```

Reload the **accounting** app once from its Web tab. Use its established production settings/environment loader. The bridge migration adds only a signature replay-protection table; it does not copy or replace the accounting database.

With the HelloSama worker running, creating/enabling portal credentials in accounting automatically creates the company and its HelloSama owner within 60 seconds. First login also creates the owner immediately if it has not synced yet. The same account number and password work, with central verification; no password or hash is copied into HelloSama. The new owner completes their profile on first login and can then add company employees. Password changes and disabled status propagate; disabled companies lose access for both owner and employees.

## 6. Create the administrator and start the worker

```bash
cd /home/Samatours2026/HelloSama
.venv/bin/python manage.py create_ceo --username sama.admin --email YOUR_ADMIN_EMAIL --first-name YOUR_FIRST_NAME --last-name YOUR_LAST_NAME
```

The password is prompted privately. Use **People & access** to add Sama sales/accounting users. Company owners come from accounting.

Create this always-on task:

```bash
bash /home/Samatours2026/HelloSama/deploy/worker.sh
```

The worker synchronizes accounts, delivers notifications, checks SMS delivery reports, receives new mailbox replies and expires quotes. An update changes `.release`; the worker exits so PythonAnywhere restarts it with the updated code. Confirm the task restarts after the first update.

The first IMAP connection starts at the latest existing mailbox UID and does not import old mailbox history. New replies are staged for CEO review. Email never approves a quotation. Attachments remain in IONOS for review and upload.

## 7. Verify on PythonAnywhere

```bash
cd /home/Samatours2026/HelloSama
.venv/bin/python manage.py check_readiness
.venv/bin/python manage.py check_connections --accounting --openai --email --sms
```

Connection checks do not send email/SMS, change accounting records or print credentials. Then complete [LIVE_TESTING.md](docs/LIVE_TESTING.md), including a controlled email/SMS delivery and browser-push test, before inviting clients. Local checks and GitHub CI do not prove that the production host can reach each provider.

## 8. Future updates: one command

```bash
bash /home/Samatours2026/HelloSama/deploy/update.sh
```

This pulls fast-forward only, installs locked dependencies, validates configuration, applies migrations, collects static files and reloads the portal. It never discards tracked changes or replaces private settings, uploads or database content. Take a database backup before production updates. Back up the database, encrypted uploads and private keys separately and test restoration.

## 9. Move to HelloSama.com after testing

Rename the HelloSama web app to the final domain using the Web tab; keep the same project and database. Configure its DNS using PythonAnywhere's exact instructions and enable HTTPS. Preserve IONOS MX, SPF, DKIM and DMARC records.

Update `PUBLIC_URL`, `DJANGO_ALLOWED_HOSTS` and the exact `PA_WSGI_FILE` path in `.env`, then run the update command. `PUBLIC_URL` supplies CSRF trusted origins and notification links. Existing SMS/email links to the temporary domain will need a redirect web app or a fresh notification; plan that transition before removing the temporary address. Browser push subscriptions belong to the old origin and must be enabled again on the new domain.

Sources: [custom PythonAnywhere subdomains](https://help.pythonanywhere.com/pages/CustomPythonAnywhereSubdomains), [Django deployment](https://help.pythonanywhere.com/pages/DeployExistingDjangoProject/), [changing a web app domain](https://help.pythonanywhere.com/pages/UsingANewDomainForExistingWebApp).

## Account creation and request files in this release

Install the updated accounting companion as described above when deploying this release. Sama CEOs can then use **Company accounts → Create company owner** in HelloSama with the accounting client code. A client record must exist in accounting first, but enabling its portal login can be done from either dashboard. The same code/password works in both; existing logins require their current password and are never silently reset.

Every company user must upload a passport copy before starting a request. This requirement is built in; an old `REQUIRE_PASSPORT_COPY=False` environment line no longer disables it and can be removed. Local showcase users receive fictional placeholder PDFs; do not copy demo uploads to production. The new **Files & documents** request tab shares the existing encrypted private storage and needs no extra public media mapping.

## Activating notifications after the initial deployment

Follow [ACTIVATE_NOTIFICATIONS.md](docs/ACTIVATE_NOTIFICATIONS.md) for exact server settings, provider checks, worker setup, controlled deliveries and switching to live recipients.
