"""
Category taxonomy: 14 primary categories, ~50 sub-categories.
Categories 1-10 are "spend" (included in budget totals).
Categories 11-14 are "non-spend" (excluded from budget totals).
"""

from dataclasses import dataclass, field
from enum import Enum


class SpendType(str, Enum):
    SPEND = "spend"
    NON_SPEND = "non_spend"


@dataclass(frozen=True)
class SubCategory:
    id: str
    name: str
    examples: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PrimaryCategory:
    id: str
    name: str
    spend_type: SpendType
    sub_categories: list[SubCategory] = field(default_factory=list)

    def get_sub(self, sub_id: str) -> SubCategory | None:
        return next((s for s in self.sub_categories if s.id == sub_id), None)

    @property
    def sub_ids(self) -> list[str]:
        return [s.id for s in self.sub_categories]


# === SPEND CATEGORIES (1-10) ===

FOOD_AND_DINING = PrimaryCategory(
    id="food_and_dining",
    name="Food & Dining",
    spend_type=SpendType.SPEND,
    sub_categories=[
        SubCategory("groceries", "Groceries", ["Kroger", "Aldi", "Safeway", "Publix", "H-E-B"]),
        SubCategory("restaurants", "Restaurants", ["Olive Garden", "Applebee's", "local restaurants"]),
        SubCategory("fast_food", "Fast Food", ["McDonald's", "Chick-fil-A", "Taco Bell", "Wendy's"]),
        SubCategory("coffee_shops", "Coffee Shops", ["Starbucks", "Dunkin'", "Peet's"]),
        SubCategory("food_delivery", "Food Delivery", ["DoorDash", "Uber Eats", "Grubhub"]),
        SubCategory("alcohol_and_bars", "Alcohol & Bars", ["liquor stores", "bars", "breweries"]),
        SubCategory("convenience_stores", "Convenience Stores", ["7-Eleven", "Casey's", "Wawa"]),
        SubCategory("vending_and_snacks", "Vending & Snacks", ["vending machines", "snack shops"]),
    ],
)

SHOPPING = PrimaryCategory(
    id="shopping",
    name="Shopping",
    spend_type=SpendType.SPEND,
    sub_categories=[
        SubCategory("general", "General", ["Walmart", "Amazon", "Target", "Costco"]),
        SubCategory("clothing", "Clothing", ["Nike", "H&M", "Zara", "Old Navy"]),
        SubCategory("electronics", "Electronics", ["Best Buy", "Apple Store", "Newegg"]),
        SubCategory("home_and_furniture", "Home & Furniture", ["Home Depot", "Lowe's", "IKEA"]),
        SubCategory("pet_supplies", "Pet Supplies", ["PetSmart", "Petco", "Chewy"]),
        SubCategory("sporting_goods", "Sporting Goods", ["Dick's", "REI", "Academy Sports"]),
    ],
)

TRANSPORTATION = PrimaryCategory(
    id="transportation",
    name="Transportation",
    spend_type=SpendType.SPEND,
    sub_categories=[
        SubCategory("gas", "Gas", ["Shell", "Chevron", "BP", "ExxonMobil", "Circle K"]),
        SubCategory("rideshare", "Rideshare", ["Uber", "Lyft"]),
        SubCategory("public_transit", "Public Transit", ["MTA", "BART", "CTA", "Metro"]),
        SubCategory("parking_and_tolls", "Parking & Tolls", ["ParkMobile", "E-ZPass"]),
        SubCategory("auto_maintenance", "Auto Maintenance", ["AutoZone", "Jiffy Lube", "Midas"]),
    ],
)

