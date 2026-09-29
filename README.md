# HelloSama

An English B2B travel portal for Sama Tours. Separate Django application and PostgreSQL database, connected to the existing accounting system through a signed integration for shared company logins and read-only financial records.

## Start here

- **Private credentials:** `.env` — edit `OPENAI_API_KEY` and `EMAIL_HOST_PASSWORD`. This file is excluded from Git.
- **Hosting instructions and one-command updates:** [DEPLOY_PYTHONANYWHERE.md](DEPLOY_PYTHONANYWHERE.md).
- **Permissions and product behavior:** [docs/OPERATING_GUIDE.md](docs/OPERATING_GUIDE.md).
- **Integration and service details:** [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md).
- **Live acceptance checks:** [docs/LIVE_TESTING.md](docs/LIVE_TESTING.md).
- **Local demo accounts and screenshot walkthrough:** [docs/DEMO_GUIDE.md](docs/DEMO_GUIDE.md).

## Local development (Windows)

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.lock
.\.venv\Scripts\python deploy/configure.py --local
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py seed_demo
.\.venv\Scripts\python manage.py runserver 127.0.0.1:8765
```

Open `http://127.0.0.1:8765`. Demo accounts are fictional and the seed command prints a newly generated local-only password. It refuses to run in production or with external services enabled. Demo users are not created by deployment. If this workspace was initialized during development, `.demo-access.txt` holds the local demo login details and is excluded from Git.

## Tests

```powershell
.\.venv\Scripts\python manage.py test portal --noinput
```

Tests mock external services and use a separate temporary test database. For browser checks, install `requirements-dev.txt`, run `python manage.py seed_showcase`, then run `python scripts/browser_smoke.py` with the local preview running. Browser checks use only fictional demo accounts, including the three showcase approvers. Screenshots go to ignored `test-results/`.

GitHub Actions runs the same suite on PostgreSQL, including concurrent claiming, approvals and budget reservations. Those three tests are intentionally skipped with SQLite; a SQLite pass is not a claim that PostgreSQL row-lock behavior was exercised locally.

## Application modules

- `portal/models.py`: companies, users, drafts, requests, conversations, quote versions, approvals, private files, outbox, AI usage, audit events.
- `portal/workflow.py`: transactional claiming, quote versions, approval snapshots, booking transitions.
- `portal/permissions.py`: company, role, ownership and document access.
- `portal/accounting.py`: signed company authentication and financial connections.
- `portal/ai.py`: public travel research and structured request drafts; no authority to approve or book.
- `portal/notifications.py`, `portal/mailbox.py`: notifications, durable delivery queue, reviewed incoming correspondence.
- `integrations/accounting/hellosama_bridge/`: the restricted accounting companion app.
- `deploy/`: repeatable setup and updates.

## Current service boundaries

SMS approval alerts use the Broadnet GW3N API with tracked submission and delivery status. Credentials and an approved sender ID are configured privately. Initial deployments restrict external notifications to test recipients. OpenAI, IONOS, web push and the production accounting connection require their configuration and live verification. No real travel is booked automatically. A Sama specialist confirms the supplier booking in the portal after all approvals.

The portal is not a flight reservation engine. Public web search is used for suggestions with sources; the salesperson verifies fares and availability. There is no separate financial ledger in HelloSama.
