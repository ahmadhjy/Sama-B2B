# Deploy HelloSama on PythonAnywhere

HelloSama is a separate web app, virtual environment and PostgreSQL database. Keep the accounting app and its existing database in place. These instructions assume a paid custom plan with another web app and an always-on task slot.

## 1. Repository and private configuration

After the GitHub repository URL is available, push this **HelloSama folder** as its own repository. Never push `.env`, `.demo-access.txt`, local databases, uploads or backups. The accounting bridge is also included in this repository under `integrations/accounting/`.

Clone the new repository on PythonAnywhere, for example to `/home/YOUR_USERNAME/HelloSama`. Use Python 3.12, or set `PYTHON_BIN` to a supported version of Python 3.10 or later on your plan.

Run:

```bash
cd /home/YOUR_USERNAME/HelloSama
bash deploy/update.sh
```

On the first run this creates `.venv` and a private `.env` with generated application, encryption, accounting-integration and web-push keys. It stops at configuration validation until PostgreSQL settings are supplied. Edit `.env` in PythonAnywhere's Files editor, or with `nano .env`.

**Your two requested secret fields are:**

```dotenv
OPENAI_API_KEY=your-replacement-OpenAI-project-key
EMAIL_HOST_PASSWORD=the-password-for-info@hellosama.com
```

These values stay on the server. They are not JavaScript settings and must not be entered into GitHub files. Use a dedicated OpenAI project/key for this portal. The earlier key pasted in chat should be replaced. Do not use the main IONOS account password.

Fill in these connection fields:

```dotenv
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=hellosama.com,www.hellosama.com
PUBLIC_URL=https://hellosama.com
DB_NAME=your_separate_hellosama_database
DB_USER=your_postgresql_user
DB_PASSWORD=your_postgresql_password
DB_HOST=your_postgresql_host
DB_PORT=your_postgresql_port
DB_SSLMODE=prefer
ACCOUNTING_BASE_URL=https://your-accounting-domain
EMAIL_HOST_USER=info@hellosama.com
EMAIL_HOST=smtp.ionos.com
EMAIL_PORT=587
BUSINESS_EMAIL=info@hellosama.com
IMAP_HOST=imap.ionos.com
```

Use the exact PostgreSQL host/port from your Databases tab; PythonAnywhere can use a non-default port. Create a separate database; do not point HelloSama at the accounting database. Set SSL mode according to the database host's requirements. Preserve `DATA_ENCRYPTION_KEY` permanently; losing it means losing access to existing encrypted passport information and files.

Enable each external service when its connection is ready:

```dotenv
AI_ENABLED=True
EMAIL_ENABLED=True
IMAP_ENABLED=True
```

The API key alone does not confirm billing/model access. The monthly application allowance is capped at $20 and may be configured lower. External usage of the same OpenAI key/project is outside HelloSama's meter. SMS remains disabled.

## 2. Create the new web app and database

In PythonAnywhere's Web tab, add a **new** manually configured Python web app for `hellosama.com`. Select the same Python version used by the virtual environment.

Set:

- Source directory: `/home/YOUR_USERNAME/HelloSama`
- Working directory: `/home/YOUR_USERNAME/HelloSama`
- Virtualenv: `/home/YOUR_USERNAME/HelloSama/.venv`
- Static mapping `/static/` → `/home/YOUR_USERNAME/HelloSama/staticfiles`

**Do not create a `/media/` or `/private_uploads/` static mapping.** Uploaded documents are encrypted and only downloaded through signed-in, permission-checked views.

Copy the exact new web app WSGI path into `PA_WSGI_FILE` in `.env`. It normally looks like `/var/www/hellosama_com_wsgi.py`; use the path actually shown by PythonAnywhere. Never use the accounting app's WSGI path.

Run `bash deploy/update.sh` again. It applies HelloSama migrations, collects static files, checks deployment settings, and generates `deploy/generated_wsgi.py`. On first setup, paste this generated content into the **new HelloSama** WSGI file in the Web tab. Subsequent updates manage/reload only a file bearing the HelloSama marker. Existing, unmarked WSGI files are preserved.

Configure the domain DNS using PythonAnywhere's exact instructions for that web app and enable its HTTPS certificate. Keep IONOS MX/mail records intact when changing website DNS. Verify SPF/DKIM/DMARC mail authentication before live sending.