BILLS = PrimaryCategory(
    id="bills",
    name="Bills",
    spend_type=SpendType.SPEND,
    sub_categories=[
        SubCategory("rent_mortgage", "Rent / Mortgage", ["landlord", "mortgage company"]),
        SubCategory("electricity_and_gas", "Electricity & Gas", ["electric company", "gas utility"]),
        SubCategory("water_and_sewer", "Water & Sewer", ["water utility"]),
        SubCategory("internet_and_phone", "Internet & Phone", ["AT&T", "Verizon", "T-Mobile", "Comcast"]),
        SubCategory("insurance", "Insurance", ["Progressive", "Geico", "State Farm", "Allstate"]),
        SubCategory("subscriptions", "Subscriptions", ["Amazon Prime", "Google One", "iCloud"]),
        SubCategory("other_bills", "Other Bills", ["childcare", "storage", "HOA"]),
    ],
)

ENTERTAINMENT = PrimaryCategory(
    id="entertainment",
    name="Entertainment",
    spend_type=SpendType.SPEND,
    sub_categories=[
        SubCategory("streaming", "Streaming", ["Netflix", "Spotify", "Disney+", "Hulu", "YouTube"]),
        SubCategory("gaming", "Gaming", ["Xbox", "PlayStation", "Steam", "Nintendo", "Animal Jam"]),
        SubCategory("events_and_activities", "Events & Activities", ["movies", "concerts", "museums"]),
        SubCategory("other_entertainment", "Other Entertainment", ["hobbies", "recreation"]),
    ],
)

GAMBLING = PrimaryCategory(
    id="gambling",
    name="Gambling",
    spend_type=SpendType.SPEND,
    sub_categories=[
        SubCategory("gambling", "Gambling", ["FanDuel", "DraftKings", "BetMGM", "PrizePicks", "Chumba Casino"]),
    ],
)

HEALTH = PrimaryCategory(
    id="health",
    name="Health",
    spend_type=SpendType.SPEND,
    sub_categories=[
        SubCategory("pharmacy", "Pharmacy", ["CVS", "Walgreens", "Rite Aid"]),
        SubCategory("doctor_and_dental", "Doctor & Dental", ["doctor", "dentist", "hospital"]),
        SubCategory("gym_and_fitness", "Gym & Fitness", ["Planet Fitness", "LA Fitness", "CrossFit"]),
        SubCategory("vision", "Vision", ["LensCrafters", "Warby Parker"]),
        SubCategory("health_insurance", "Health Insurance", ["health insurance premiums"]),
    ],
)

PERSONAL_CARE = PrimaryCategory(
    id="personal_care",
    name="Personal Care",
    spend_type=SpendType.SPEND,
    sub_categories=[
        SubCategory("hair_and_beauty", "Hair & Beauty", ["salons", "barbershops", "Sephora", "Ulta"]),
        SubCategory("laundry_and_dry_cleaning", "Laundry & Dry Cleaning", ["laundromat", "dry cleaner"]),
    ],
)

TRAVEL = PrimaryCategory(
    id="travel",
    name="Travel",
    spend_type=SpendType.SPEND,
    sub_categories=[
        SubCategory("flights", "Flights", ["United", "Delta", "Southwest", "American Airlines"]),
        SubCategory("hotels_and_lodging", "Hotels & Lodging", ["Hilton", "Marriott", "Airbnb", "Motel 6"]),
        SubCategory("rental_cars", "Rental Cars", ["Enterprise", "Hertz", "Turo"]),
        SubCategory("other_travel", "Other Travel", ["Expedia", "Booking.com", "travel agencies"]),
    ],
)

EDUCATION = PrimaryCategory(
    id="education",
    name="Education",
    spend_type=SpendType.SPEND,
    sub_categories=[
        SubCategory("education", "Education", ["tuition", "textbooks", "courses", "student fees"]),
    ],
)

# === NON-SPEND CATEGORIES (11-14) ===

