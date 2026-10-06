# Using HelloSama

## Access and people

Creating/enabling a client portal account in accounting gives that company a linked HelloSama account. The existing account number and password are used centrally. Passwords are never displayed or stored in readable form. First and last name, email, mobile with country code, passport number/expiry and nationality must be complete for company users. A passport copy (PDF, JPG or PNG) is mandatory before a company user can start a request. Missing details or a missing copy lead to the profile completion screen; Sama staff do not need passport documents.

Sama CEOs can also open **Company accounts → Create company owner** in HelloSama. Enter an existing accounting client code, the owner's first and last name, and choose whether to create a new shared login or connect an existing one. New logins are created in accounting immediately and linked back to HelloSama. Existing logins require their current password and are never overwritten. The company name is read from accounting, so its statements, invoices and receipts use the correct client. Add a new customer's client record in accounting first; their portal login can then be created from either dashboard. This screen requires the accounting connection to be configured. A login provisioned by the background sync is reused, not duplicated.

Company administrators create team users with first name, last name and password. Login IDs are generated automatically and displayed after creation. Optional details can be filled by the administrator or completed by the user at first sign-in. Share initial credentials through your approved private channel. Users can change individual passwords. The primary company password remains managed by accounting.

Roles:

- Company administrator: manages company users, oversees company requests, and sees financial records.
- Sales/requester: creates requests and follows their own conversations.
- Company accountant: sees company financial records. Request access comes only from ownership of a request or an assigned approval.
- Sama CEO: oversees all companies, requests, approvals and financial records; manages staff, reassigns work and reviews email.
- Sama salesperson: sees minimal unassigned queue summaries, claims a request and works only on assigned requests.
- Sama accounting: sees financial records; no general sales conversation access.

**Can approve quotations** is a separate checkbox on company users. The HR person or sales manager can use whichever base role fits their day-to-day access, with the checkbox enabled. Their job title alone does not grant approval. The main company administrator starts as an approver. All active designated approvers are required by default, including a requester who is also an approver; set `ALLOW_SELF_APPROVAL=False` to exclude the requester if that is the company's policy.

## From conversation to confirmed booking

1. Plan a trip with the assistant, or fill in the form directly. Drafts are private and are not in the sales queue.
2. Select **Review my request**. Check the route, dates, passenger breakdown and preferences. Budget is optional and the assistant never asks for it.
3. Submit the request. It receives a reference and enters Pending.
4. A Sama salesperson takes over. Their name appears in the conversation and the status changes to In progress.
5. Discuss details and attach files. Status updates appear as system boxes in the conversation. Messages are retained.
6. Sama prepares a quotation, including price/currency, details, inclusions, exclusions, terms and validity. The client can download its branded PDF.
7. The requester or company administrator submits that version for approval. The displayed approver list is saved against that version.
8. Each required person approves or rejects inside the portal. Progress is visible to relevant participants. A rejection requires a reason.
9. Only all approvals together produce Approved. Sama starts booking and later enters a supplier booking reference to confirm it.
10. Confirmed journeys can be closed; history remains available.

Quote revisions always create a new version and need fresh approvals. Expired quotes cannot start booking. A disabled or replaced approver never silently disappears: pending quotations must be revised/cancelled before removing that person's approval access. A user cannot record someone else's approval. Neither receiving an SMS/push nor opening a link counts as approval.

## Files and privacy

Both sides can attach PDF, JPG or PNG files, up to five files per message and 10 MB per file. These defaults intentionally exclude executable files and Office macros. Passport numbers, private traveller details and file contents are encrypted at rest by the application. Downloads require current permissions; there is no public uploads URL.

Open **Files & documents** within any request to see its images, documents and every quotation version. The requester's profile passport is included for authorized viewers. Files stay attached to their original chat messages, with a **View in conversation** link back to the message. Image previews and downloads use the same permissions, and private pages are not cached.

Mark traveller/passport attachments as private. Approvers do not automatically receive passport access. Sama internal notes are visible only to the current assignee and CEO. After reassignment, the previous salesperson loses request/file access.

## Notifications and correspondence

In-portal notifications are always available. Email and push require configuration and device permission. New requests notify the business mailbox; quotations and approval decisions notify participants. SMS approval alerts notify each required approver when a quotation is submitted. Device pushes contain a generic update message and a portal link rather than passport or payment information.

The CEO reviews new incoming mailbox replies before adding them to conversations. This avoids trusting a forged From address. The recorded conversation message identifies the email sender and staff reviewer. This first release deliberately uses reviewed incoming replies instead of automatic email impersonation. Attachments can be reviewed in IONOS and uploaded through the request interface.

Delivery status is visible in Operations. Uncertain delivery outcomes need a provider check before retrying, so an interrupted connection does not automatically create duplicate messages. Opt-in pushes are supported where the browser/device allows; on iPhone/iPad use the Home Screen app. In-portal notifications remain available even if device delivery fails.

