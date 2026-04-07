## ADDED Requirements

### Requirement: Seed data extraction from globaltransactions
The system SHALL process the 460M globaltransactions corpus to build the initial deterministic lookup table and LLM training examples. The pipeline SHALL extract merchant name → category mappings using vendor agreement as the quality signal. The pipeline SHALL use Pave's pavePrettyName as the primary merchant key, falling back to Plaid's prettyName, then normalized raw name.

#### Scenario: Gold label extraction
- **WHEN** a transaction has Plaid confidenceLevel "VERY_HIGH" and the Pave primary tag maps to the same internal primary category as the Plaid primaryName
- **THEN** the transaction is classified as a "gold label" and used to seed the deterministic lookup table

#### Scenario: Hard case extraction
- **WHEN** a transaction has Plaid and Pave labels that map to different internal primary categories
- **THEN** the transaction is classified as a "hard case" and reserved for LLM benchmark testing

#### Scenario: Vendor labels mapped through internal taxonomy
- **WHEN** a transaction has Plaid detailedName "GENERAL_SERVICES_ACCOUNTING_AND_FINANCIAL_PLANNING" and merchant is an EWA provider
- **THEN** the pipeline maps it to "Debt & Loans > Cash Advance / EWA" using the internal taxonomy mapping, overriding the Plaid label

### Requirement: Transfer and non-spend data included in training
The pipeline SHALL include all transaction types in training data — including transfers (41.6% of corpus), debt payments, income, and fees. The engine must correctly categorize non-spend transactions so downstream features can reliably exclude them from budget totals.

#### Scenario: Transfer sub-types distinguished in training
- **WHEN** processing transfer transactions for training
- **THEN** the pipeline distinguishes internal transfers, savings transfers, P2P payments, ATM withdrawals, investment transfers, and cash advances as separate sub-categories

#### Scenario: P2P transactions labeled in training
- **WHEN** a Cash App, Venmo, or Zelle transaction appears in training data
- **THEN** it is labeled as "Transfers > Peer-to-Peer" by default

### Requirement: Merchant lookup table seeding
The pipeline SHALL aggregate gold-label transactions by merchant key (pavePrettyName preferred) and compute the most common internal category mapping. Merchants with ≥ 100 gold-label transactions and ≥ 95% agreement on a single category SHALL be added to the deterministic lookup table with confidence 1.0.

#### Scenario: High-volume merchant added to lookup
- **WHEN** "McDonald's" has 50,000 gold-label transactions and 99% map to "Food & Dining > Fast Food"
- **THEN** "McDonald's" is added to the lookup table as "Food & Dining > Fast Food" with confidence 1.0

#### Scenario: Low-volume merchant not added
- **WHEN** "Tiki Jim's" has only 3 gold-label transactions
- **THEN** it is NOT added to the deterministic lookup table (falls to pattern rules or LLM)

#### Scenario: EWA merchants seeded with override
- **WHEN** the lookup table is built
- **THEN** all known EWA merchants (Earnin, Dave, Brigit, Cleo, etc.) are added as "Debt & Loans > Cash Advance / EWA" regardless of their vendor label agreement

### Requirement: Pattern rule generation
The pipeline SHALL identify common merchant name prefixes/patterns from the gold-label data and generate pattern rules. Patterns SHALL be generated when a prefix covers ≥ 50 distinct raw merchant name variants all mapping to the same category. The pipeline SHALL also generate rules for known platform prefixes (DD *, SQ *, SP ).

#### Scenario: Pattern rule generated from variants
- **WHEN** the corpus contains "CHICK-FIL-A #00709", "CHICK-FIL-A #02847", "CHICK-FIL-A #01234" (50+ variants) all mapping to "Food & Dining > Fast Food"
- **THEN** a pattern rule "CHICK-FIL-A*" → "Food & Dining > Fast Food" is generated

#### Scenario: Platform prefix rule generated
- **WHEN** the corpus shows "DD *" prefix transactions consistently map to "Food & Dining > Food Delivery"
- **THEN** a prefix rule "DD *" → "Food & Dining > Food Delivery" is generated with high confidence

### Requirement: Gambling merchant identification
The pipeline SHALL build an explicit gambling merchant list from the corpus. Merchants categorized as "ENTERTAINMENT_CASINOS_AND_GAMBLING" by Plaid with ≥ 100 transactions SHALL be added to a gambling merchant list for the deterministic layer.

#### Scenario: Gambling merchants extracted
- **WHEN** the pipeline processes the corpus
- **THEN** FanDuel, DraftKings, Crown Coins Casino, Hard Rock Bet, BetMGM, PrizePicks, and all other gambling merchants with ≥ 100 transactions are added to the gambling merchant list

