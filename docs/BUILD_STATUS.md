# Build and validation status

Prepared locally on 28 September 2026. The application has not yet been deployed to PythonAnywhere or connected to live providers.

## Included

- Separate Django portal with the existing Sama branding and responsive English interface.
- Accounting-backed company access, company user management and cross-role approval permissions.
- Private request conversations, sales queue and assignment, attachments and progress updates.
- Versioned PDF quotations, unanimous approval tracking and booking confirmation.
- Public travel research assistant, editable summaries and a manual request path.
- Read-only accounting views through the included signed accounting bridge.
- Email outbox, incoming-email review, opt-in browser push and operational history.
- Private configuration, encrypted passport numbers and uploads, PostgreSQL deployment configuration and one-command updates.

SMS delivery is postponed. Incoming email is staged for CEO review before it is published into a request conversation; email does not authorize approvals or bookings.

## Verified locally

- 52 HelloSama automated tests passed.
- 18 accounting-side tests passed, including the new bridge and the existing client portal.
- A browser journey passed from request creation through sales assignment, quotation, two approvers and booking confirmation.
- Desktop and mobile layouts were inspected; the browser journey reported no page JavaScript errors or horizontal overflow.
- Production Django configuration checks, migration consistency and deployment script syntax checks passed.
- Repository exclusions cover credentials, databases, documents, local demo access and test artifacts.

Three PostgreSQL concurrency tests are included and run in the GitHub Actions configuration. They are skipped on the local SQLite database and have not yet been run against PostgreSQL. Production configuration validation does not establish a database connection or prove live delivery.

## Pending live setup and verification

1. Supply the new GitHub repository URL, push the source and run its PostgreSQL CI checks.
2. Provision the new PythonAnywhere web app, separate PostgreSQL database and always-on worker.
3. Enter the replacement OpenAI project key and IONOS mailbox password in the server's private `.env`.
4. Deploy the accounting bridge, share its private integration secret and verify company login and financial visibility.
5. Configure domain routing and HTTPS, preserving IONOS mail records.
6. Test OpenAI billing/model access, public research, email sending/receiving and browser push with controlled accounts.
7. Complete the scenarios in [LIVE_TESTING.md](LIVE_TESTING.md) before inviting customers.

See [the deployment guide](../DEPLOY_PYTHONANYWHERE.md) for the exact setup and update commands.
