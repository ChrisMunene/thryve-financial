"""Tests for taxonomy definitions, mappings, and merchant lists."""

from app.engine.mappings import (
    EWA_MERCHANTS,
    GAMBLING_MERCHANTS,
    PAVE_TAG_TO_INTERNAL,
    PLAID_DETAILED_TO_INTERNAL,
    is_ewa_merchant,
    is_gambling_merchant,
    resolve_pave_tags,
)
from app.engine.taxonomy import (
    ALL_CATEGORIES,
    ALL_SUB_IDS,
    CATEGORY_BY_ID,
    NON_SPEND_CATEGORIES,
    SPEND_CATEGORIES,
    SpendType,
    get_category,
    is_spend,
    is_valid_category,
)


class TestTaxonomyStructure:
    def test_exactly_14_primary_categories(self):
        assert len(ALL_CATEGORIES) == 14

    def test_exactly_10_spend_categories(self):
        assert len(SPEND_CATEGORIES) == 10
        assert all(c.spend_type == SpendType.SPEND for c in SPEND_CATEGORIES)

    def test_exactly_4_non_spend_categories(self):
        assert len(NON_SPEND_CATEGORIES) == 4
        assert all(c.spend_type == SpendType.NON_SPEND for c in NON_SPEND_CATEGORIES)

    def test_all_primary_ids_unique(self):
        ids = [c.id for c in ALL_CATEGORIES]
        assert len(ids) == len(set(ids))

    def test_all_sub_ids_unique_within_primary(self):
        for cat in ALL_CATEGORIES:
            sub_ids = [s.id for s in cat.sub_categories]
            assert len(sub_ids) == len(set(sub_ids)), f"Duplicate sub_id in {cat.id}"

    def test_every_primary_has_at_least_one_sub(self):
        for cat in ALL_CATEGORIES:
            assert len(cat.sub_categories) >= 1, f"{cat.id} has no sub-categories"

    def test_total_sub_categories_in_expected_range(self):
        total = sum(len(c.sub_categories) for c in ALL_CATEGORIES)
        assert 50 <= total <= 70, f"Expected 50-70 sub-categories, got {total}"

    def test_is_valid_category(self):
        assert is_valid_category("food_and_dining", "groceries")
        assert is_valid_category("gambling", "gambling")
        assert not is_valid_category("food_and_dining", "nonexistent")
        assert not is_valid_category("nonexistent", "groceries")

    def test_get_category(self):
        cat = get_category("food_and_dining")
        assert cat is not None
        assert cat.name == "Food & Dining"
        assert get_category("nonexistent") is None

    def test_is_spend(self):
        assert is_spend("food_and_dining")
        assert is_spend("shopping")
        assert is_spend("gambling")
        assert not is_spend("transfers")
        assert not is_spend("income")
        assert not is_spend("other")

    def test_category_by_id_lookup(self):
        assert "food_and_dining" in CATEGORY_BY_ID
        assert "transfers" in CATEGORY_BY_ID
        assert len(CATEGORY_BY_ID) == 14

    def test_specific_categories_exist(self):
        expected = [
            "food_and_dining", "shopping", "transportation", "bills",
            "entertainment", "gambling", "health", "personal_care",
            "travel", "education", "transfers", "debt_and_loans",
            "income", "other",
        ]
        for cat_id in expected:
            assert cat_id in CATEGORY_BY_ID, f"Missing category: {cat_id}"


