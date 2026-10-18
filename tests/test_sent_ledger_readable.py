"""
Whether this service may read the sent ledger, asked of Pub/Sub (N01 operations): a
configured ledger that cannot be read makes every retry after an unknown send fail closed,
so the permission is checked where an operator can see it. The subscription is never named.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(__file__))
from test_evidence_execution import _with_pubsub  # noqa: E402
from test_routes import FlaskTestBase  # noqa: E402
from vf_logistics import tools  # noqa: E402

LEDGER = "very-private-ledger-name"
CONSUME = "pubsub.subscriptions.consume"


def _subscriber(permissions=None, error=None):
    client = MagicMock()
    client.subscription_path.side_effect = lambda project, sub: f"projects/{project}/subscriptions/{sub}"
    if error is not None:
        client.test_iam_permissions.side_effect = error
    else:
        client.test_iam_permissions.return_value = SimpleNamespace(permissions=list(permissions or []))
    module = MagicMock()
    module.SubscriberClient.return_value = client
    return module, client


class TestTheLedgerPermissionCheck(unittest.TestCase):
    def setUp(self):
        tools._LEDGER_CHECK.update(at=0.0, readable=None)
        self.env = patch.dict(os.environ, {"PROJECT_ID": "test-project"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        tools._LEDGER_CHECK.update(at=0.0, readable=None)

    def test_no_ledger_configured_is_none_and_asks_nothing(self):
        module, client = _subscriber([CONSUME])
        with patch.object(tools, "SENT_LEDGER_SUBSCRIPTION", ""), _with_pubsub(module):
            self.assertIsNone(tools.sent_ledger_readable())
        client.test_iam_permissions.assert_not_called()

    def test_a_ledger_this_service_may_consume_is_readable(self):
        module, client = _subscriber([CONSUME])
        with patch.object(tools, "SENT_LEDGER_SUBSCRIPTION", LEDGER), _with_pubsub(module):
            self.assertIs(tools.sent_ledger_readable(), True)
        request = client.test_iam_permissions.call_args.kwargs["request"]
        self.assertEqual(request["resource"], f"projects/test-project/subscriptions/{LEDGER}")
        self.assertEqual(request["permissions"], [CONSUME])

    def test_a_ledger_without_the_permission_is_not_readable(self):
        module, _ = _subscriber([])
        with patch.object(tools, "SENT_LEDGER_SUBSCRIPTION", LEDGER), _with_pubsub(module):
            self.assertIs(tools.sent_ledger_readable(), False)

    def test_a_check_pubsub_does_not_answer_is_not_readable(self):
        module, _ = _subscriber(error=RuntimeError("503 Service Unavailable"))
        with patch.object(tools, "SENT_LEDGER_SUBSCRIPTION", LEDGER), _with_pubsub(module):
            self.assertIs(tools.sent_ledger_readable(), False)

    def test_the_answer_is_kept_for_a_while(self):
        module, client = _subscriber([CONSUME])
        with patch.object(tools, "SENT_LEDGER_SUBSCRIPTION", LEDGER), _with_pubsub(module):
            tools.sent_ledger_readable()
            tools.sent_ledger_readable()
        self.assertEqual(client.test_iam_permissions.call_count, 1)


class TestTheLedgerRoute(FlaskTestBase):
    def setUp(self):
        super().setUp()
        tools._LEDGER_CHECK.update(at=0.0, readable=None)

    def tearDown(self):
        tools._LEDGER_CHECK.update(at=0.0, readable=None)
        super().tearDown()

    def test_the_route_says_configured_and_readable_without_the_name(self):
        module, _ = _subscriber([CONSUME])
        with patch.dict(os.environ, {"PROJECT_ID": "test-project"}), \
                patch.object(tools, "SENT_LEDGER_SUBSCRIPTION", LEDGER), _with_pubsub(module):
            response = self.client.get("/api/v1/ops/sent-ledger")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.data), {"configured": True, "readable": True})
        self.assertNotIn(LEDGER, response.get_data(as_text=True))

    def test_the_route_says_not_configured(self):
        with patch.object(tools, "SENT_LEDGER_SUBSCRIPTION", ""):
            response = self.client.get("/api/v1/ops/sent-ledger")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.data), {"configured": False, "readable": None})


if __name__ == "__main__":
    unittest.main()
