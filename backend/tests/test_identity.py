from app.identity import verify_or_claim


async def test_first_claim_succeeds():
    assert await verify_or_claim("tim@example.com", "tims-real-token") is True


async def test_matching_token_succeeds_again():
    await verify_or_claim("tim@example.com", "tims-real-token")
    assert await verify_or_claim("tim@example.com", "tims-real-token") is True


async def test_mismatched_token_is_rejected():
    # This is the actual security property: once "tim@example.com" has
    # been claimed by one token, a DIFFERENT token claiming to be the
    # same user_key - the exact shape of one person trying to act as
    # another just by knowing/guessing their email - must fail.
    await verify_or_claim("tim@example.com", "tims-real-token")
    assert await verify_or_claim("tim@example.com", "attackers-token") is False


async def test_empty_user_key_is_rejected():
    assert await verify_or_claim("", "some-token") is False


async def test_empty_token_is_rejected():
    assert await verify_or_claim("tim@example.com", "") is False


async def test_different_user_keys_do_not_collide():
    assert await verify_or_claim("tim@example.com", "tims-token") is True
    assert await verify_or_claim("alice@example.com", "alices-token") is True
    # Confirms the two identities are independent, not sharing one slot.
    assert await verify_or_claim("tim@example.com", "alices-token") is False
    assert await verify_or_claim("alice@example.com", "tims-token") is False
