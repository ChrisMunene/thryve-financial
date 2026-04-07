## ADDED Requirements

### Requirement: Two-layer categorization pipeline
The system SHALL process each incoming transaction through a two-layer pipeline: a deterministic layer first, then an LLM layer as fallback. The deterministic layer SHALL attempt classification using user overrides, exact merchant lookup, pattern/prefix rules, and MCC code mapping, in that priority order. Each layer SHALL return a category (primary + sub-category) and a confidence score between 0 and 1.

#### Scenario: Transaction matches deterministic layer with high confidence
- **WHEN** a transaction with merchant name "WALMART SUPERCENTER #1234" arrives
- **THEN** the deterministic layer returns category "Shopping > General" with confidence ≥ 0.9 and the LLM layer is NOT invoked

#### Scenario: Transaction falls below deterministic confidence threshold
- **WHEN** a transaction with merchant name "SQ *JOSE'S TACO 512" arrives and the deterministic layer returns confidence < 0.8
- **THEN** the system routes the transaction to the LLM layer for classification

#### Scenario: LLM layer classifies with high confidence
- **WHEN** the LLM layer processes a transaction and returns confidence ≥ 0.8
- **THEN** the system accepts the LLM category as the final classification

#### Scenario: Both layers return low confidence
- **WHEN** the deterministic layer returns confidence < 0.8 and the LLM layer returns confidence < 0.8
- **THEN** the system assigns the LLM's best-guess category and flags the transaction for user review in the weekly recap

### Requirement: Merchant key resolution
The system SHALL resolve merchant identity using Pave's pavePrettyName as the primary key. When pavePrettyName is unavailable, the system SHALL fall back to Plaid's prettyName, then to a normalized form of the raw merchant name. The resolved merchant key SHALL be used for lookup table matching, user display, and correction aggregation.

#### Scenario: Pave name preferred
- **WHEN** a transaction has raw name "DD *DOORDASH BETOSMEXI", Plaid prettyName "Betosmexi", and Pave pavePrettyName "DoorDash"
- **THEN** the merchant key is "DoorDash"

#### Scenario: Pave unavailable, Plaid fallback
- **WHEN** a transaction has Plaid prettyName "Tpumps" and no Pave pavePrettyName
- **THEN** the merchant key is "Tpumps"

#### Scenario: Both unavailable, raw name normalized
- **WHEN** a transaction has only raw name "SQ *TIKI JIMS BROADWAY" with no vendor pretty names
- **THEN** the merchant key is the normalized form of the raw name

### Requirement: Deterministic layer lookup priority
The deterministic layer SHALL resolve categories in the following priority order: (1) user override for this merchant (from user_overrides table), (2) universal rule for this merchant (from merchant_rules table, status="universal"), (3) exact merchant key match in the seed lookup table (SQLite), (4) prefix/pattern match via rules, (5) MCC code mapping. The user_overrides and merchant_rules tables are live Postgres state, separate from the static seed lookup table. The highest-priority match that exceeds the confidence threshold SHALL be used.

#### Scenario: User override takes highest priority
- **WHEN** User A has overridden "Costco" to "Food & Dining > Groceries" and a universal rule says "Shopping > General"
- **THEN** User A's transaction uses the override ("Food & Dining > Groceries") with confidence 1.0

#### Scenario: Universal rule takes priority over seed lookup
- **WHEN** "SQ *JOSE'S TACO" has a universal rule mapping to "Food & Dining > Restaurants" and no user override exists
- **THEN** the universal rule is used with confidence 0.95, and the seed lookup table is not consulted

#### Scenario: Seed lookup used when no override or universal rule
- **WHEN** a transaction has merchant key "McDonald's" with no user override and no merchant_rules entry
- **THEN** the seed lookup table match is used

#### Scenario: No exact match, falls to pattern
- **WHEN** a transaction has raw name "CHICK-FIL-A #02847" with no override, no universal rule, and no exact seed lookup match, but matches the pattern "CHICK-FIL-A*"
- **THEN** the pattern rule result is used with slightly lower confidence than an exact match

#### Scenario: Ambiguous merchant lowers confidence
- **WHEN** a transaction's merchant key has a merchant_rules entry with status="ambiguous" and no user override exists
- **THEN** the system applies the best-guess category but with reduced confidence (≤ 0.6) to ensure it surfaces in the weekly recap

### Requirement: Merchant name pattern matching
The deterministic layer SHALL normalize raw merchant names by uppercasing and stripping trailing digits and special characters. It SHALL then attempt progressively shorter prefix matches. Known platform prefixes (SQ *, DD *, SP ) SHALL be recognized and handled: DD * always maps to "Food & Dining > Food Delivery", SQ * and SP  are routed to LLM with the post-prefix name as context.

#### Scenario: DoorDash prefix recognized
- **WHEN** a transaction has raw name "DD *DOORDASH BETOSMEXI"
- **THEN** the prefix "DD *" is recognized and the transaction is categorized as "Food & Dining > Food Delivery" with high confidence

#### Scenario: Square prefix delegates to LLM
- **WHEN** a transaction has raw name "SQ *TIKI JIMS BROADWAY"
- **THEN** the prefix "SQ *" is recognized as a Square POS merchant and the post-prefix name "TIKI JIMS BROADWAY" is sent to the LLM for classification

### Requirement: EWA merchant explicit identification
The deterministic layer SHALL maintain an explicit list of known Earned Wage Access / cash advance merchants (Earnin, Dave, Brigit, Cleo, Albert, Floatme, Klover, MoneyLion, Chime MyPay, Credit Genie, Flex Finance, Ava Finance, Vola Finance, True Finance, Tilt Finance). Transactions from these merchants SHALL be categorized as "Debt & Loans > Cash Advance / EWA" regardless of vendor labels.

