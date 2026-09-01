"""
Data-governance knowledge base (KM) - items 3 and 5 of the user's
agent-improvement wishlist, built together after confirming via
AskUserQuestion that item 3 ("answer based on KM with reasons and ask
reasonable followup questions") needs a real KM source to answer from,
which is exactly what item 5 ("answer with content not given in the
structured db") already called for.

Fake content (the recommended AskUserQuestion option): a handful of
internal data-governance policy documents - maturity-level definitions,
the approval SLA policy, and the data-access-request FAQ - things this
app's own users would plausibly ask about that live outside the
`data_products` catalog entirely (no amount of catalog matching could
ever answer "what does Gold maturity mean?").

Deliberately NOT routed through WrenAI's governed SQL engine
(wrenai_client.py) - that mechanism exists to validate *structured*
queries against a live data source, which doesn't fit prose Q&A over a
handful of static documents. The zero-hallucination guarantee here is
necessarily weaker than the catalog-matching path's (no structural
verification step), so it leans on two things instead: a keyword
pre-filter (find_relevant_docs(), same deterministic-substring-match
spirit as chat.py's local_rule_match()) that must actually hit before
the LLM is even asked, and an explicit prompt instruction to say so
plainly rather than guess when the matched document(s) don't actually
answer the question. Worth being upfront about (see HANDOFF.md's "KM
answering" section) - this is not as strong a guarantee as the
structured path, an inherent tradeoff of supporting unstructured content
at all.

Deliberately NOT a new LLM-based intent classification step (catalog
question vs. policy question) - that would carry the same small-model
reliability risk already hit and reverted once for greeting detection
(see chat.py's is_greeting() docstring history). find_relevant_docs()
runs first, cheaply and deterministically, with no LLM call; only a real
keyword hit routes into the KM answer path at all - everything else
falls through to the existing catalog-matching flow, unchanged.
"""

KM_DOCS: dict[str, dict] = {
    "data-maturity-levels": {
        "title_zh": "資料成熟度分級標準",
        "title_en": "Data Maturity Level Classification",
        "keywords": [
            "成熟度",
            "maturity",
            "gold",
            "silver",
            "bronze",
            "分級",
            "分级",
            "等級",
            "等级",
            "品質分數",
            "quality score",
        ],
        "content_zh": (
            "本組織的資料主體依成熟度分為三級：\n"
            "- Gold（金級）：由正式資料擁有者（Data Owner）維護，資料品質分數 95% 以上，"
            "每日更新，已通過正式流程審核，可用於正式生產排程與對外報表。\n"
            "- Silver（銀級）：由部門級單位維護，資料品質分數介於 80%~95%，通常每週更新，"
            "僅建議用於 PoC（概念驗證）或內部分析，尚未通過正式生產審核。\n"
            "- Bronze（銅級）：屬於臨時性或實驗性資料，資料品質分數低於 80%，"
            "更新頻率不固定，不提供任何 SLA 保證，使用前應自行確認資料正確性。"
        ),
        "content_en": (
            "Data subjects in this organization are classified into three maturity levels:\n"
            "- Gold: maintained by a formal Data Owner, 95%+ data quality score, refreshed "
            "daily, has passed formal review, approved for production scheduling and "
            "external-facing reports.\n"
            "- Silver: maintained at the department level, 80-95% data quality score, "
            "typically refreshed weekly, recommended for PoC/internal analysis only - not "
            "yet approved for production use.\n"
            "- Bronze: ad-hoc or experimental data, below 80% data quality score, refresh "
            "frequency not guaranteed, no SLA whatsoever - verify correctness yourself "
            "before use."
        ),
    },
    "approval-sla-policy": {
        "title_zh": "簽核 SLA 政策",
        "title_en": "Approval SLA Policy",
        "keywords": [
            "sla",
            "簽核",
            "签核",
            "核准",
            "approval",
            "approve",
            "審核時間",
            "审核时间",
            "多久",
            "逾期",
            "升級",
            "升级",
            "escalat",
        ],
        "content_zh": (
            "每一張資料存取申請單會自動指派給至少 3 位簽核人（優先為相關資料主體的 Data Owner，"
            "不足 3 位時由預設的 compliance/infosec 稽核人員補足）。\n"
            "每位簽核人的標準 SLA 為 24 小時內完成核准或拒絕；超過 24 小時未處理會在追蹤頁面顯示 "
            "SLA 警示（⚠ 提示），但目前尚未有自動升級或提醒通知機制（此為已知待補項目）。\n"
            "任一簽核人拒絕，整張申請單即視為 REJECTED；拒絕時必須填寫理由。所有簽核人皆核准後，"
            "申請單狀態才會變成 APPROVED，此時申請人才能取得該資料的連線資訊或執行查詢。"
        ),
        "content_en": (
            "Each data-access ticket is automatically assigned to at least 3 approvers "
            "(prioritizing the relevant data subjects' Data Owners, padded with default "
            "compliance/infosec auditors if fewer than 3).\n"
            "The standard SLA per approver is 24 hours to approve or reject; an approver "
            "still pending past 24 hours triggers an SLA warning banner on the tracking page "
            "- there is currently no automatic escalation or reminder notification yet (a "
            "known open item).\n"
            "Any single rejection moves the whole ticket to REJECTED and requires a reason. "
            "Only once every approver has approved does the ticket become APPROVED, at which "
            "point the requester can get connection info or run queries against that data."
        ),
    },
    "data-access-request-faq": {
        "title_zh": "資料存取申請常見問題",
        "title_en": "Data Access Request FAQ",
        "keywords": [
            "申請",
            "申请",
            "流程",
            "request",
            "ticket",
            "怎麼申請",
            "怎么申请",
            "存取權限",
            "存取权限",
            "access",
            "連線",
            "连线",
            "connection",
        ],
        "content_zh": (
            "如何申請存取資料：在「探索與申請」頁面搜尋想要的資料主體，加入申請清單後，"
            "填寫業務目的與資料用途（PoC 或 Production）並送出，系統會自動建立一張申請單並啟動簽核流程。\n"
            "送出後可以在「簽核與追蹤」頁面查看目前狀態（待簽核 / 已核准 / 已拒絕）與每位簽核人的進度。\n"
            "申請單全數核准後，可在該筆申請單展開後點選「取得資料連線程式碼」，取得資料庫連線資訊（Python "
            "/ Java 範例程式碼），若該資料主體已接上真實業務資料庫，也可以直接用自然語言查詢資料。"
        ),
        "content_en": (
            "How to request data access: search for the data subject you need on the "
            "Discover & Request page, add it to your request list, fill in the business "
            "objective and data usage (PoC or Production), and submit - this creates a "
            "ticket and automatically starts the approval workflow.\n"
            "After submitting, track its status (pending / approved / rejected) and each "
            "approver's progress on the Approvals & Tracking page.\n"
            "Once every approver has approved, expand the ticket and click 'Get connection "
            "code' to get database connection info (Python/Java sample code) - and if that "
            "data subject is wired to a real business database, you can also query it "
            "directly in natural language."
        ),
    },
}


