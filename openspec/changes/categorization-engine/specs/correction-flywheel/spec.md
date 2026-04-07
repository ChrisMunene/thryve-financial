## ADDED Requirements

### Requirement: Correction event logging
Every user interaction with a transaction's category — whether a correction or a confirmation — SHALL be recorded as an immutable, append-only event. Each event SHALL capture the user, transaction, merchant key, the original and target categories, the event type, the source (weekly recap or inline), and the engine context at the time of the event (which layer produced the original category, its confidence score, and the rule ID if applicable).

#### Scenario: Correction event recorded with engine context
- **WHEN** User A corrects a transaction from "Shopping > General" to "Food & Dining > Groceries" during the weekly recap, where the original was produced by the deterministic lookup with confidence 0.92
- **THEN** a correction_event is stored with event_type="correction", source="weekly_recap", engine_source="deterministic", engine_confidence=0.92, and the relevant rule ID

#### Scenario: Confirmation event recorded
- **WHEN** User A taps "confirm" on a transaction categorized as "Food & Dining > Fast Food" during the weekly recap
- **THEN** a correction_event is stored with event_type="confirmation", from and to categories identical, source="weekly_recap"

#### Scenario: Events are immutable
- **WHEN** a user corrects the same merchant multiple times (e.g. first to Groceries, then back to Shopping)
- **THEN** both events are stored; the most recent correction determines the user's current override

### Requirement: User override — synchronous
When a user corrects a transaction's category, the system SHALL immediately (synchronously) update the user's override for that merchant key. The override SHALL apply to all future transactions from that user with the same resolved merchant key. The override SHALL NOT affect other users' categorizations. The merchant key used for overrides SHALL be the resolved key (Pave → Plaid → normalized), not the raw merchant string.

#### Scenario: Override applies to all locations of same merchant
- **WHEN** User A corrects "COSTCO WHSE #1234" (merchant key "Costco") to "Food & Dining > Groceries"
- **THEN** a future transaction from "COSTCO WHSE #5678" (also merchant key "Costco") for User A is categorized as "Food & Dining > Groceries"

#### Scenario: Override is user-scoped
- **WHEN** User A has overridden "Costco" to "Food & Dining > Groceries"
- **THEN** User B's "Costco" transactions are still categorized by the default engine

#### Scenario: Latest correction wins
- **WHEN** User A corrects "Costco" to "Food & Dining > Groceries", then later corrects it back to "Shopping > General"
- **THEN** the override for User A is "Shopping > General"

### Requirement: Crowd aggregation — asynchronous hourly batch
The system SHALL recompute correction aggregates per merchant key on an hourly batch schedule. Aggregation SHALL group correction events by merchant key and target category, counting distinct correcting users, total corrections, and total confirmations. Confirmations SHALL contribute to the weighted score at 0.5 weight (corrections at 1.0 weight). The aggregation SHALL NOT block user-facing operations.

#### Scenario: Hourly aggregation runs
- **WHEN** the hourly batch job executes
- **THEN** correction_aggregates are recomputed from all correction_events, with weighted_score = (corrections × 1.0 + confirmations × 0.5) per category per merchant

#### Scenario: Confirmation has lower weight than correction
- **WHEN** a merchant has 5 corrections to Category A and 20 confirmations of Category B
- **THEN** Category A weighted score = 5.0 and Category B weighted score = 10.0 (not 20.0)

### Requirement: Candidate rule promotion
When 5 or more distinct users have corrected a merchant to the same category and the correction-only agreement rate (excluding confirmations) is ≥ 90%, the system SHALL promote the merchant to a universal rule. Promotion SHALL add the rule to the merchant_rules table with status "universal" and the resolved category. Universal rules are a separate store from the seeded lookup table — they are checked at priority 2 (after user overrides, before the seed lookup).

#### Scenario: Correction reaches promotion threshold
- **WHEN** 6 distinct users have corrected "SQ *JOSE'S TACO" to "Food & Dining > Restaurants" and no users have corrected it to a different category
- **THEN** the merchant_rules entry is created with status="universal", resolved to "Food & Dining > Restaurants"

#### Scenario: Correction below threshold is not promoted
- **WHEN** only 3 users have corrected "SQ *TIKI JIMS" to "Food & Dining > Restaurants"
- **THEN** no merchant_rules entry is created; individual user overrides continue to apply

#### Scenario: Universal rule applies to users without overrides
- **WHEN** "SQ *JOSE'S TACO" is a universal rule mapping to "Food & Dining > Restaurants"
- **THEN** a new user's transaction from "SQ *JOSE'S TACO" is categorized as "Food & Dining > Restaurants" with confidence 0.95

#### Scenario: Personal override takes precedence over universal rule
- **WHEN** User A has a personal override for "Costco → Food & Dining > Groceries" and a universal rule says "Costco → Shopping > General"
- **THEN** User A's transactions use their personal override

