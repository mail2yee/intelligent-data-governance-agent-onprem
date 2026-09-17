from app.identity import reset_identity, verify_or_claim


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


async def test_reset_identity_returns_false_when_nothing_was_claimed():
    assert await reset_identity("nobody@example.com") is False


async def test_reset_identity_clears_the_binding_so_a_new_token_can_claim_it():
    # This is the actual recovery scenario: Tim lost his original token
    # (cleared browser storage) and needs a fresh one to work again.
    await verify_or_claim("tim@example.com", "tims-lost-token")
    assert await verify_or_claim("tim@example.com", "a-new-token") is False

    assert await reset_identity("tim@example.com") is True

    assert await verify_or_claim("tim@example.com", "a-new-token") is True
    # The old token is no longer valid - the reset really replaced the
    # binding, not just left both tokens accepted.
    assert await verify_or_claim("tim@example.com", "tims-lost-token") is False
