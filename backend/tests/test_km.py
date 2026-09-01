from app.km import KM_DOCS, build_km_prompt, find_relevant_docs


def test_find_relevant_docs_matches_maturity_keyword():
    assert find_relevant_docs("什麼是 Gold 等級的資料？") == ["data-maturity-levels"]


def test_find_relevant_docs_matches_english_keyword():
    assert find_relevant_docs("what is the SLA for approval?") == ["approval-sla-policy"]


def test_find_relevant_docs_matches_faq_keyword():
    assert find_relevant_docs("要怎麼申請資料存取權限？") == ["data-access-request-faq"]


def test_find_relevant_docs_no_match_for_unrelated_message():
    assert find_relevant_docs("我想分析特定客戶的產能") == []


def test_find_relevant_docs_can_match_multiple_docs():
    matched = find_relevant_docs("申請通過後 SLA 是多久？")
    assert "approval-sla-policy" in matched
    assert "data-access-request-faq" in matched


def test_find_relevant_docs_is_case_insensitive():
    assert find_relevant_docs("What does GOLD maturity mean?") == ["data-maturity-levels"]


def test_build_km_prompt_includes_matched_doc_content_zh():
    prompt = build_km_prompt("什麼是 Gold", "zh", ["data-maturity-levels"])
    assert KM_DOCS["data-maturity-levels"]["title_zh"] in prompt
    assert "95%" in prompt
    assert "Traditional Chinese" in prompt


def test_build_km_prompt_includes_matched_doc_content_en():
    prompt = build_km_prompt("what is gold", "en", ["data-maturity-levels"])
    assert KM_DOCS["data-maturity-levels"]["title_en"] in prompt
    assert "English" in prompt
    # Only the requested language's content should be spliced in.
    assert KM_DOCS["data-maturity-levels"]["content_zh"] not in prompt


def test_build_km_prompt_includes_multiple_docs():
    prompt = build_km_prompt("申請跟 SLA", "zh", ["approval-sla-policy", "data-access-request-faq"])
    assert KM_DOCS["approval-sla-policy"]["title_zh"] in prompt
    assert KM_DOCS["data-access-request-faq"]["title_zh"] in prompt


def test_build_km_prompt_includes_history_block():
    history = [{"role": "user", "content": "什麼是 Gold 等級？"}]
    prompt = build_km_prompt("那 Silver 呢？", "zh", ["data-maturity-levels"], history)
    assert "[Conversation so far]" in prompt
    assert "什麼是 Gold 等級" in prompt


def test_build_km_prompt_omits_history_block_when_none():
    prompt = build_km_prompt("什麼是 Gold", "zh", ["data-maturity-levels"])
    assert "[Conversation so far]" not in prompt


def test_km_docs_have_required_fields():
    for doc_id, doc in KM_DOCS.items():
        assert doc["title_zh"], doc_id
        assert doc["title_en"], doc_id
        assert doc["content_zh"], doc_id
        assert doc["content_en"], doc_id
        assert doc["keywords"], doc_id
