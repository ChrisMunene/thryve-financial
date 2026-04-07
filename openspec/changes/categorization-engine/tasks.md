## 0. Project Scaffolding

- [x] 0.1 Initialize project: pyproject.toml with dependencies (fastapi, uvicorn, sqlalchemy[asyncio], asyncpg, alembic, pydantic-settings, anthropic, celery, redis, httpx)
- [x] 0.2 Create project structure: app/ (main, config, dependencies, db/, models/, schemas/, api/, services/, engine/, workers/, workflows/, middleware/), pipeline/, tests/, scripts/, alembic/
- [x] 0.3 Set up FastAPI app factory (app/main.py): lifespan events for startup (load pattern rules, warm Redis) and shutdown (close connections)
- [x] 0.4 Set up pydantic-settings config (app/config.py): DATABASE_URL, REDIS_URL, ANTHROPIC_API_KEY, SUPABASE_JWT_SECRET, env-based
- [x] 0.5 Set up async SQLAlchemy session factory (app/db/session.py): async engine, async sessionmaker, get_db dependency
- [x] 0.6 Set up Redis client (app/db/redis.py): async redis connection, cache helper functions (get/set with TTL, invalidate)
- [x] 0.7 Set up Alembic with async support: alembic.ini, env.py configured for asyncpg
- [x] 0.8 Create SQLAlchemy base model (app/models/base.py): DeclarativeBase, TimestampMixin (created_at, updated_at), UUIDMixin
- [x] 0.9 Set up Celery app (app/workers/celery_app.py): Redis broker, beat schedule for hourly/weekly tasks
- [x] 0.10 Create docker-compose.yml: Postgres 16, Redis 7, Celery worker, Celery beat, Temporal (optional for v1)
- [x] 0.11 Set up pytest with FastAPI TestClient, async test fixtures, test database

## 1. Category Taxonomy

- [x] 1.1 Define the taxonomy data structure (14 primary, ~50 sub-categories) with IDs, display names, icons, and spend/non-spend classification
- [x] 1.2 Build Plaid detailedName → internal taxonomy mapping table (106 → ~50), including overrides for EWA merchants, gambling, travel, and convenience stores
- [x] 1.3 Build Pave tags → internal taxonomy mapping table (100+ → ~50), with multi-tag priority resolution logic
- [x] 1.4 Build EWA merchant explicit list (~15 known providers: Earnin, Dave, Brigit, Cleo, Albert, Floatme, Klover, MoneyLion, Chime MyPay, Credit Genie, Flex Finance, Ava Finance, Vola Finance, True Finance, Tilt Finance)
- [x] 1.5 Build gambling merchant explicit list (FanDuel, DraftKings, BetMGM, PrizePicks, Chumba Casino, etc.)
- [x] 1.6 Write tests verifying all 106 Plaid detailedNames map to exactly one internal category, all Pave tags resolve, and EWA/gambling overrides work correctly

## 2. Training Pipeline — Seed Data Extraction

- [ ] 2.1 Write DuckDB extraction script to scan globaltransactions corpus and resolve merchant key (pavePrettyName → prettyName → normalized raw name)
- [ ] 2.2 Apply taxonomy mappings to classify each transaction's Plaid label and Pave label into internal taxonomy
- [ ] 2.3 Classify label quality for each transaction: gold (Plaid VERY_HIGH + Pave agrees), silver (Plaid HIGH + Pave agrees), bronze (Plaid MED/LOW + Pave agrees), hard case (disagree), unknown (missing)
- [ ] 2.4 Generate label quality distribution report — validate expected proportions (gold ~30-40%, hard cases ~10-15%)
- [ ] 2.5 Include all transaction types in pipeline: transfers, income, debt, fees — not just spend categories

## 3. Training Pipeline — Artifact Generation

- [ ] 3.1 Aggregate gold-label data by merchant key and compute most-common category mapping per merchant
- [ ] 3.2 Generate deterministic lookup table: merchants with ≥100 gold-label txns and ≥95% category agreement, plus EWA and gambling explicit lists
- [ ] 3.3 Generate pattern rules: identify common merchant prefixes with ≥50 raw name variants mapping to same category
- [ ] 3.4 Generate platform prefix rules (DD * → Food Delivery, SQ * → delegate to LLM, SP → delegate to LLM)
- [ ] 3.5 Identify ambiguous merchants: merchants where no single category reaches 70% agreement across ≥100 transactions
- [ ] 3.6 Create train/validation/test split (70/15/15), stratified by all 14 primary categories, with hard cases enriched to ≥30% of test set
- [ ] 3.7 Generate tagged few-shot pool (50-80 examples): prefix examples (SQ*, DD*, SP, TST*, MC Platinum DC), category anchors (1-2 per category), ambiguous cases (Costco, CVS, Apple, 7-Eleven, Venmo), edge cases (misleading names, refunds). Each example tagged with prefix type, amount range, channel, difficulty, primary category. Include reasoning field.
- [ ] 3.8 Output few_shot_pool.json with selection metadata for dynamic few-shot selector
- [ ] 3.9 Generate pipeline report: coverage stats, lookup table size, uncovered top-50 merchants, label quality distribution, few-shot pool coverage by category