#### Scenario: EWA merchant overrides Plaid label
- **WHEN** a transaction from "Earnin" arrives with Plaid detailedName "GENERAL_SERVICES_ACCOUNTING_AND_FINANCIAL_PLANNING"
- **THEN** it is categorized as "Debt & Loans > Cash Advance / EWA", not "Bills > Other Bills"

### Requirement: LLM prompt assembly
The LLM prompt SHALL be assembled from five components: (1) system instructions with domain rules (static), (2) full taxonomy definition with inline merchant examples (static), (3) dynamically selected few-shot examples (8-12 per call), (4) user context — last 5 categorized transactions plus user corrections for similar merchants (dynamic), and (5) the current transaction with structured JSON output format. The system rules SHALL encode domain knowledge including platform prefix conventions (SQ*, DD*, SP, TST*), transfer signal words, and EWA override rules.

#### Scenario: Prompt includes relevant few-shot examples
- **WHEN** a transaction with prefix "SQ *" is sent to the LLM
- **THEN** the prompt includes at least 2 examples of SQ* transactions from the few-shot pool, showing different category outcomes

#### Scenario: Prompt includes user corrections for consistency
- **WHEN** a user has previously corrected "SQ *JOSE'S TACO" to "Food & Dining > Restaurants"
- **THEN** the user context section includes this correction as a personalization signal

#### Scenario: Prompt includes taxonomy with inline merchant examples
- **WHEN** the LLM processes any transaction
- **THEN** the taxonomy section lists all 14 primary categories with sub-categories, each sub-category annotated with 2-3 representative merchant names

### Requirement: Dynamic few-shot example selection
The LLM layer SHALL select 8-12 few-shot examples per call from a pool of 50-80 tagged examples using a deterministic scoring function. Selection SHALL prioritize: prefix match (strongest), amount range similarity, payment channel match, and difficulty level. Selection SHALL ensure category spread — at least one example from each plausible category for the transaction. The same input SHALL always produce the same example selection for debuggability.

#### Scenario: Prefix match prioritized
- **WHEN** a transaction with prefix "SQ *" is scored against the example pool
- **THEN** examples tagged with "sq_prefix" receive the highest score boost and are selected first

#### Scenario: Category spread ensured
- **WHEN** top-scoring examples are all from "Food & Dining"
- **THEN** the selector adds at least one example from other plausible categories (Shopping, Personal Care, Entertainment) to avoid bias

#### Scenario: Selection is deterministic
- **WHEN** the same transaction is processed twice
- **THEN** the same set of few-shot examples is selected both times

### Requirement: LLM output with mandatory reasoning
The LLM SHALL return a structured JSON response containing: primary category, sub-category, confidence score (0-1), and a reasoning field explaining the categorization logic. The reasoning field is mandatory — responses without reasoning SHALL be treated as malformed. On malformed response, the system SHALL retry once, then fall back to "Other > Uncategorized" with confidence below 0.5.

#### Scenario: Valid LLM response
- **WHEN** the LLM categorizes "SQ *TIKI JIMS BROADWAY"
- **THEN** the response includes `{"primary": "Food & Dining", "sub": "Restaurants", "confidence": 0.85, "reasoning": "SQ* prefix = Square POS. TIKI JIMS sounds like a bar/restaurant..."}`

#### Scenario: Malformed response triggers retry
- **WHEN** the LLM returns a response that cannot be parsed as valid JSON or is missing the reasoning field
- **THEN** the system retries once with the same prompt

#### Scenario: Persistent failure falls back to Uncategorized
- **WHEN** the LLM fails to return a valid response after one retry
- **THEN** the system returns "Other > Uncategorized" with confidence 0.3 and flags the transaction for user review

### Requirement: LLM layer context enrichment
The LLM layer SHALL receive the following transaction context: raw merchant name, resolved merchant key (if available), transaction amount, payment channel (in-store/online/other), and location (city/state when available).

#### Scenario: LLM uses location for disambiguation
- **WHEN** a transaction with merchant name "SQUARE *THE SPOT" and location "Austin, TX" is sent to the LLM
- **THEN** the LLM uses location and merchant context to determine the most likely category

#### Scenario: LLM uses amount as signal
- **WHEN** a transaction at an unknown merchant has amount $7.99 and is online
- **THEN** the LLM considers that this amount pattern suggests a subscription or small digital purchase

### Requirement: Promotion mechanism
The system SHALL automatically promote LLM classifications to the deterministic layer when a merchant key has been classified by the LLM with ≥ 0.9 confidence to the same category across ≥ 3 distinct users. Promoted entries SHALL be added to the exact merchant lookup table.

#### Scenario: Merchant reaches promotion threshold
- **WHEN** "Tiki Jim's" has been classified as "Food & Dining > Restaurants" by the LLM with ≥ 0.9 confidence for 3 different users
- **THEN** the mapping "Tiki Jim's → Food & Dining > Restaurants" is added to the deterministic lookup table

#### Scenario: Inconsistent LLM results prevent promotion
- **WHEN** a merchant is classified differently across users with no single category reaching 90% agreement
- **THEN** the merchant is NOT promoted to the deterministic layer

### Requirement: Categorization response time
The deterministic layer SHALL return results within 5ms. The full pipeline (including LLM fallback) SHALL return results within 3 seconds.

#### Scenario: Deterministic fast path
- **WHEN** a transaction is resolved by the deterministic layer
- **THEN** the response time is under 5ms

#### Scenario: LLM fallback path
- **WHEN** a transaction requires LLM classification
- **THEN** the response time is under 3 seconds