### Requirement: LLM few-shot example pool generation
The pipeline SHALL generate a tagged pool of 50-80 few-shot examples for dynamic selection at LLM inference time. Each example SHALL include: raw merchant name, merchant key, amount, payment channel, location (if available), the correct categorization result (primary, sub, confidence, reasoning), and selection metadata tags (prefix type, amount range, channel, difficulty level, primary category).

The pool SHALL contain:
- **Prefix examples (15-20):** 3-4 SQ* (restaurant, salon, retail, service), 3-4 SP (Shopify — various), 2-3 DD* (delivery), 2 TST* (Toast POS), 2-3 MC Platinum DC (credit union POS with messy strings)
- **Category anchors (14-20):** 1-2 per primary category, the clearest representative
- **Ambiguous cases (8-10):** Costco, CVS/Walgreens, Apple (subscription vs product), 7-Eleven, Venmo, merchants with mixed vendor labels
- **Edge cases (5-8):** Merchants where the name is misleading (e.g., Animal Jam is a game not veterinary), refund patterns, university payments, casino-hotels, Cleo subscription vs EWA

Each example SHALL include a reasoning field demonstrating chain-of-thought categorization logic.

#### Scenario: Pool covers all categories
- **WHEN** the few-shot pool is generated
- **THEN** at least 2 examples exist for each of the 14 primary categories

#### Scenario: Prefix examples cover common patterns
- **WHEN** the pool is generated
- **THEN** at least 3 SQ* examples are included showing different category outcomes (restaurant, salon, retail)

#### Scenario: Transfer disambiguation examples included
- **WHEN** the pool is generated
- **THEN** it includes examples distinguishing internal transfers, P2P payments (Venmo/Zelle), savings transfers, ATM withdrawals, and cash advances

#### Scenario: Ambiguous merchant examples included
- **WHEN** a merchant like "Costco" has mixed categorizations in the training data
- **THEN** the pool includes an example showing how context (amount, user history) can disambiguate

#### Scenario: Edge case examples show reasoning through misleading names
- **WHEN** the pool is generated
- **THEN** it includes at least 2 examples where the merchant name is misleading (e.g., "Animal Jam" → Entertainment > Gaming, not Health > Doctor & Dental)

#### Scenario: Examples are tagged for dynamic selection
- **WHEN** each example is generated
- **THEN** it is tagged with prefix type (sq_prefix, dd_prefix, sp_prefix, tst_prefix, or none), amount range (micro, small, medium, large), channel (in_store, online), difficulty (easy, medium, hard), and primary category

### Requirement: Few-shot pool output format
The pool SHALL be output as a JSON file (few_shot_pool.json) where each entry is a complete example with selection metadata. This file SHALL be loaded by the API server on startup and used by the dynamic few-shot selector at inference time.

#### Scenario: Pool file is loadable
- **WHEN** the API server starts
- **THEN** it loads few_shot_pool.json into memory and validates that all examples have complete tags and valid category references

### Requirement: Training/validation/test split
The pipeline SHALL split the processed data into training (70%), validation (15%), and test (15%) sets. The test set SHALL be enriched with hard cases (vendor disagreement) to ensure the LLM is evaluated on the most challenging transactions. The split SHALL be stratified by primary category to ensure representation across all 14 categories.

#### Scenario: Stratified split
- **WHEN** the data is split into train/val/test
- **THEN** each split contains proportional representation of all 14 primary categories

#### Scenario: Hard cases concentrated in test set
- **WHEN** the test set is constructed
- **THEN** at least 30% of the test set consists of hard cases (vendor disagreement)

### Requirement: Ongoing retraining from user corrections
The pipeline SHALL support incremental retraining. Universal rules and user confirmations SHALL be added to the training dataset on a weekly cadence. The system SHALL track accuracy metrics before and after each retraining cycle to detect regressions.

#### Scenario: Weekly retraining incorporates corrections
- **WHEN** the weekly retraining cycle runs
- **THEN** all new universal rules and user confirmations from the past week are included in the training data

#### Scenario: Regression detection
- **WHEN** accuracy on the held-out test set drops by ≥ 2% after retraining
- **THEN** the system raises an alert and does not deploy the new model version

### Requirement: Pipeline report generation
The pipeline SHALL generate a report after each run containing: total transactions processed, gold/silver/hard-case/unknown label distribution, lookup table size and coverage percentage, pattern rules generated, uncovered high-volume merchants, and accuracy estimates.

#### Scenario: Report generated
- **WHEN** the pipeline completes a run
- **THEN** a report is generated showing the lookup table covers ≥ 80% of transaction volume and listing the top 50 uncovered merchants by volume
