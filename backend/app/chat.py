"""
Chat / search assistant logic - ported behavior from the GCP PoC's /chat
route (see HANDOFF.md), rewired to call the on-prem LLM client and
stream via the same step/token/final SSE event shape.
"""

import json
from collections.abc import AsyncIterator

from .integrations import wrenai_client
from .integrations.llm_client import stream_chat_completion

GREETING_WORDS = {
    "hi",
    "hello",
    "hey",
    "hiya",
    "howdy",
    "yo",
    "good morning",
    "good afternoon",
    "good evening",
    "你好",
    "您好",
    "哈囉",
    "安安",
    "哈羅",
    "嗨",
    "早安",
    "午安",
    "晚安",
}


def is_greeting(msg: str) -> bool:
    cleaned = msg.strip().strip("!！?？.,。~、 ").lower()
    if not cleaned:
        return False
    if cleaned in GREETING_WORDS:
        return True
    return len(cleaned) <= 12 and any(g in cleaned for g in GREETING_WORDS)


NOT_FOUND_REPLY = {
    "zh": "抱歉，在我們的資料目錄中目前沒有找到符合您需求的資料主體，無法為您提供推薦或權限申請。",
    "en": "Sorry, no data subject in our catalog matches your request, so I can't recommend one or start a request for it.",
}
GREETING_REPLY = {
    "zh": "您好！我是<b>小幫手</b>，很高興為您服務！<br>您可以直接描述您的報表或分析需求，我將為您在資料目錄中檢索並推薦最適合的資料主體。",
    "en": "Hi, I'm your <b>Assistant</b>! Happy to help.<br>Describe your reporting need and I'll search the catalog and recommend the most suitable data subjects for you.",
}


def sse_event(event_type: str, **data) -> str:
    return f"data: {json.dumps({'type': event_type, **data}, ensure_ascii=False)}\n\n"


def build_prompt(user_msg: str, lang: str, catalog: dict) -> str:
    knowledge_base = json.dumps(catalog, ensure_ascii=False)
    lang_name = "English" if lang == "en" else "Traditional Chinese (繁體中文)"
    not_found_sentence = NOT_FOUND_REPLY[lang]
    return f"""
    [Role]
    You are a rigorous data governance expert for this organization's data catalog.
    The catalog currently contains these data subjects:
    {knowledge_base}

    The user's reporting need is: "{user_msg}"

    [Reply rules - zero hallucination]
    1. Only recommend data subjects that literally exist in the catalog above.
    2. If the user's request is unrelated to the catalog, or asks for data that doesn't exist there:
       - Never invent a fake data subject, database, or owner name.
       - Reply with exactly this sentence, and nothing else: "{not_found_sentence}"
    3. If it matches, recommend the most suitable data subject(s) and mention their
       maturity level and data quality score.
    4. Reply entirely in {lang_name}, regardless of what language the user's request was written in.
    """


def build_sql_prompt(user_msg: str, catalog: dict) -> str:
    """Prompt asking the LLM to write SQL against the data_products
    semantic model instead of recommending a subject in free text - the
    resulting SQL gets executed through WrenAI's governed engine
    (wrenai_client.py), which structurally can't return a row that
    doesn't exist. This is what actually enforces zero-hallucination
    here; build_prompt()'s reply is still generated for the user-facing
    text, but no longer trusted for deciding matched_products."""
    ids = json.dumps(list(catalog.keys()), ensure_ascii=False)
    return f"""
    You have a Postgres table `data_products` with columns (all text):
    id, name, description, owner, maturity_level, data_quality_score,
    frequency, tables_joined, db_type, db_host, db_port, db_schema.
    It currently has rows for exactly these ids: {ids}

    Write ONE SQL SELECT statement, selecting only the `id` and `name`
    columns from `data_products`, that finds the row(s) matching this
    request: "{user_msg}"
    Use ILIKE with '%...%' on name/description/tables_joined to match.
    If nothing in the table plausibly matches, reply with exactly:
    NO_MATCH
    Reply with the SQL (or NO_MATCH) only - no explanation, no markdown
    code fences, no trailing semicolon.
    """


