## ADDED Requirements

### Requirement: Weekly recap generation
The system SHALL generate a weekly recap for each active user every 7 days. The recap SHALL contain all transactions from the past week, grouped by primary category, with total spend per category and a comparison to the prior week.

#### Scenario: Recap generated on schedule
- **WHEN** 7 days have elapsed since the user's last recap
- **THEN** a new recap is generated covering all transactions in that 7-day period

#### Scenario: Recap groups by category
- **WHEN** a recap is generated for a user with 25 transactions across 5 categories
- **THEN** the recap displays transactions grouped under each primary category with subtotals

### Requirement: Low-confidence transaction surfacing
The recap SHALL highlight transactions that were categorized with low confidence (below the confirmation threshold) and transactions from ambiguous merchants. These SHALL be surfaced prominently for the user to confirm or correct. The system SHALL surface a maximum of 10 low-confidence transactions per recap to avoid overwhelming the user.

#### Scenario: Low-confidence transactions highlighted
- **WHEN** a recap contains 3 transactions flagged as low-confidence
- **THEN** those 3 transactions appear in a dedicated "Review These" section at the top of the recap

#### Scenario: Cap at 10 review items
- **WHEN** a user has 15 low-confidence transactions in a given week
- **THEN** only the 10 lowest-confidence transactions are surfaced for review, with the remaining 5 auto-categorized at best-guess

### Requirement: Single-tap confirmation
For each transaction in the recap, the user SHALL be able to confirm the category with a single tap. Confirmation SHALL count as a positive training signal for the correction flywheel.

#### Scenario: User confirms a transaction
- **WHEN** a user taps "confirm" on a transaction categorized as "Food & Dining > Fast Food"
- **THEN** the confirmation is recorded and the transaction is no longer flagged for review

### Requirement: Category correction in recap
For each transaction in the recap, the user SHALL be able to change the category by selecting from the taxonomy. The correction flow SHALL require at most 2 taps: one to open the category picker, one to select the new category.

#### Scenario: User corrects a category
- **WHEN** a user changes a transaction from "Shopping > General" to "Food & Dining > Groceries"
- **THEN** the correction is saved as a user override and fed into the correction flywheel

### Requirement: Recap completion tracking
The system SHALL track whether the user completed their weekly recap (viewed + confirmed/corrected all flagged items). Completion rate SHALL be available as a metric for engagement tracking.

#### Scenario: Recap marked complete
- **WHEN** a user has confirmed or corrected all flagged transactions in their recap
- **THEN** the recap is marked as "complete"

#### Scenario: Recap partially complete
- **WHEN** a user reviews 3 of 5 flagged transactions and leaves the recap
- **THEN** the recap is marked as "partial" with 3/5 items resolved