def find_relevant_docs(user_msg: str) -> list[str]:
    """Deterministic keyword pre-filter, no LLM call - only a real
    substring hit against a doc's own keyword list routes into the KM
    answer path at all (see this module's docstring for why)."""
    msg_lower = user_msg.lower()
    return [doc_id for doc_id, doc in KM_DOCS.items() if any(kw.lower() in msg_lower for kw in doc["keywords"])]


def _format_history(history: list[dict] | None) -> str:
    """Small, deliberate duplicate of chat.py's _format_history() (not a
    shared import) - keeps this module a leaf, importable from chat.py
    without a circular dependency."""
    if not history:
        return ""
    lines = "\n".join(f"{turn['role']}: {turn['content']}" for turn in history)
    return f"\n[Conversation so far]\n{lines}\n"


def build_km_prompt(user_msg: str, lang: str, doc_ids: list[str], history: list[dict] | None = None) -> str:
    lang_name = "English" if lang == "en" else "Traditional Chinese (繁體中文)"
    title_field = "title_en" if lang == "en" else "title_zh"
    content_field = "content_en" if lang == "en" else "content_zh"
    docs_block = "\n\n".join(
        f"## {KM_DOCS[doc_id][title_field]}\n{KM_DOCS[doc_id][content_field]}" for doc_id in doc_ids
    )
    history_block = _format_history(history)
    return f"""
    [Role]
    You are this organization's data governance policy assistant. Answer
    the user's question using ONLY the policy document(s) below - never
    use outside knowledge, and never invent anything not actually stated
    in these documents.

    [Document(s)]
    {docs_block}
    {history_block}
    The user's latest message is: "{user_msg}"

    [Reply rules]
    1. Answer using only the document content above. If these documents
       don't actually contain an answer to this specific question, say
       so plainly instead of guessing.
    2. Briefly explain your reasoning by referencing which policy/
       document your answer comes from.
    3. If there is exactly one natural, genuinely useful follow-up
       question the user might want answered next, ask it at the end -
       only when it's truly relevant, never forced, never more than one.
    4. Reply entirely in {lang_name}, regardless of what language the
       user's message was written in.
    """
