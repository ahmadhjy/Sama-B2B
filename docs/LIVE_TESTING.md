# Live acceptance checks

Use a fictional test company first. This checklist is for the configured PythonAnywhere environment; it is not a claim that external services have already been tested.

## Hosting and accounts

- HTTPS works on the intended HelloSama domain and sessions remain signed in.
- The new database is separate from accounting. `check --deploy` passes.
- The worker heartbeat advances, and its last sync shows no error.
- Create/enable a company in accounting. It appears in HelloSama within 60 seconds and signs in with the same account/password.
- Add a second client record in accounting without enabling its portal login. From HelloSama as Sama CEO, create its owner using that client code. Check the same credentials in both portals and verify the correct financial records. Repeat sync: no duplicate owner/company appears.
- Connect an existing portal login using its current password; a wrong password must not reset it. A missing client code, disabled login or duplicate local company must produce a clear error without creating a partial account.
- Change its password in accounting. The old password no longer works; an existing primary session is invalidated within 60 seconds.
- Disable the accounting portal account. Both the primary user and company employees lose access within the verification window.
- Create a company user with first name, last name, password. Complete their profile at first sign-in, including a passport copy. Starting or submitting a request without that copy must be blocked.
- A second company cannot access the first company's request, file, quote PDF or financial record by URL.

## Requests and approvals

- A draft is private and does not appear in the sales queue before submission.
- Two Sama sales users attempt to take over the same request. Only one succeeds.
- The assignee can view the profile/documents; the other salesperson cannot.
- CEO reassigns the request; the previous assignee loses access.
- Both parties upload a PDF and an image. Check Files & documents: images, PDFs, quotations and the requester passport appear in their groups. Open a preview, download a file, and use View in conversation to return to its message. Other companies, unassigned sales and unauthorized approvers must not see restricted files.
- Internal notes never appear to the client. Approvers cannot access private passport files solely through approval permission.
- The quote appears in the conversation, and its PDF accurately matches the version and price.
- Submit to two approvers of different roles. First approval leaves it pending. Second approval makes it Approved.
- Rejection, revised quote, expiry and disabled-approver cases behave as documented.
- Starting booking requires all approvals. Confirmation requires the supplier booking reference.

## Connected services

- Read a company statement, invoice and receipt against the accounting system; confirm totals/currencies and file scope.
- Send a travel question using the configured OpenAI project. Confirm account billing/model access, current public sources, safe unavailable handling and editable summary generation.
- Lower the AI allowance temporarily to test the cutoff; manual request submission still works. Restore the intended allowance afterward.
- Generate a new request and verify the business mailbox notification. Verify a quote and approval email to controlled test recipients.
- Reply to a portal notification; see it in Incoming email, review it, then add it to the proper conversation. Confirm it cannot approve a quote.
- Opt in to push on desktop/Android, and on an installed Home Screen app on iPhone/iPad. Denying permission must not prevent portal use.
- Review uncertain deliveries and only retry after checking provider records.
- In test-recipient mode, submit a quotation to approved test numbers. Each approver receives one SMS with a portal link; a numeric provider response shows Submitted until a delivery report confirms Delivered.
- Follow the SMS link while signed out: signing in returns to the correct request. A different user's account cannot open that notification.
- Approve or supersede a quotation before its queued SMS sends; the obsolete alert must be skipped.
- Keep test recipients restricted until these checks pass; remove restrictions deliberately when opening to real companies.

## Operations

- Run the one-command update and confirm web app reload, worker restart, and preserved uploads/configuration/data.
- Back up and restore the test database and encrypted documents with the saved encryption key.
- Confirm mandatory passport copies and agree self-approval and data-retention settings before inviting real clients.
- Confirm the provider-approved SMS sender, transport, balance and delivery reports from PythonAnywhere itself.
