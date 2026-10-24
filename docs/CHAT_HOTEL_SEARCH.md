# Conversational trip planning and hotel search

Service choices, cabins, hotel ratings, meal plans, cancellation preferences and offers use buttons or cards in the chat. Route, date, airline, transfer and note replies use the chat composer. Calendars remain optional. Insurance birth-date replies are handled privately by the browser and quote endpoint: they do not become chat messages or OpenAI input.

Shared city, country, dates and passenger counts are reused between services. Hotel rooms are allocated with short choices for each room and child age. The review and explicit **Send request to Sama** action remain the final submission step.

## What a hotel refinement does

1. OpenAI returns a validated structured hotel-search intent, separately from conversational text. A simple rule-based fallback can interpret initial preferences if the model is unavailable.
2. The application merges changed filters with saved preferences. Null means unchanged; empty names, an empty rating list, or `any` clears the corresponding filter. Reset clears all hotel filters.
3. Landmarks, districts, airports and stations are matched against IRIX's locations in the chosen hotel city. Ambiguous matches become selection buttons. Unmapped places require clarification rather than an unfiltered city search. Coordinates come from the provider, never the model or client.
4. IRIX's asynchronous destination search checks city/geographic inventory rather than a fixed first 100 hotel IDs. Geographic radii are in kilometres. “Near” defaults to 1 km; distances displayed are straight-line distances, not walking distances.
5. Hotel name and rating filters are sent to IRIX. Selected room packages are checked again against meal and refundability requirements. Unknown cancellation terms do not satisfy “refundable only.” Missing coordinates do not satisfy proximity filters.
6. Up to six distinct hotels are displayed with supplier prices, stars, address, room/meal/cancellation facts and available room details. **More matching hotels** excludes properties already shown in the current unexpired search. Changing criteria expires earlier hotel cards and clears the hotel selection while preserving other services.

## Boundaries and recovery

Searches, pages, offer loads and polling are bounded. The interface says when additional matches may be available; distance sorting means nearest among checked matches. This is not a claim that every property or offer in a destination has been inspected.

Preferences such as quiet rooms, sea views or special facilities that are not implemented as verified filters are saved explicitly for Sama to verify. They are not presented as guarantees. A supplier error or missing coordinates is reported separately from a completed search returning no matching offers. Existing cards are never relabelled as fresh results after a failed refinement.

Selections are preferences only. No new booking or payment endpoints are called. Supplier result tokens remain transient and are excluded from browser responses and stored offer references. Existing ownership, draft locking, quote expiry, approval and accounting rules still apply.

## Deployment and checks

Use the existing HelloSama update script. No new credentials, environment variables or database migrations are needed for this change. The existing IRIX `read:mapping` and `read:hotels-search` access is used.

Regression coverage is in `portal/test_hotel_search.py`, with the existing provider, concierge, submission, privacy and concurrency suites. Browser checks should include typing a route and dates, refining a hotel area/rating/meal, resolving an ambiguous location, requesting more options, selecting other services, private insurance dates, reload, review and submission.
