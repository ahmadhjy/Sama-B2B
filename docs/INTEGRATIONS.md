# Integrations and trust boundaries

## Accounting

HelloSama has its own database and credentials for staff/company employees. The company's primary login is verified by accounting on every login; HelloSama stores an unusable local password for that account. An opaque HMAC identity version detects central password changes without transferring a password hash. The company's active status is checked with a maximum 60-second cache; if a refresh fails, access fails closed.

The companion bridge implements POST-only `/hellosama-api/authenticate/`, `/companies/`, `/status/`, `/owner-account/`, `/finance/` and `/file/`. Each server-to-server request has a timestamp, random nonce, body digest and HMAC-SHA256 signature. Used nonces are persisted briefly to reject replay. Keep the shared key in each app's private environment. Use HTTPS in production. Do not expose the existing broad ERP REST scaffold to client browsers.

Financial endpoints first resolve an active company portal profile and scope all object queries to its client. Only client-visible selling data is serialized. Costs, suppliers, internal notes and arbitrary ERP object serializers are excluded. Attachments are fetched through the scoped service and then the HelloSama user's financial permission is checked. Totals from the existing accounting helpers are labelled in USD; original line/schedule currencies are shown separately.

Automatic account creation uses a 60-second worker sync and immediate provisioning on first successful login. This avoids a slow external call during accounting client creation. If sync is down, the Operations heartbeat identifies it. First-time company provisioning is idempotent. Disabling a company blocks all its HelloSama users; an individual employee's access is managed in HelloSama.

The narrowly scoped `owner-account` action lets a signed HelloSama server request create portal credentials for an existing accounting client code. The HelloSama screen and service require the Sama CEO role. Accounting locks the client record, checks password rules and username conflicts, and returns only the normal company identity response. It does not create financial client records, reset existing passwords, re-enable disabled accounts, or accept arbitrary user/financial fields. Connecting an existing login verifies its current password. Repeating the same request after a lost response reuses that login. HelloSama records the administrator action without credentials. A background sync and simultaneous first login share the same single primary owner record.

Both dashboards therefore manage the same primary identity, with accounting as the credential authority. Company employees and profile details are managed in HelloSama. Company password resets and disabling continue to originate in accounting. Update the companion on the accounting host when deploying this release; updating HelloSama alone does not install the new action.

## OpenAI

The backend calls the Responses API with GPT-6 Luna, public `web_search`, `store=false`, a maximum of two tool calls and a 1,500-token output bound. Context is limited to recent travel conversation text. The summary uses strict structured output and then goes through Django form validation and explicit user submission. No model output is treated as an application instruction or permission decision.

The reviewed price basis is $0.10 per million input tokens / $0.50 per million output tokens at normal context, long-context multipliers when applicable, and $0.01 per web search call. A $0.35 reservation covers the allowed call's full-context upper bound plus searches and a cache-write margin. Completed usage is reconciled conservatively, without cache discounts. Model changes are blocked until pricing/budget assumptions are reviewed. Provider pricing changes also require review. Application usage limits do not cover other applications using the same key.

Sources: [model capabilities](https://developers.openai.com/api/docs/models/gpt-6-luna), [pricing](https://developers.openai.com/api/docs/pricing), [web search](https://developers.openai.com/api/docs/guides/tools-web-search), [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

## IONOS

SMTP: `smtp.ionos.com:587`, STARTTLS, authenticated with `info@hellosama.com` and its mailbox password. IMAP: `imap.ionos.com:993`, TLS. Receiving reads new INBOX messages without marking them read or deleting them. Sender headers are not trusted as proof of identity; messages are staged for staff review. On first connection or mailbox UID-validity reset, the worker starts from the latest existing UID and imports subsequent replies only.

The notification outbox is saved in the same database transaction as the business event. Each delivery has a unique key. Unexpected/unknown send outcomes are not automatically retried; a CEO can review provider records and authorize a retry through Operations. A failed notification never reverses an already-recorded approval.

Reference: [IONOS official mail server settings](https://www.ionos.com/help/email/general-topics/ionos-mail-server-details-for-imap-pop3-and-smtp/).

## Web push

VAPID keys are generated locally during private configuration setup. Private pages are never cached by the service worker. Push subscriptions are scoped to a signed-in user; validated browser-provider hostnames prevent arbitrary URL submission. Disabling a user/company or losing request access prevents a queued notification from being sent. Device pushes contain only a generic notification and authenticated portal link. Browser support, user consent and delivery vary by device.

## SMS

The Broadnet GW3N guide supplied on 29 September 2026 documents `/websmpp/websms` (POST form fields `user`, `pass`, `sid`, `mno`, `type=1`, `text`), `/websmpp/websmsstatus` (`respid`) and `/websmpp/balanceReport`. Credentials are sent in a POST body, never added to URLs, source code or logs. The approved sender ID is a required configuration value.

Submitting a quotation for approval creates one SMS delivery per designated approver. Alerts contain the requester's name and a short authenticated `/n/<notification-id>/` link. Login preserves that destination; other users cannot open the recipient's notification. Stale, superseded or already-decided approval alerts are skipped. A numeric provider response means **submitted**, not delivered. The worker polls the documented status endpoint and records `DELIVRD` separately. Known provider rejections are marked failed; timeouts/unknown submission results are uncertain and never automatically resent. Unsigned provider callbacks are not accepted.

The supplied host is `http://smppa3.broadnet.me:8080/websmpp`. HTTPS checks failed during local verification. This requires an explicit `SMS_ALLOW_HTTP=True` setting; it does not disable certificate checking or silently downgrade HTTPS. Portal OTP does not encrypt this separate HTTP API connection. Prefer a provider-confirmed HTTPS endpoint when available.

`NOTIFICATION_TEST_MODE=True` restricts email and SMS to `NOTIFICATION_TEST_EMAILS` and `NOTIFICATION_TEST_PHONES`, and suppresses push delivery. Demo-company records never send external notifications. SMS remains off until sender/recipient delivery testing is complete. Provider authentication and balance were verified locally; actual handset delivery requires a designated test number.
