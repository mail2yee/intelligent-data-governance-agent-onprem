"""
Chat / search assistant logic - ported behavior from the GCP PoC's /chat
route (see HANDOFF.md), rewired to call the on-prem LLM client and
stream via the same step/token/final SSE event shape.
"""

import json
import logging
from collections.abc import AsyncIterator

from sqlalchemy import select

from .config import settings
from .db import DataProduct, UnmatchedQuery, async_session
from .integrations import wrenai_client
from .integrations.llm_client import stream_chat_completion

logger = logging.getLogger("dgo")

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

# Extra words that only ever show up as small talk *right after* a
# greeting - if every whitespace-separated word in the message is either
# part of a GREETING_WORDS phrase or one of these, it's still just
# chit-chat no matter how long the sentence spells it out. Replaces an
# earlier character-length heuristic (`len(cleaned) <= 12`) that
# misclassified e.g. "hi how are you" (14 chars) as a real catalog
# request just for being a couple characters over an arbitrary cutoff -
# confirmed via a live test against the real running app (2026-07-31).
# English only, since it's whitespace-tokenized; see CHITCHAT_PHRASES_ZH
# below for Chinese, which has no whitespace between words for this
# word-by-word approach to work on.
CHITCHAT_WORDS = {
    "how",
    "are",
    "you",
    "doing",
    "today",
    "going",
    "it's",
    "its",
    "what's",
    "whats",
    "up",
    "there",
    "you're",
    "youre",
    "things",
    "do",
    # Texting shorthand - confirmed via live testing that "hi how r u?"
    # (a very common casual phrasing) was missed without these.
    "r",
    "u",
    "ur",
    "hru",
}

# Whole Chinese greeting+filler phrases, matched as exact strings (after
# is_greeting's own punctuation-stripping) rather than word-split, since
# Chinese has no whitespace between words for CHITCHAT_WORDS' approach to
# work on.
CHITCHAT_PHRASES_ZH = {
    "你好嗎",
    "您好嗎",
    "最近好嗎",
    "近來好嗎",
    "近況如何",
    "最近如何",
    "你好不好",
}

# Flattens multi-word GREETING_WORDS entries (e.g. "good morning") into
# their individual words too, so "good morning, how are you" is
# recognized word-by-word below even though "good"/"morning" aren't
# themselves complete greetings on their own.
_GREETING_TOKENS = {word for phrase in GREETING_WORDS for word in phrase.split()}
_CHITCHAT_TOKENS = _GREETING_TOKENS | CHITCHAT_WORDS


def is_greeting(msg: str) -> bool:
    cleaned = msg.strip().strip("!！?？.,。~、 ").lower()
    if not cleaned:
        return False
    if cleaned in GREETING_WORDS or cleaned in CHITCHAT_PHRASES_ZH:
        return True
    if not any(g in cleaned for g in GREETING_WORDS):
        return False
    # cleaned only has punctuation stripped from its own start/end (see
    # above) - a mid-sentence comma like "hello, how are you" would
    # otherwise stay glued to "hello," as one token and never match
    # _CHITCHAT_TOKENS's plain "hello".
    words = [w for w in (w.strip(",.!?！？。～、") for w in cleaned.split()) if w]
    return len(words) > 1 and all(w in _CHITCHAT_TOKENS for w in words)


def not_found_reply(catalog: dict, lang: str) -> str:
    """Same spirit as GREETING_REPLY below - added 2026-07-31 after an
    LLM-based 3-way classification (greeting vs no-match vs match) proved
    unreliable on a small local model (it kept misclassifying genuinely
    off-topic messages like "what's the weather" as a greeting) -
    reverted to a plain 2-way match/no-match decision and folded a
    "here's how to ask" hint into this reply instead.

    Extended 2026-08-27: a genuinely vague request (e.g. "I want to make
    a report, what data sources are there?") isn't off-topic - it's a
    real need that's just too unspecific to match one data subject via
    search_text/SQL, and got the same flat rejection as a truly
    off-topic message, a dead end for the user. Listing the catalog's
    actual data subjects turns the rejection into a clarifying nudge
    instead, without needing multi-turn conversation state (the frontend
    only ever sends the current message, no history - see api.js) or a
    new vague-vs-specific classification step, which would carry the
    same small-model reliability risk the greeting classifier above was
    reverted for.

    Keep the leading "抱歉"/"沒有找到" (zh) and "Sorry"/"no data subject"
    (en) substrings intact if editing this - run_chat() below matches on
    them to detect that the LLM actually followed this instruction
    rather than replying with something else entirely.
    """
    names = [str(item.get("name", pid)) for pid, item in catalog.items()]
    if lang == "zh":
        listed = "、".join(names) if names else "（目前目錄是空的）"
        return (
            f"抱歉，目前資料目錄中沒有找到明確符合您需求的資料主體。"
            f"目前目錄中有這些主題：{listed}。"
            f"可以請您說明一下想分析的報表主要跟哪個方向有關嗎？我會依此推薦最合適的資料主體。"
        )
    listed = ", ".join(names) if names else "(the catalog is currently empty)"
    return (
        f"Sorry, no data subject in our catalog clearly matches your request. "
        f"Currently available data subjects: {listed}. "
        f"Could you tell me more about which area your report is about, so I can recommend the best match?"
    )
