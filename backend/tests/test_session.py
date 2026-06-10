"""Tests for the single-active-chat invariant (ChatSession)."""

import asyncio

from app.session import ChatSession


async def test_first_chat_claims_slot(session: ChatSession):
    assert session.active_chat_id is None
    assert await session.claim(111) is True
    assert session.active_chat_id == 111
    assert session.has_active_chat is True


async def test_second_chat_is_rejected_while_first_is_bound(session: ChatSession):
    await session.claim(111)
    # A different chat cannot take the slot...
    assert await session.claim(222) is False
    # ...and the original chat remains bound.
    assert session.active_chat_id == 111


async def test_bound_chat_can_claim_again(session: ChatSession):
    await session.claim(111)
    # The same chat messaging again is accepted (idempotent), not a new claim.
    assert await session.claim(111) is True
    assert session.active_chat_id == 111


async def test_configured_override_allows_only_the_pinned_chat(session: ChatSession):
    pinned = ChatSession(allowed_chat_id=999)
    # The pinned chat binds normally...
    assert await pinned.claim(999) is True
    assert pinned.active_chat_id == 999


async def test_configured_override_rejects_other_chat_even_if_first():
    pinned = ChatSession(allowed_chat_id=999)
    # A non-pinned chat is rejected even though no one has claimed yet.
    assert await pinned.claim(111) is False
    assert pinned.active_chat_id is None


async def test_reset_clears_the_slot(session: ChatSession):
    await session.claim(111)
    await session.reset()
    assert session.active_chat_id is None
    # After reset a different chat may claim.
    assert await session.claim(222) is True
    assert session.active_chat_id == 222


async def test_concurrent_claims_only_one_wins(session: ChatSession):
    # Fire many distinct chats at the unbound session simultaneously. The asyncio.Lock
    # must ensure exactly one wins and the slot is consistent.
    chat_ids = list(range(1, 21))
    results = await asyncio.gather(*(session.claim(cid) for cid in chat_ids))

    assert results.count(True) == 1
    winner = chat_ids[results.index(True)]
    assert session.active_chat_id == winner
