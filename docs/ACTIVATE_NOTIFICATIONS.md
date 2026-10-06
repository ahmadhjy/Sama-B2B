# Enable HelloSama email and SMS on PythonAnywhere

This is a server configuration step. Pulling from GitHub does not copy your local `.env` or activate notifications. Edit `/home/Samatours2026/HelloSama/.env` in PythonAnywhere Files. Keep secrets out of screenshots and GitHub.

## 1. Add the private settings

Keep existing passwords if already entered. Replace the placeholder sender and phone with your provider-approved sender and your own test mobile in international format. Do not assume the SMS portal display name is an approved sender.

```dotenv
PUBLIC_URL=https://hellosama-samatours2026.pythonanywhere.com
EMAIL_HOST=smtp.ionos.com
EMAIL_PORT=587
EMAIL_HOST_USER=info@hellosama.com
EMAIL_HOST_PASSWORD="YOUR_IONOS_MAILBOX_PASSWORD"
BUSINESS_EMAIL=info@hellosama.com
EMAIL_ENABLED=True
IMAP_ENABLED=False

SMS_BASE_URL=http://smppa3.broadnet.me:8080/websmpp
SMS_USERNAME="YOUR_SMS_API_USERNAME"
SMS_PASSWORD="YOUR_SMS_API_PASSWORD"
SMS_SENDER_ID=YOUR_APPROVED_SENDER
SMS_ENABLED=True
SMS_ALLOW_HTTP=True

NOTIFICATION_TEST_MODE=True
NOTIFICATION_TEST_EMAILS=info@hellosama.com
NOTIFICATION_TEST_PHONES=YOUR_TEST_NUMBER_WITH_COUNTRY_CODE
```

If the provider supplies a working HTTPS API endpoint, use that exact URL and set `SMS_ALLOW_HTTP=False`. The supplied GW3N API uses HTTP; `SMS_ALLOW_HTTP=True` permits unencrypted API transport. Portal OTP does not protect API requests. SMS credentials must belong to this API endpoint, which is separate from the browser dashboard URL.

Email sending uses authenticated SMTP with TLS. `IMAP_ENABLED=False` leaves incoming-mail import off; outgoing notifications still work. You can enable IMAP later with `IMAP_HOST=imap.ionos.com`. Never replace your IONOS MX records to activate the portal.

The test allowlists restrict delivery to the specified recipients. Add your own second email separated by a comma if you want to test a client email too. These are allowlists, not forwarding rules: a user must have that actual email/mobile in their profile. Push is suppressed while test mode is on.

For example, replace this illustrative number with your own international mobile number:

```dotenv
NOTIFICATION_TEST_MODE=True
NOTIFICATION_TEST_PHONES=+96170123456
```

Use the country code with no spaces. Multiple numbers are comma-separated. Keep the same number in the intended approver's profile. This is the existing Broadnet **SMS** integration, not WhatsApp; WhatsApp credentials or a WhatsApp account are not required.

## 2. Check provider access without sending

In the HelloSama Bash console:

```bash
cd /home/Samatours2026/HelloSama
.venv/bin/python manage.py check_connections --email --sms
```

This checks SMTP and IMAP login plus SMS balance. It sends no messages and prints no credentials. A successful SMS balance check does not prove the sender is approved; the delivery test below verifies that.

If email authentication fails, verify the mailbox password (not the main IONOS account password). If SMS fails, verify the endpoint, credentials, HTTP setting and provider account access. Do not repeatedly send tests while the outcome of a previous send is unknown.

## 3. Update the portal and start its background worker

After the application changes are on GitHub:

```bash
bash /home/Samatours2026/HelloSama/deploy/update.sh
```

Reload the HelloSama web app from the Web tab if automatic reload is not configured. In PythonAnywhere **Tasks → Always-on tasks**, add this command, or restart the existing HelloSama task rather than adding a second one:

```bash
bash /home/Samatours2026/HelloSama/deploy/worker.sh
```

The worker delivers messages and checks delivery reports. Web-app reload alone does not start it. Restart the worker after editing `.env` so it picks up the new settings. The update script also signals a running worker to restart, but check that the always-on task actually comes back up.

```bash
cd /home/Samatours2026/HelloSama
.venv/bin/python manage.py check_readiness
```

Confirm email and SMS are enabled and the worker heartbeat is recent. Operations shows notification delivery results. Existing `disabled`, `test_blocked` or `skipped` records are not automatically replayed when settings change. If an old backlog exists, leave test mode on while the worker processes it before turning on live recipients.

## 4. Test with a controlled company request

Use a designated test company linked through accounting and users you control. The built-in `DEMO-` showcase companies intentionally suppress external notifications and cannot prove delivery.

1. Create a new request. The business mailbox should receive a new-request email.
2. As Sama sales, take it over and send a quotation. Check the allowed client recipient's email; their profile must have email notifications selected.
3. Submit the quote for approval. Each required approver whose mobile is allowlisted should receive one SMS with a portal link. Use your test number in the intended approver's profile.
4. Check Operations. Email `sent` means SMTP accepted it; confirm it actually arrived in the inbox or spam folder. SMS `submitted` means provider acceptance; wait for `delivered` and verify the phone received it.
5. Follow the SMS link and sign in as its intended approver. It must open the request; approving remains a separate action inside HelloSama.
6. Complete the approvals and confirm Sama sees the results and email update. Do not create a real supplier booking merely to test notifications.

If SMS is `uncertain`, inspect the provider's records before trying again. A timeout can happen after the provider accepted a message. If `failed`, review the error, sender approval, balance and phone format. A missing worker heartbeat means queued messages will wait.

SMS is specifically for pending quotation approvals, not every chat message. Email covers new business requests, quotations, approval events and the other events configured in the existing workflow. In-app notifications continue independently of email and SMS delivery.

## 5. Open notifications to clients

After controlled deliveries succeed and the test backlog is processed, set:

```dotenv
NOTIFICATION_TEST_MODE=False
```

Reload HelloSama and restart its worker. New eligible events can now reach real recipients. Existing push subscriptions also become eligible when leaving test mode; only users who already opted in have subscriptions. Keep email/mobile profiles accurate. Incoming email is a separate optional step and never approves quotations.

No custom-domain change is needed for this setup. Links will use the temporary HTTPS portal address until `PUBLIC_URL` is changed during the later domain move.