class TestPlaidMapping:
    def test_all_mappings_resolve_to_valid_categories(self):
        for plaid_name, (primary, sub) in PLAID_DETAILED_TO_INTERNAL.items():
            assert is_valid_category(primary, sub), (
                f"Plaid '{plaid_name}' maps to invalid category ({primary}, {sub})"
            )

    def test_covers_all_106_plaid_detailed_names(self):
        # All known Plaid detailedName values from the 460M corpus
        assert len(PLAID_DETAILED_TO_INTERNAL) >= 106

    def test_convenience_stores_map_to_food(self):
        primary, sub = PLAID_DETAILED_TO_INTERNAL["GENERAL_MERCHANDISE_CONVENIENCE_STORES"]
        assert primary == "food_and_dining"
        assert sub == "convenience_stores"

    def test_gambling_maps_to_own_category(self):
        primary, sub = PLAID_DETAILED_TO_INTERNAL["ENTERTAINMENT_CASINOS_AND_GAMBLING"]
        assert primary == "gambling"

    def test_travel_lodging_maps_to_travel(self):
        primary, sub = PLAID_DETAILED_TO_INTERNAL["TRAVEL_LODGING"]
        assert primary == "travel"
        assert sub == "hotels_and_lodging"

    def test_travel_flights_maps_to_travel(self):
        primary, sub = PLAID_DETAILED_TO_INTERNAL["TRAVEL_FLIGHTS"]
        assert primary == "travel"
        assert sub == "flights"

    def test_cash_advances_map_to_ewa(self):
        primary, sub = PLAID_DETAILED_TO_INTERNAL["TRANSFER_IN_CASH_ADVANCES_AND_LOANS"]
        assert primary == "debt_and_loans"
        assert sub == "cash_advance_ewa"

    def test_income_maps_correctly(self):
        primary, _ = PLAID_DETAILED_TO_INTERNAL["INCOME_WAGES"]
        assert primary == "income"

    def test_transfers_map_correctly(self):
        primary, _ = PLAID_DETAILED_TO_INTERNAL["TRANSFER_OUT_ACCOUNT_TRANSFER"]
        assert primary == "transfers"

    def test_rent_maps_to_bills(self):
        primary, sub = PLAID_DETAILED_TO_INTERNAL["RENT_AND_UTILITIES_RENT"]
        assert primary == "bills"
        assert sub == "rent_mortgage"


class TestPaveMapping:
    def test_all_mappings_resolve_to_valid_categories(self):
        for tag, (primary, sub) in PAVE_TAG_TO_INTERNAL.items():
            assert is_valid_category(primary, sub), (
                f"Pave tag '{tag}' maps to invalid category ({primary}, {sub})"
            )

    def test_resolve_single_tag(self):
        result = resolve_pave_tags(["Restaurant"])
        assert result == ("food_and_dining", "restaurants")

    def test_resolve_skips_generic_first(self):
        # "Miscellaneous" is generic, should skip to "Restaurant"
        result = resolve_pave_tags(["Miscellaneous", "Restaurant"])
        assert result == ("food_and_dining", "restaurants")

    def test_resolve_skips_retail_for_more_specific(self):
        result = resolve_pave_tags(["Retail", "Grocery"])
        assert result == ("food_and_dining", "groceries")

    def test_resolve_falls_back_to_generic(self):
        result = resolve_pave_tags(["Miscellaneous"])
        assert result == ("other", "uncategorized")

    def test_resolve_empty_tags(self):
        result = resolve_pave_tags([])
        assert result is None

    def test_resolve_unknown_tag(self):
        result = resolve_pave_tags(["SomeNewTagWeveNeverSeen"])
        assert result is None

    def test_earned_wage_access_tag(self):
        result = resolve_pave_tags(["Earned Wage Access", "Cash Advance"])
        assert result == ("debt_and_loans", "cash_advance_ewa")

    def test_payment_app_maps_to_p2p(self):
        result = resolve_pave_tags(["Payment App"])
        assert result == ("transfers", "peer_to_peer")

    def test_gambling_tag(self):
        result = resolve_pave_tags(["Gambling"])
        assert result == ("gambling", "gambling")


class TestEWAMerchants:
    def test_known_ewa_merchants_identified(self):
        for merchant in ["Earnin", "Dave Inc", "Brigit", "Cleo", "Albert Cash", "Floatme"]:
            assert is_ewa_merchant(merchant), f"{merchant} should be EWA"

    def test_case_insensitive(self):
        assert is_ewa_merchant("earnin")
        assert is_ewa_merchant("DAVE INC")
        assert is_ewa_merchant("cLeo")

    def test_non_ewa_not_matched(self):
        assert not is_ewa_merchant("McDonald's")
        assert not is_ewa_merchant("Walmart")
        assert not is_ewa_merchant("Chase")

    def test_minimum_merchant_count(self):
        assert len(EWA_MERCHANTS) >= 15


class TestGamblingMerchants:
    def test_known_gambling_merchants_identified(self):
        for merchant in ["FanDuel", "DraftKings", "BetMGM", "PrizePicks", "Chumba Casino"]:
            assert is_gambling_merchant(merchant), f"{merchant} should be gambling"

    def test_case_insensitive(self):
        assert is_gambling_merchant("fanduel")
        assert is_gambling_merchant("DRAFTKINGS")

    def test_non_gambling_not_matched(self):
        assert not is_gambling_merchant("Netflix")
        assert not is_gambling_merchant("Starbucks")

    def test_minimum_merchant_count(self):
        assert len(GAMBLING_MERCHANTS) >= 20
