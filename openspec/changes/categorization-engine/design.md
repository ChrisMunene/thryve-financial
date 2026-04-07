## Context

We're building the foundational categorization engine for a new consumer PFM app. There is no existing codebase — this is greenfield. We have a 460M transaction dataset with dual-vendor labels (Plaid categories + Pave tags) and a 6.6M card transaction dataset from Mine. The target user is a 25-30 year old financial beginner who needs things to "just work" — they won't tolerate manual categorization maintenance.

The engine must be accurate enough on day one to feel reliable (pre-trained on vendor data), and improve continuously through user corrections fed back via a weekly recap flow.

## Goals / Non-Goals

**Goals:**
- Categorize transactions with ≥90% accuracy on day one using the seed dataset
- Route only 10-15% of transactions to the LLM layer (the rest handled deterministically)
- Enable user corrections that improve the system for everyone over time (flywheel)
- Keep LLM inference costs manageable by promoting high-confidence patterns to the deterministic layer
- Support the weekly recap as both a user feature and a labeling pipeline
- Correctly handle transfers and non-spend categories — a major pain point in incumbent apps

**Non-Goals:**
- Building budgeting, insights, or coaching features (downstream consumers of categorization — separate changes)
- Real-time transaction notifications (categorization can be async, seconds not milliseconds)
- Supporting multiple currencies or international transactions in v1
- Building a custom fine-tuned model from scratch — start with prompt engineering + few-shot, evolve from there
- Building the bank connection layer (use Plaid SDK directly, not part of this engine)

## Decisions

### 1. Two-layer architecture: Deterministic + LLM

**Decision:** Separate fast deterministic layer from LLM layer, with the deterministic layer handling the majority of transactions.