GREETING_REPLY = {
    # Plain text, not HTML - the frontend renders this (and every other
    # reply string here, including raw LLM output) as plain text, not
    # dangerouslySetInnerHTML (see the 2026-07-30 XSS fix in
    # DiscoverView.jsx/CopilotDock.jsx). Newline relies on the frontend's
    # `white-space: pre-wrap` CSS, not an HTML <br>.
    # Acknowledges small talk ("how are you") before explaining capability
    # with a concrete example - a bare "hi, I'm your assistant" with no
    # example left first-time users unsure what to actually type
    # (2026-07-31 feedback).
    "zh": (
        "您好，我很好，謝謝關心！我是小幫手，可以協助您在資料目錄中找到適合完成報表的資料主體 (Data Subject)。\n"
        "請直接描述您的報表或分析目的，例如「我想分析特定客戶的產能與出貨預估」，我會為您檢索並推薦最合適的資料主體。"
    ),
    "en": (
        "Hi, I'm doing well, thanks for asking! I'm your Assistant — I can help you find the right "
        "data subject(s) in our catalog to complete your report.\n"
        "Just describe your reporting or analysis need, e.g. \"I want to analyze a customer's capacity "
        "and shipment forecast\", and I'll search the catalog and recommend the best match."
    ),
}


def sse_event(event_type: str, **data) -> str:
    return f"data: {json.dumps({'type': event_type, **data}, ensure_ascii=False)}\n\n"


async def record_unmatched_query(message: str, lang: str) -> None:
    """Best-effort logging into UnmatchedQuery (db.py) for
    scripts/review_unmatched_queries.py's offline review - never raises,
    same fallback philosophy as the integrations/ clients, since a
    logging failure must not break the actual chat response."""
    try:
        async with async_session() as session:
            session.add(UnmatchedQuery(message=message, lang=lang))
            await session.commit()
    except Exception as e:
        logger.warning("Failed to record unmatched query: %s", e)