TRANSFERS = PrimaryCategory(
    id="transfers",
    name="Transfers",
    spend_type=SpendType.NON_SPEND,
    sub_categories=[
        SubCategory("internal", "Internal", ["own account transfers", "between checking/savings"]),
        SubCategory("to_from_savings", "To/From Savings", ["savings transfers", "round-ups"]),
        SubCategory("peer_to_peer", "Peer-to-Peer", ["Venmo", "Zelle", "Cash App", "PayPal"]),
        SubCategory("investment", "Investment & Retirement", ["brokerage", "401k", "IRA"]),
        SubCategory("atm_withdrawal", "ATM Withdrawal", ["ATM cash withdrawal"]),
        SubCategory("other_transfer", "Other Transfer", ["wire transfer", "other"]),
    ],
)

DEBT_AND_LOANS = PrimaryCategory(
    id="debt_and_loans",
    name="Debt & Loans",
    spend_type=SpendType.NON_SPEND,
    sub_categories=[
        SubCategory("credit_card_payment", "Credit Card Payment", ["credit card bill"]),
        SubCategory("student_loan", "Student Loan", ["student loan payment"]),
        SubCategory("auto_loan", "Auto Loan", ["car payment"]),
        SubCategory("personal_loan", "Personal Loan", ["personal loan payment"]),
        SubCategory("mortgage_payment", "Mortgage Payment", ["mortgage payment"]),
        SubCategory("cash_advance_ewa", "Cash Advance / EWA", ["Earnin", "Dave", "Brigit", "Cleo"]),
    ],
)

INCOME = PrimaryCategory(
    id="income",
    name="Income",
    spend_type=SpendType.NON_SPEND,
    sub_categories=[
        SubCategory("paycheck", "Paycheck", ["direct deposit", "payroll"]),
        SubCategory("side_income_gig", "Side Income / Gig", ["freelance", "Uber driver", "DoorDash driver"]),
        SubCategory("interest_and_dividends", "Interest & Dividends", ["interest earned", "dividends"]),
        SubCategory("refunds_and_cashback", "Refunds & Cashback", ["refunds", "cashback rewards"]),
    ],
)

OTHER = PrimaryCategory(
    id="other",
    name="Other",
    spend_type=SpendType.NON_SPEND,
    sub_categories=[
        SubCategory("fees", "Fees", ["ATM fees", "overdraft fees", "foreign transaction fees"]),
        SubCategory("taxes", "Taxes", ["tax payments", "IRS"]),
        SubCategory("donations", "Donations", ["charitable donations", "GoFundMe"]),
        SubCategory("uncategorized", "Uncategorized", []),
    ],
)

# === REGISTRY ===

ALL_CATEGORIES: list[PrimaryCategory] = [
    FOOD_AND_DINING,
    SHOPPING,
    TRANSPORTATION,
    BILLS,
    ENTERTAINMENT,
    GAMBLING,
    HEALTH,
    PERSONAL_CARE,
    TRAVEL,
    EDUCATION,
    TRANSFERS,
    DEBT_AND_LOANS,
    INCOME,
    OTHER,
]

SPEND_CATEGORIES = [c for c in ALL_CATEGORIES if c.spend_type == SpendType.SPEND]
NON_SPEND_CATEGORIES = [c for c in ALL_CATEGORIES if c.spend_type == SpendType.NON_SPEND]

# Lookup maps
CATEGORY_BY_ID: dict[str, PrimaryCategory] = {c.id: c for c in ALL_CATEGORIES}
ALL_PRIMARY_IDS: set[str] = {c.id for c in ALL_CATEGORIES}
ALL_SUB_IDS: set[tuple[str, str]] = {
    (c.id, s.id) for c in ALL_CATEGORIES for s in c.sub_categories
}


def is_valid_category(primary_id: str, sub_id: str) -> bool:
    return (primary_id, sub_id) in ALL_SUB_IDS


def get_category(primary_id: str) -> PrimaryCategory | None:
    return CATEGORY_BY_ID.get(primary_id)


def is_spend(primary_id: str) -> bool:
    cat = CATEGORY_BY_ID.get(primary_id)
    return cat.spend_type == SpendType.SPEND if cat else False