**Rationale:** Most transactions (~85%) are from well-known merchants (Walmart, Amazon, McDonald's, Shell) where a simple lookup is both faster and cheaper than an LLM call. The LLM is reserved for genuinely ambiguous cases — novel merchants, cryptic raw strings, context-dependent categorization.

**Alternatives considered:**
- *LLM-only:* Simpler architecture but prohibitively expensive at scale (460M+ transactions) and adds unnecessary latency for obvious cases
- *Deterministic-only:* Fast and cheap but fails on the long tail of merchants that drive user frustration — the exact problem we're solving
- *Fine-tuned classifier model:* Good middle ground but requires significant ML ops infrastructure and retraining cycles — start with prompt engineering, evolve to this if needed

### 2. Confidence scoring drives routing

**Decision:** Both layers return a confidence score (0-1). Deterministic layer uses match quality (exact=1.0, prefix=0.8, MCC-only=0.5). LLM layer uses self-reported confidence from the prompt. Threshold for "resolved" is configurable, starting at 0.8.

**Rationale:** A single threshold controls the quality/cost tradeoff. Lower it to send more to LLM (higher accuracy, higher cost). Raise it to rely more on deterministic (lower cost, more misses). Transactions below both thresholds get flagged for user review.

### 3. Category taxonomy: 14 primary / ~50 sub-categories

**Decision:** Fixed primary categories, fixed sub-categories. Users cannot create custom categories in v1. 14 primary categories split into "spend" (categories 1-10, included in budget totals) and "non-spend" (categories 11-14, excluded from budget totals).

**Rationale:** User-defined categories kill the flywheel — corrections can't generalize when everyone has different taxonomies. A fixed taxonomy lets corrections from User A improve results for User B. 14 categories covers all prominent spend areas with sufficient clarity. The spend/non-spend split fixes one of the biggest incumbent complaints: inflated spending numbers from transfers being counted as spend.

**Key taxonomy decisions validated against 460M transactions:**
- "Housing" renamed to "Bills" — internet, phone, and insurance are bills, not housing. This is how users think about them.
- Gambling promoted to its own primary category — 18.4M transactions, 205K users, easily identified merchants (FanDuel, DraftKings). Hiding it under Entertainment helps nobody.
- Cash Advance / EWA added as sub-category under Debt & Loans — ~23M transactions across Earnin, Dave, Brigit, Cleo, etc. Currently mislabeled by Plaid as "accounting and financial planning."
- Travel separated from Transportation — completely different spending patterns (daily $20 gas vs occasional $155 flights), zero merchant overlap, clean split.
- Education promoted from "Other" to its own primary — ~500K transactions, distinct enough to stand alone.
- Convenience stores mapped to Food & Dining — 7M transactions, primary use case is food/drink purchases. Users can override via correction flywheel.

**Alternatives considered:**
- *User-defined (YNAB model):* Maximum flexibility but incompatible with cross-user learning
- *Plaid's 16 categories:* Too many, with meaningless labels ("GENERAL_MERCHANDISE", "GENERAL_SERVICES")
- *Flat tags (Pave model):* Flexible but harder to budget against — budgets need exclusive categories, not overlapping tags
- *Transportation as sub-category of Travel:* Rejected — 28M daily transportation transactions vs 1.5M occasional travel. Making the daily category a child of the rare one would be backwards.

### 4. Merchant key: Pave prettyName preferred

**Decision:** Use Pave's pavePrettyName as the primary merchant key for the lookup table and user display. Fall back to Plaid's prettyName when Pave is unavailable. Normalize raw name as last resort.

**Rationale:** Validated against 460M transactions. Plaid and Pave names disagree 55.7% of the time. The top disagreements are overwhelmingly transfers where Pave gives the cleaner, more user-recognizable label:
- Pave: "Transfer From Savings" vs Plaid: "Transfer from Chime Savings Ac" (bank-branded, verbose)
- Pave: "DoorDash" vs Plaid: "Betosmexi" (Pave sees the platform users recognize, Plaid resolves to underlying restaurant)
- Pave: "Dunkin' Donuts" vs Plaid: "Dunkin'" (Pave preserves full name)

Plaid's prettyName is still useful as metadata (e.g., knowing which restaurant a DoorDash order was from).

**Alternatives considered:**
- *Plaid preferred:* 100% coverage vs Pave's 99.5%, but Plaid's naming is less user-friendly for the top disagreement cases
- *Raw name:* Most authoritative but too noisy for display ("DD *DOORDASH BETOSMEXI")

### 5. Backend framework: FastAPI monolith with SQLAlchemy

**Decision:** Single FastAPI monolith for the entire backend. SQLAlchemy for ORM, Alembic for migrations, Pydantic as the universal schema layer across API, engine, and LLM integration. The categorization engine is a pure Python module within the project — framework-agnostic, no FastAPI imports, receives injected dependencies.

**Rationale:** This is an AI-first product that happens to have CRUD features, not a CRUD app with AI bolted on. The product trajectory includes streaming conversational interfaces, multi-step agent workflows, and real-time AI-powered coaching — all of which require native async support. FastAPI provides:
- Native async for streaming LLM responses (SSE/WebSockets) and agent workflows in the request path
- Pydantic as a single schema layer shared across API request/response validation, engine internal contracts, LLM prompt output schemas, and Celery task arguments — eliminating the impedance mismatch between multiple validation systems
- Lighter weight with no unused framework features (templates, forms, admin panel)

For CRUD operations (users, transactions, bank accounts), reusable patterns are built once and applied across resources. SQLAlchemy provides full query power for complex operations (correction aggregation, spending analytics, merchant lookups with joins). Alembic handles migrations.

**Alternatives considered:**
- *Django + DRF:* Best-in-class for CRUD-heavy apps with built-in migrations, admin panel, ModelViewSet. But Django's async story is incomplete (ORM still largely sync), DRF serializers and Pydantic are separate validation worlds, and the admin panel advantage is diminished by AI-assisted dashboard tooling. The 20% CRUD velocity gain doesn't offset the async limitations for an AI-first product.
- *FastAPI + Node.js (two services):* Theoretically "best tool for each job" but creates massive operational complexity — two languages, two ORMs, two migration systems, inter-service HTTP calls on every transaction, shared database ownership ambiguity. Almost every feature touches both categorization and app logic, making the split boundary artificial.
- *Node.js only (Express/Adonis):* Strong ecosystem for general backend, but poor fit for the data pipeline (pandas, DuckDB, pyarrow are Python-only), and the Anthropic SDK is Python-first.

**Project structure — strict layer separation:**
```
pfm/
├── app/
│   ├── main.py                    # FastAPI app factory, startup/shutdown
│   ├── config.py                  # Settings via pydantic-settings
│   ├── dependencies.py            # Shared deps (db session, auth, redis)
│   │
│   ├── models/                    # SQLAlchemy models (DB schema source of truth)
│   │   ├── base.py                # DeclarativeBase, common mixins
│   │   ├── user.py
│   │   ├── banking.py
│   │   ├── transaction.py
│   │   ├── categorization.py      # SeedMerchantLookup, PatternRule
│   │   └── correction.py          # CorrectionEvent, UserOverride, MerchantRule
│   │
│   ├── schemas/                   # Pydantic (API + internal contracts)
│   │   ├── categorization.py      # CategoryResult, TransactionInput
│   │   ├── correction.py          # CorrectionRequest, ConfirmationRequest
│   │   └── ...
│   │
│   ├── api/                       # Route handlers (thin, delegate to services)
│   │   ├── router.py              # Main router, mounts sub-routers
│   │   ├── transactions.py
│   │   ├── corrections.py
│   │   └── ...
│   │
│   ├── services/                  # Business logic
│   │   ├── correction_service.py
│   │   ├── recap_service.py
│   │   └── ...
│   │
│   ├── engine/                    # Categorization (framework-agnostic)
│   │   ├── orchestrator.py        # Override → rules → lookup → pattern → MCC → LLM
│   │   ├── deterministic.py
│   │   ├── llm.py
│   │   ├── taxonomy.py
│   │   ├── merchant_resolver.py
│   │   └── cache.py
│   │
│   ├── workers/                   # Celery tasks
│   ├── workflows/                 # Temporal workflows
│   ├── middleware/                 # Auth, logging, error handling
│   └── db/                        # Session factory, Redis client
│
├── pipeline/                      # Data pipeline (local, not deployed)
│   ├── run.py
│   ├── config/                    # taxonomy.json, mappings
│   └── ...
│
├── tests/                         # pytest + FastAPI TestClient
├── alembic/                       # Migrations
├── scripts/                       # Operational (seed_lookup, warm_cache)
├── docker-compose.yml             # Local dev environment
└── Dockerfile
```

**Layer responsibilities:**
- `api/` — HTTP concerns only. Thin handlers (5-10 lines), delegate to services.
- `services/` — Business logic, authorization, orchestration. Calls engine and DB.
- `engine/` — Categorization logic. Pure Python, no framework imports. Injected dependencies. Testable in isolation.
- `models/` — SQLAlchemy models. DB schema only, no business logic.
- `schemas/` — Pydantic. Universal contracts shared across API, engine, LLM, and workers.
- `workers/` — Celery tasks. Import services, call them. No direct DB access.
- `workflows/` — Temporal. Same principle as workers.
- `pipeline/` — Separate package. Runs locally. Imports nothing from app/.

### 6. Data stores: Postgres + Redis

**Decision:** Postgres as the single database for all app data including the seed merchant lookup table. Redis as cache layer (merchant lookups, LLM results) and Celery broker.

**Rationale:** SQLite was initially considered for the seed lookup table (embedded, sub-ms reads), but it breaks horizontal scaling — each instance would need its own copy, and keeping them in sync on promotions/demotions is messy. The lookup table is ~50K-200K rows, queried by primary key — Postgres handles this with indexed PK lookups in 1-5ms. Redis cache in front handles the hot path (same 1,000 merchants hit repeatedly) at sub-ms. This gives Redis speed for hot merchants, Postgres durability and queryability for the full table, and zero scaling problems.

**Alternatives considered:**
- *SQLite for lookup:* Sub-ms reads but embedded per-instance, no sharing, awkward deployments (file in Docker image), demotion requires redeployment. Marginal latency advantage doesn't justify the operational cost.
- *Redis only for lookup:* Fast but no complex queries, no joins for analytics/reporting, data lost if Redis restarts without persistence config.

**Redis usage:**
- Celery broker
- Merchant lookup cache (Postgres → Redis on first miss, 24h TTL)
- LLM result cache (merchant_key → category, 24h TTL)
- User override cache (on-demand, invalidated on correction)

### 7. LLM choice: Claude Haiku (or equivalent) via API

**Decision:** Use a fast, cheap model (Claude Haiku class) for the LLM layer. Prompt engineering with few-shot examples from the training corpus, not fine-tuning.

**Rationale:** Haiku-class models handle transaction categorization well — it's a constrained classification task with rich context. Fine-tuning adds ops complexity for marginal accuracy gains at this stage. Revisit when we have enough user correction data to justify it.

**Cost estimate:** ~$0.0004 per LLM call with dynamic few-shot selection (~700 input tokens + ~100 output tokens). At 15% LLM hit rate and 1,000 transactions/user/month: ~$0.06/user/month.

**Alternatives considered:**
- *GPT-4o-mini:* Comparable, acceptable alternative
- *Open-source (Llama/Mistral):* Lower cost at scale but requires hosting infrastructure — defer until volume justifies it
- *Fine-tuned model:* Best accuracy eventually, but premature before we have production correction data

### 8. LLM prompt architecture: assembled from components

**Decision:** The prompt is not a single static string. It's assembled from five components per call: system instructions + rules (static), taxonomy definition (static), dynamically selected few-shot examples (8-12 from a pool of 50-80), user context (dynamic, last 5 categorized transactions + user corrections), and the current transaction + output format.

**Rationale:** Separating components allows each to be updated independently. The system rules encode domain knowledge (prefix conventions, transfer signals, EWA overrides). The taxonomy is the source of truth for valid categories. The few-shot examples teach judgment. The user context provides personalization. Each has a different update cadence — rules change rarely, examples update on pipeline re-runs, user context changes per request.

**Prompt structure:**
```
SYSTEM + RULES (~400 tokens, static)
  Role definition, 7 core rules covering:
  - Specificity preference (Fast Food > Restaurants when confident)
  - Amount as signal not rule
  - Platform prefixes (SQ*, DD*, SP, TST*)
  - Transfer signal words
  - EWA override rule
  - Uncategorized fallback for low confidence

TAXONOMY (~800 tokens, static)
  14 categories with sub-categories
  Each sub-category includes 2-3 merchant examples inline
  (more token-efficient than separate examples for obvious cases)

FEW-SHOT EXAMPLES (~500 tokens, dynamic)
  8-12 selected from pool of 50-80
  Selected via scoring function, not vector search
  Includes reasoning field (chain-of-thought)

USER CONTEXT (~200 tokens, dynamic)
  Last 5 confirmed/corrected transactions
  User's own corrections as personalization signal

TRANSACTION + OUTPUT FORMAT (~100 tokens, dynamic)
  Raw name, merchant key, amount, channel, location
  Structured JSON output schema with reasoning field
```

**Key design decisions within the prompt:**
- Reasoning field is mandatory in LLM output. Not for the user — for diagnostics. Corrections paired with reasoning help identify systematic errors and feed the flywheel.
- Few-shot examples include reasoning (chain-of-thought). Teaches the LLM how to think about categorization, not just what the answer is.
- Taxonomy includes merchant examples inline. Anchors the LLM's understanding of what belongs where while being more token-efficient than separate examples.
- Rules encode absolutes (DD* = always Food Delivery), examples encode judgment (SQ *TIKI JIMS at $9.80 is probably a restaurant).

### 9. Dynamic few-shot selection from static pool

**Decision:** Select 8-12 relevant examples per LLM call from a pool of 50-80 tagged examples, using a deterministic scoring function. No vector search or embedding-based retrieval.

**Rationale:** Concentrated, relevant context improves LLM accuracy more than a large volume of generic examples. Sending 50 static examples wastes tokens on irrelevant cases and dilutes the signal. Dynamic selection reduces input tokens by ~68% (3,000 → 600) while giving the LLM focused examples for exactly this type of transaction.

**Selection algorithm (scoring-based, ~40 lines):**
- Prefix match (strongest signal): +3.0 if transaction has same prefix as example (SQ*, DD*, SP)
- Amount range similarity: +1.0 if amounts are in the same bucket ($1-15, $15-50, $50-200, $200+)
- Channel match: +0.5 if same payment channel (in_store, online)
- Difficulty bonus: +0.5 for medium/hard examples over easy ones
- Category spread: ensure at least one example from each plausible category to avoid bias
- Deterministic: same input always selects same examples — debuggable

**Pool structure (curated by pipeline, stored as JSON):**
- Prefix examples (15-20): SQ*, SP, DD*, TST*, MC Platinum DC
- Category anchors (14-20): 1-2 per primary category
- Ambiguous cases (8-10): Costco, CVS, Apple, 7-Eleven, Venmo
- Edge cases (5-8): Animal Jam (not veterinary), MGCCC refund, Cleo subscription vs EWA

**Each example is tagged with:** prefix type, amount range, channel, difficulty, primary category — enabling fast scoring without embeddings.

**Alternatives considered:**
- *Static examples:* Simpler but 68% more expensive in tokens and less accurate due to diluted context
- *Vector similarity search:* More sophisticated but requires embedding infrastructure, adds latency, and overkill for a pool of 80 examples
- *No few-shot (zero-shot):* Much worse accuracy — tested informally, the LLM makes significantly more errors without examples

### 8. Mobile: Flutter

**Decision:** Flutter for the mobile app (iOS + Android).

**Rationale:** Best cross-platform framework for fintech use cases. Strong charting libraries (fl_chart), official Plaid Link SDK support, single codebase for both platforms. Chosen based on team expertise.

### 9. Background processing: Celery + Temporal

**Decision:** Celery + Redis for simple periodic and fire-and-forget tasks. Temporal for complex multi-step stateful workflows.

**Celery handles:**
- Hourly correction aggregation, promotion/demotion checks
- Weekly recap generation and training data export
- Async batch transaction categorization (on Plaid webhook)
- Push notification delivery

**Temporal handles:**
- Bank account connection workflow (multi-step, retries, timeouts)
- Historical transaction sync (paginated, long-running)
- Plaid re-auth workflow (when connection breaks)

**Rationale:** Celery is simple and well-integrated with FastAPI via celery beat. But bank connection is a multi-step workflow with failure modes at each step (token exchange, account fetch, transaction sync, categorization, notification) — Temporal is purpose-built for this kind of orchestration.

### 12. Auth: Supabase Auth

**Decision:** Supabase Auth for user authentication, phone-first. JWT verification in FastAPI middleware.

**Rationale:** Best Flutter integration among managed auth providers. Phone-first auth matches target user behavior (mobile-first, neobank users). Handles MFA, social login, and session management. FastAPI middleware verifies Supabase JWTs and maps to the SQLAlchemy User model.

### 11. Hosting: Railway (MVP) → AWS (SOC 2)

**Decision:** Railway for MVP deployment. Migrate to AWS (ECS + RDS + ElastiCache + Temporal Cloud) when pursuing SOC 2 compliance for fintech regulatory requirements.

**Railway deployment:**
- API server (Django web service)
- Celery worker (background service)
- Temporal worker (workflow service)
- Postgres (managed)
- Redis (managed)

### 12. Monitoring: Sentry + PostHog + Datadog

**Decision:** Sentry for error tracking and performance monitoring. PostHog for product analytics and feature flags. Datadog for infrastructure monitoring.

### 13. Data pipeline: local execution

**Decision:** The training pipeline (DuckDB + pandas, processing 460M transactions) runs locally on the M4 Pro / Mac Studio. Pipeline artifacts (seed lookup SQL dump, pattern rules, few-shot examples) are deployed to the production database. CI pipeline for this is deferred until team grows.

**Rationale:** Processing 460M transactions is compute-intensive and infrequent (initial seed + periodic retraining). Local execution avoids CI costs. Artifacts are small (SQL dump, JSON files) and easy to deploy manually.

### 7. Correction generalization: three-tier with ambiguity detection

**Decision:** User override → candidate rule (5+ users, 90%+ agreement) → universal rule. Merchants with <70% agreement on any single category are flagged as "ambiguous" and never promoted — respect user preference.

**Rationale:** This balances personalization (your Costco = Groceries) with collective intelligence (everyone agrees MCDONALD'S = Food & Dining). The ambiguity detection prevents the system from flip-flopping on genuinely multi-purpose merchants.

### 8. Training data strategy: vendor agreement as quality signal

**Decision:** Use Plaid/Pave agreement to create tiered training data:
- **Gold labels:** Plaid VERY_HIGH confidence + Pave tag agrees on same internal primary → deterministic layer seed
- **Silver labels:** Plaid HIGH + Pave agrees → training + validation
- **Hard cases:** Plaid/Pave disagree → LLM benchmark test set
- **LLM territory:** Plaid LOW confidence → evaluate LLM accuracy here

**Rationale:** Two independent vendors agreeing on a categorization is a strong quality signal. Their disagreements are exactly the cases where current solutions fail — and where our LLM layer needs to prove its value.

### 9. Transfer handling: train on them, exclude from spend

**Decision:** Include all transfer, income, debt, and fee categories in training data. The categorization engine must correctly identify these. Downstream features (budgets, spend insights) exclude non-spend categories (Transfers, Debt & Loans, Income, Other) from spend totals.

**Rationale:** Transfers are 41.6% of all transactions in the corpus. Correctly identifying internal transfers vs P2P payments vs savings transfers is one of the biggest pain points in incumbent apps. Excluding them from training would leave the engine blind to the most common transaction type. The engine categorizes everything; the budget/insight layer decides what counts as "spend."

**Key transfer sub-types identified from data:**
- Internal account transfers: 126M (must identify to exclude from spend)
- Savings transfers: 25.8M (must track for savings features)
- P2P (Cash App, Venmo, Zelle): ~30M (ambiguous — could be spend or transfer)
- ATM withdrawals: 6.3M (cash, tracked separately)
- Cash advances / EWA: 16.9M (moved to Debt & Loans)
- Investment transfers: 3.7M (tracked for net worth features)

### 10. Correction data model: four-table architecture

**Decision:** The correction system uses four tables: correction_events (append-only log), user_overrides (materialized user preference), correction_aggregates (crowd-level stats), and merchant_rules (promotion/demotion/ambiguity state). The event log is the source of truth; aggregates and rules are derived views recomputed hourly.

**Rationale:** Separating the raw events from derived state allows recomputation, debugging, and auditing. The append-only log captures engine context (which layer produced the original, confidence, rule ID) enabling diagnostics — e.g., finding which deterministic rules generate the most corrections or which LLM prompt patterns produce low confidence.

### 11. Correction processing: sync overrides, async aggregation

**Decision:** User override upsert is synchronous (the user's correction applies immediately to their future transactions). Crowd aggregation, threshold checks, promotions, demotions, and training exports run as an hourly async batch job.

**Rationale:** Users only care that *their* correction applies instantly. Whether it becomes a universal rule this second or an hour from now is invisible to them. Batch processing is more efficient for aggregation queries and avoids write contention on the aggregates table.

### 12. Confirmation weighting in aggregation

**Decision:** Confirmations count toward agreement scoring but at 0.5 weight (corrections at 1.0). Promotion and ambiguity thresholds use correction-only agreement rates. A separate correction_rate metric (correcting_users / total_interacting_users) determines whether the default is validated (<20% correction rate = default holds) or challenged (>50% = flag for review).

**Rationale:** A confirmation is a weaker signal — users may tap "looks good" without really checking. But large volumes of confirmations are still meaningful — they validate that the default works for most people. Keeping promotions based on corrections-only ensures that only strong disagreement drives changes to the system.

### 13. Demotion mechanism built into core

**Decision:** Universal rules can be demoted when 3+ distinct users submit corrections against the rule after its promotion date. Demotion removes the rule from the merchant_rules store, resets the aggregation window, and returns the merchant to LLM evaluation. The promotion_count field tracks how many times a merchant has cycled between promotion and demotion, flagging unstable merchants for manual review.

**Rationale:** Correctness is a top priority. A promotion system without demotion is brittle — bad rules would persist indefinitely. Demotion is part of the learning process. The post-promotion timestamp filter ensures that only fresh disagreement triggers demotion, not historical corrections from before the rule existed.

### 14. Separate stores: merchant_rules vs seed lookup table

**Decision:** Universal rules live in the merchant_rules Postgres table, separate from the seeded SQLite lookup table. At query time, the priority chain is: user_overrides → merchant_rules (universal) → seed lookup (SQLite) → pattern rules → MCC.

**Rationale:** The seed lookup table is a static artifact regenerated by the training pipeline. The merchant_rules table is live, evolving state driven by user corrections. Keeping them separate means: (a) demotion doesn't require touching the seed table, (b) you can distinguish "the corpus told us this" from "users told us this", (c) the seed table stays read-only and simple.

### 15. Training signal weights

**Decision:** Training examples carry weights based on source: universal rules (1.0), individual user corrections (0.5), user confirmations (0.3), vendor agreement baseline (0.2). Demoted rules are flagged for re-evaluation in the next training cycle.

**Rationale:** A universal rule is the strongest signal — crowd-validated, threshold-checked. Vendor labels are the weakest — they're the baseline we're trying to improve on. This hierarchy ensures the model progressively learns from human judgment while not over-indexing on any single user's preference.

## Risks / Trade-offs

**[Cold start accuracy]** → Day-one accuracy depends entirely on the quality of the vendor-labeled seed data. Mitigate by validating a sample of gold labels manually before launch and by setting conservative confidence thresholds (route more to LLM initially, tighten as the deterministic layer proves out).

**[LLM cost at scale]** → If the deterministic layer doesn't absorb enough volume, LLM costs grow linearly with users. Mitigate with the promotion mechanism — aggressively promote high-confidence LLM results. Monitor the deterministic hit rate weekly; target 85%+ within 3 months.

**[Correction spam / adversarial input]** → Users could submit incorrect corrections (trolling, mistakes, misunderstanding categories). Mitigate with the threshold system — one user's bad correction stays personal; it takes 5+ agreeing users to promote. Also flag corrections that contradict high-confidence vendor labels for manual review.

**[Taxonomy rigidity]** → Fixed categories may not fit every user's mental model. Mitigate by making the taxonomy data-driven (validated against actual spending patterns from the 460M corpus) and by allowing sub-category visibility to be user-configurable even if the taxonomy itself is fixed.

**[Ambiguous merchant detection is imperfect]** → The 70% agreement threshold is a heuristic. Too low = promotes bad rules. Too high = nothing promotes. Mitigate by making the threshold configurable and monitoring promotion quality metrics.

**[Weekly recap fatigue]** → If the recap surfaces too many transactions or too many corrections, it becomes the "work" we're trying to eliminate. Mitigate by only surfacing low-confidence transactions (3-5 per week max) and making confirmation a single tap.

**[P2P ambiguity]** → Venmo/Zelle/Cash App transactions could be spend (splitting a dinner bill) or transfers (paying rent to roommate). Neither vendor nor the engine can reliably distinguish these without user input. Mitigate by defaulting to "Transfers > Peer-to-Peer" and surfacing in the weekly recap for user correction. Over time, the correction flywheel will learn patterns (e.g., recurring $500 Cash App to same person = rent).

**[EWA/Cash Advance mislabeling]** → Plaid categorizes Earnin, Dave, Brigit, Cleo as "GENERAL_SERVICES_ACCOUNTING_AND_FINANCIAL_PLANNING." Our engine must override this. Mitigate by building an explicit EWA merchant list (~15 known providers) into the deterministic layer from day one.