### Requirement: Demotion mechanism
When a universal rule exists and 3 or more distinct users submit corrections *against* that rule (corrections created after the rule's promoted_at timestamp), the system SHALL demote the rule. Demotion SHALL set the status to "demoted", record the demotion timestamp and reason, remove the merchant from the universal rules store, and reset the aggregation window so the merchant is re-evaluated from fresh correction data. The merchant SHALL re-enter LLM evaluation for new transactions.

#### Scenario: Universal rule demoted after disagreement
- **WHEN** "SQ *JOSE'S TACO" was promoted as "Food & Dining > Restaurants" on Day 10, and on Day 65 three users correct it to "Shopping > General"
- **THEN** the rule is demoted: status="demoted", demotion_reason="user_corrections_post_promotion", and the merchant re-enters LLM evaluation

#### Scenario: Promotion churn tracked
- **WHEN** a merchant is promoted, demoted, and promoted again
- **THEN** the promotion_count field tracks the number of promotions, flagging merchants that churn between states for manual review

#### Scenario: Existing user overrides preserved on demotion
- **WHEN** a universal rule is demoted
- **THEN** all user_overrides for that merchant remain intact — only the universal rule is removed

### Requirement: Ambiguous merchant detection
When corrections for a merchant are split — no single target category receives ≥ 70% of correction-only agreement from 5+ correcting users — AND the overall correction rate exceeds 30% of all interacting users, the system SHALL flag that merchant as "ambiguous." Ambiguous merchants SHALL NOT be promoted to universal rules. The system SHALL store the top category distribution for ambiguous merchants. New users encountering an ambiguous merchant SHALL have it surfaced in the weekly recap for explicit preference selection.

#### Scenario: Merchant flagged as ambiguous
- **WHEN** 10 users have corrected "COSTCO": 5 to "Food & Dining > Groceries" and 5 to "Shopping > General", and correction_rate = 10/14 = 71%
- **THEN** "COSTCO" is flagged as ambiguous with top_categories showing the 50/50 split

#### Scenario: Low correction rate means default holds
- **WHEN** 100 users interact with "Walmart": 8 correct to various categories, 92 confirm the default
- **THEN** correction_rate = 8% (< 30%) — merchant is NOT flagged as ambiguous; the default holds

#### Scenario: Ambiguous merchant surfaced in recap
- **WHEN** a new user has a transaction from ambiguous merchant "COSTCO" with no personal override
- **THEN** the system applies its best-guess category but surfaces it in the weekly recap for the user to confirm or correct

### Requirement: Default assumption override via correction volume
When the system uses a default category mapping that was a deliberate design choice (e.g., convenience stores → Food & Dining), and the correction rate exceeds 50% across a statistically significant sample (50+ total interactions), the system SHALL flag that default for review and potential taxonomy update by setting status to "default_challenged."

#### Scenario: Convenience store default challenged
- **WHEN** 60 users have corrected convenience store transactions away from "Food & Dining > Convenience Stores" and only 30 users have confirmed the original
- **THEN** the default mapping is flagged with status="default_challenged"

#### Scenario: Default holds
- **WHEN** 100 users have interacted with convenience store categorization and only 15 corrected away
- **THEN** correction_rate = 15% (< 50%) — the default mapping is retained

### Requirement: Correction data feeds model training with weighted signals
All correction and confirmation data SHALL be exported to the training pipeline on a weekly cadence. Each training example SHALL carry a weight based on its source:
- Universal rule (crowd-validated): weight 1.0
- User correction (individual): weight 0.5
- User confirmation: weight 0.3
- Vendor agreement (Plaid + Pave baseline): weight 0.2

The system SHALL track the source of each training example for data quality auditing.

#### Scenario: Universal rule in training data
- **WHEN** "SQ *JOSE'S TACO → Food & Dining > Restaurants" becomes a universal rule
- **THEN** it is added to the training dataset with source="user_correction_universal" and weight=1.0

#### Scenario: User confirmation in training data
- **WHEN** a user confirms "MCDONALD'S → Food & Dining > Fast Food" is correct
- **THEN** it is added to the training dataset with source="user_confirmation" and weight=0.3

#### Scenario: Demoted rule removed from training
- **WHEN** a universal rule is demoted
- **THEN** its training examples are flagged for re-evaluation in the next training cycle

### Requirement: Diagnostic query support
The correction_events log with engine context SHALL support diagnostic queries: identifying which deterministic rules generate the most corrections, which LLM prompt patterns produce low confidence, and which merchants cycle between promotion and demotion.

#### Scenario: Identify problematic rules
- **WHEN** an operator queries for deterministic rules with the highest correction rate
- **THEN** the system returns a ranked list of rule IDs by (corrections / total_transactions) showing which rules need refinement

#### Scenario: Identify LLM weak spots
- **WHEN** an operator queries for LLM-categorized transactions with the highest correction rate grouped by primary category
- **THEN** the system shows which categories the LLM struggles with most
