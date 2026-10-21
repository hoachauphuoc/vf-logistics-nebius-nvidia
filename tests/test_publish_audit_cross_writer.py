"""Independent N01 check: the normal publisher and the sent ledger race for one send."""
import asyncio
import os
from unittest.mock import AsyncMock, patch

from test_evidence_eval_approve import Base
from test_evidence_execution import _fake_pubsub, _with_pubsub
from test_sent_ledger import _ledger, _received
from vf_logistics import tools


class TestNormalPublisherAndLedger(Base):
    def test_sequential_normal_publish_then_ledger_keeps_one_row(self):
        case_id, key, message_id, tenant = 'CASE-SF-N01-CONTROL', 'exec-sf-control', 'msg-sf-control', 'default'
        pubsub, published = _fake_pubsub([message_id])
        acked = _ledger(pubsub, [[_received(case_id, key, message_id, tenant=tenant)]])
        with patch.dict(os.environ, {'PROJECT_ID': 'test-project'}), _with_pubsub(pubsub), patch.object(tools, 'SENT_LEDGER_SUBSCRIPTION', 'decisions-sent'):
            asyncio.run(tools.publish_decision_direct(case_id, {'case_id': case_id, 'outcome': 'RELEASED_BY_HUMAN', 'idempotency_key': key}, tenant_id=tenant))
            saved = asyncio.run(tools._settle_from_ledger())
        rows = asyncio.run(self.store.list_audit(limit=100, tenant_id=tenant))
        matching = [r for r in rows if r.get('action') == 'publish_decision' and r.get('detail', {}).get('idempotency_key') == key]
        assert len(published) == 1 and saved == 0 and len(matching) == 1
        assert acked == ['ack-1']

    def test_one_broker_message_has_one_audit_row_even_if_ledger_writes_first(self):
        case_id, key, message_id, tenant = 'CASE-SF-N01-CROSS-WRITER', 'exec-sf-one-send', 'msg-sf-one', 'default'
        pubsub, published = _fake_pubsub([message_id])
        acked = _ledger(pubsub, [[_received(case_id, key, message_id, tenant=tenant)]])
        real_audit = tools._audit

        async def interleaving():
            broker_accepted = asyncio.Event()
            ledger_saved = asyncio.Event()

            async def delayed_normal_audit(cid, action, detail, status='done', tenant_id=None):
                if cid == case_id and action == 'publish_decision':
                    broker_accepted.set()
                    await asyncio.wait_for(ledger_saved.wait(), timeout=5)
                return await real_audit(cid, action, detail, status=status, tenant_id=tenant_id)

            async def drain():
                await asyncio.wait_for(broker_accepted.wait(), timeout=5)
                count = await tools._settle_from_ledger()
                ledger_saved.set()
                return count

            with patch.object(tools, '_audit', new=delayed_normal_audit):
                return await asyncio.gather(
                    tools.publish_decision_direct(case_id, {'case_id': case_id, 'outcome': 'RELEASED_BY_HUMAN', 'idempotency_key': key}, tenant_id=tenant),
                    drain(),
                )

        # Both writers can observe no earlier row; only the shared atomic id
        # can prevent the normal publisher from adding a second receipt.
        with patch.dict(os.environ, {'PROJECT_ID': 'test-project'}), _with_pubsub(pubsub), patch.object(tools, 'SENT_LEDGER_SUBSCRIPTION', 'decisions-sent'), patch.object(tools, '_earlier_publish', new=AsyncMock(return_value=None)):
            _receipt, saved = asyncio.run(interleaving())
        rows = asyncio.run(self.store.list_audit(limit=100, tenant_id=tenant))
        matching = [r for r in rows if r.get('action') == 'publish_decision' and r.get('detail', {}).get('idempotency_key') == key]
        assert len(published) == 1
        assert saved == 1 and acked == ['ack-1']
        assert {r['detail']['message_id'] for r in matching} == {message_id}
        assert len(matching) == 1

    def test_failed_and_unknown_attempts_are_kept_beside_one_success(self):
        detail = {'idempotency_key': 'exec-history', 'message_id': 'msg-history'}

        async def history():
            await tools._audit('CASE-HISTORY', 'publish_decision', detail, status='failed')
            await tools._audit('CASE-HISTORY', 'publish_decision', detail, status='unknown')
            first = await tools._audit('CASE-HISTORY', 'publish_decision', detail)
            second = await tools._audit('CASE-HISTORY', 'publish_decision', detail)
            return first, second

        first, second = asyncio.run(history())
        rows = asyncio.run(self.store.list_audit(limit=100))
        assert sorted(row['status'] for row in rows) == ['done', 'failed', 'unknown']
        assert first['audit_id'] == second['audit_id']

    def test_implicit_and_explicit_default_tenant_share_the_atomic_id(self):
        detail = {'idempotency_key': 'exec-tenant-alias', 'message_id': 'msg-alias'}

        async def stale_readers():
            await tools._audit('CASE-ALIAS', 'publish_decision', detail)
            return await tools.record_publish_audit('CASE-ALIAS', detail, 'reviewer@test.invalid', tenant_id='default')

        with patch.object(tools, '_earlier_publish', new=AsyncMock(return_value=None)):
            assert asyncio.run(stale_readers()) is False
        rows = asyncio.run(self.store.list_audit(limit=100))
        assert len(rows) == 1

    def test_a_legacy_random_id_record_is_reused_without_another_row(self):
        detail = {'idempotency_key': 'exec-legacy', 'message_id': 'msg-legacy'}
        legacy = {'audit_id': 'old-random-id', 'case_id': 'CASE-LEGACY', 'action': 'publish_decision', 'status': 'done', 'detail': detail, 'at': '2026-10-21T00:00:00Z'}
        asyncio.run(self.store.add_audit(legacy))
        receipt = asyncio.run(tools._audit('CASE-LEGACY', 'publish_decision', detail))
        assert receipt['audit_id'] == 'old-random-id'
        assert len(asyncio.run(self.store.list_audit(limit=100))) == 1