def build_prompt(user_msg: str, lang: str, catalog: dict) -> str:
    """Deliberately a plain 2-way match/no-match decision, not a 3-way
    classification that also tries to detect greetings - that was tried
    and reverted 2026-07-31: a small local model kept misclassifying
    genuinely off-topic messages (e.g. "what's the weather") as a
    greeting, conflating categories that a weak model can't reliably
    keep apart. Greeting detection stays entirely in is_greeting()'s
    cheap keyword check (run_chat() tries that first, no LLM call) - if
    a greeting slips past that, it just falls through to this prompt and
    gets not_found_reply(), which is written to be a helpful answer
    either way (see its own comment)."""
    knowledge_base = json.dumps(catalog, ensure_ascii=False)
    lang_name = "English" if lang == "en" else "Traditional Chinese (繁體中文)"
    not_found_sentence = not_found_reply(catalog, lang)
    return f"""
    [Role]
    You are a rigorous data governance expert. Every user of this tool is
    trying to find the right data subject(s) in this organization's data
    catalog to complete a report or analysis - that is the only thing
    this tool is for. Interpret every request through that lens: what
    data subject(s) below would help the user build their report.
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
    frequency, tables_joined, db_type, db_host, db_port, db_schema,
    search_text (name + description + tables_joined, already present in
    both Traditional and Simplified Chinese - always match against this
    column, never against name/description/tables_joined directly, and
    never convert your own keywords between scripts yourself).
    It currently has rows for exactly these ids: {ids}

    The user's request is: "{user_msg}"

    First, extract 2-4 short keywords or synonyms from the request,
    written in whichever script the request itself uses - never use the
    entire sentence as a match pattern, catalog text is short and a
    full-sentence substring will essentially never match it. Prefer a
    keyword specific enough to distinguish between catalog rows (e.g.
    "customer capacity" rather than just "customer", which most rows
    would mention).

    Write ONE SQL SELECT statement, selecting only the `id` and `name`
    columns from `data_products`, using the standard SQL operator form
    `search_text ILIKE '%keyword%'` (not a function-call form like
    `ilike(col, pattern)`) - OR the keyword conditions together.

    Example shape only (do not reuse "capacity", extract your own
    keywords from the actual request above):
    SELECT id, name FROM data_products WHERE search_text ILIKE '%capacity%' OR search_text ILIKE '%capacity allocation%'

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
        [{"role": "user", "content": build_sql_prompt(user_msg, catalog)}],
        model=settings.llm_sql_model or None,
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
            # Plain text - item['name'] ultimately comes from the DataHub
            # catalog, so it isn't safe to splice into an HTML string (see
            # the 2026-07-30 XSS fix - the frontend renders this as plain
            # text, not HTML, same as every other reply here).
            reply = (
                f"💡 我為您找到了 {item['name']}（{item.get('maturity_level', '')} 級，品質分 {item.get('data_quality_score', '')}）。"
                if lang == "zh"
                else f"💡 I found {item['name']} ({item.get('maturity_level', '')}-certified, quality score {item.get('data_quality_score', '')})."
            )
            return [product_id], reply
    return [], not_found_reply(catalog, lang)


RESULTS_FOUND_REPLY = {
    "zh": lambda n: f"為您找到 {n} 筆符合的資料主體。",
    "en": lambda n: f"Found {n} matching data subject{'' if n == 1 else 's'}.",
}


async def keyword_search(user_msg: str, lang: str, catalog: dict) -> tuple[list[str], str]:
    """Default "general search" mode (as opposed to "AI search" -
    see the 2026-07-31 design discussion): plain substring matching
    against data_products.search_text, no LLM/WrenAI involved. Multiple
    keywords (split on whitespace) must ALL match (AND), same
    catalog-mirror table the AI-mode SQL path already queries via
    WrenAI - see wrenai_client.sync_catalog()'s docstring for why a
    Postgres table exists in the first place.

    Deliberately not Postgres full-text search (tsvector/to_tsquery):
    confirmed this catalog's Chinese content has no whitespace between
    words, so Postgres's default parser can't tokenize it into
    sub-string-matchable words the way ILIKE naturally does - multiple
    ILIKE clauses ANDed together is the correct choice here, not a
    simplification.
    """
    await wrenai_client.sync_catalog(catalog)
    keywords = [kw.strip() for kw in user_msg.split() if kw.strip()]
    if not keywords:
        return [], not_found_reply(catalog, lang)

    async with async_session() as session:
        stmt = select(DataProduct.id)
        for kw in keywords:
            stmt = stmt.where(DataProduct.search_text.ilike(f"%{kw}%"))
        result = await session.execute(stmt)
        matched = [pid for (pid,) in result.all() if pid in catalog]

    reply = RESULTS_FOUND_REPLY[lang](len(matched)) if matched else not_found_reply(catalog, lang)
    return matched, reply


async def run_chat(user_msg: str, lang: str, catalog: dict, mode: str = "ai") -> AsyncIterator[str]:
    """Async generator of SSE event strings - step / token / final.

    `mode="keyword"` is the default "general search" path (see
    keyword_search() above) - no LLM/WrenAI call, no step/token events,
    just an immediate final event. `mode="ai"` (default, for backward
    compatibility) is everything below: greeting fast-path, then the
    LLM + semantic-layer verification chain."""
    thinking_steps: list[str] = []

    def step(text: str) -> str:
        thinking_steps.append(text)
        return sse_event("step", text=text)

    if mode == "keyword":
        matched, reply = await keyword_search(user_msg, lang, catalog)
        yield sse_event("final", reply=reply, matched_products=matched, thinking_steps=thinking_steps)
        return

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
                await record_unmatched_query(user_msg, lang)
        else:
            not_found_markers = (
                ["抱歉", "沒有找到"]
                if lang == "zh"
                else ["sorry", "no data subject", "doesn't match", "does not match"]
            )
            if any(m.lower() in reply.lower() for m in not_found_markers):
                matched_products = []
                yield step("⚠️ 判定此需求與資料目錄無關，已啟動 Zero Hallucination 攔截。")
                await record_unmatched_query(user_msg, lang)
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
