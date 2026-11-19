# Knowledge screen: UX review and changes

**Date:** 2026-11-19

**Reviewed code:** `main` at `f623be6` (Knowledge alerts and the knowledge system review, #630). The "before" audit and its screenshots were taken on this commit. The changes below were verified on commit `776d5e9`, the first commit of the pull request.

**Scope:** the web app's Knowledge section (`web/src/features/knowledge/`) and the two API additions it needed. Chat, the conversation list, "Your data" and the sign-in flow were not changed.

**Method:** the full local stack (Postgres with pgvector, `setup`, `neuron-worker`, the API on Postgres with knowledge on, the stand-in sign-in provider and the web app). It was driven in Chromium with Playwright at 1280 px and 390 px, in light and dark, before and after the change. The references were the project and file views of mature AI products (Claude's Projects): a list of containers, then one container's own page.

## What the review found

| # | Finding | Effect |
|---|---|---|
| 1 | The create form (name, two radio paragraphs, language, help text) was always open above the list | It took the first screen on every visit, and the bases were below the fold |
| 2 | Bases and their documents were on one card: opening a base showed its documents, then its sharing, under the whole list | No page for a base, a weak selected state, and long scrolling with several bases |
| 3 | No search, sort or filter for bases or documents | Hard to use past a handful of items |
| 4 | At most 100 documents shown ("Showing the first 100 of N"), with no way to see the rest | Documents after the 100th could not be seen or deleted in the UI |
| 5 | No dates, no document counts, no file type | Little to tell items apart or see what changed |
| 6 | Delete one document at a time only | Clearing a base meant two clicks per file |
| 7 | No way to download a document, though the API serves the file | A user could not get back what they uploaded |
| 8 | Inline "Confirm delete" buttons replaced the row's controls; rename was an inline form in the row | Easy to misread; no room to explain what a delete does |
| 9 | A web page's address was not shown, and the add-page field was always visible | Pages showed only their title |
| 10 | Empty state was one line of grey text; errors were plain red text | Not much guidance on what to do next |

What already worked was kept: the wording of every message, error and failure code; the privacy notice before upload; upload retries with the same idempotency key; polling that slows down; dropping items deleted in another tab; the retry of the list after a rate limit; focus management; and the access rules per role.

## What changed

**Knowledge index**
- A page header with one primary action, "New knowledge base", which opens a dialog.
- Bases as cards (default) or a list, remembered per browser. Each shows its name, document count, creation date, where its text is processed and, if shared, the access.
- Search by name, "Shared with you" / "Created by you" filter (shown only when some base is shared), and sort: newest, oldest, name.
- A menu on each base: Open, Rename (admins), Delete (owner). Rename and delete are dialogs. The delete dialog says what is lost, and Cancel has focus.
- Empty state with an explanation and a create button; "no match" state with "Clear search and filters"; skeleton cards while loading.

**A base's page**
- Back link, name, badges (processing, access), language and creation date, and the same menu.
- Tabs: Documents, and Sharing for the owner and admins.

**Documents**
- "Upload files" and "Add web page" buttons; the whole panel accepts dropped files; a large drop zone when the base is empty.
- Search by name, filter by status (processing, ready, failed) and sort (oldest, newest, name, recently updated, largest). These run on the server, over the whole base.
- "Show more" loads 100 more at a time; polling reloads every page shown.
- Each row: type icon, title, kind (PDF, Word, web page…), size, date added, a web page's address as text, the status with a spinner while processing, and the failure reason.
- Select one, several or all shown; delete them together after one confirmation. A partial failure keeps what was deleted and says what failed.
- A menu per document: Download (the original file, through the existing authenticated route), Delete.
- Read-only access: no upload, selection or delete; Download stays.

**Sharing:** the same behaviour, with the access levels laid out as three short cards and a clearer empty state.

**API additions** (both additive to `/v1`): `GET /v1/knowledge/bases/{kb_id}/documents` takes `q`, `status` and `sort`, each validated against fixed values (`422` otherwise), with the title search's `%` and `_` matched literally. `GET /v1/knowledge/bases` returns `document_count`. The authorization filter is unchanged and applies to the page and its total.

**Shared UI:** `components/ui/dialog.tsx` and `dropdown-menu.tsx` wrap the Radix primitives already in `radix-ui`; no new dependency. `lib/request.ts` gained a `blob` option for downloads.

## Accessibility and responsiveness

- Dialogs trap focus, close on Escape and return focus; after a delete, focus goes to the page heading. Opening a base moves focus to its name.
- Every icon button has a name ("Actions for Policies"); the selection checkboxes name their document; the view toggle uses `aria-pressed`; tabs are Radix tabs.
- Status changes ("Deleted 2 documents.", "Added 3 files.") are announced through a status region.
- axe reports no violations in unit tests (grid, list, a base's page, documents) and in the browser e2e test in light and dark.
- At 390 px the toolbars wrap with search on its own row, cards stack, and the sidebar is the existing drawer.

## Verification

- Web: 646 unit tests, typecheck, lint and format pass. 79 of them cover Knowledge.
- The knowledge browser e2e suite (6 flows: upload to cited answer, citations after reload and delete, picker, export and erase, hostile markup, sharing by role) passes against the local stack.
- The other e2e flows pass. One erase flow timed out once in teardown and passed on two reruns.
- Python: `make format lint typecheck test security` passes (2,814 tests, including a new unit test for the title search's escaping and the fixed sort fragments). All knowledge Postgres integration tests pass, including a new one for search, filters, sorting, wildcard escaping, invalid values and document counts.

## Security review

The `security-reviewer` agent ran on 2026-11-19, on the changes over `f623be6` before they were committed. It checked the SQL, the route validation, the document count and the download path. It found no injection or authorization gap: `sort` and `status` map to fixed fragments, `q` is a bound and escaped parameter, and the page and its total share the readable-bases filter.

It found one low-severity issue, now fixed. The browser download saved the file under the raw title, bypassing the server's sanitized `Content-Disposition` name. A title with a bidi override (`invoice\u202Efdp.exe`) could look like another file type. Downloads now use `downloadName()`: control and format characters, and path and reserved characters, become `_`, and the name is trimmed and capped. A unit test covers it. The fix is part of `776d5e9`.

## Deliberately not done

| Item | Why |
|---|---|
| Archive and restore a base | Needs a schema change and a decision on whether an archived base is still searched, which is an ADR 0014 amendment. Delete remains the lifecycle end. |
| Rename a document | No API exists. The title comes from the file name or the page. |
| Bulk actions on bases | At most 20 bases per user (`APP_KNOWLEDGE_MAX_BASES_PER_USER`). Deleting a base removes all its documents, so one at a time with a confirmation is safer. |
| Server-side search for bases | The same cap makes filtering in the browser enough. |
| A URL per base (deep links, browser back) | The app has no router; adding one affects every section. |
| Pagination numbers for documents | "Show more" fits the 1,000-document per-user cap. |