## 4. Deterministic Layer

- [ ] 4.1 Create SQLAlchemy model for SeedMerchantLookup (merchant_key, category_primary, category_sub, confidence, source, raw_variants_count) with indexed merchant_key. Generate Alembic migration.
- [ ] 4.2 Write seed script (scripts/seed_lookup.py) to load pipeline output (task 3.2) into Postgres via bulk insert
- [ ] 4.3 Implement Redis cache layer for merchant lookups: check Redis first (HGET), fall back to Postgres async query, cache on miss (24h TTL)
- [ ] 4.4 Build pattern matching engine: normalize raw name (uppercase, strip trailing digits/special chars), then try progressively shorter prefixes
- [ ] 4.5 Load pattern rules from task 3.3 and platform prefix rules from task 3.4 into pattern engine (loaded into memory on FastAPI startup event)
- [ ] 4.6 Implement MCC code → internal taxonomy fallback mapping
- [ ] 4.7 Build the deterministic classification function: user override → merchant_rules (universal) → seed lookup (Postgres/Redis) → pattern match → MCC, returning CategoryResult Pydantic schema
- [ ] 4.8 Write tests verifying priority order (override > universal rule > seed lookup > pattern > MCC), confidence scoring, EWA/gambling overrides, platform prefix handling, and Redis cache hit/miss
- [ ] 4.9 Benchmark deterministic layer against validation set — target ≥85% hit rate with ≥90% accuracy on hits

## 5. LLM Layer

- [ ] 5.1 Build prompt assembler: compose final prompt from 5 components — system+rules (static), taxonomy (static), few-shot examples (dynamic), user context (dynamic), transaction+output format (dynamic)
- [ ] 5.2 Write system instructions with domain rules: specificity preference, amount-as-signal, platform prefix conventions (SQ*, DD*, SP, TST*), transfer signal words, EWA override, uncategorized fallback
- [ ] 5.3 Write taxonomy prompt section: 14 categories with sub-categories, each sub-category annotated with 2-3 representative merchant names inline
- [ ] 5.4 Implement dynamic few-shot selector (engine/few_shot_selector.py): scoring function over example pool — prefix match (+3.0), amount range (+1.0), channel match (+0.5), difficulty bonus (+0.5), with category spread enforcement. Select 8-12 per call. Must be deterministic.
- [ ] 5.5 Implement user context injection: fetch last 5 confirmed/corrected transactions for the user, plus any user corrections for merchants similar to the current one
- [ ] 5.6 Implement LLM classification function using Claude Haiku API (async): assemble prompt, call API, parse response
- [ ] 5.7 Implement Pydantic response validation: parse JSON, verify primary/sub exist in taxonomy, verify reasoning field present. On malformed response: retry once, then fallback to "Other > Uncategorized" at confidence 0.3
- [ ] 5.8 Implement LLM result caching in Redis: cache merchant_key → CategoryResult (24h TTL) to avoid duplicate API calls for the same merchant
- [ ] 5.9 Benchmark LLM layer against hard-case test set — measure accuracy vs Plaid and Pave individually, per-category accuracy
- [ ] 5.10 Tune confidence threshold (start at 0.8) based on validation set precision/recall tradeoff
- [ ] 5.11 Write tests for: prompt assembly, few-shot selector (deterministic output, prefix prioritization, category spread), response parsing (valid, malformed, retry), cache hit/miss

## 6. Two-Layer Pipeline Integration

- [ ] 6.1 Build the orchestrator: route transaction through deterministic layer first, fall through to LLM if confidence < threshold
- [ ] 6.2 Implement transaction flagging: mark low-confidence results (both layers below threshold) for weekly recap review
- [ ] 6.3 Implement the promotion mechanism: track LLM classifications per merchant key, auto-promote to deterministic when threshold met (≥3 users, ≥0.9 confidence, same category)
- [ ] 6.4 Write end-to-end tests: known merchant → deterministic, unknown merchant → LLM, EWA merchant → override, gambling → override, transfer → correct sub-type, ambiguous merchant → flagged
- [ ] 6.5 Benchmark full pipeline on test set — measure overall accuracy, deterministic hit rate, LLM invocation rate, per-category accuracy, and latency

