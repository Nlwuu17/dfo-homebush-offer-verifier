"""v0.4 judge: an offer is recognised together with its conditions.

Synthetic sources only; no candidate case's verdict is asserted here. Each
example has a variant that must come out differently, so a judge that
ignores the condition fails.
"""

import unittest

import bf26


def case(offer, as_of="2026-11-26"):
    return {
        "case_id": "T",
        "brand": "Testbrand",
        "offer": offer,
        "as_of_date": as_of,
        "timezone": "Australia/Sydney",
        "centre": "DFO Homebush",
    }


def page(text, key="P1"):
    return {
        "id": key,
        "title": "Testbrand | Offer - DFO Homebush",
        "publisher": "DFO Homebush",
        "source_type": "商场品牌优惠页",
        "checked_date": "2026-11-26",
        "passages": [{"summary_zh": text}],
    }


def flyer(text, key="F1"):
    return {
        "id": key,
        "title": "DFO Homebush The Big Shopping Week 2026 活动传单",
        "publisher": "DFO Homebush",
        "source_type": "商场活动传单",
        "checked_date": "2026-11-26",
        "passages": [{"locator": "第 1 页 / Testbrand", "summary_zh": text}],
    }


def verdict(offer, *docs, as_of="2026-11-26"):
    return bf26.assess(case(offer, as_of), list(docs))[0]


PERIOD = "2026-11-26 至 2026-11-29："


class PerItemPriceTests(unittest.TestCase):
    """「指定身体护理每件 $12」keeps its product scope."""

    SOURCE = page(PERIOD + "全店买一送一；精选身体护理每件 $12。")

    def test_same_scope_is_supported(self):
        self.assertEqual(verdict("精选身体护理每件 $12", self.SOURCE), bf26.YES)
        self.assertEqual(verdict("指定身体护理每件 $12", self.SOURCE), bf26.YES)

    def test_storewide_is_broader_than_a_selected_range(self):
        self.assertEqual(verdict("全店每件 $12", self.SOURCE), bf26.UNKNOWN)

    def test_dropping_the_selection_is_broader(self):
        self.assertEqual(verdict("身体护理每件 $12", self.SOURCE), bf26.UNKNOWN)

    def test_another_price_is_not_the_same_offer(self):
        self.assertEqual(verdict("精选身体护理每件 $10", self.SOURCE), bf26.UNKNOWN)


class BundlePriceTests(unittest.TestCase):
    """「任选三杯共 $20」is a price for the set, not for each cup."""

    SOURCE = page(PERIOD + "任选三杯大杯饮品共 $20。")

    def test_bundle_is_supported_in_either_numeral(self):
        self.assertEqual(verdict("任选三杯大杯饮品共 $20", self.SOURCE), bf26.YES)
        self.assertEqual(verdict("任选 3 杯大杯饮品 $20", self.SOURCE), bf26.YES)

    def test_bundle_price_does_not_support_a_per_cup_price(self):
        self.assertEqual(verdict("大杯饮品每杯 $20", self.SOURCE), bf26.UNKNOWN)

    def test_a_different_set_size_is_not_the_same_offer(self):
        self.assertEqual(verdict("任选两杯大杯饮品共 $20", self.SOURCE), bf26.UNKNOWN)

    def test_per_cup_price_does_not_support_a_bundle(self):
        source = page(PERIOD + "大杯饮品每杯 $20。")
        self.assertEqual(verdict("任选三杯大杯饮品共 $20", source), bf26.UNKNOWN)


class MemberBogoTests(unittest.TestCase):
    """「会员买一送一」keeps the member condition and its explicit date."""

    SOURCE = page(
        "仅限 2026-11-27 一天，仅限 App 会员：购买任一饮品，送一杯价格相同或更低的饮品。"
    )

    def test_before_the_explicit_start_is_rule_a(self):
        label, _, refs, _ = bf26.assess(case("会员买一送一"), [self.SOURCE])
        self.assertEqual((label, refs), (bf26.NO, ["P1"]))

    def test_on_the_day_it_applies(self):
        self.assertEqual(verdict("会员买一送一", self.SOURCE, as_of="2026-11-27"), bf26.YES)

    def test_dropping_the_member_condition_is_broader(self):
        self.assertEqual(verdict("买一送一", self.SOURCE, as_of="2026-11-27"), bf26.UNKNOWN)

    def test_broader_wording_of_an_out_of_window_offer_is_not_rule_a(self):
        # The offer is not established as the same one, so rule A cannot use it.
        self.assertEqual(verdict("买一送一", self.SOURCE), bf26.UNKNOWN)

    def test_explicit_bogo_wording(self):
        source = page(PERIOD + "全店买一送一；洗手液每支 $6。")
        self.assertEqual(verdict("全店买一送一", source), bf26.YES)
        # A narrower description inside the stated scope stands (rule B).
        self.assertEqual(verdict("洗手液买一送一", source), bf26.YES)


