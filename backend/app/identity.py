"""
Trust-on-first-use (TOFU) identity for a self-declared `user_key` - see
`UserIdentity`'s docstring in db.py for the full rationale.

This is deliberately NOT real authentication: there is no password, no
server-issued session, no proof the `user_key` a browser claims is the
real name/email of the person using it. What it *does* provide is
distinguishing individuals from each other - the first client to claim
a given `user_key` mints a random token (client-side, stored in that
browser's localStorage); every later request claiming the same
`user_key` must present the same token, or it's rejected. Two different
people can no longer silently collide on the same `user_key` (e.g. both
typing "Tim"), and nobody can act as a `user_key` they didn't originate
just by knowing/guessing it (e.g. an owner's email, visible in ticket
data) - closing the specific gap a security review found: `submit_approval()`
and the `/api/preferences` endpoints trusted a self-reported identity
with no ownership check whatsoever.

Real per-user identity requires the company's SSO/OIDC - out of scope
until that's available (see main.py's submit_approval docstring).
"""

import hashlib

from sqlalchemy.exc import IntegrityError

from .db import UserIdentity, async_session


def _hash_token(token: str) -> str:
    # Not a password hash (no salt/stretching needed) - the token is a
    # high-entropy value generated client-side (crypto.randomUUID()),
    # never a human-chosen secret to defend against offline guessing.
    # Hashed at rest purely so a DB read doesn't hand over the literal
    # bearer token.
    return hashlib.sha256(token.encode()).hexdigest()


async def verify_or_claim(user_key: str, token: str) -> bool:
    """True if `token` is valid for `user_key` - either it already
    matches what was claimed first, or `user_key` has never been
    claimed before (in which case this claims it now, atomically with
    the check, so the first caller for a given user_key always wins).
    False means a different token was already bound to this user_key -
    callers should treat that as a hard rejection (403), not a
    fallback-to-anonymous."""
    if not user_key or not token:
        return False
    token_hash = _hash_token(token)
    async with async_session() as session:
        existing = await session.get(UserIdentity, user_key)
        if existing is None:
            session.add(UserIdentity(user_key=user_key, token_hash=token_hash))
            try:
                await session.commit()
                return True
            except IntegrityError:
                # Two first-claims for the same brand-new user_key raced
                # each other - whichever committed first legitimately
                # owns it now, re-check against that instead of erroring.
                await session.rollback()
                existing = await session.get(UserIdentity, user_key)
        return existing is not None and existing.token_hash == token_hash
