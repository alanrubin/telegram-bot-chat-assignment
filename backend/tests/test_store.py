"""Tests for the message store and the broadcast fan-out (ordering, delivery, pruning)."""

import asyncio
import json

from app.store import ConnectionManager, MessageStore


def test_ids_are_monotonic_in_insertion_order(store: MessageStore, ts):
    a = store.add(text="one", direction="incoming", sender="Alan", timestamp=ts(0))
    b = store.add(text="two", direction="outgoing", sender="You", timestamp=ts(1))
    c = store.add(text="three", direction="incoming", sender="Alan", timestamp=ts(2))
    assert [m.id for m in (a, b, c)] == [1, 2, 3]
    assert [m.text for m in store.messages] == ["one", "two", "three"]


async def test_broadcast_fans_out_to_all_clients(manager: ConnectionManager, new_client, ts):
    c1, c2 = new_client(), new_client()
    await manager.connect(c1)
    await manager.connect(c2)

    msg = await manager.record_and_broadcast(
        text="hi", direction="incoming", sender="Alan", timestamp=ts(0)
    )

    for client in (c1, c2):
        assert len(client.received) == 1
        frame = json.loads(client.received[0])
        assert frame["type"] == "message"
        assert frame["message"]["id"] == msg.id
        assert frame["message"]["text"] == "hi"


async def test_broadcast_prunes_dead_client(manager: ConnectionManager, new_client, dead_client, ts):
    alive = new_client()
    await manager.connect(alive)
    await manager.connect(dead_client)

    await manager.record_and_broadcast(
        text="hello", direction="incoming", sender="Alan", timestamp=ts(0)
    )

    # The live client still received the message; the dead one was pruned.
    assert len(alive.received) == 1
    assert manager.client_count == 1


async def test_record_and_broadcast_preserves_order_under_concurrency(
    manager: ConnectionManager, new_client, ts
):
    client = new_client()
    await manager.connect(client)

    # Fire many broadcasts concurrently; the lock must serialize them so both the stored
    # ids and the per-client delivery order are 1..N in call order.
    texts = [f"m{i}" for i in range(10)]
    await asyncio.gather(
        *(
            manager.record_and_broadcast(
                text=t, direction="incoming", sender="Alan", timestamp=ts(i)
            )
            for i, t in enumerate(texts)
        )
    )

    delivered = [json.loads(p)["message"] for p in client.received]
    assert [m["id"] for m in delivered] == list(range(1, 11))


async def test_send_history_replays_full_session(
    manager: ConnectionManager, store: MessageStore, new_client, ts
):
    store.add(text="one", direction="incoming", sender="Alan", timestamp=ts(0))
    store.add(text="two", direction="outgoing", sender="You", timestamp=ts(1))

    client = new_client()
    await manager.send_history(client)

    frame = json.loads(client.received[0])
    assert frame["type"] == "history"
    assert [m["text"] for m in frame["messages"]] == ["one", "two"]


async def test_connect_and_sync_sends_status_then_history_then_registers(
    manager: ConnectionManager, new_client, ts
):
    # Seed some history so the snapshot is non-trivial.
    await manager.record_and_broadcast(
        text="earlier", direction="incoming", sender="Alan", timestamp=ts(0)
    )

    client = new_client()
    await manager.connect_and_sync(client, active_chat=True)

    status = json.loads(client.received[0])
    history = json.loads(client.received[1])
    assert status["type"] == "status" and status["activeChat"] is True
    assert history["type"] == "history" and [m["text"] for m in history["messages"]] == ["earlier"]

    # The client is now registered, so a subsequent broadcast reaches it exactly once.
    await manager.record_and_broadcast(
        text="later", direction="incoming", sender="Alan", timestamp=ts(1)
    )
    frames = [json.loads(p) for p in client.received]
    message_texts = [f["message"]["text"] for f in frames if f["type"] == "message"]
    assert message_texts == ["later"]


async def test_reset_history_clears_store_and_pushes_empty_history(
    manager: ConnectionManager, store: MessageStore, new_client, ts
):
    client = new_client()
    await manager.connect(client)
    await manager.record_and_broadcast(
        text="old", direction="incoming", sender="Alan", timestamp=ts(0)
    )

    await manager.reset_history()

    assert len(store) == 0
    # The client received an empty history frame so its UI clears too.
    last = json.loads(client.received[-1])
    assert last["type"] == "history" and last["messages"] == []