class ThresholdAndMultiOfferTests(unittest.TestCase):
    SOURCE = page(PERIOD + "$3,000 以下的首饰最高 50% off，另外全部首饰额外 10% off。")

    def test_omitting_a_threshold_is_broader(self):
        self.assertEqual(verdict("全部首饰最高 50% off", self.SOURCE), bf26.UNKNOWN)
        self.assertEqual(verdict("$3,000 以下的首饰最高 50% off", self.SOURCE), bf26.YES)

    def test_a_threshold_stays_with_its_own_clause(self):
        self.assertEqual(verdict("全部首饰额外 10% off", self.SOURCE), bf26.YES)

    def test_a_silent_source_does_not_override_a_stated_threshold(self):
        silent = flyer("最高 50% off，有效期 11/20–11/30。")
        label, _, refs, _ = bf26.assess(case("全部首饰最高 50% off"), [self.SOURCE, silent])
        self.assertEqual(label, bf26.UNKNOWN)
        self.assertIn("P1", refs)

    def test_category_price_inside_a_multi_offer_line(self):
        source = flyer("鞋履和服装最高 50% off，装备 30% off，有效期 11/20–11/30。")
        self.assertEqual(verdict("装备 30% off", source), bf26.YES)
        self.assertEqual(verdict("全店 30% off", source), bf26.UNKNOWN)


class ParsingTests(unittest.TestCase):
    def keys(self, text):
        return [o["key"] for o in bf26.offer_items(text)]

    def test_kinds(self):
        self.assertEqual(self.keys("全店买一送一"), ["买一送一"])
        self.assertEqual(self.keys("精选身体护理每件 $12"), ["单价$12"])
        self.assertEqual(self.keys("任选三杯大杯饮品共 $20"), ["3杯共$20"])
        self.assertEqual(self.keys("任选 3 杯大杯果茶或奶茶 $20"), ["3杯共$20"])
        self.assertEqual(self.keys("全店 30% off"), ["30%"])

    def test_thresholds_are_not_prices(self):
        self.assertEqual(self.keys("$3,000 以下的首饰最高 50% off"), ["50%"])
        item = bf26.offer_items("$3,000 以下的首饰最高 50% off")[0]
        self.assertIn("门槛$3000以下", item["quals"])
        self.assertTrue(item["top"])


class UnknownScopeTests(unittest.TestCase):
    """A limiting word outside the category list still limits the offer."""

    def test_unknown_category_is_not_read_as_storewide(self):
        source = page(PERIOD + "床品 30% off。")
        self.assertEqual(verdict("全店 30% off", source), bf26.UNKNOWN)
        self.assertEqual(verdict("30% off", source), bf26.UNKNOWN)

    def test_the_same_unknown_word_matches_verbatim(self):
        source = page(PERIOD + "床品 30% off。")
        self.assertEqual(verdict("床品 30% off", source), bf26.YES)
        self.assertEqual(verdict("毛巾 30% off", page(PERIOD + "床品 30% off。")), bf26.UNKNOWN)

    def test_explicit_storewide_wording_still_counts(self):
        source = page(PERIOD + "黑五期间全店 30% off。")
        self.assertEqual(verdict("全店 30% off", source), bf26.YES)

    def test_a_narrower_unknown_word_inside_a_storewide_offer_stands(self):
        source = page(PERIOD + "全店 30% off。")
        self.assertEqual(verdict("床品 30% off", source), bf26.YES)

    def test_wording_around_the_price_is_not_a_limit(self):
        for text in (
            "标题为全店 30% off。",
            "另外全店 30% off。",
            "在 Testbrand Store 购买全店商品 30% off。",
        ):
            self.assertEqual(verdict("全店 30% off", page(PERIOD + text)), bf26.YES, text)


class OutletTests(unittest.TestCase):
    """「Outlet 门店」 is a store type; 「Outlet 商品」 is a product scope."""

    def test_outlet_store_still_needs_the_store_type(self):
        plain = page(PERIOD + "全店 50% off。")
        limited = page(PERIOD + "全店 50% off。条款限定 Testbrand Outlet。")
        self.assertEqual(verdict("Outlet 全店 50% off", plain), bf26.UNKNOWN)
        self.assertEqual(verdict("Outlet 全店 50% off", limited), bf26.YES)

    def test_outlet_goods_are_a_scope_with_quantity_and_extra(self):
        source = page(PERIOD + "买 2 件 Outlet 商品额外 20% off，买 3 件或以上 Outlet 商品额外 30% off。")
        self.assertEqual(verdict("买两件 Outlet 商品额外 20% off", source), bf26.YES)
        self.assertEqual(verdict("买 3 件 Outlet 商品额外 20% off", source), bf26.UNKNOWN)
        self.assertEqual(verdict("买两件 Outlet 商品 20% off", source), bf26.UNKNOWN)
        self.assertEqual(verdict("买两件全店额外 20% off", source), bf26.UNKNOWN)

    def test_threshold_values_must_match(self):
        source = page(PERIOD + "$2,000 以下的首饰最高 50% off。")
        self.assertEqual(verdict("$2,000 以下的首饰最高 50% off", source), bf26.YES)
        self.assertEqual(verdict("$3,000 以下的首饰最高 50% off", source), bf26.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