def _extract_sql(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned
    return cleaned.strip().rstrip(";").strip()


async def resolve_via_semantic_layer(user_msg: str, catalog: dict) -> list[str]:
    """Ask the LLM to write SQL against the data_products semantic model
    and execute it through WrenAI's governed engine - matched ids come
    from real query rows, not from scanning free-form LLM prose.

    Returns [] for a legitimate "nothing matches" (the LLM replied
    NO_MATCH, or the query genuinely returned no rows) - that's a
    verified answer, not a failure. Raises on any actual integration
    failure (LLM unreachable for this second call, WrenAI/MDL not
    available, invalid SQL rejected by governance, etc.) - callers
    should treat that like any other integration failure in this app
    and fall back accordingly, not treat it as "verified: no match".
    """
    sql_reply = ""
    async for piece in stream_chat_completion(
        [{"role": "user", "content": build_sql_prompt(user_msg, catalog)}]
    ):
        sql_reply += piece
    sql = _extract_sql(sql_reply)
    if not sql or sql.upper() == "NO_MATCH":
        return []

    await wrenai_client.sync_catalog(catalog)
    rows = await wrenai_client.resolve_matches(sql)
    return [row["id"] for row in rows if isinstance(row, dict) and row.get("id") in catalog]


# Crude keyword-to-product map used only when the LLM gateway is
# unreachable, so the app degrades gracefully instead of just erroring
# out - not a substitute for the real LLM grounding (see HANDOFF.md).
# Chinese has no whitespace between words, so generic tokenization
# doesn't work here; this mirrors the GCP PoC's proven approach of
# matching known keyword phrases per catalog entry directly. It only
# knows about the mock catalog's 3 entries - once DataHub is wired with
# real, varied catalog contents, this fallback should either be reworked
# to something more generic or dropped in favor of always requiring a
# working LLM.
LOCAL_MATCH_KEYWORDS = {
    "customer-capacity-allocation": ["產能", "分配", "capacity", "allocation"],
    "move-forecast-summary": ["move", "出貨", "預估", "shipment", "forecast"],
    "customer-demand-orders": ["訂單", "order", "demand"],
}


def local_rule_match(user_msg: str, lang: str, catalog: dict) -> tuple[list[str], str]:
    msg_lower = user_msg.lower()
    for product_id, keywords in LOCAL_MATCH_KEYWORDS.items():
        item = catalog.get(product_id)
        if not item:
            continue
        if any(k.lower() in msg_lower for k in keywords):
            reply = (
                f"💡 我為您找到了 <b>{item['name']}</b>（{item.get('maturity_level', '')} 級，品質分 {item.get('data_quality_score', '')}）。"
                if lang == "zh"
                else f"💡 I found <b>{item['name']}</b> ({item.get('maturity_level', '')}-certified, quality score {item.get('data_quality_score', '')})."
            )
            return [product_id], reply
    return [], NOT_FOUND_REPLY[lang]


async def run_chat(user_msg: str, lang: str, catalog: dict) -> AsyncIterator[str]:
    """Async generator of SSE event strings - step / token / final."""
    thinking_steps: list[str] = []

    def step(text: str) -> str:
        thinking_steps.append(text)
        return sse_event("step", text=text)

    if is_greeting(user_msg):
        yield step("💬 偵測到日常問候，直接快速回覆。")
        reply = GREETING_REPLY[lang]
        yield sse_event("token", text=reply)
        yield sse_event("final", reply=reply, matched_products=[], thinking_steps=thinking_steps)
        return

    yield step("🧠 收到需求，開始進行 Reasoning 與任務拆解...")
    yield step("🔍 正在檢索資料目錄...")

    prompt = build_prompt(user_msg, lang, catalog)
    matched_products: list[str] = []
    reply = ""

    try:
        async for piece in stream_chat_completion([{"role": "user", "content": prompt}]):
            reply += piece
            yield sse_event("token", text=piece)

        reply_lower = reply.lower()
        for product_id, item in catalog.items():
            name_lower = str(item.get("name", "")).lower()
            # Check the display name too, not just the literal id slug - a
            # real LLM naturally answers with the human-readable name
            # ("Specific Customer Capacity Allocation"), not the hyphenated
            # slug ("customer-capacity-allocation"), so id-only matching
            # would silently never match a real model's natural phrasing.
            if (
                product_id in reply_lower
                or product_id in user_msg.lower()
                or (name_lower and name_lower in reply_lower)
            ):
                matched_products.append(product_id)

        verified: list[str] | None = None
        try:
            yield step("🧬 透過語意層 (WrenAI) 驗證比對結果...")
            verified = await resolve_via_semantic_layer(user_msg, catalog)
        except Exception as e:
            yield step(
                f"⚠️ 語意層驗證失敗（{e}），改用文字比對結果。"
                if lang == "zh"
                else f"⚠️ Semantic layer verification failed ({e}), falling back to text matching."
            )

        if verified is not None:
            matched_products = verified
            if matched_products:
                yield step(f"🏁 語意層驗證完畢，推薦：{json.dumps(matched_products)}")
            else:
                yield step("⚠️ 判定此需求與資料目錄無關，已啟動 Zero Hallucination 攔截。")
        else:
            not_found_markers = (
                ["抱歉", "沒有找到"]
                if lang == "zh"
                else ["sorry", "no data subject", "doesn't match", "does not match"]
            )
            if any(m.lower() in reply.lower() for m in not_found_markers):
                matched_products = []
                yield step("⚠️ 判定此需求與資料目錄無關，已啟動 Zero Hallucination 攔截。")
            else:
                yield step(f"🏁 任務規劃與執行完畢，推薦：{json.dumps(matched_products)}")
    except Exception as e:
        yield step(
            f"⚠️ LLM 無法連線（{e}），降級至本地關鍵字比對。"
            if lang == "zh"
            else f"⚠️ LLM unreachable ({e}), falling back to local keyword matching."
        )
        matched_products, reply = local_rule_match(user_msg, lang, catalog)
        yield sse_event("token", text=reply)
        if not matched_products:
            yield step("⚠️ 判定此需求與資料目錄無關，已啟動 Zero Hallucination 攔截。")

    yield sse_event("final", reply=reply, matched_products=matched_products, thinking_steps=thinking_steps)
