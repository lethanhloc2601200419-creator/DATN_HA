"""
Unit tests cho luồng PayOS Payout integration (V2 spec).

Chạy:
    python manage.py test admin_panel.test_payos_integration

Đa số tests dùng mock thay vì hit DB / network thật để chạy nhanh và không
phụ thuộc credentials. TestCase được dùng cho webhook/handler vì cần
DisbursementProposal.objects lookup.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal
from unittest import mock
from urllib.parse import quote

from django.test import RequestFactory, SimpleTestCase, override_settings

from client.payos_payout import (
    PayosPayoutService,
    PayoutRequestError,
    _PAYOS_ENCODE_SAFE,
    _build_payout_signature,
    _resolve_bank_bin,
)


# ==========================================================================
# Helpers — build mock proposal/org/campaign objects mà không cần DB.
# ==========================================================================
class _StubObj:
    """
    Simple attribute container — KHÁC MagicMock vì missing-attribute access raise
    AttributeError → getattr(obj, 'x', default) trả về default. Đó là behavior
    mong muốn cho `_resolve_bank_bin` (cần fall-through khi không có bank_bin).
    """

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def _make_mock_proposal(
    proposal_id=42,
    amount=1_500_000,
    bank_account='0123456789',
    bank_name='MB Bank',
    bank_bin=None,
    payos_payout_id=None,
    v3_status='ready_to_payout',
    multisig_confirmed_tx_hash='0xabc',
):
    org_kwargs = dict(
        bank_account_number=bank_account,
        bank_name=bank_name,
        wallet_address='0x1234567890123456789012345678901234567890',
    )
    if bank_bin is not None:
        org_kwargs['bank_bin'] = bank_bin
    org = _StubObj(**org_kwargs)

    campaign = _StubObj(id=7, organization=org)

    proposal = _StubObj(
        id=proposal_id,
        pk=proposal_id,
        amount_requested=Decimal(str(amount)),
        campaign=campaign,
        campaign_id=campaign.id,
        payos_payout_id=payos_payout_id,
        v3_status=v3_status,
        multisig_confirmed_tx_hash=multisig_confirmed_tx_hash,
        bank_tx_id=None,
        burn_tx_hash=None,
        payout_error=None,
    )
    # save() is a Mock so tests can assert call counts.
    proposal.save = mock.MagicMock()
    return proposal


# ==========================================================================
# TASK 1 — PayosPayoutService
# ==========================================================================
@override_settings(
    PAYOS_PAYOUT_CLIENT_ID='test-client',
    PAYOS_PAYOUT_API_KEY='test-api-key',
    PAYOS_PAYOUT_CHECKSUM_KEY='test-checksum',
    # KHÔNG set PAYOS_CLIENT_ID/API_KEY/CHECKSUM_KEY — để chứng minh service
    # chỉ dùng key Kênh Chi (PAYOS_PAYOUT_*), không leak sang Kênh Thu.
    PAYOS_PAYOUT_MOCK=False,
)
class PayosPayoutServiceTests(SimpleTestCase):
    def test_resolve_bank_bin_from_explicit_field(self):
        org = mock.MagicMock()
        org.bank_bin = '970422'
        self.assertEqual(_resolve_bank_bin(org), '970422')

    def test_resolve_bank_bin_from_name_mapping(self):
        org = mock.MagicMock()
        del org.bank_bin
        org.bank_name = 'MB Bank'
        self.assertEqual(_resolve_bank_bin(org), '970422')

    def test_resolve_bank_bin_substring_match(self):
        org = mock.MagicMock()
        del org.bank_bin
        org.bank_name = 'Vietcombank — Chi nhánh HCM'
        self.assertEqual(_resolve_bank_bin(org), '970436')

    def test_resolve_bank_bin_unknown_returns_empty(self):
        org = mock.MagicMock()
        del org.bank_bin
        org.bank_name = 'Một ngân hàng lạ hoắc'
        self.assertEqual(_resolve_bank_bin(org), '')

    def test_init_raises_when_no_credentials_in_real_mode(self):
        # Spec tách tuyệt đối: thiếu PAYOS_PAYOUT_* → phải raise NGAY,
        # KHÔNG fallback sang PAYOS_* (Kênh Thu) dù các biến đó có set.
        with override_settings(
            PAYOS_PAYOUT_CLIENT_ID='',
            PAYOS_PAYOUT_API_KEY='',
            PAYOS_PAYOUT_CHECKSUM_KEY='',
            # PAYOS_* set sẵn — service vẫn PHẢI raise (không được fallback).
            PAYOS_CLIENT_ID='thu-client',
            PAYOS_API_KEY='thu-api',
            PAYOS_CHECKSUM_KEY='thu-checksum',
            PAYOS_PAYOUT_MOCK=False,
        ):
            with self.assertRaises(PayoutRequestError):
                PayosPayoutService()

    @mock.patch('client.payos_payout._http_requests.get')
    def test_check_balance_success(self, mock_get):
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'code': '00', 'data': {'balance': 5_000_000}}
        mock_get.return_value = mock_resp

        service = PayosPayoutService()
        balance = service.check_balance()
        self.assertEqual(balance, 5_000_000)
        # Verify đã pass đúng headers.
        call_kwargs = mock_get.call_args.kwargs
        self.assertEqual(call_kwargs['headers']['x-client-id'], 'test-client')
        self.assertEqual(call_kwargs['headers']['x-api-key'], 'test-api-key')

    @mock.patch('client.payos_payout._http_requests.get')
    def test_check_balance_payos_reject_raises(self, mock_get):
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {'code': '20', 'desc': 'invalid api key'}
        mock_get.return_value = mock_resp

        service = PayosPayoutService()
        with self.assertRaises(PayoutRequestError):
            service.check_balance()

    @mock.patch('client.payos_payout._http_requests.post')
    def test_create_payout_success_persists_payout_id(self, mock_post):
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'code': '00',
            'data': {'payoutId': 'PAYOUT-XYZ-123', 'status': 'PROCESSING'},
        }
        mock_post.return_value = mock_resp

        service = PayosPayoutService()
        proposal = _make_mock_proposal()

        response = service.create_payout(proposal)

        # Response trả về raw payload.
        self.assertEqual(response['data']['payoutId'], 'PAYOUT-XYZ-123')
        # Side-effect: gán payos_payout_id + v3_status='payout_processing'.
        self.assertEqual(proposal.payos_payout_id, 'PAYOUT-XYZ-123')
        self.assertEqual(proposal.v3_status, 'payout_processing')
        proposal.save.assert_called_once()
        # Body chỉ chứa flat required fields + signature đúng canonical sorted keys.
        headers = mock_post.call_args.kwargs['headers']
        self.assertEqual(headers['x-idempotency-key'], 'proposal_42')
        self.assertIn('x-signature', headers)
        self.assertEqual(len(headers['x-signature']), 64)  # hex SHA256
        body = mock_post.call_args.kwargs['json']
        self.assertEqual(
            set(body.keys()),
            {'amount', 'description', 'referenceId', 'toAccountNumber', 'toBin'},
        )
        self.assertEqual(body['referenceId'], 'proposal_42')
        self.assertEqual(body['amount'], 1_500_000)
        self.assertEqual(body['toAccountNumber'], '0123456789')
        self.assertEqual(body['toBin'], '970422')  # MB Bank
        sign_string = '&'.join(
            f"{key}={quote(str(body[key]), safe=_PAYOS_ENCODE_SAFE)}"
            for key in sorted(body.keys())
        )
        expected_signature = hmac.new(
            b'test-checksum',
            sign_string.encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(headers['x-signature'], expected_signature)

    def test_create_payout_missing_bank_info_raises(self):
        service = PayosPayoutService()
        proposal = _make_mock_proposal(bank_account='', bank_name='')
        with self.assertRaises(PayoutRequestError):
            service.create_payout(proposal)
        # Không touch DB nếu fail validate.
        proposal.save.assert_not_called()

    @mock.patch('client.payos_payout._http_requests.post')
    def test_create_payout_payos_reject_raises(self, mock_post):
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {'code': '99', 'desc': 'duplicated reference'}
        mock_post.return_value = mock_resp

        service = PayosPayoutService()
        proposal = _make_mock_proposal()
        with self.assertRaises(PayoutRequestError):
            service.create_payout(proposal)
        # Không persist khi PayOS reject.
        proposal.save.assert_not_called()

    @mock.patch('client.payos_payout._http_requests.get')
    def test_get_payout_status_succeeded(self, mock_get):
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'code': '00', 'data': {'status': 'SUCCESS'}}
        mock_get.return_value = mock_resp
        service = PayosPayoutService()
        self.assertEqual(service.get_payout_status('PAYOUT-1'), 'SUCCEEDED')

    @mock.patch('client.payos_payout._http_requests.get')
    def test_get_payout_status_failed(self, mock_get):
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'code': '00', 'data': {'status': 'CANCELLED'}}
        mock_get.return_value = mock_resp
        service = PayosPayoutService()
        self.assertEqual(service.get_payout_status('PAYOUT-1'), 'FAILED')

    @mock.patch('client.payos_payout._http_requests.get')
    def test_get_payout_status_processing(self, mock_get):
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'code': '00', 'data': {'status': 'PROCESSING'}}
        mock_get.return_value = mock_resp
        service = PayosPayoutService()
        self.assertEqual(service.get_payout_status('PAYOUT-1'), 'PROCESSING')

    def test_get_payout_status_empty_id_raises(self):
        service = PayosPayoutService()
        with self.assertRaises(PayoutRequestError):
            service.get_payout_status('')


@override_settings(
    PAYOS_PAYOUT_CLIENT_ID='cid',
    PAYOS_PAYOUT_API_KEY='akey',
    PAYOS_PAYOUT_CHECKSUM_KEY='cksum',
    PAYOS_PAYOUT_MOCK=True,
)
class PayosPayoutServiceMockModeTests(SimpleTestCase):
    """MOCK mode: KHÔNG gọi mạng, trả response dummy."""

    def test_check_balance_mock_returns_huge_value(self):
        service = PayosPayoutService()
        self.assertGreaterEqual(service.check_balance(), 1_000_000_000)

    def test_create_payout_mock_persists_fake_payout_id(self):
        service = PayosPayoutService()
        proposal = _make_mock_proposal()
        response = service.create_payout(proposal)
        self.assertTrue(response.get('mock'))
        self.assertTrue(proposal.payos_payout_id.startswith('PAYOUT-'))
        self.assertEqual(proposal.v3_status, 'payout_processing')

    def test_get_payout_status_mock_returns_processing(self):
        service = PayosPayoutService()
        self.assertEqual(service.get_payout_status('any-id'), 'PROCESSING')


# ==========================================================================
# TASK 2 — BlockchainService.finalize_disbursement
# ==========================================================================
class BlockchainServiceFinalizeTests(SimpleTestCase):
    @mock.patch('client.blockchain.BlockchainService.__init__', return_value=None)
    def test_finalize_disbursement_calls_smart3_with_correct_args(self, mock_init):
        from client.blockchain import BlockchainService
        bc = BlockchainService()
        # Inject mock for finalize_burn_with_bank_tx.
        bc.finalize_burn_with_bank_tx = mock.MagicMock(return_value={
            'tx_hash': '0xdeadbeef',
            'receipt': mock.MagicMock(),
            'status': 1,
        })
        proposal = _make_mock_proposal()
        result = bc.finalize_disbursement(proposal, bank_tx_id='BANK-TX-123')
        bc.finalize_burn_with_bank_tx.assert_called_once_with(
            proposal_id=proposal.id,
            multisig_vault=proposal.campaign.organization.wallet_address,
            bank_tx_id='BANK-TX-123',
        )
        self.assertEqual(result, '0xdeadbeef')

    @mock.patch('client.blockchain.BlockchainService.__init__', return_value=None)
    def test_finalize_disbursement_empty_bank_tx_id_raises(self, mock_init):
        from client.blockchain import BlockchainService
        bc = BlockchainService()
        proposal = _make_mock_proposal()
        with self.assertRaises(ValueError):
            bc.finalize_disbursement(proposal, bank_tx_id='')

    @mock.patch('client.blockchain.BlockchainService.__init__', return_value=None)
    def test_finalize_disbursement_missing_multisig_vault_raises(self, mock_init):
        from client.blockchain import BlockchainService
        bc = BlockchainService()
        proposal = _make_mock_proposal()
        proposal.campaign.organization.wallet_address = ''
        with self.assertRaises(ValueError):
            bc.finalize_disbursement(proposal, bank_tx_id='BANK-1')


# ==========================================================================
# TASK 3 — Webhook handler
# ==========================================================================
@override_settings(PAYOS_PAYOUT_CHECKSUM_KEY='webhook-secret', PAYOS_CHECKSUM_KEY='')
class PayosPayoutWebhookTests(SimpleTestCase):
    """
    SimpleTestCase + mock-heavy: tránh hit DB. transaction.atomic và
    transaction.on_commit được patch về no-op vì SimpleTestCase không có
    transaction context active.
    """

    def setUp(self):
        self.factory = RequestFactory()
        # Patch transaction.atomic & on_commit để chạy được trong SimpleTestCase.
        from contextlib import contextmanager

        @contextmanager
        def _noop_atomic(*args, **kwargs):  # noqa: ARG001
            yield

        self._atomic_patcher = mock.patch(
            'admin_panel.webhook_views.transaction.atomic',
            _noop_atomic,
        )
        self._on_commit_patcher = mock.patch(
            'admin_panel.webhook_views.transaction.on_commit',
            side_effect=lambda fn: fn(),
        )
        self._atomic_patcher.start()
        self._on_commit_patcher.start()
        self.addCleanup(self._atomic_patcher.stop)
        self.addCleanup(self._on_commit_patcher.stop)

    @staticmethod
    def _build_signed_request(factory, body_dict):
        """Tạo POST request có x-signature đúng (HMAC raw body)."""
        body = json.dumps(body_dict).encode('utf-8')
        sig = hmac.new(
            b'webhook-secret', body, hashlib.sha256,
        ).hexdigest()
        request = factory.post(
            '/webhook/payos/payout/',
            data=body,
            content_type='application/json',
            HTTP_X_SIGNATURE=sig,
        )
        return request

    def test_invalid_signature_returns_200_no_crash(self):
        from admin_panel.webhook_views import payos_payout_webhook
        body = json.dumps({'payoutId': 'PAYOUT-1', 'status': 'SUCCEEDED'}).encode('utf-8')
        request = self.factory.post(
            '/webhook/payos/payout/',
            data=body,
            content_type='application/json',
            HTTP_X_SIGNATURE='invalid-signature',
        )
        response = payos_payout_webhook(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'invalid_signature', response.content)

    def test_succeeded_branch_calls_finalize_and_notifies(self):
        from admin_panel import webhook_views
        # Mock proposal & DB lookup.
        mock_proposal = _make_mock_proposal(payos_payout_id='PAYOUT-1')
        with mock.patch.object(
            webhook_views.DisbursementProposal.objects, 'filter'
        ) as mock_filter, mock.patch.object(
            webhook_views, '_spawn_finalize_thread'
        ) as mock_spawn, mock.patch.object(
            webhook_views.NotificationService, 'notify_disbursement_success'
        ) as mock_notify:
            mock_filter.return_value.first.return_value = mock_proposal
            request = self._build_signed_request(self.factory, {
                'payoutId': 'PAYOUT-1',
                'status': 'SUCCEEDED',
                'bankTransactionId': 'BANK-TX-XYZ',
            })
            response = webhook_views.payos_payout_webhook(request)
            self.assertEqual(response.status_code, 200)
            # bank_tx_id + status được lưu lên proposal.
            self.assertEqual(mock_proposal.bank_tx_id, 'BANK-TX-XYZ')
            self.assertEqual(mock_proposal.v3_status, 'fiat_transferred')
            mock_proposal.save.assert_called_once()
            mock_spawn.assert_called_once_with(mock_proposal.id, 'BANK-TX-XYZ')
            mock_notify.assert_called_once_with(mock_proposal)

    def test_failed_branch_marks_payout_failed(self):
        from admin_panel import webhook_views
        mock_proposal = _make_mock_proposal(payos_payout_id='PAYOUT-2')
        with mock.patch.object(
            webhook_views.DisbursementProposal.objects, 'filter'
        ) as mock_filter, mock.patch.object(
            webhook_views.NotificationService, 'notify_disbursement_failed'
        ) as mock_notify:
            mock_filter.return_value.first.return_value = mock_proposal
            request = self._build_signed_request(self.factory, {
                'payoutId': 'PAYOUT-2',
                'status': 'FAILED',
                'desc': 'Bank rejected: insufficient funds at receiver',
            })
            response = webhook_views.payos_payout_webhook(request)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(mock_proposal.v3_status, 'payout_failed')
            self.assertIn('insufficient funds', mock_proposal.payout_error)
            mock_proposal.save.assert_called_once()
            mock_notify.assert_called_once_with(mock_proposal)

    def test_proposal_not_found_returns_200(self):
        from admin_panel import webhook_views
        with mock.patch.object(
            webhook_views.DisbursementProposal.objects, 'filter'
        ) as mock_filter:
            mock_filter.return_value.first.return_value = None
            request = self._build_signed_request(self.factory, {
                'payoutId': 'NON-EXISTENT',
                'status': 'SUCCEEDED',
                'bankTransactionId': 'X',
            })
            response = webhook_views.payos_payout_webhook(request)
            self.assertEqual(response.status_code, 200)

    def test_unexpected_exception_still_returns_200(self):
        from admin_panel import webhook_views
        with mock.patch.object(
            webhook_views.DisbursementProposal.objects, 'filter',
            side_effect=RuntimeError('DB down'),
        ):
            request = self._build_signed_request(self.factory, {
                'payoutId': 'P-1',
                'status': 'SUCCEEDED',
            })
            response = webhook_views.payos_payout_webhook(request)
            self.assertEqual(response.status_code, 200)


# ==========================================================================
# TASK 4 — trigger_payos_payout task
# ==========================================================================
class TriggerPayosPayoutTaskTests(SimpleTestCase):
    @mock.patch('admin_panel.tasks.disbursement_tasks.PayosPayoutService')
    def test_skip_when_payout_id_already_set(self, mock_service_cls):
        from admin_panel.tasks.disbursement_tasks import trigger_payos_payout
        proposal = _make_mock_proposal(payos_payout_id='ALREADY-EXIST')
        with mock.patch(
            'admin_panel.models.DisbursementProposal.objects.select_related'
        ) as mock_sel:
            mock_sel.return_value.get.return_value = proposal
            # task underlying fn (unwrap if wrapper).
            fn = getattr(trigger_payos_payout, 'fn', trigger_payos_payout)
            result = fn(proposal.id)
        self.assertTrue(result['skipped'])
        self.assertEqual(result['payout_id'], 'ALREADY-EXIST')
        # PayosPayoutService không được khởi tạo (skip trước khi đến đó).
        mock_service_cls.assert_not_called()

    @mock.patch('admin_panel.tasks.disbursement_tasks.PayosPayoutService')
    def test_creates_payout_when_balance_sufficient(self, mock_service_cls):
        from admin_panel.tasks.disbursement_tasks import trigger_payos_payout
        proposal = _make_mock_proposal()
        proposal.payos_payout_id = None

        service = mock_service_cls.return_value
        service.check_balance.return_value = 100_000_000
        service.create_payout.return_value = {
            'code': '00',
            'data': {'payoutId': 'PAYOUT-NEW-1', 'status': 'PROCESSING'},
        }
        with mock.patch(
            'admin_panel.models.DisbursementProposal.objects.select_related'
        ) as mock_sel:
            mock_sel.return_value.get.return_value = proposal
            fn = getattr(trigger_payos_payout, 'fn', trigger_payos_payout)
            result = fn(proposal.id)
        self.assertFalse(result['skipped'])
        self.assertEqual(result['payout_id'], 'PAYOUT-NEW-1')
        service.check_balance.assert_called_once()
        service.create_payout.assert_called_once_with(proposal)

    @mock.patch('admin_panel.tasks.disbursement_tasks.PayosPayoutService')
    def test_balance_insufficient_marks_failed(self, mock_service_cls):
        """Khi balance < amount: KHÔNG raise (retry vô ích), mà mark
        v3_status='payout_failed' + return dict với reason để admin theo dõi."""
        from admin_panel.tasks.disbursement_tasks import trigger_payos_payout
        proposal = _make_mock_proposal(amount=10_000_000)
        proposal.payos_payout_id = None
        service = mock_service_cls.return_value
        service.check_balance.return_value = 1_000_000  # ít hơn amount
        with mock.patch(
            'admin_panel.models.DisbursementProposal.objects.select_related'
        ) as mock_sel:
            mock_sel.return_value.get.return_value = proposal
            fn = getattr(trigger_payos_payout, 'fn', trigger_payos_payout)
            result = fn(proposal.id)
        # Behavior: ghi DB + return skipped=True, không raise.
        self.assertTrue(result['skipped'])
        self.assertEqual(result['reason'], 'insufficient_balance')
        self.assertEqual(result['balance'], 1_000_000)
        self.assertEqual(result['required'], 10_000_000)
        self.assertEqual(proposal.v3_status, 'payout_failed')
        self.assertIn('balance', proposal.payout_error.lower())
        proposal.save.assert_called_once()
        service.create_payout.assert_not_called()


# ==========================================================================
# Helper — verify _build_payout_signature deterministic.
# ==========================================================================
class PayoutSignatureHelperTests(SimpleTestCase):
    def test_signature_deterministic_and_hex(self):
        body = {'amount': 1000, 'referenceId': 'p_1', 'category': ['charity']}
        sig1 = _build_payout_signature(body, 'k')
        sig2 = _build_payout_signature(body, 'k')
        self.assertEqual(sig1, sig2)
        self.assertEqual(len(sig1), 64)
        # Different key → different sig.
        self.assertNotEqual(sig1, _build_payout_signature(body, 'other-key'))

    def test_signature_ignores_existing_signature_field(self):
        body = {'a': 1, 'b': 2}
        sig_no_field = _build_payout_signature(body, 'k')
        body_with_sig = {**body, 'signature': 'old-sig'}
        sig_with_field = _build_payout_signature(body_with_sig, 'k')
        self.assertEqual(sig_no_field, sig_with_field)