## 3. Connect the accounting system

From the HelloSama directory:

```bash
.venv/bin/python deploy/install_accounting_bridge.py /home/YOUR_USERNAME/YOUR_ACCOUNTING_PROJECT
```

This copies the `hellosama_bridge` app and adds exactly one app registration and one URL registration to accounting. Review/commit those additions in the accounting repository as part of its next deployment so they are not lost on accounting updates.

Copy `ACCOUNTING_SHARED_SECRET` from HelloSama's private `.env` into the accounting project's **root `.env`** under the name:

```dotenv
HELLOSAMA_SHARED_SECRET=the-same-integration-secret
```

The existing accounting settings load that root `.env`. If you instead use a production environment loader, make sure it loads this value for both accounting's web process and management commands. Keep the file private (`chmod 600 .env`). No user passwords are copied between applications.

Using the accounting virtual environment, run its migrations and reload the accounting web app. Use its existing deployment process after committing the bridge. The additional migration creates only a short-lived signature replay-protection table.

HelloSama automatically synchronizes company accounts every 60 seconds while the worker is running. A company's first sign-in also provisions it immediately. Changes to company account names and enabled status synchronize; password changes are verified centrally, and primary sessions are invalidated within the 60-second status window. Company employees have individual HelloSama logins tied to the centrally enabled company. They do not get duplicate financial accounts.

## 4. Create your Sama administrator

```bash
.venv/bin/python manage.py create_ceo --username sama.admin --email YOUR_ADMIN_EMAIL --first-name YOUR_FIRST_NAME --last-name YOUR_LAST_NAME
```

The command privately prompts for a password. It does not print or store it in a text document. Sign in and create Sama sales/accounting users through **People & access**. Company accounts come from accounting.

## 5. Start the background worker

Create an always-on task in PythonAnywhere:

```bash
bash /home/YOUR_USERNAME/HelloSama/deploy/worker.sh
```

The worker delivers notifications, synchronizes accounts, receives new mailbox correspondence and expires quotations. It avoids overlapping workers. Web conversations refresh every 20 seconds when idle; unsent message text is preserved by showing a refresh prompt instead.

A deployment updates `.release`; an already-running worker detects it and exits so PythonAnywhere's always-on supervisor restarts it with the updated code. Confirm the task resumes after the first update. If running manually, restart it manually. A scheduled `manage.py portal_worker --once` can be used for diagnostics, but hourly schedules will delay notifications and provisioning, so use an always-on slot for the intended experience.

The first successful IMAP connection establishes a starting point and does **not** import your existing mailbox history. New replies appear in **Incoming email** for CEO review. Email attachments remain in IONOS for review before upload. Email is never an approval mechanism.

## 6. Updates: one command

After changes are pushed to GitHub:

```bash
bash /home/YOUR_USERNAME/HelloSama/deploy/update.sh
```

It pulls using fast-forward only, installs locked dependencies, validates deployment settings, applies migrations, collects static files and requests a reload. It never resets/discards local tracked changes. Private configuration, uploaded files and database data are preserved. If you use another virtualenv path, set `VENV_PATH` consistently for the update and worker scripts.

## 7. Backups and recovery

Before production updates, take a PostgreSQL backup using your existing backup procedure. Back up the **HelloSama database**, `private_uploads/`, and the private encryption/configuration keys. Keep the keys separate from the data backup, restrict access and test restoration. No automatic data deletion/retention job is enabled until the business approves its retention policy.

If an update fails, the script stops. Review the error before restarting. Do not run data-wipe commands. Database schema rollback is migration-specific; restore a tested backup if needed. The repository preserves quote, approval and audit history.

## 8. Verify before opening to clients

Run `.venv/bin/python manage.py check_readiness`, inspect **Operations**, and follow [docs/LIVE_TESTING.md](docs/LIVE_TESTING.md). Configure a test company and use a controlled mailbox/phone before inviting real customers. SMS integration is postponed until provider documentation is available.

Sources used for hosting behavior: [PythonAnywhere Django deployment](https://help.pythonanywhere.com/pages/DeployExistingDjangoProject/), [reload via WSGI file](https://help.pythonanywhere.com/pages/ReloadWebApp/), [background management commands](https://help.pythonanywhere.com/pages/DjangoManagementCommands/).