## 7. Correction Flywheel — Data Model

- [ ] 7.1 Create CorrectionEvent SQLAlchemy model: append-only log with user_id (FK), transaction_id (FK), merchant_key, raw_name, from/to categories, event_type, source, engine context (engine_source, engine_confidence, engine_rule_id), created_at
- [ ] 7.2 Create UserOverride SQLAlchemy model: UniqueConstraint(user_id, merchant_key), current category preference, correction_count, timestamps
- [ ] 7.3 Create CorrectionAggregate SQLAlchemy model: UniqueConstraint(merchant_key, target_primary, target_sub), distinct_users, total_corrections, total_confirmations, weighted_score, updated_at
- [ ] 7.4 Create MerchantRule SQLAlchemy model: merchant_key (unique), status as Enum (universal/ambiguous/candidate/default_challenged/demoted), resolved category, top_categories as JSON, promoted_at, demoted_at, demotion_reason, promotion_count
- [ ] 7.5 Generate Alembic migration for all correction models, verify indexes on merchant_key and user_id+merchant_key

## 8. Correction Flywheel — Sync Path

- [ ] 8.1 Implement POST /corrections endpoint (FastAPI): write correction_event + upsert user_override in single async DB transaction, invalidate Redis override cache
- [ ] 8.2 Implement POST /confirmations endpoint (FastAPI): write correction_event with event_type="confirmation" in async DB transaction
- [ ] 8.3 Implement user override lookup in deterministic layer: check Redis cache → Postgres user_overrides → return confidence 1.0 on hit
- [ ] 8.4 Write tests: correction applies immediately for user, does not affect other users, latest correction wins on repeated corrections

## 9. Correction Flywheel — Async Batch Job

- [ ] 9.1 Build hourly aggregation job: recompute correction_aggregates from correction_events grouped by merchant_key + target category, with weighted scoring (corrections × 1.0, confirmations × 0.5)
- [ ] 9.2 Implement promotion check: if correction-only agreement ≥ 0.90 and distinct correcting users ≥ 5, set merchant_rules status="universal" with resolved category
- [ ] 9.3 Implement ambiguity check: if max correction agreement < 0.70 and correction_rate > 0.30, set merchant_rules status="ambiguous" with top_categories distribution
- [ ] 9.4 Implement demotion check: if existing universal rule has ≥ 3 distinct users correcting against it post-promotion, set status="demoted", record reason, increment promotion_count
- [ ] 9.5 Implement default challenge check: if system default mapping has correction_rate > 0.50 across 50+ interactions, set status="default_challenged"
- [ ] 9.6 Implement merchant_rules lookup in deterministic layer: check Redis cache → Postgres merchant_rules after user_overrides, before seed lookup; ambiguous merchants get reduced confidence (≤ 0.6); update Redis on promotion/demotion
- [ ] 9.7 Write tests for full lifecycle: override → aggregation → promotion → demotion → re-evaluation; ambiguous detection; default challenge; promotion churn flagging; Redis cache invalidation

## 10. Weekly Recap

- [ ] 10.1 Build recap generation: aggregate user's transactions for past 7 days, group by primary category, compute totals and week-over-week comparison, separate spend vs non-spend
- [ ] 10.2 Implement low-confidence transaction surfacing: select up to 10 lowest-confidence transactions plus ambiguous merchant transactions for "Review These" section
- [ ] 10.3 Wire single-tap confirmation to correction flywheel confirmation endpoint (task 8.2)
- [ ] 10.4 Wire category correction to correction flywheel correction endpoint (task 8.1)
- [ ] 10.5 Implement recap completion tracking: mark complete/partial based on items resolved
- [ ] 10.6 Write tests for recap generation, confirmation flow, correction flow, ambiguous merchant surfacing, and spend/non-spend separation

## 11. Ongoing Training Pipeline

- [ ] 11.1 Build weekly training data export: query correction_events for new universal rules (weight 1.0), individual corrections (weight 0.5), confirmations (weight 0.3), with source tracking; flag demoted rules for re-evaluation
- [ ] 11.2 Implement incremental training data update: append weighted examples to training set
- [ ] 11.3 Implement accuracy regression check: evaluate updated model on held-out test set, alert if accuracy drops ≥2%
- [ ] 11.4 Build diagnostics queries: top deterministic rules by correction rate, LLM weak categories, merchants cycling between promotion/demotion
- [ ] 11.5 Build metrics dashboard: track deterministic hit rate, LLM invocation rate, correction rate, promotion rate, demotion rate, recap completion rate, per-category accuracy, and cost per transaction over time
