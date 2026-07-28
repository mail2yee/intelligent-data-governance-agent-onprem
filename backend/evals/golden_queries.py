"""
Golden query set for the /api/chat semantic-layer eval (see test_chat_eval.py).

Each entry's `expected_product_ids` is checked against MOCK_CATALOG.expected
ids at import time (see test_chat_eval.py) so this file can't silently drift
from the actual mock catalog contents in datahub_client.py.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GoldenQuery:
    id: str
    lang: str
    message: str
    expected_product_ids: frozenset[str] = field(default_factory=frozenset)

    @property
    def in_catalog(self) -> bool:
        return bool(self.expected_product_ids)


GOLDEN_QUERIES = [
    GoldenQuery(
        id="zh-capacity",
        lang="zh",
        message="我想分析特定客戶產能分配",
        expected_product_ids=frozenset({"customer-capacity-allocation"}),
    ),
    GoldenQuery(
        id="zh-demand-orders",
        lang="zh",
        message="全球客戶投片訂單與需求排程",
        expected_product_ids=frozenset({"customer-demand-orders"}),
    ),
    GoldenQuery(
        id="zh-move-forecast",
        lang="zh",
        message="生產Move與WIP出貨預估",
        expected_product_ids=frozenset({"move-forecast-summary"}),
    ),
    GoldenQuery(
        id="zh-out-of-catalog-salary",
        lang="zh",
        message="員工薪資查詢",
        expected_product_ids=frozenset(),
    ),
    GoldenQuery(
        id="en-capacity",
        lang="en",
        message="I want to analyze specific customer capacity allocation",
        expected_product_ids=frozenset({"customer-capacity-allocation"}),
    ),
    GoldenQuery(
        id="en-out-of-catalog-weather",
        lang="en",
        message="what's the weather today",
        expected_product_ids=frozenset(),
    ),
]
