# Developer Guide — read this before any change

These rules are **non-negotiable** and override default behavior. They apply to every
request in this repository, regardless of phrasing.

## 1. Load context dynamically — never the whole tree

`context/` holds distributed, per-module project context (`context/overview.md` for
project-wide structure, `context/<app>/overview.md` per app/feature). Before working
on a request:

- Identify which module(s) the request touches (e.g. a question about roles/overrides
  → `context/rbac/overview.md`; auth/Okta/email → `context/users/overview.md`).
- Read **only** that file (plus `context/overview.md` if the request is structural/
  project-wide). Do not read every file under `context/` for every request — it does
  not scale and wastes the window.
- If a module has no context file yet, say so rather than guessing; create one after
  finishing non-trivial work in that module (see `track-context`-style convention:
  update the relevant `context/<app>/overview.md` after a change, don't let it rot).

### Context updates are mandatory, not best-effort

After **every** change that touches a module's models, selectors, services, views,
permissions, URLs, or seed data — update that module's `context/<app>/overview.md`
in the same turn, before reporting the task done. This is not optional cleanup:
- New/changed model fields, constants, or permission codes → reflect in "Key files".
- New/changed architectural decision (e.g. a new declaration pattern, a deliberately
  unassigned permission, a cross-app dependency) → add or amend a bullet under
  "Decisions".
- A new app with no `context/<app>/overview.md` yet → create one before finishing,
  following the existing files' structure (Purpose / Key files / Decisions / Status).
- If a change is structural/cross-cutting (new app, new shared utility under
  `common/`), also update `context/overview.md`.
A task is not complete until the relevant context file(s) match the code as left —
treat this the same as the testing/gate requirements in §3, not a nice-to-have.

### Changelog updates are mandatory, not best-effort

`changelog/` holds one file per day, named `YYYY-MM-DD.md` (see
`changelog/README.md`), logging what changed and why. After **every** change that
touches code (not just docs/context) in the same turn:
- Get today's date and check whether `changelog/YYYY-MM-DD.md` exists.
- If it exists, append a new bullet to it. If not, create it with a `# YYYY-MM-DD`
  heading and the first bullet.
- Each bullet is short: what changed and why — not a full diff (`git log`/`git diff`
  remain the source of truth for that).
A task is not complete until today's changelog file reflects the change, same as
the context-file rule above.

## 2. Local guideline folder — gitignored, per-developer, not in this repo

A **best-practices / architecture-docs folder** (legacy module specs, design-pattern
references, etc.) informs implementation decisions but is **not committed here**.
It is:

- **Developer-local.** Each engineer keeps their own copy, at whatever path suits
  their machine — there is no single canonical path baked into this repo.
- **Distributed out-of-band** (shared drive, internal wiki, or similar — not git), so
  it can be updated independently of the codebase and never leaks into version
  control or CI.
- **Not assumed to exist.** If a request needs prior-art / legacy-system context and
  no such folder has been pointed out yet in the conversation, ask the developer
  where their guideline folder lives (or proceed from the codebase alone if they say
  there isn't one) — never guess a path.

When a guideline folder *is* known (named by the developer earlier in the session,
or recorded in memory from a prior session): before implementing in a domain it
covers, read only the doc(s) in it relevant to the current request — same dynamic-
loading discipline as `context/`, not a full-folder read.

Any such folder placed inside this repo (e.g. `architecture-docs/`,
`*-architecture-docs/`, `best-practices/`) is gitignored — see `.gitignore` — so it
never gets pushed regardless of where a developer chooses to put it locally.

## 3. Enforced conventions (see `context/overview.md` for the full list)

- **App layout:** every Django app lives under `apps/<app_name>/` (never at the repo
  root, never nested inside the `config/` project package). Shared, cross-app code
  lives under `common/` (`common/api/`, `common/constants/`, `common/services/base.py`
  → `BaseService`, `common/selectors/base.py` → `BaseSelector`). A change that needs
  a new app creates `apps/<app_name>/` with the standard layout — `models.py`,
  `serializers.py`, `views.py`, `urls.py`, `admin.py`, `constants.py`, `messages.py`,
  `services/`, `selectors/`, `migrations/`, `tests/` — before it's considered started.
- **API versioning:** endpoints are mounted under `/api/v1/<app_name>/…` from
  `config/urls.py`. Don't add unversioned routes; a breaking change gets a `v2`
  namespace, it doesn't mutate `v1` in place.
- No magic literals — constants come from `common/constants/`.
- All user-facing text is translatable (`gettext_lazy`) and centralized in a
  `messages.py` registry — never inlined.
- Class-based/OOP throughout: DRF class-based views, `BaseService`/`BaseSelector`
  subclasses for writes/reads.
- Services = writes/orchestration, selectors = reads, views = HTTP only.
- Fail-fast config via `config/env.py:AppEnv` — never `os.getenv` scattered in code.
- Sign off on architecture (e.g. RBAC redesign) before implementing it — don't
  silently redesign a module mid-task.

### Views and serializers stay thin

- A view's `get`/`post`/`patch`/... method does at most: deserialize → call one
  service/selector method → wrap the result in `ApiResponse`
  (`common/api/response.py`). No branching business logic, no direct ORM writes, no
  inline permission/role math in a view body.
- A serializer validates and (de)serializes shape only — `validate_*`/`validate()`
  for field-level/cross-field input rules is fine; it must never call out to other
  models for side effects (sending email, assigning roles, mutating unrelated rows).
  If a serializer needs to do that, the logic belongs in a service the view calls
  after `serializer.is_valid()`.
- Business logic — anything with a decision, a side effect, or more than one write —
  lives in a `services/<name>_service.py` class (`BaseService` subclass) or a
  `selectors/<name>.py` class (`BaseSelector` subclass for reads), never inline in
  `views.py`/`api/v1/views/*.py`. If you find yourself writing an `if` that decides
  business outcome inside a view, stop and move it to a service method.

### Testing — required, not optional, for every change

- Every new service/selector method, permission class, and API endpoint gets a test
  in the matching `<app>/tests/test_*.py` before the task is considered done — not
  "I'll add tests later."
- Cover the **happy path AND edge cases** explicitly: empty/missing input, the
  not-found case, the unauthorized/forbidden case, boundary values (e.g. an OTP at
  exactly its expiry instant), idempotency (calling a write op twice), and any
  documented business rule (e.g. "DENY wins over GRANT" needs its own test, not just
  "GRANT works").
- API-level changes get an HTTP-level test via DRF's `APIClient` (status code +
  envelope shape), not only a service-level unit test — the two catch different
  classes of bugs (wiring vs logic).
- Mock external systems (Okta, SMTP, anything over the network) at the boundary
  (e.g. inject a fake/mocked client) — never let a test depend on a real external
  call.
- A task is not complete until `pytest`, `ruff check`, `ruff format --check`, and
  `manage.py check` all pass clean on the changed code; run them before reporting
  done, not after the user asks.

### Admin registration is mandatory

Every new Django model must be registered in the app's `admin.py` before the task is
considered done — no exceptions. Use a `ModelAdmin` subclass (not bare
`admin.site.register(MyModel)`) and expose at minimum `list_display`, `search_fields`,
and any relevant `list_filter` fields so the model is usable in the admin panel.

### Other strict rules

- No bare `except:`/`except Exception:` swallowing errors silently — catch the
  specific exception, or let it propagate so `custom_exception_handler` deals with
  it. Domain-expected failures raise `ApplicationError` (or a subclass) with a
  message from the relevant `messages.py`, never a raw string.
- Type hints on every function/method signature you write or touch (this repo
  targets a clean `mypy` baseline going forward — don't introduce new untyped code
  even though some pre-existing Django-stubs noise is tolerated).
- No `print()` for diagnostics — use the configured `logging` module.
- Cache/state invalidation is explicit at the point of every write that affects it
  (mirrors the RBAC resolver pattern: change a role's permissions → invalidate every
  holder immediately) — never rely on TTL-only eventual correctness for anything
  authorization-related.
- **Caching — add it when a new selector read is added:**
  - Single-value reads (parameters_config, detail) → use `read_through()` from
    `common/api/cache_helpers.py`. Register the cache key + TTL in
    `common/constants/keys.py` (`CacheKey` enum, `CacheTTL` class) first; alias it
    in the app's `constants.py` as the per-app override point.
  - List views → implement `list_cache_key(request) -> str | None` on the selector,
    returning `None` for uncacheable shapes (free-text search, pages beyond
    `DEFAULT_MAX_CACHEABLE_LIST_PAGE`). Use version-bump invalidation via
    `get_version`/`bump_version`. Pass the key to `paginated_list_response()`.
  - Forced-fresh bypass: wire `wants_fresh_data(request)` in every view that caches;
    pass the resulting `fresh` bool down to the selector. Clients send
    `Cache-Control: no-cache` or `?refresh=1` to bypass.
  - **Invalidation is mandatory**: every write path (webhook handler, STP/ERP
    callback, admin bulk-edit, backfill re-run) must call the app's
    `invalidate_*_caches()` function. Add a reminder bullet to the app's
    `context/<app>/overview.md` under the Caching section listing all callers that
    must invalidate.
- **DB indexes — add them before reaching for more caching:**
  - Every new model whose list view has filter/sort columns → add `Meta.indexes` for
    those columns in `models.py` and generate the migration in the same turn.
  - At minimum: index each standalone filter field, then composite indexes for the
    two most common (filter + sort) pairs. Match the `common.api.query_params`
    contract: `filter`/`filter_by`, `sort`/`sort_direction`, date ranges.
  - Naming convention: `<app>_<model_abbrev>_<col(s)>_idx`
    (e.g. `orders_date_idx`, `catalog_prod_plat_status_idx`).
  - Don't add speculative indexes for columns that aren't currently queried.
- Don't widen scope beyond the request: a bug fix or a single endpoint doesn't
  justify refactoring unrelated files, renaming things "while we're in there," or
  adding speculative abstractions for hypothetical future use.

## 4. Memory instruction

For every request in this project, before answering or implementing: consult this
file's context-loading rule (§1) and, if a developer guideline folder is known for
this project (per §2), treat it as an active source to check for the relevant
domain — don't rely on training-data assumptions about this codebase's legacy
behavior when a local source of truth is available.