## AI limits

The assistant uses public travel information and source links. It cannot reserve seats, guarantee prices, approve a quote or submit a request. Passport fields, attachments and financial records are not supplied to it. Known personal identifiers in typed chat are redacted before an API call; users should still keep all sensitive information in private profile/document fields.

The monthly allowance is shared across the entire application and capped at $20. The app reserves a conservative maximum per API call and reconciles completed calls from usage data. Timed-out calls retain their reservation because billing may have occurred. When the allowance is unavailable or a provider is down, the request form continues to work.

## Business defaults to review during live testing

- Passport copy, number, expiry, nationality, email and mobile are mandatory for company profiles.
- Requesters who are designated approvers may approve their own request unless disabled in configuration.
- All company approvers must approve each version; no majority rule or automatic bypass.
- PDF/JPG/PNG only, 10 MB per file, five per message.
- No automatic document/history deletion until the retention policy is agreed.
- Email, push and SMS active only when configured; initial staging notifications are restricted to test recipients.


## Client navigation and guided requests — October 2026

Company users now see Home and a direct New travel request menu entry. Company owners see Company requests and Company users; individual requesters retain My requests. Dashboard shortcuts open existing pages without changing permissions.

In New travel request, describe the trip in the chat, then select **Review my request** directly below the conversation. The assistant asks only for missing essentials, never asks for a budget, and keeps replies short. It collects departure city, destinations, dates/duration and adults/children/infants. Passenger breakdown and duration are preserved in the trip details field; total passengers includes infants.

The review button fills an editable form and brings it into view. Check it, fill required gaps and select **Submit request to Sama**. No request enters the queue until that final action. You can use **Fill in the form myself** at any time. The manual form remains available if AI is unavailable. Additional optional fields are collapsed to keep the main form focused. Generating again after editing asks before replacing trip edits and preserves private traveller details.

Existing requests now show brief next-step prompts for quotations, approvals and booking progress. The quotation prompt links directly to the quotation, including on mobile.

For email/SMS activation, see [ACTIVATE_NOTIFICATIONS.md](ACTIVATE_NOTIFICATIONS.md). Configuration and actual delivery must be checked separately; the app does not assume messages arrived merely because credentials exist.

## Saved trips, approvals and travel overview — 5 October 2026

- **Another trip** starts a separate private draft. Use the trip tabs to switch between them. Select **Save reviewed details** before switching after editing the form. This saves valid trip details; private traveller details and selected files must be submitted from the current form. **Close this draft** keeps it under **Closed drafts**, where it can be restored. Up to 12 drafts can be open.
- **Review & submit all open drafts** presents each trip for review. Complete every required field before submitting. They become separate requests together; an invalid form prevents the batch from being submitted. Use the individual trip form if you need to attach files at submission.
- If the assistant provides cited flight or hotel suggestions, **Choose this preference** puts the choice in your message box. Send it to include it in the conversation. It is a preference for Sama to verify, not a reservation or a live availability guarantee.
- **Company requests** can be searched by reference, trip, route, booking reference or requester name, and filtered by service, status and departure dates. **My personal requests** shows your own requests and opens a conversation alongside recent history.
- Open a request to download its summary or export its conversation as a PDF. Exports follow the same permissions as the conversation. Files remain in **Files & documents**. You can edit trip details before a quotation exists; after that, ask Sama for a revision in the conversation.
- Approval links open a focused review page. Check the amount, itinerary, terms and expiry before deciding. Every designated approver still needs to approve the current quotation. **Remind pending approvers** queues a reminder, limited to once per hour per request. Delivery depends on configured channels and the worker.
- **Travel overview**, available to company owners and the Sama administrator, lists confirmed trips by recorded dates: underway, leaving within seven days, or without a recorded return. It identifies the requester and party size, not each passenger's live location. Select active confirmed trips to post the same update to their portal conversations; closed trips remain read-only. A PDF overview and requester contact links are available.
- **People & access** supports name/email/login searches and role filters. **Accounting** supports date/search filters and CSV exports for statements, invoices and receipts; statement PDFs include the filtered entries. Account totals and running balances remain the values supplied by Sama Accounting.
- In the profile, choose passport expiry using separate **day, month and year** selectors. Nationality uses a country list; existing recorded values remain available when editing.

The login page's service labels do not create extra account types. Sign in using the same company or individual credentials and permissions as before.

On **Create a company owner**, **Login user name** means the accounting client code. **Company name** shows the saved name for an already connected company; for a new connection, Accounting confirms the name when the owner is created or connected. Company names continue to be managed in Sama Accounting. The **Account setup** selection controls whether to create a new shared login or connect an existing one.

See [the reference completion review](CLIENT_UPDATES_2026-10.md#completion-review--6-october-2026) for the remaining differences between the client's mockups and the implemented portal.
