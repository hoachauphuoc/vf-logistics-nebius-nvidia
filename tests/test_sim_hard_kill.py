"""
Simulation of the one N01 case the sender cannot close: the process is killed outright
after the broker accepted the decision and before anything was saved.

Runs against the Pub/Sub and Firestore emulators and is skipped without them:

    gcloud beta emulators firestore start --host-port=127.0.0.1:8681
    gcloud beta emulators pubsub start --host-port=127.0.0.1:8085
    FIRESTORE_EMULATOR_HOST=127.0.0.1:8681 PUBSUB_EMULATOR_HOST=127.0.0.1:8085 python -m pytest tests/test_sim_hard_kill.py

A child process executes the approval and is killed the moment the broker has the
message, so no handler runs. A Resume after the lease publishes again: the sender
cannot know the first one went out. The reference receiver
(scripts/reference_receiver.py) then applies the decision once.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from reference_receiver import apply_once, firestore_claim  # noqa: E402
from test_evidence_eval_approve import REVIEWER, Base, run  # noqa: E402
from vf_logistics import evidence, tools  # noqa: E402
from vf_logistics import store as store_mod  # noqa: E402

FIRESTORE = os.getenv("FIRESTORE_EMULATOR_HOST", "")
PUBSUB = os.getenv("PUBSUB_EMULATOR_HOST", "")
PROJECT = "vf-sim-hard-kill"
CHILD = os.path.join(os.path.dirname(__file__), "sim_hard_kill_child.py")


def _wipe_firestore() -> None:
    request = urllib.request.Request(
        f"http://{FIRESTORE}/emulator/v1/projects/{PROJECT}/databases/(default)/documents",
        method="DELETE",
    )
    urllib.request.urlopen(request, timeout=10).close()  # noqa: S310 - local emulator


def _fresh_subscription():
    """A subscription created now on the decisions topic, so it holds only this test's messages."""
    from google.api_core.exceptions import AlreadyExists
    from google.cloud import pubsub_v1

    publisher = pubsub_v1.PublisherClient()
    subscriber = pubsub_v1.SubscriberClient()
    topic = publisher.topic_path(PROJECT, tools.DECISIONS_TOPIC)
    try:
        publisher.create_topic(name=topic)
    except AlreadyExists:
        pass
    subscription = subscriber.subscription_path(PROJECT, f"sim-{time.time_ns()}")
    subscriber.create_subscription(name=subscription, topic=topic)
    return subscriber, subscription


def _pull_all(subscriber, subscription: str, expected: int) -> list:
    from google.api_core.exceptions import DeadlineExceeded

    messages: list = []
    deadline = time.time() + 30
    while len(messages) < expected and time.time() < deadline:
        try:
            response = subscriber.pull(subscription=subscription, max_messages=10, timeout=5)
        except DeadlineExceeded:
            continue
        if response.received_messages:
            messages += [m.message for m in response.received_messages]
            subscriber.acknowledge(
                subscription=subscription, ack_ids=[m.ack_id for m in response.received_messages],
            )
    return messages


@pytest.mark.skipif(not (FIRESTORE and PUBSUB), reason="needs FIRESTORE_EMULATOR_HOST and PUBSUB_EMULATOR_HOST")
class TestAHardKillAfterTheBrokerAccepted(Base):
    def setup_method(self):
        super().setup_method()
        _wipe_firestore()
        self.emulators = patch.dict(os.environ, {"STORE_BACKEND": "firestore", "PROJECT_ID": PROJECT})
        self.emulators.start()
        self.store = store_mod.FirestoreStore(PROJECT)
        store_mod._store = self.store

    def teardown_method(self):
        self.emulators.stop()
        super().teardown_method()

    def test_the_decision_is_published_twice_and_applied_once(self):
        self.put()
        self.request_and_submit()
        run(evidence.reevaluate("CASE-1"))
        approval_id = run(evidence.approve(
            "CASE-1", "release", REVIEWER, note="Reviewed", actor_auth="password",
        ))["approval"]["approval_id"]
        subscriber, subscription = _fresh_subscription()

        # 1. The child executes the approval and is killed once the broker has the message.
        child = subprocess.run([sys.executable, CHILD, "CASE-1", approval_id, REVIEWER], timeout=120)
        assert child.returncode != 0
        assert self.stored()["state"] == "EXECUTING"
        rows = [r for r in run(self.store.list_audit(limit=500)) if r.get("action") == "publish_decision"]
        assert rows == []  # nothing was saved: the sender cannot know the decision went out

        # 2. After the lease, a Resume publishes again under the same key.
        case = self.stored()
        case["verification"]["executions"][0]["claim_expires_epoch"] = time.time() - 1
        run(self.store.put_case(case))
        result = run(evidence.execute_approval("CASE-1", approval_id, REVIEWER, actor_auth="password"))
        assert result["state"] == "RELEASED_BY_HUMAN"

        messages = _pull_all(subscriber, subscription, expected=2)
        assert [m.attributes["idempotency_key"] for m in messages] == [f"exec-{approval_id}"] * 2

        # 3. The reference receiver applies it once.
        from google.cloud import firestore

        claim = firestore_claim(firestore.Client(project=PROJECT))
        applied: list[str] = []
        outcomes = [apply_once(m.attributes, claim, lambda m=m: applied.append(m.message_id)) for m in messages]
        assert sorted(outcomes) == ["applied", "duplicate"]
        assert len(applied) == 1
