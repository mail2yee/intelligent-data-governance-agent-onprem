"""
Golden query set for keyword mode's hit-rate eval (see
test_keyword_search_eval.py). Deliberately mixes two phrasing styles,
not just clean keywords - see that file's module docstring for why.

Each entry's `expected_product_ids` is what a real user asking that
question would actually want - checked against MOCK_CATALOG's real ids
at import time so this file can't silently drift from the actual
catalog contents in datahub_client.py. This is NOT the same as
asserting the query is expected to match - see the `expect_match` flag:
`False` means this phrasing is a documented, known limitation of plain
substring AND-matching (not a bug to fix), included specifically to
measure how much natural phrasing actually costs, not to hide it.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class KeywordGoldenQuery:
    id: str
    lang: str
    message: str
    expected_product_ids: frozenset[str] = field(default_factory=frozenset)
    # True: a real, working keyword-style query - keyword_search()
    # returning anything else is a regression.
    # False: realistic natural-language phrasing that AND-substring
    # matching is known not to handle (see module docstring) - included
    # to measure the real-world cost, not asserted as a hard pass.
    expect_match: bool = True


KEYWORD_GOLDEN_QUERIES = [
    # --- Clean, well-formed keyword-style queries - AND-matching's
    # actual sweet spot, confirmed to work today.
    KeywordGoldenQuery(
        id="zh-capacity-keywords",
        lang="zh",
        message="產能 客戶",
        expected_product_ids=frozenset({"customer-capacity-allocation"}),
    ),
    KeywordGoldenQuery(
        id="zh-move-keywords",
        lang="zh",
        message="Move 出貨",
        expected_product_ids=frozenset({"move-forecast-summary"}),
    ),
    KeywordGoldenQuery(
        id="zh-demand-keywords",
        lang="zh",
        message="訂單 客戶",
        expected_product_ids=frozenset({"customer-demand-orders"}),
    ),
    KeywordGoldenQuery(
        id="en-capacity-keywords",
        lang="en",
        message="specific capacity allocation",
        expected_product_ids=frozenset({"customer-capacity-allocation"}),
    ),
    # --- Realistic full-sentence phrasing - the UI's own search
    # placeholder shows exactly this style as the suggested example, so
    # real users type it. A whole Chinese sentence with no whitespace
    # becomes ONE giant token that essentially never appears verbatim in
    # a short catalog description; a whole English sentence requires
    # every single word ("i", "want", "to"...) to independently match.
    # Both realistically fail today - included to measure that cost,
    # not treated as a bug to silently fix in this eval.
    KeywordGoldenQuery(
        id="zh-capacity-full-sentence",
        lang="zh",
        message="我想分析特定客戶的產能與出貨預估",
        expected_product_ids=frozenset({"customer-capacity-allocation"}),
        expect_match=False,
    ),
    KeywordGoldenQuery(
        id="en-capacity-full-sentence",
        lang="en",
        message="I want to analyze specific customer capacity allocation",
        expected_product_ids=frozenset({"customer-capacity-allocation"}),
        expect_match=False,
    ),
    # --- Genuinely out-of-catalog - correctly expected to match nothing,
    # not a phrasing-cost case.
    KeywordGoldenQuery(
        id="zh-out-of-catalog-salary",
        lang="zh",
        message="員工薪資查詢",
        expected_product_ids=frozenset(),
    ),
    KeywordGoldenQuery(
        id="en-out-of-catalog-weather",
        lang="en",
        message="what's the weather today",
        expected_product_ids=frozenset(),
    ),
]
