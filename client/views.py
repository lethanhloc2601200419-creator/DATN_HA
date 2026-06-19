from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponseRedirect, JsonResponse
from admin_panel.models import (
    UserProfile, Campaign, CampaignCategory, Donation, TargetProgram,
    BankStatement, ActivityLog,
    DisbursementProposal, ProposalVote, Organization, OrganizationRepresentative,
)
from admin_panel.forms import GuestOrganizationForm, GuestRepresentativeForm
from django.utils.text import slugify
from admin_panel.disbursement_utils import check_and_execute_proposal, estimate_gas_per_tx_vnd
from django.contrib import messages
from django.db.models import Sum, Count, F, Q
from django.conf import settings
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.utils import timezone
from django.db import transaction, IntegrityError
from django.db.models import F
import hashlib
import hmac
import threading
import traceback
import urllib.parse
import json
import os
from decimal import Decimal
from datetime import datetime, timedelta
import pytz
import re
import requests as http_requests
from web3 import Web3
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

# Import Service Blockchain đã viết
from .blockchain import BlockchainService, get_eth_vnd_rate
from .blockchain_processor import start_blockchain_thread
from .forms import UserProfileForm

WEI_IN_ETH = Decimal('1000000000000000000')
SYBIL_DONATION_WINDOW = timedelta(hours=1)
SYBIL_DONATION_THRESHOLD = 3

def _wei_to_vnd(wei, eth_vnd_rate):
    return (Decimal(str(wei)) / WEI_IN_ETH) * eth_vnd_rate

vietnam_tz = pytz.timezone('Asia/Ho_Chi_Minh')
PAYOS_API_BASE = 'https://api-merchant.payos.vn'


def _build_web3_username(address):
    normalized = re.sub(r'[^a-zA-Z0-9_]+', '', (address or '').lower())
    return f'web3_{normalized[-12:] or "user"}'


def _get_or_create_web3_user(wallet_address, eoa_address='', email='', display_name=''):
    checksum_wallet = Web3.to_checksum_address(wallet_address)
    checksum_eoa = Web3.to_checksum_address(eoa_address) if eoa_address and Web3.is_address(eoa_address) else ''
    email = (email or '').strip().lower()
    display_name = (display_name or '').strip()

    profile = None
    if checksum_wallet:
        profile = UserProfile.objects.filter(
            Q(wallet_address__iexact=checksum_wallet) |
            Q(smart_account_address__iexact=checksum_wallet) |
            Q(eoa_address__iexact=checksum_wallet)
        ).select_related('user').first()

    if not profile and checksum_eoa:
        profile = UserProfile.objects.filter(
            Q(eoa_address__iexact=checksum_eoa) |
            Q(wallet_address__iexact=checksum_eoa) |
            Q(smart_account_address__iexact=checksum_eoa)
        ).select_related('user').first()

    user = profile.user if profile else None

    if not user and email:
        user = User.objects.filter(email__iexact=email).first()

    if not user:
        base_username = _build_web3_username(checksum_wallet)
        username = base_username
        suffix = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}_{suffix}"
            suffix += 1

        user = User.objects.create(
            username=username,
            email=email,
            first_name=display_name[:150] if display_name else '',
        )

    profile, _created = UserProfile.objects.get_or_create(user=user)
    if email and user.email != email:
        user.email = email
    if display_name and not user.first_name:
        user.first_name = display_name[:150]
    user.save(update_fields=['email', 'first_name'])

    profile.display_name = display_name or profile.display_name or user.first_name or user.username
    profile.eoa_address = checksum_eoa or profile.eoa_address
    profile.smart_account_address = checksum_wallet
    profile.wallet_address = checksum_wallet
    # Web3 login = Google / Web3Auth → đánh dấu để chặn ở form đăng ký tổ chức.
    # Không override nếu profile đã được admin set='web' từ trước.
    update_fields = [
        'display_name',
        'eoa_address',
        'smart_account_address',
        'wallet_address',
        'updated_at',
    ]
    if profile.account_source != 'web':
        profile.account_source = 'google'
        update_fields.append('account_source')
    profile.save(update_fields=update_fields)

    return user, profile

from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse

@csrf_exempt
@require_POST
def api_web3_login(request):
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'message': 'Invalid JSON payload.'}, status=400)

    wallet_address = (payload.get('wallet_address') or '').strip()
    eoa_address = (payload.get('eoa_address') or '').strip()
    email = (payload.get('email') or '').strip()
    display_name = (payload.get('display_name') or payload.get('name') or '').strip()
    provider = (payload.get('provider') or 'web3auth_google').strip()

    if not wallet_address or not Web3.is_address(wallet_address):
        return JsonResponse({'ok': False, 'message': 'wallet_address không hợp lệ.'}, status=400)

    if eoa_address and not Web3.is_address(eoa_address):
        return JsonResponse({'ok': False, 'message': 'eoa_address không hợp lệ.'}, status=400)

    user, profile = _get_or_create_web3_user(
        wallet_address=wallet_address,
        eoa_address=eoa_address,
        email=email,
        display_name=display_name,
    )

    login(request, user, backend='django.contrib.auth.backends.ModelBackend')

    ActivityLog.objects.create(
        user=user,
        type='web3_login',
        description=f'Đăng nhập Django session qua {provider} | ví {profile.wallet_address}',
    )

    return JsonResponse({
        'ok': True,
        'message': 'Đăng nhập Web3 thành công.',
        'user': {
            'id': user.id,
            'username': user.username,
            'email': user.email,
        },
        'wallet_address': profile.wallet_address,
        'eoa_address': profile.eoa_address or '',
        'smart_account_address': profile.smart_account_address or '',
    })


def get_client_ip(request):
    """Lấy IP client"""
    ip_headers = ['HTTP_X_FORWARDED_FOR', 'HTTP_X_REAL_IP', 'REMOTE_ADDR']
    for header in ip_headers:
        ip = request.META.get(header)
        if ip:
            ip = ip.split(',')[0].strip()
            if ip and ip != '127.0.0.1' and not ip.startswith('192.168.'):
                return ip
    return '203.162.71.6'


def _normalize_payos_value(value):
    if value in (None, 'undefined', 'null'):
        return ''
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, list):
        normalized_items = []
        for item in value:
            if isinstance(item, dict):
                normalized_items.append({k: _normalize_payos_value(v) for k, v in sorted(item.items())})
            else:
                normalized_items.append(_normalize_payos_value(item))
        return json.dumps(normalized_items, ensure_ascii=False, separators=(',', ':'))
    if isinstance(value, dict):
        normalized_dict = {k: _normalize_payos_value(v) for k, v in sorted(value.items())}
        return json.dumps(normalized_dict, ensure_ascii=False, separators=(',', ':'))
    return str(value)


def _flag_recent_sybil_donations(device_fingerprint):
    if not device_fingerprint:
        return False, 0

    window_start = timezone.now() - SYBIL_DONATION_WINDOW
    recent_qs = Donation.objects.filter(
        device_fingerprint=device_fingerprint,
        created_at__gte=window_start,
    )
    recent_count = recent_qs.count()
    if recent_count > SYBIL_DONATION_THRESHOLD:
        reason = (
            f'Fingerprint {device_fingerprint} tạo hơn {SYBIL_DONATION_THRESHOLD} '
            f'giao dịch trong {int(SYBIL_DONATION_WINDOW.total_seconds() // 60)} phút.'
        )
        recent_qs.update(
            is_sybil=True,
            sybil_flag_reason=reason,
            updated_at=timezone.now(),
        )
        return True, recent_count

    return False, recent_count


def _build_payos_signature_payload(data):
    sorted_items = sorted(data.items(), key=lambda item: item[0])
    return "&".join(f"{key}={_normalize_payos_value(value)}" for key, value in sorted_items)


def _create_payos_signature(data):
    payload = _build_payos_signature_payload(data)
    return hmac.new(
        settings.PAYOS_CHECKSUM_KEY.encode('utf-8'),
        payload.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


def _verify_payos_signature(data, signature):
    expected_signature = _create_payos_signature(data)
    return hmac.compare_digest(expected_signature.lower(), str(signature or '').lower())


def _generate_payos_order_code(donation_id):
    # PayOS nhận orderCode dạng number. Nếu vượt ngưỡng số nguyên an toàn của JS
    # (2^53 - 1), phía nhận có thể làm tròn và khiến signature bị lệch.
    # Dùng Unix timestamp (10 chữ số) + 5 chữ số donation_id để luôn < 10^15.
    timestamp_prefix = int(timezone.now().timestamp())
    donation_suffix = donation_id % 100000
    return int(f"{timestamp_prefix}{donation_suffix:05d}")


def _parse_payos_datetime(value):
    if not value:
        return None
    try:
        dt = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
        return vietnam_tz.localize(dt)
    except (TypeError, ValueError):
        return None


def _create_payos_payment_link(request, donation):
    return_url = request.build_absolute_uri(reverse('client:payos_return', args=[donation.id]))
    cancel_url = request.build_absolute_uri(reverse('client:payos_cancel', args=[donation.id]))
    order_code = _generate_payos_order_code(donation.id)
    description = f"DCP{donation.id:06d}"[-25:]
    payload = {
        'orderCode': order_code,
        'amount': int(donation.amount),
        'description': description,
        'buyerName': donation.donor_name or 'Nha hao tam',
        'buyerEmail': donation.donor_email or '',
        'buyerPhone': donation.donor_phone or '',
        'items': [
            {
                'name': f'Ung ho chien dich {donation.campaign.id}',
                'quantity': 1,
                'price': int(donation.amount),
            }
        ],
        'cancelUrl': cancel_url,
        'returnUrl': return_url,
        'expiredAt': int((timezone.now() + timedelta(minutes=15)).timestamp()),
    }
    signature_payload = {
        'amount': payload['amount'],
        'cancelUrl': payload['cancelUrl'],
        'description': payload['description'],
        'orderCode': payload['orderCode'],
        'returnUrl': payload['returnUrl'],
    }
    raw_signature_payload = _build_payos_signature_payload(signature_payload)
    generated_signature = _create_payos_signature(signature_payload)
    payload['signature'] = generated_signature

    if settings.DEBUG:
        print("\n========== PAYOS SIGNATURE DEBUG ==========")
        print("DONATION_ID:", donation.id)
        print("PAYOS_CLIENT_ID:", settings.PAYOS_CLIENT_ID)
        print("PAYOS_API_KEY_PRESENT:", bool(settings.PAYOS_API_KEY))
        print("PAYOS_CHECKSUM_KEY_REPR:", repr(settings.PAYOS_CHECKSUM_KEY))
        print("SIGNATURE_PAYLOAD_DICT:", signature_payload)
        print("SIGNATURE_PAYLOAD_RAW:", raw_signature_payload)
        print("GENERATED_SIGNATURE:", generated_signature)
        print("RETURN_URL:", payload['returnUrl'])
        print("CANCEL_URL:", payload['cancelUrl'])
        print("DESCRIPTION:", payload['description'])
        print("ORDER_CODE:", payload['orderCode'])
        print("AMOUNT:", payload['amount'])
        print("==========================================\n")

    response = http_requests.post(
        f'{PAYOS_API_BASE}/v2/payment-requests',
        json=payload,
        headers={
            'x-client-id': settings.PAYOS_CLIENT_ID,
            'x-api-key': settings.PAYOS_API_KEY,
            'Content-Type': 'application/json',
        },
        timeout=20,
    )
    try:
        response_payload = response.json()
    except ValueError:
        response_payload = {'raw_text': response.text}

    if settings.DEBUG:
        print("\n========== PAYOS CREATE RESPONSE ==========")
        print("STATUS_CODE:", response.status_code)
        print("RESPONSE_BODY:", response_payload)
        print("==========================================\n")

    response.raise_for_status()
    if response_payload.get('code') != '00' or 'data' not in response_payload:
        raise ValueError(response_payload.get('desc') or 'Không tạo được link thanh toán PayOS.')

    data = response_payload['data']
    donation.order_code = data.get('orderCode', order_code)
    donation.transaction_id = donation.transaction_id or f"PAYOS-{donation.order_code}"
    donation.payos_payment_link_id = data.get('paymentLinkId')
    donation.payos_checkout_url = data.get('checkoutUrl')
    donation.payos_qr_code = data.get('qrCode')
    donation.payos_reference = data.get('description') or description
    donation.save(update_fields=[
        'order_code',
        'transaction_id',
        'payos_payment_link_id',
        'payos_checkout_url',
        'payos_qr_code',
        'payos_reference',
        'updated_at',
    ])
    return data


def _mark_payos_donation_completed(donation, webhook_data):
    if donation.status == 'completed':
        return False

    paid_at = _parse_payos_datetime(webhook_data.get('transactionDateTime')) or timezone.now()
    donation.status = 'completed'
    donation.payment_method = 'payos'
    donation.payos_paid_at = paid_at
    donation.payos_webhook_received_at = timezone.now()
    donation.payos_transaction_id = webhook_data.get('transactionId') or webhook_data.get('reference') or donation.payos_transaction_id
    donation.payos_reference = webhook_data.get('reference') or donation.payos_reference
    donation.payos_payment_link_id = webhook_data.get('paymentLinkId') or donation.payos_payment_link_id
    donation.bank_transaction_no = webhook_data.get('reference') or donation.bank_transaction_no
    donation.blockchain_status = 'pending'
    donation.save(update_fields=[
        'status',
        'payment_method',
        'payos_paid_at',
        'payos_webhook_received_at',
        'payos_transaction_id',
        'payos_reference',
        'payos_payment_link_id',
        'bank_transaction_no',
        'blockchain_status',
        'updated_at',
    ])

    campaign = donation.campaign
    Campaign.objects.filter(pk=campaign.pk).update(current_amount=F('current_amount') + donation.amount)

    statement_defaults = {
        'campaign': campaign,
        'donation': donation,
        'transaction_date': paid_at,
        'transaction_type': 'in',
        'amount': donation.amount,
        'reference_number': webhook_data.get('reference') or str(donation.order_code),
        'description': f"PayOS: {donation.donor_name or 'Ẩn danh'} ủng hộ chiến dịch {campaign.title}",
        'sender_name': webhook_data.get('counterAccountName') or donation.donor_name,
        'sender_account': webhook_data.get('counterAccountNumber') or '',
        'source': 'payos',
    }
    BankStatement.objects.get_or_create(
        donation=donation,
        reference_number=statement_defaults['reference_number'],
        defaults=statement_defaults,
    )

    ActivityLog.objects.create(
        user=donation.donor,
        type='payos_webhook_paid',
        description=f"PayOS xác nhận thanh toán thành công cho Donation #{donation.id} - orderCode {donation.order_code}",
        campaign=campaign,
        donation=donation,
    )
    return True


def _trigger_record_donation_bridge(donation):
    bc = BlockchainService()
    if not donation.donor_wallet_address and donation.donor_id and hasattr(donation.donor, 'profile'):
        donation.donor_wallet_address = (
            donation.donor.profile.smart_account_address
            or donation.donor.profile.wallet_address
            or None
        )
    donor_address = donation.donor_wallet_address or bc.get_fallback_donor_address()

    # V4 ("Double Integrity"): recordDonation cần địa chỉ multisig vault để
    # smart2 mint VNDT ký quỹ. MVP dùng chính ví tổ chức làm vault — đã set
    # ở bước createCampaign, nên BẮT BUỘC phải khớp ở đây (nếu không contract
    # sẽ revert với "multisig khong khop").
    organization = getattr(donation.campaign, 'organization', None)
    multisig_address = (organization.wallet_address or '').strip() if organization else ''
    if not multisig_address:
        raise Exception(
            f"Campaign #{donation.campaign_id} chưa có wallet_address tổ chức → "
            "không xác định được multisig vault để recordDonation. Hãy vào "
            "'Quản lý tổ chức' cập nhật ví crypto rồi sync lại chiến dịch."
        )

    donation.blockchain_status = 'processing'
    donation.blockchain_started_at = timezone.now()
    donation.blockchain_error = None
    donation.blockchain_retry_count = (donation.blockchain_retry_count or 0) + 1
    donation.save(update_fields=[
        'blockchain_status',
        'blockchain_started_at',
        'blockchain_error',
        'blockchain_retry_count',
        'updated_at',
    ])

    tx_result = bc.trigger_record_donation(
        campaign_id=donation.campaign_id,
        donor_address=donor_address,
        multisig_address=multisig_address,
        fiat_amount=int(donation.amount),
    )
    tx_hash = tx_result['tx_hash']

    donation.eth_tx_hash = tx_hash
    donation.is_blockchain_synced = True
    donation.blockchain_status = 'confirmed'
    donation.blockchain_completed_at = timezone.now()
    donation.blockchain_error = None
    donation.donor_wallet_address = donor_address
    donation.save(update_fields=[
        'eth_tx_hash',
        'is_blockchain_synced',
        'blockchain_status',
        'blockchain_completed_at',
        'blockchain_error',
        'donor_wallet_address',
        'updated_at',
    ])

    ActivityLog.objects.create(
        user=donation.donor,
        type='record_donation_onchain',
        description=f"recordDonation thành công cho Donation #{donation.id} - tx {tx_hash}",
        campaign=donation.campaign,
        donation=donation,
    )
    return tx_hash


def _run_record_donation_bridge_safe(donation_id):
    """
    Wrapper an toàn chạy `_trigger_record_donation_bridge` trong background thread.

    Trách nhiệm:
      • Load lại Donation từ DB bằng id (tránh dùng instance stale từ request cha).
      • Bắt MỌI exception (Web3, RPC timeout, revert…) — thread không được crash
        ngầm vì Gunicorn sẽ không thấy lỗi.
      • Ghi lỗi vào `blockchain_status='failed'` + `blockchain_error` để FE polling
        qua `api_donation_blockchain_status` biết và cho phép retry.
      • Đóng DB connection cuối cùng (Django mở connection theo thread-local,
        không auto-close khi thread phụ kết thúc → leak connection nếu bỏ qua).

    Được gọi bên trong `transaction.on_commit` từ `payos_webhook_view` để:
      - Thread chỉ start SAU khi donation đã commit status='completed' → đọc được
        bản mới nhất.
      - Nếu outer transaction rollback → thread không spawn → không có tx on-chain
        mồ côi.
    """
    from django.db import connection
    try:
        try:
            donation = Donation.objects.select_related('campaign', 'donor').get(pk=donation_id)
        except Donation.DoesNotExist:
            print(f"⚠️ [BG RECORD] Donation #{donation_id} không tồn tại (đã bị xóa?) — bỏ qua.")
            return

        try:
            tx_hash = _trigger_record_donation_bridge(donation)
            print(f"✅ [BG RECORD] Donation #{donation_id} recordDonation OK, tx={tx_hash}")
        except Exception as exc:
            # In rõ type + message + traceback để Railway logs thấy EVM revert reason.
            print(f"❌ [BG RECORD] Donation #{donation_id} recordDonation FAIL: "
                  f"{type(exc).__name__}: {exc}")
            print(traceback.format_exc())
            try:
                failed = Donation.objects.get(pk=donation_id)
                failed.blockchain_status = 'failed'
                failed.blockchain_completed_at = timezone.now()
                failed.blockchain_error = f"{type(exc).__name__}: {exc}"[:500]
                failed.save(update_fields=[
                    'blockchain_status',
                    'blockchain_completed_at',
                    'blockchain_error',
                    'updated_at',
                ])
            except Exception as save_exc:
                # Thậm chí việc ghi lỗi cũng fail (DB down…) — chỉ log, không raise.
                print(f"❌ [BG RECORD] Không thể ghi blockchain_error vào DB: {save_exc}")
    finally:
        # Đóng DB connection thread-local để tránh leak.
        try:
            connection.close()
        except Exception:
            pass


def _spawn_record_donation_thread(donation_id):
    """Spawn daemon thread chạy `_run_record_donation_bridge_safe`.

    daemon=True để thread không chặn process shutdown (Gunicorn graceful stop).
    """
    thread = threading.Thread(
        target=_run_record_donation_bridge_safe,
        args=(donation_id,),
        daemon=True,
        name=f'record-donation-{donation_id}',
    )
    thread.start()
    return thread

# ==========================================
# HELPER: Tính phí gas và lưu vào donation
# ==========================================

def _save_gas_fee_to_donation(bc, donation, tx_hash):
    try:
        gas_info = bc.get_transaction_gas_fee(tx_hash)
        eth_vnd_rate = get_eth_vnd_rate()
        donation.gas_fee_eth = gas_info['gas_fee_eth']
        donation.gas_fee_vnd = int(gas_info['gas_fee_eth'] * eth_vnd_rate)
        donation.net_amount = max(0, int(donation.amount) - donation.gas_fee_vnd)
        print(f"⛽ Gas: {gas_info['gas_used']} units × {gas_info['gas_price_gwei']} Gwei")
        print(f"⛽ Phí gas: {gas_info['gas_fee_eth']:.10f} ETH = {donation.gas_fee_vnd:,} VNĐ")
        print(f"💰 Thực nhận: {donation.net_amount:,} VNĐ (gốc: {int(donation.amount):,})")
    except Exception as e:
        print(f"⚠️ Không thể tính phí gas: {e}")
        donation.net_amount = int(donation.amount)  # Fallback: không trừ gas

# ==========================================
# CÁC VIEW CŨ CỦA BẠN
# ==========================================

def trangchu(request):
    # 1. Lấy thống kê toàn sàn
    total_donated = Donation.objects.aggregate(Sum('amount'))['amount__sum'] or 0
    total_campaigns = Campaign.objects.count()

    # 2. Lấy danh sách chiến dịch ĐANG CHẠY (Active)
    active_campaigns = Campaign.objects.filter(status='active').order_by('-created_at')[:6]

    context = {
        'total_donated': total_donated,
        'total_campaigns': total_campaigns,
        'active_campaigns': active_campaigns,
    }
    return render(request, 'client/trangchu.html', context)

def gioithieu(request):
    return render(request, 'client/gioithieu.html')

def ungho(request, pk):
    if not request.user.is_authenticated:
        messages.warning(request, 'Vui lòng đăng nhập để ủng hộ chiến dịch.')
        return redirect('admin_panel:dangnhap')
    
    campaign = get_object_or_404(Campaign, pk=pk)
    
    if request.method == 'POST':
        try:
            # 1. Lấy dữ liệu từ form (LUỒNG MỚI: không còn MetaMask)
            amount = request.POST.get('amount').replace(',', '') # Xóa dấu phẩy
            message = request.POST.get('message')
            payment_method = request.POST.get('payment_method') or 'payos'
            device_fingerprint = (request.POST.get('device_fingerprint') or '').strip()

            # 2. Tạo đối tượng Donation
            donation = Donation()
            donation.campaign = campaign
            donation.amount = amount
            donation.message = message
            donation.payment_method = payment_method
            donation.donor_wallet_address = None
            donation.device_fingerprint = device_fingerprint or None
            donation.ip_address = get_client_ip(request)
            donation.user_agent = request.META.get('HTTP_USER_AGENT', '')[:1000]

            # 3. Xử lý User (Đăng nhập hay vãng lai)
            is_anonymous_req = request.POST.get('is_anonymous') == 'on'
            
            if request.user.is_authenticated:
                donation.donor = request.user
                
                # Lấy địa chỉ ví để làm định danh ẩn danh
                wallet_address = None
                if hasattr(request.user, 'profile'):
                    wallet_address = (
                        request.user.profile.smart_account_address
                        or request.user.profile.wallet_address
                    )
                
                if is_anonymous_req:
                    donation.is_anonymous = True
                    donation.donor_name = "Mạnh thường quân"
                    # Tạo email ẩn danh dựa trên ví hoặc ID để gửi sang PayOS
                    mask_id = wallet_address or f"user_{request.user.id}"
                    donation.donor_email = f"{mask_id}@anonymous.fund"
                    donation.donor_wallet_address = wallet_address
                else:
                    if hasattr(request.user, 'profile'):
                        donation.donor_name = request.user.profile.display_name or request.user.username
                        donation.donor_wallet_address = wallet_address
                    else:
                        donation.donor_name = request.user.username
                    donation.donor_email = request.user.email
            else:
                donation.donor_name = request.POST.get('donor_name')
                donation.donor_email = request.POST.get('donor_email')
                donation.is_anonymous = True

            # 4. Lưu vào DB SQL trước
            donation.save()
            is_sybil, recent_count = _flag_recent_sybil_donations(device_fingerprint)
            if is_sybil:
                donation.refresh_from_db(fields=['is_sybil', 'sybil_flag_reason'])
                ActivityLog.objects.create(
                    user=request.user,
                    type='sybil_donation_flagged',
                    description=(
                        f'Donation #{donation.id} bị gắn cờ Sybil. '
                        f'Fingerprint={device_fingerprint}, recent_count={recent_count}'
                    ),
                    campaign=campaign,
                    donation=donation,
                    ip_address=donation.ip_address,
                    user_agent=donation.user_agent,
                )
            
            # ======================================================
            # CODE DEBUG GHI BLOCKCHAIN (Dành cho Tiền mặt/Chuyển khoản)
            # ======================================================
            if payment_method != 'payos':
                campaign.current_amount += int(amount)
                campaign.save()
                messages.success(request, "Cảm ơn tấm lòng vàng của bạn!")
                return redirect('client:camon', pk=donation.id)

            payos_data = _create_payos_payment_link(request, donation)
            checkout_url = payos_data.get('checkoutUrl')
            if not checkout_url:
                raise ValueError('PayOS không trả về checkoutUrl hợp lệ.')

            print(f"\n🚀 [PAYOS] Redirecting to PayOS checkout for donation #{donation.id}")
            print(f"🔗 URL: {checkout_url[:120]}...")
            return HttpResponseRedirect(checkout_url)

        except Exception as e:
            messages.error(request, f"Lỗi xử lý: {e}")
            print(f"Lỗi hệ thống: {e}")

    return render(request, 'client/ungho.html', {
        'campaign': campaign,
    })
def camon(request, pk):
    donation = get_object_or_404(Donation, pk=pk)
    return render(request, 'client/camon.html', {'donation': donation})

# client/views.py

def saoke(request):
    donations = Donation.objects.select_related('campaign').all().order_by('-created_at')
    total_system_amount = Donation.objects.aggregate(Sum('amount'))['amount__sum'] or 0
    total_gas_vnd = Donation.objects.filter(gas_fee_vnd__isnull=False).aggregate(
        total=Sum('gas_fee_vnd')
    )['total'] or Decimal('0')
    total_net_amount = total_system_amount - total_gas_vnd

    context = {
        'donations': donations,
        'total_system_amount': total_system_amount,
        'total_gas_vnd': total_gas_vnd,
        'total_net_amount': total_net_amount,
    }
    return render(request, 'client/saoke.html', context)

def payos_return(request, donation_id):
    donation = get_object_or_404(Donation, pk=donation_id)
    status = (request.GET.get('status') or '').upper()
    is_cancelled = (request.GET.get('cancel') or '').lower() == 'true'
    payment_link_id = request.GET.get('id')
    order_code = request.GET.get('orderCode')

    if payment_link_id and not donation.payos_payment_link_id:
        donation.payos_payment_link_id = payment_link_id
        donation.save(update_fields=['payos_payment_link_id', 'updated_at'])

    if is_cancelled or status == 'CANCELLED':
        return render(request, "client/payment_failed.html", {
            "message": "Bạn đã hủy thanh toán trên PayOS.",
        })

    return render(request, "client/payment_success.html", {
        "donation": donation,
        "payment_provider": "PayOS",
        "payment_status": status or ('PAID' if donation.status == 'completed' else 'PENDING'),
        "show_blockchain_status": False,
        "message": "Thanh toán đã được gửi tới PayOS. Hệ thống sẽ xác nhận chính thức khi webhook hợp lệ được nhận.",
        "payos_order_code": order_code or donation.order_code,
    })


def payos_cancel(request, donation_id):
    donation = get_object_or_404(Donation, pk=donation_id)
    return render(request, "client/payment_failed.html", {
        "message": f"Bạn đã hủy thanh toán PayOS cho giao dịch #{donation.id}.",
    })
    
@csrf_exempt
@require_POST
def api_wallet_sync(request):
    """
    Đồng bộ Smart Account / EOA vào profile của user.
    Không dùng @login_required để tránh trả về HTML redirect (302) khi
    session chưa kịp được middleware nhận diện ở production (Railway + HTTPS).
    Nếu request.user chưa authenticated, xác định user từ payload
    (wallet_address / eoa_address / email) rồi login lại qua session.
    """
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'message': 'Invalid JSON payload.'}, status=400)

    wallet_address = (payload.get('wallet_address') or '').strip()
    eoa_address = (payload.get('eoa_address') or '').strip()
    smart_account_address = (payload.get('smart_account_address') or '').strip()
    email = (payload.get('email') or '').strip()
    display_name = (payload.get('display_name') or payload.get('name') or '').strip()
    provider = (payload.get('provider') or 'web3auth').strip()

    if not smart_account_address and wallet_address:
        smart_account_address = wallet_address

    if not smart_account_address:
        return JsonResponse({'ok': False, 'message': 'Thiếu smart_account_address.'}, status=400)

    if eoa_address and not Web3.is_address(eoa_address):
        return JsonResponse({'ok': False, 'message': 'EOA address không hợp lệ.'}, status=400)

    if not Web3.is_address(smart_account_address):
        return JsonResponse({'ok': False, 'message': 'Smart Account address không hợp lệ.'}, status=400)

    checksum_eoa = Web3.to_checksum_address(eoa_address) if eoa_address else ''
    checksum_smart = Web3.to_checksum_address(smart_account_address)

    # Xác định user: ưu tiên session hiện tại, fallback theo payload.
    user = request.user if request.user.is_authenticated else None
    if user is None:
        user, profile = _get_or_create_web3_user(
            wallet_address=checksum_smart,
            eoa_address=checksum_eoa,
            email=email,
            display_name=display_name,
        )
        # Tạo session để các request sau được authenticated đúng cách.
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    else:
        profile, _created = UserProfile.objects.get_or_create(user=user)

    profile.eoa_address = checksum_eoa or profile.eoa_address or None
    profile.smart_account_address = checksum_smart
    profile.wallet_address = checksum_smart
    profile.save(update_fields=[
        'eoa_address',
        'smart_account_address',
        'wallet_address',
        'updated_at',
    ])

    ActivityLog.objects.create(
        user=user,
        type='wallet_sync',
        description=f'Đồng bộ Smart Account {checksum_smart} từ {provider}' + (f' | EOA {checksum_eoa}' if checksum_eoa else ''),
    )

    return JsonResponse({
        'ok': True,
        'wallet_address': checksum_smart,
        'eoa_address': checksum_eoa,
        'smart_account_address': checksum_smart,
        'provider': provider,
        'user': {
            'id': user.id,
            'username': user.username,
            'email': user.email,
        },
    })
    

from django.http import HttpResponse
from django.template.loader import get_template
from xhtml2pdf import pisa
from django.utils import timezone
from django.contrib.staticfiles import finders


def _pdf_link_callback(uri, rel):
    """
    Resolver cho xhtml2pdf:
      - Map STATIC_URL / MEDIA_URL về đường dẫn filesystem tuyệt đối.
      - Hỗ trợ font tiếng Việt (DejaVuSans*) trong static/fonts/.
      - Cho phép URL HTTP/HTTPS đi qua (xhtml2pdf tự fetch).
      - Đường dẫn tuyệt đối (đã là filesystem) thì trả về nguyên.
    Mục tiêu: đảm bảo @font-face load được file .ttf để render tiếng Việt
    có dấu trong PDF (báo cáo tổng hợp + chứng nhận).
    """
    if not uri:
        return uri

    # URL HTTP/HTTPS — để xhtml2pdf tự fetch.
    if uri.startswith(('http://', 'https://')):
        return uri

    # Đường dẫn filesystem tuyệt đối — trả về nếu file tồn tại.
    if os.path.isabs(uri) and os.path.exists(uri):
        return uri

    static_url = getattr(settings, 'STATIC_URL', '/static/') or '/static/'
    media_url = getattr(settings, 'MEDIA_URL', '/media/') or '/media/'
    static_root = getattr(settings, 'STATIC_ROOT', None)
    media_root = getattr(settings, 'MEDIA_ROOT', None)

    path = None
    if uri.startswith(static_url):
        relative = uri[len(static_url):]
        # Ưu tiên STATIC_ROOT (sau collectstatic), fallback dùng staticfiles finders.
        if static_root:
            candidate = os.path.join(static_root, relative)
            if os.path.exists(candidate):
                path = candidate
        if not path:
            path = finders.find(relative)
    elif uri.startswith(media_url) and media_root:
        path = os.path.join(media_root, uri[len(media_url):])
    else:
        # Đường dẫn tương đối hoặc đường dẫn không có scheme — thử ghép
        # với BASE_DIR (cho trường hợp template truyền absolute path từ
        # settings.BASE_DIR như font_path).
        candidate = os.path.join(getattr(settings, 'BASE_DIR', ''), uri.lstrip('/'))
        if os.path.exists(candidate):
            path = candidate

    if path and os.path.exists(path):
        return path
    return uri


@login_required(login_url='admin_panel:dangnhap')
def profile_view(request):
    """
    Trang hoữ sơ cá nhân của user.

    - GET: hiển thị form với thông tin hiện tại + thống kê đóng góp.
    - POST: lưu thông tin cơ bản (display_name, phone, address, province, bio, avatar)
      đồng thời update first_name/last_name/email trên auth.User.

    Không cho phép đổi phần on-chain (wallet/eoa/smart_account) qua form này
    — các field đó do flow Web3Auth/wallet-sync đảm nhiệm.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        form = UserProfileForm(request.POST, request.FILES, instance=profile, user=request.user)
        if form.is_valid():
            p = form.save()
            # Cập nhật avatar_url text field từ CloudinaryField URL để tương thích
            if p.avatar:
                p.avatar_url = p.avatar.url
                p.save(update_fields=['avatar_url'])
            
            ActivityLog.objects.create(
                user=request.user,
                type='profile_updated',
                description=f'User {request.user.username} cập nhật thông tin profile.',
                ip_address=get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:1000],
            )
            messages.success(request, 'Cập nhật thông tin thành công!')
            return redirect('client:profile')
        messages.error(request, 'Vui lòng kiểm tra lại các trường đã nhập.')
    else:
        form = UserProfileForm(instance=profile, user=request.user)

    # Thống kê nhỏ cho user xem.
    completed_donations = Donation.objects.filter(donor=request.user, status='completed')
    total_donated = completed_donations.aggregate(total=Sum('amount'))['total'] or 0
    donation_count = completed_donations.count()
    campaigns_supported = completed_donations.values('campaign').distinct().count()

    context = {
        'form': form,
        'profile': profile,
        'total_donated': total_donated,
        'donation_count': donation_count,
        'campaigns_supported': campaigns_supported,
    }
    return render(request, 'client/profile.html', context)


@login_required(login_url='admin_panel:dangnhap')
def lichsu_quyen_gop(request):
    """
    Trang hiển thị lịch sử quyên góp của cá nhân người dùng với bộ lọc thời gian.
    """
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    # Xử lý trường hợp giá trị là chuỗi "None" hoặc rỗng
    if start_date in [None, '', 'None']: start_date = None
    if end_date in [None, '', 'None']: end_date = None
    
    donations = Donation.objects.filter(donor=request.user, status='completed').select_related('campaign').order_by('-created_at')
    
    if start_date:
        donations = donations.filter(created_at__date__gte=start_date)
    if end_date:
        donations = donations.filter(created_at__date__lte=end_date)
        
    context = {
        'donations': donations,
        'start_date': start_date,
        'end_date': end_date,
    }
    return render(request, 'client/lichsu_quyen_gop.html', context)

@login_required(login_url='admin_panel:dangnhap')
def export_donation_report(request):
    """
    Xuất báo cáo tổng hợp quyên góp (PDF) cho một khoảng thời gian.
    """
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    # Xử lý trường hợp giá trị là chuỗi "None" hoặc rỗng
    if start_date in [None, '', 'None']: start_date = None
    if end_date in [None, '', 'None']: end_date = None
    
    donations = Donation.objects.filter(donor=request.user, status='completed').select_related('campaign').order_by('created_at')
    
    if start_date:
        donations = donations.filter(created_at__date__gte=start_date)
    if end_date:
        donations = donations.filter(created_at__date__lte=end_date)
        
    total_amount = donations.aggregate(Sum('amount'))['amount__sum'] or 0

    font_path = os.path.join(settings.BASE_DIR, 'static', 'fonts')

    context = {
        'donations': donations,
        'user': request.user,
        'start_date': start_date,
        'end_date': end_date,
        'total_amount': total_amount,
        'now': timezone.now(),
        'font_path': font_path,
    }
    
    template = get_template('client/donation_report_pdf.html')
    html = template.render(context)
    
    response = HttpResponse(content_type='application/pdf')
    filename = f"Bao_Cao_Quyen_Gop_{request.user.username}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    pisa_status = pisa.CreatePDF(
        html,
        dest=response,
        encoding='utf-8',
        link_callback=_pdf_link_callback,
    )
    if pisa_status.err:
        return HttpResponse('Lỗi tạo báo cáo PDF', status=500)
    return response

def export_donation_pdf(request, donation_id):
    """
    Xuất file PDF chứng nhận quyên góp cho một giao dịch cụ thể.

    Lưu ý quan trọng (khai thuế cá nhân):
      - Mặc dù donation có thể được công bố ở chế độ ẨN DANH trên trang sao kê
        công khai, giấy chứng nhận PDF (do chính donor tự xuất) BẮT BUỘC phải
        hiển thị tên thật + thông tin liên hệ để cơ quan thuế đối chiếu.
      - Tên ưu tiên: profile.display_name → user.get_full_name() → user.first_name
        → user.username → donation.donor_name (fallback cho donation cũ trước khi
        có user account).
    """
    donation = get_object_or_404(Donation, id=donation_id)

    # Kiểm tra bảo mật: Chỉ donor hoặc staff mới được tải
    if donation.donor != request.user and not request.user.is_staff:
        return HttpResponse("Bạn không có quyền tải chứng nhận này.", status=403)

    organization = donation.campaign.organization

    font_path = os.path.join(settings.BASE_DIR, 'static', 'fonts')

    # Lấy tên thật của donor để in lên cert (phục vụ khai thuế).
    donor_user = donation.donor
    donor_profile = getattr(donor_user, 'profile', None) if donor_user else None

    donor_display_name = ''
    if donor_profile and donor_profile.display_name:
        donor_display_name = donor_profile.display_name
    elif donor_user:
        full_name = donor_user.get_full_name().strip()
        donor_display_name = full_name or donor_user.first_name or donor_user.username
    if not donor_display_name:
        # Donation vãng lai (không có user account) — fallback về donor_name từ form.
        donor_display_name = donation.donor_name or 'Nhà hảo tâm'

    donor_email = (donor_user.email if donor_user else '') or ''
    # Bỏ email ẩn danh dạng <wallet>@anonymous.fund (nếu có).
    if donor_email.endswith('@anonymous.fund'):
        donor_email = ''
    if not donor_email and donation.donor_email and not donation.donor_email.endswith('@anonymous.fund'):
        donor_email = donation.donor_email

    donor_phone = ''
    donor_address = ''
    if donor_profile:
        donor_phone = donor_profile.phone or ''
        # Ghép address + province nếu có.
        addr_parts = [donor_profile.address, donor_profile.province]
        donor_address = ', '.join([p for p in addr_parts if p])
    if not donor_phone:
        donor_phone = donation.donor_phone or ''

    context = {
        'donation': donation,
        'organization': organization,
        'now': timezone.now(),
        'font_path': font_path,
        'donor_display_name': donor_display_name,
        'donor_email': donor_email,
        'donor_phone': donor_phone,
        'donor_address': donor_address,
    }
    
    # Render template HTML
    template = get_template('client/donation_certificate_pdf.html')
    html = template.render(context)

    # Tạo file PDF
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="Chung_Nhan_Quyen_Gop_{donation.id}.pdf"'
    
    # Chuyển HTML thành PDF
    pisa_status = pisa.CreatePDF(
        html,
        dest=response,
        encoding='utf-8',
        link_callback=_pdf_link_callback,
    )
    
    if pisa_status.err:
        return HttpResponse('Đã có lỗi xảy ra khi tạo file PDF.', status=500)
    
    return response


# client/views.py

def chitiet_chiendich(request, pk):
    campaign = get_object_or_404(Campaign.objects.select_related('detail'), pk=pk)
    donations = Donation.objects.filter(campaign=campaign).order_by('-created_at')

    # Breakdown gas cho trang public (luồng v2)
    gas_subsidized_vnd = Decimal('0')        # Tổng totalGasCost on-chain (A+B+C)
    est_disbursement_gas_vnd = Decimal('0')  # Gas dự trù cho lần giải ngân tiếp theo
    gas_recovered_vnd = Decimal('0')
    onchain_total_fund_vnd = campaign.current_amount
    onchain_total_disbursed_vnd = campaign.disbursed_amount
    onchain_available_vnd = Decimal('0')

    # Luồng v2: gas A (recordBankDonation) + gas B (donateOnBehalf) từ Donation table
    gas_bank_record_vnd = Donation.objects.filter(
        campaign=campaign, bank_record_gas_vnd__isnull=False
    ).aggregate(total=Sum('bank_record_gas_vnd'))['total'] or Decimal('0')
    gas_donate_onbehalf_vnd = Donation.objects.filter(
        campaign=campaign, donate_onbehalf_gas_vnd__isnull=False
    ).aggregate(total=Sum('donate_onbehalf_gas_vnd'))['total'] or Decimal('0')

    # Legacy: gas sendEthToUser (chỉ còn donation cũ)
    gas_admin_sendeth_vnd = Donation.objects.filter(
        campaign=campaign, admin_send_eth_gas_fee_vnd__isnull=False
    ).aggregate(total=Sum('admin_send_eth_gas_fee_vnd'))['total'] or Decimal('0')

    gas_disbursement_vnd = DisbursementProposal.objects.filter(
        campaign=campaign, status='executed', disbursement_gas_fee_vnd__isnull=False
    ).aggregate(total=Sum('disbursement_gas_fee_vnd'))['total'] or Decimal('0')

    try:
        bc = BlockchainService()
        eth_vnd_rate = get_eth_vnd_rate()
        stats = bc.get_campaign_onchain_stats(campaign.id)
        # V4 ("Double Integrity"): contract không còn lưu totalGasCost / totalDisbursed
        # on-chain — gas do Admin Relayer tự trả từ ví riêng. Dùng trực tiếp
        # current_amount_vnd (đã chia 10^18) làm tổng quỹ đã huy động on-chain.
        onchain_total_fund_vnd = Decimal(str(stats.get('current_amount_vnd', 0)))
        # V4: token không còn burn khi giải ngân, currentAmount không giảm —
        # lấy disbursed từ SQL (DisbursementProposal đã execute).
        onchain_total_disbursed_vnd = campaign.disbursed_amount
        # Các key legacy giờ luôn = 0 ở V4 (không còn mô hình gas pool / admin recovery).
        gas_subsidized_vnd = Decimal('0')
        gas_recovered_vnd = Decimal('0')
        est_per_tx_gas_vnd, _est_wei = estimate_gas_per_tx_vnd(eth_vnd_rate, bc=bc)
        est_disbursement_gas_vnd = est_per_tx_gas_vnd
        est_recovery_gas_vnd = Decimal('0')
        # onchain_available_vnd = quỹ on-chain - phần đã giải ngân (SQL) - gas dự trù
        onchain_available_vnd = max(
            Decimal('0'),
            onchain_total_fund_vnd - onchain_total_disbursed_vnd - est_disbursement_gas_vnd,
        )
    except Exception:
        pass

    # Tổng gas: gas_subsidized_vnd (=total_gas_cost_wei từ contract) đã bao gồm gas admin đã chi (A+B+C)
    # + gas giải ngân đã thực thi + 1 gas dự trù cho lần giải ngân tiếp theo
    # KHÔNG cộng gas_bank_record_vnd/gas_donate_onbehalf_vnd lần nữa (đã nằm trong totalGasCost on-chain).
    # Khi quỹ on-chain = 0 (chưa ai donate), bỏ qua est_disbursement_gas_vnd để không hiển thị gas âm vô nghĩa.
    if onchain_total_fund_vnd <= 0:
        est_disbursement_gas_vnd = Decimal('0')
    total_gas_vnd = gas_subsidized_vnd + gas_disbursement_vnd + est_disbursement_gas_vnd + gas_admin_sendeth_vnd
    # net_receivable = tổng quỹ on-chain - tổng gas (clamp >= 0 để không hiển thị âm khi quỹ = 0)
    net_receivable = max(Decimal('0'), onchain_total_fund_vnd - total_gas_vnd)

    voting_powers, total_system_power = campaign.calculate_voting_distribution()

    user_can_vote = False
    user_voting_power = Decimal('0')
    user_voting_pct = 0.0

    if request.user.is_authenticated:
        for vp in voting_powers:
            if vp['user_id'] == request.user.id:
                user_voting_power = vp['power']
                user_voting_pct = vp['percentage']
                user_can_vote = True
                break

    active_proposals = DisbursementProposal.objects.filter(
        campaign=campaign, status='voting'
    ).select_related('created_by', 'approved_by').order_by('-created_at')

    proposal_data = []
    for p in active_proposals:
        votes = ProposalVote.objects.filter(proposal=p)
        yes_power = votes.filter(is_agree=True).aggregate(t=Sum('voting_power'))['t'] or Decimal('0')
        no_power = votes.filter(is_agree=False).aggregate(t=Sum('voting_power'))['t'] or Decimal('0')
        total_voted = yes_power + no_power

        user_voted = None
        if request.user.is_authenticated:
            user_vote = votes.filter(user=request.user).first()
            if user_vote:
                user_voted = user_vote.is_agree

        proposal_data.append({
            'proposal': p,
            'yes_power': yes_power,
            'no_power': no_power,
            'total_voted': total_voted,
            'total_system_power': total_system_power,
            'yes_pct': float(yes_power / total_voted * 100) if total_voted > 0 else 0,
            'no_pct': float(no_power / total_voted * 100) if total_voted > 0 else 0,
            'user_voted': user_voted,
            'votes_count': votes.count(),
            'total_donors': len(voting_powers),
        })

    completed_proposals = DisbursementProposal.objects.filter(
        campaign=campaign, status__in=['executed', 'rejected', 'approved']
    ).select_related('created_by').order_by('-created_at')

    completed_data = []
    for p in completed_proposals:
        votes = ProposalVote.objects.filter(proposal=p)
        yes_power = votes.filter(is_agree=True).aggregate(t=Sum('voting_power'))['t'] or Decimal('0')
        no_power = votes.filter(is_agree=False).aggregate(t=Sum('voting_power'))['t'] or Decimal('0')
        total_voted = yes_power + no_power

        completed_data.append({
            'proposal': p,
            'yes_power': yes_power,
            'no_power': no_power,
            'yes_pct': float(yes_power / total_voted * 100) if total_voted > 0 else 0,
            'votes_count': votes.count(),
        })

    context = {
        'campaign': campaign,
        'donations': donations,
        'active_proposals': proposal_data,
        'completed_proposals': completed_data,
        'user_can_vote': user_can_vote,
        'user_voting_power': user_voting_power,
        'user_voting_pct': user_voting_pct,
        'total_gas_vnd': total_gas_vnd,
        'net_receivable': net_receivable,
        # Breakdown v2
        'gas_bank_record_vnd': gas_bank_record_vnd,
        'gas_donate_onbehalf_vnd': gas_donate_onbehalf_vnd,
        'gas_subsidized_vnd': gas_subsidized_vnd,       # totalGasCost on-chain (A+B+C)
        'gas_disbursement_vnd': gas_disbursement_vnd,   # gas giải ngân thực tế
        'est_disbursement_gas_vnd': est_disbursement_gas_vnd,
        # Legacy
        'gas_admin_sendeth_vnd': gas_admin_sendeth_vnd,
        'gas_recovered_vnd': gas_recovered_vnd,
        'onchain_total_fund_vnd': onchain_total_fund_vnd,
        'onchain_total_disbursed_vnd': onchain_total_disbursed_vnd,
        'onchain_available_vnd': onchain_available_vnd,
    }
    return render(request, 'client/chitiet_chiendich.html', context)


@login_required(login_url='admin_panel:dangnhap')
@require_POST
def vote_proposal(request, campaign_id, proposal_id):
    campaign = get_object_or_404(Campaign, pk=campaign_id)
    proposal = get_object_or_404(DisbursementProposal, pk=proposal_id, campaign=campaign)

    if proposal.status != 'voting':
        messages.error(request, 'Đề xuất này không trong giai đoạn bỏ phiếu.')
        return redirect('client:chitiet_chiendich', pk=campaign_id)

    if proposal.end_date and timezone.now() > proposal.end_date:
        messages.error(request, 'Thời gian bỏ phiếu đã kết thúc.')
        return redirect('client:chitiet_chiendich', pk=campaign_id)

    voting_powers, total_system_power = campaign.calculate_voting_distribution()
    user_power = Decimal('0')
    for vp in voting_powers:
        if vp['user_id'] == request.user.id:
            user_power = vp['power']
            break

    if user_power <= 0:
        messages.error(request, 'Bạn chưa ủng hộ chiến dịch này nên không thể bỏ phiếu.')
        return redirect('client:chitiet_chiendich', pk=campaign_id)

    if ProposalVote.objects.filter(proposal=proposal, user=request.user).exists():
        messages.warning(request, 'Bạn đã bỏ phiếu cho đề xuất này rồi.')
        return redirect('client:chitiet_chiendich', pk=campaign_id)

    is_agree = request.POST.get('vote') == 'yes'

    try:
        from django.db import IntegrityError
        ProposalVote.objects.create(
            proposal=proposal,
            user=request.user,
            is_agree=is_agree,
            voting_power=user_power,
        )
    except IntegrityError:
        messages.warning(request, 'Bạn đã bỏ phiếu cho đề xuất này rồi.')
        return redirect('client:chitiet_chiendich', pk=campaign_id)

    # Voting off-chain: không gọi blockchain

    executed, blockchain_error = check_and_execute_proposal(proposal)

    vote_text = 'đồng ý' if is_agree else 'từ chối'
    messages.success(request, f'Đã bỏ phiếu {vote_text} thành công!')
    if executed:
        messages.success(request, '✅ Giải ngân đã được thực thi thành công trên blockchain! ETH đã chuyển cho tổ chức.')
    elif blockchain_error:
        messages.error(request, f'⚠️ {blockchain_error}')
    return redirect('client:chitiet_chiendich', pk=campaign_id)

def ban_do_page(request):
    """
    Trang Bản đồ thiện nguyện — hiển thị toàn bộ chiến dịch (Campaign)
    có toạ độ GIS dưới dạng marker trên Leaflet map.

    Quy tắc lấy toạ độ:
      - Ưu tiên `campaign.beneficiary_lat/lng` (do creator nhập).
      - Fallback sang `target_program.beneficiary_lat/lng` nếu campaign
        chưa có toạ độ. Logic này cũng đã được implement ở
        Campaign.save() — nhưng vẫn fallback ở đây để chắc chắn.

    Trạng thái hiển thị: active / completed / ended (không show pending,
    rejected, hidden, paused, deleted).
    """
    qs = (
        Campaign.objects
        .filter(status__in=['active', 'completed', 'ended'])
        .filter(
            Q(beneficiary_lat__isnull=False, beneficiary_lng__isnull=False)
            | Q(
                target_program__beneficiary_lat__isnull=False,
                target_program__beneficiary_lng__isnull=False,
            )
        )
        .select_related('organization', 'target_program', 'category')
        .order_by('-created_at')
    )

    map_data = []
    province_set = set()
    category_ids_used = set()
    total_raised = 0
    total_supporters = 0
    today = timezone.now().date()

    for c in qs:
        lat = c.beneficiary_lat
        lng = c.beneficiary_lng
        if (not lat or not lng) and c.target_program:
            lat = lat or c.target_program.beneficiary_lat
            lng = lng or c.target_program.beneficiary_lng
        if not lat or not lng:
            continue

        target_amount = int(c.target_amount or 0)
        current_amount = int(c.current_amount or 0)
        progress_pct = (current_amount / target_amount * 100) if target_amount > 0 else 0
        progress_pct = round(min(progress_pct, 100), 1)

        days_left = None
        if c.end_date:
            days_left = (c.end_date - today).days

        province = (c.beneficiary_province or '').strip()
        if province:
            province_set.add(province)
        if c.category_id:
            category_ids_used.add(c.category_id)

        total_raised += current_amount
        total_supporters += int(c.support_count or 0)

        # Xử lý URL ảnh: ưu tiên cover -> avatar -> default.
        # Nếu là đường dẫn tương đối (không bắt đầu bằng http/https hoặc /), thêm settings.MEDIA_URL.
        raw_img = c.cover_image_url or c.avatar_image_url or ''
        if raw_img:
            if raw_img.startswith(('http://', 'https://', '/')):
                campaign_img = raw_img
            else:
                campaign_img = settings.MEDIA_URL + raw_img
        else:
            campaign_img = '/static/client/img/bg_trangchu.jpg'

        map_data.append({
            'id': c.id,
            'title': c.title,
            'short_description': (c.short_description or '')[:200],
            'lat': float(lat),
            'lng': float(lng),
            'address': c.beneficiary_address or '',
            'province': province,
            'ward': (c.beneficiary_ward or '').strip(),
            'image': campaign_img,
            'url_detail': reverse('client:chitiet_chiendich', args=[c.id]),
            'url_donate': reverse('client:ungho', args=[c.id]),
            'status': c.status,
            'status_label': c.get_status_display(),
            'category_id': c.category_id,
            'category_name': c.category.name if c.category else '',
            'organization_name': c.organization.name if c.organization else '',
            'organization_logo': (c.organization.logo_url if c.organization else '') or '',
            'target_amount': target_amount,
            'current_amount': current_amount,
            'progress_pct': progress_pct,
            'support_count': int(c.support_count or 0),
            'days_left': days_left,
            'end_date': c.end_date.isoformat() if c.end_date else '',
            'is_protected_beneficiary': c.is_protected_beneficiary,
        })

    # Chỉ hiển thị danh mục có chiến dịch đang show — cho dropdown gọn.
    categories = list(
        CampaignCategory.objects
        .filter(id__in=category_ids_used, is_active=True)
        .order_by('display_order', 'name')
        .values('id', 'name')
    )

    context = {
        # Sử dụng json.dumps với ensure_ascii=False để hiển thị tiếng Việt trực tiếp,
        # giúp tránh các lỗi mã hóa \u0110... trên browser.
        'map_data_json': json.dumps(map_data, ensure_ascii=False),
        'categories': categories,
        'stats': {
            'total_campaigns': len(map_data),
            'total_provinces': len(province_set),
            'total_raised': total_raised,
            'total_supporters': total_supporters,
        },
    }
    return render(request, 'client/ban_do_thien_nguyen.html', context)

def chitiet_chuongtrinh(request, program_id):
    # 1. Lấy thông tin Chương trình mục tiêu (TargetProgram)
    # Dùng biến 'program' để khớp với template {{ program.name }} của bạn
    program = get_object_or_404(TargetProgram, pk=program_id)
    
    # 2. Lấy danh sách các CHIẾN DỊCH CON (Campaign)
    # Lưu ý quan trọng:
    # - target_program: là tên trường ForeignKey trong model Campaign
    # - status='active': chỉ lấy chiến dịch đang hoạt động
    campaigns = Campaign.objects.filter(
        target_program=program, 
        status='active'
    ).order_by('-created_at') # Sắp xếp mới nhất lên đầu

    context = {
        'program': program,
        'campaigns': campaigns,
    }
    
    return render(request, 'client/chitiet_chuongtrinh.html', context)


# =====================================================
# TRANG BIẾN ĐỘNG SỐ DƯ PUBLIC
# =====================================================

def biendong_sodu(request):
    campaign_id = request.GET.get('campaign')
    txn_type_filter = request.GET.get('type')

    statements = BankStatement.objects.select_related('campaign', 'donation').order_by('-transaction_date')

    if campaign_id:
        statements = statements.filter(campaign_id=campaign_id)
    if txn_type_filter in ('in', 'out'):
        statements = statements.filter(transaction_type=txn_type_filter)

    total_in = statements.filter(transaction_type='in').aggregate(t=Sum('amount'))['t'] or 0
    total_out = statements.filter(transaction_type='out').aggregate(t=Sum('amount'))['t'] or 0
    total_balance = total_in - total_out
    total_transactions = statements.count()

    campaigns_summary = Campaign.objects.filter(
        id__in=BankStatement.objects.values_list('campaign_id', flat=True).distinct()
    ).annotate(
        camp_in=Sum('bankstatement__amount', filter=Q(bankstatement__transaction_type='in')),
        camp_out=Sum('bankstatement__amount', filter=Q(bankstatement__transaction_type='out')),
        stmt_count=Count('bankstatement'),
    ).order_by('-created_at')

    campaigns_summary_list = []
    for camp in campaigns_summary:
        camp_in = camp.camp_in or 0
        camp_out = camp.camp_out or 0
        campaigns_summary_list.append({
            'campaign': camp,
            'total_in': camp_in,
            'total_out': camp_out,
            'balance': camp_in - camp_out,
            'count': camp.stmt_count,
        })

    all_campaigns = Campaign.objects.all().order_by('-created_at')

    context = {
        'statements': statements[:200],
        'total_in': total_in,
        'total_out': total_out,
        'total_balance': total_balance,
        'total_transactions': total_transactions,
        'campaigns_summary': campaigns_summary_list,
        'all_campaigns': all_campaigns,
        'selected_campaign': campaign_id,
        'selected_type': txn_type_filter,
    }
    return render(request, 'client/biendong_sodu.html', context)


# =====================================================
# API WEBHOOK NHẬN BIẾN ĐỘNG SỐ DƯ (Casso/SePay)
# =====================================================

@csrf_exempt
@require_POST
def api_webhook_bank_statement(request):
    secret = request.headers.get('X-Casso-Secret', '')
    if secret != settings.CASSO_SECRET_KEY:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    amount = data.get('amount')
    description = data.get('description', '')
    transaction_datetime = data.get('transactionDateTime')
    txn_type = data.get('type', 'in')
    campaign_id = data.get('campaign_id')

    if not amount or not transaction_datetime:
        return JsonResponse({'error': 'Thiếu amount hoặc transactionDateTime'}, status=400)

    if txn_type not in ('in', 'out'):
        return JsonResponse({'error': 'type phải là "in" hoặc "out"'}, status=400)

    try:
        txn_date = datetime.strptime(transaction_datetime, '%Y-%m-%d %H:%M:%S')
        txn_date = pytz.timezone('Asia/Ho_Chi_Minh').localize(txn_date)
    except (ValueError, TypeError):
        return JsonResponse({'error': 'transactionDateTime không đúng định dạng (YYYY-MM-DD HH:MM:SS)'}, status=400)

    # Tìm Campaign
    campaign = None
    donation = None

    if campaign_id:
        campaign = Campaign.objects.filter(id=campaign_id).first()

    # Nếu không có campaign_id, thử match từ description
    if not campaign:
        # Tìm Donation theo transaction_id trong description
        match = re.search(r'DH(\d+)', description)
        if match:
            donation = Donation.objects.filter(transaction_id=match.group(0)).first()
            if donation:
                campaign = donation.campaign

        # Fallback: tìm theo campaign ID trong description
        if not campaign:
            match = re.search(r'chien dich (\d+)', description, re.IGNORECASE)
            if match:
                campaign = Campaign.objects.filter(id=int(match.group(1))).first()

    if not campaign:
        return JsonResponse({'error': 'Không tìm được Campaign phù hợp'}, status=400)

    source = data.get('source', 'casso')
    if source not in ('casso', 'mock'):
        source = 'casso'

    # Tạo BankStatement + Cập nhật Campaign trong 1 transaction
    with transaction.atomic():
        statement = BankStatement.objects.create(
            campaign=campaign,
            donation=donation,
            transaction_date=txn_date,
            transaction_type=txn_type,
            amount=Decimal(str(amount)),
            description=description,
            source=source,
        )

        # Cập nhật Campaign
        if txn_type == 'in':
            campaign.current_amount = F('current_amount') + Decimal(str(amount))
            campaign.save(update_fields=['current_amount'])
        elif txn_type == 'out':
            campaign.disbursed_amount = F('disbursed_amount') + Decimal(str(amount))
            campaign.save(update_fields=['disbursed_amount'])

        # Ghi ActivityLog
        ActivityLog.objects.create(
            type='webhook_bank_statement',
            description=f"Webhook {txn_type}: {amount} VNĐ - Campaign #{campaign.id} - {description}",
            campaign=campaign,
            donation=donation,
        )

    return JsonResponse({
        'success': True,
        'statement_id': statement.id,
        'campaign_id': campaign.id,
        'type': txn_type,
        'amount': float(statement.amount),
    })


@csrf_exempt
@require_POST
def payos_webhook_view(request):
    """
    Webhook PayOS gọi vào sau khi khách thanh toán thành công.

    Lưu ý quan trọng:
    - PayOS gửi 1 "verification ping" khi bạn đăng ký webhook URL trong dashboard.
      Ping này có thể có `data = null` hoặc signature trống. BẮT BUỘC phải trả 200 OK
      cho ping, nếu không PayOS sẽ từ chối đăng ký webhook.
    - Với webhook thật, luôn cố gắng trả 200 OK để PayOS không retry liên tục.
      Chỉ trả 4xx khi payload rõ ràng bị hỏng (không parse được JSON).
    - Toàn bộ luồng đều log ra stdout để dễ debug trên Railway (xem `railway logs`).
    """
    raw_body = request.body.decode('utf-8', errors='replace')
    print("\n========== PAYOS WEBHOOK HIT ==========")
    print("REMOTE_ADDR:", request.META.get('REMOTE_ADDR'))
    print("X-FORWARDED-FOR:", request.META.get('HTTP_X_FORWARDED_FOR'))
    print("USER_AGENT:", request.META.get('HTTP_USER_AGENT'))
    print("RAW_BODY:", raw_body[:2000])

    try:
        payload = json.loads(raw_body) if raw_body else {}
    except json.JSONDecodeError as exc:
        print(f"❌ PAYOS WEBHOOK JSON parse error: {exc}")
        # Trả 200 để PayOS không retry vô hạn với payload hỏng.
        return JsonResponse({'success': False, 'message': 'Invalid JSON'}, status=200)

    signature = payload.get('signature')
    data = payload.get('data')
    print("PAYLOAD_KEYS:", list(payload.keys()))
    print("SIGNATURE_PRESENT:", bool(signature))
    print("DATA_TYPE:", type(data).__name__)

    # PAYOS VERIFICATION PING: khi đăng ký webhook URL, PayOS gửi 1 request test
    # với data rỗng/null hoặc không có signature. Phải trả 200 OK để URL được chấp nhận.
    if not data or not isinstance(data, dict) or not signature:
        print("ℹ️ PAYOS verification ping (no data/signature) — trả 200 OK để đăng ký webhook.")
        print("=======================================\n")
        return JsonResponse({
            'success': True,
            'code': '00',
            'desc': 'Webhook URL registered.',
            'message': 'ok',
        })

    # Verify HMAC signature để chắc chắn request đến từ PayOS.
    if not _verify_payos_signature(data, signature):
        print("❌ PAYOS WEBHOOK signature verification FAILED.")
        print("EXPECTED:", _create_payos_signature(data))
        print("RECEIVED:", signature)
        print("DATA:", data)
        print("=======================================\n")
        # 200 để PayOS không retry — request coi như bỏ qua.
        return JsonResponse({'success': False, 'message': 'Invalid signature'}, status=200)

    order_code = data.get('orderCode')
    print(f"✅ Signature OK. orderCode={order_code}, code={data.get('code')}, success={payload.get('success')}")
    if not order_code:
        print("⚠️ Webhook thiếu orderCode.")
        print("=======================================\n")
        return JsonResponse({'success': False, 'message': 'Missing orderCode'}, status=200)

    try:
        donation = Donation.objects.select_related('campaign', 'donor').get(order_code=order_code)
    except Donation.DoesNotExist:
        print(f"⚠️ Không tìm thấy Donation với orderCode={order_code}.")
        print("=======================================\n")
        # 200 OK để PayOS ngừng retry; có thể đây là order của môi trường khác.
        return JsonResponse({'success': False, 'message': 'Donation not found'}, status=200)

    # Luôn đánh dấu đã nhận webhook, bất kể trạng thái thanh toán.
    donation.payos_webhook_received_at = timezone.now()
    donation.payos_payment_link_id = data.get('paymentLinkId') or donation.payos_payment_link_id
    donation.payos_reference = data.get('reference') or donation.payos_reference
    donation.payos_transaction_id = (
        data.get('transactionId') or data.get('reference') or donation.payos_transaction_id
    )
    donation.save(update_fields=[
        'payos_webhook_received_at',
        'payos_payment_link_id',
        'payos_reference',
        'payos_transaction_id',
        'updated_at',
    ])

    # Điều kiện PayOS xác nhận thanh toán thành công.
    is_paid = bool(payload.get('success')) and str(data.get('code')) == '00'
    if not is_paid:
        print(f"ℹ️ Webhook không phải trạng thái PAID (success={payload.get('success')}, code={data.get('code')}).")
        print("=======================================\n")
        return JsonResponse({
            'success': True,
            'orderCode': order_code,
            'updated': False,
            'message': data.get('desc') or payload.get('desc') or 'Webhook received without successful payment state.',
        })

    # Cập nhật Donation + Campaign trong 1 transaction để tránh race.
    # LƯU Ý: không được dùng select_related('donor') cùng select_for_update()
    # vì `donor` là FK nullable → Postgres dùng LEFT OUTER JOIN, và Postgres
    # không cho phép FOR UPDATE trên nullable side của outer join
    # (lỗi: "FOR UPDATE cannot be applied to the nullable side of an outer join").
    # Dùng `of=('self',)` để chỉ lock dòng Donation, không lock các bảng join.
    created = False
    try:
        with transaction.atomic():
            locked_donation = (
                Donation.objects
                .select_related('campaign', 'donor')
                .select_for_update(of=('self',))
                .get(pk=donation.pk)
            )
            created = _mark_payos_donation_completed(locked_donation, data)
            donation = locked_donation
        print(f"✅ Donation #{donation.id} marked completed (created={created}).")
    except Exception as exc:
        print(f"❌ Lỗi khi đánh dấu donation completed: {exc}")
        print("=======================================\n")
        # Vẫn trả 200 để PayOS không retry — lỗi DB cần fix nội bộ, retry không giúp.
        return JsonResponse({
            'success': False,
            'orderCode': order_code,
            'message': f'Internal error: {exc}',
        }, status=200)

    # ==========================================================
    # Gọi on-chain recordDonation TRONG BACKGROUND THREAD.
    # ----------------------------------------------------------
    # Lý do: `_trigger_record_donation_bridge` gọi `wait_for_transaction_receipt`
    # của web3.py → block 10-30s chờ Sepolia confirm. Nếu chạy đồng bộ ở đây,
    # Gunicorn worker sẽ bị CRITICAL WORKER TIMEOUT (default 30s) TRƯỚC KHI
    # webhook kịp trả 200 OK cho PayOS → PayOS sẽ retry webhook vô hạn.
    #
    # Giải pháp: spawn daemon thread chạy trong nền và trả response ngay lập tức.
    # Dùng `transaction.on_commit` để đảm bảo thread chỉ start SAU khi transaction
    # đánh dấu donation='completed' đã commit (tránh thread đọc bản stale).
    #
    # FE polling endpoint `api_donation_blockchain_status` sẽ hiển thị trạng thái
    # thực tế (processing / confirmed / failed) cho user.
    # ==========================================================
    tx_hash = donation.eth_tx_hash
    blockchain_triggered = False
    if created:
        donation_id = donation.pk
        transaction.on_commit(lambda: _spawn_record_donation_thread(donation_id))
        blockchain_triggered = True
        print(f"🧵 Đã schedule background recordDonation cho Donation #{donation_id} "
              f"(chạy sau khi transaction commit).")

    print("=======================================\n")
    return JsonResponse({
        'success': True,
        'code': '00',
        'orderCode': order_code,
        'updated': created,
        'blockchain_triggered': blockchain_triggered,
        'tx_hash': tx_hash,
    })


# =====================================================
# API MOCK GỬI WEBHOOK (CHỈ KHI DEBUG=True)
# =====================================================

@csrf_exempt
@require_POST
def api_mock_bank_statement(request):
    if not settings.DEBUG:
        return JsonResponse({'error': 'Mock API chỉ hoạt động khi DEBUG=True'}, status=403)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    # Gọi nội bộ vào endpoint webhook thật
    webhook_url = request.build_absolute_uri('/api/webhook/bank-statement/')

    data['source'] = 'mock'

    response = http_requests.post(
        webhook_url,
        json=data,
        headers={
            'X-Casso-Secret': settings.CASSO_SECRET_KEY,
            'Content-Type': 'application/json',
        },
        timeout=10,
    )

    return JsonResponse({
        'mock': True,
        'webhook_status': response.status_code,
        'webhook_response': response.json(),
    })


# =====================================================
# API PUBLIC THỐNG KÊ TÀI CHÍNH THEO CAMPAIGN
# =====================================================

@require_GET
def api_campaign_finance(request, campaign_id):
    campaign = get_object_or_404(Campaign, id=campaign_id)

    statements = BankStatement.objects.filter(campaign=campaign).order_by('-transaction_date')

    total_donated = statements.filter(transaction_type='in').aggregate(
        total=Sum('amount')
    )['total'] or 0

    total_disbursed = statements.filter(transaction_type='out').aggregate(
        total=Sum('amount')
    )['total'] or 0

    transactions = []
    for s in statements:
        transactions.append({
            'id': s.id,
            'amount': float(s.amount),
            'type': s.transaction_type,
            'description': s.description,
            'source': s.source,
            'created_at': s.created_at.strftime('%Y-%m-%d %H:%M:%S') if s.created_at else '',
        })

    return JsonResponse({
        'campaign_id': campaign.id,
        'campaign_title': campaign.title,
        'total_donated': float(total_donated),
        'total_disbursed': float(total_disbursed),
        'balance': float(total_donated - total_disbursed),
        'transactions': transactions,
    })


@require_GET
def api_donation_blockchain_status(request, donation_id):
    """
    API polling cho frontend - trả về trạng thái blockchain của Donation (v2).
    Trả về 2 tx hash: A (bank_record) + B (donateOnBehalf).
    Frontend gọi mỗi 5s để biết khi nào cả 2 đã confirm.
    """
    try:
        donation = Donation.objects.get(id=donation_id)
    except Donation.DoesNotExist:
        return JsonResponse({'ok': False, 'message': 'Không tìm thấy giao dịch.'}, status=404)

    return JsonResponse({
        'ok': True,
        'donation_id': donation.id,
        'blockchain_status': donation.blockchain_status,
        'blockchain_error': donation.blockchain_error,
        # Giao dịch A: ghi sao kê NH
        'bank_record_tx_hash': donation.bank_record_tx_hash or '',
        'bank_record_gas_vnd': int(donation.bank_record_gas_vnd) if donation.bank_record_gas_vnd else 0,
        # Giao dịch B: admin nạp ETH
        'donate_onbehalf_tx_hash': donation.donate_onbehalf_tx_hash or '',
        'donate_onbehalf_gas_vnd': int(donation.donate_onbehalf_gas_vnd) if donation.donate_onbehalf_gas_vnd else 0,
        # Tổng gas admin đã chi (A+B)
        'total_admin_gas_vnd': int(donation.total_admin_gas_vnd) if donation.total_admin_gas_vnd else 0,
        # Các thông tin bổ sung
        'amount_vnd': int(donation.amount),
        'net_amount': int(donation.net_amount) if donation.net_amount else 0,
        'donated_eth_wei': str(donation.donated_eth_wei) if donation.donated_eth_wei is not None else '',
    })


@csrf_exempt
@require_POST
def api_retry_donation_blockchain(request, donation_id):
    """
    API retry blockchain cho Donation bị failed.
    """
    try:
        donation = Donation.objects.get(id=donation_id)
    except Donation.DoesNotExist:
        return JsonResponse({'ok': False, 'message': 'Không tìm thấy giao dịch.'}, status=404)

    if donation.blockchain_status == 'confirmed':
        return JsonResponse({'ok': True, 'message': 'Đã confirm trước đó.'})

    if donation.blockchain_status == 'processing':
        return JsonResponse({'ok': True, 'message': 'Đang xử lý, vui lòng đợi.'})

    try:
        start_blockchain_thread(donation.id)
        return JsonResponse({'ok': True, 'message': 'Đã bắt đầu retry.'})
    except Exception as e:
        return JsonResponse({'ok': False, 'message': str(e)}, status=500)


@csrf_exempt
@require_POST
def api_confirm_donation(request):
    try:
        data = json.loads(request.body.decode('utf-8'))
        donation_id = data.get('donation_id')
        tx_hash = data.get('tx_hash')
        from_address = data.get('from_address')

        if not donation_id or not tx_hash:
            return JsonResponse({'ok': False, 'message': 'Thiếu dữ liệu.'}, status=400)

        donation = Donation.objects.filter(id=donation_id).first()
        if not donation:
            return JsonResponse({'ok': False, 'message': 'Không tìm thấy giao dịch.'}, status=404)

        if donation.donor_wallet_address and from_address:
            if donation.donor_wallet_address.lower() != from_address.lower():
                return JsonResponse({'ok': False, 'message': 'Ví xác nhận không khớp.'}, status=400)

        donation.eth_tx_hash = tx_hash
        donation.is_blockchain_synced = True
        donation.save(update_fields=['eth_tx_hash', 'is_blockchain_synced'])
        return JsonResponse({'ok': True})
    except Exception as e:
        return JsonResponse({'ok': False, 'message': str(e)}, status=500)

def tochuc_list(request):
    """
    Trang tổ chức — gộp 2 chức năng:
      1. Hiển thị danh sách các tổ chức đã được KYC + duyệt.
      2. Cho phép user (đã login bằng tài khoản web nội bộ) nộp hồ sơ đăng ký
         tổ chức mới (anchor #dangky-section).

    Quy tắc gating form đăng ký (theo `fix_to_chuc.md`):
      • Chưa login              → KHÔNG render form, hiển thị CTA login.
      • Login bằng Google/Web3  → KHÔNG render form, hiển thị thông báo
        không đủ điều kiện. Hướng dẫn dùng tài khoản web nội bộ.
      • Login bằng tài khoản web → render form bình thường, kèm trạng thái
        hồ sơ hiện có (đã nộp / đang thẩm định / bị từ chối / đã duyệt).
      • Đã là manager của 1 tổ chức đã duyệt → KHÔNG cho gửi lại form.

    GET  → render list + (có thể) form rỗng.
    POST → chỉ chấp nhận từ user web đủ điều kiện; gắn manager=request.user
           để admin duyệt sẽ chuyển user thành tài khoản tổ chức.
    """
    org_form = None
    rep_form = None

    # ---- 1. Xác định trạng thái tài khoản người dùng ----
    user = request.user if request.user.is_authenticated else None
    user_profile = None
    user_account_source = ''
    if user is not None:
        user_profile, _ = UserProfile.objects.get_or_create(user=user)
        user_account_source = user_profile.account_source or 'web'

    # Hồ sơ tổ chức đã có do user gửi (nếu là user web nội bộ).
    # Quan hệ: Organization.manager → User. Một user chỉ làm manager 1 tổ chức
    # tại 1 thời điểm, nhưng để defensive lấy bản mới nhất.
    user_existing_org = None
    if user is not None:
        user_existing_org = Organization.objects.filter(manager=user).order_by('-created_at').first()

    is_web_account = (user is not None) and (user_account_source == 'web')
    is_google_account = (user is not None) and (user_account_source == 'google')
    # User đã có tổ chức đã duyệt → không cho gửi lại; vẫn cho xem trạng thái.
    has_approved_org = bool(
        user_existing_org
        and user_existing_org.kyc_status == 'approved'
        and user_existing_org.is_verified
    )
    # User có hồ sơ đang chờ / đang thẩm định → chặn submit lại để tránh duplicate.
    has_pending_org = bool(
        user_existing_org and user_existing_org.kyc_status in ('submitted', 'under_review')
    )
    can_submit_form = is_web_account and not has_approved_org and not has_pending_org

    if can_submit_form:
        org_form = GuestOrganizationForm()
        rep_form = GuestRepresentativeForm()

    if request.method == 'POST':
        # Gate: chỉ user web nội bộ + chưa có tổ chức được duyệt / pending.
        if user is None:
            messages.warning(request, 'Vui lòng đăng nhập bằng tài khoản web nội bộ để gửi hồ sơ tổ chức.')
            return redirect(reverse('admin_panel:dangnhap') + '?next=' + reverse('client:tochuc_list') + '%23dangky-section')
        if is_google_account:
            messages.error(
                request,
                'Tài khoản Google không được phép gửi hồ sơ đăng ký tổ chức. '
                'Vui lòng đăng ký một tài khoản web nội bộ riêng để thực hiện thủ tục KYC.'
            )
            return redirect(reverse('client:tochuc_list') + '#dangky-section')
        if has_approved_org:
            messages.info(request, 'Tài khoản của bạn đã liên kết với một tổ chức đã được duyệt.')
            return redirect(reverse('client:tochuc_list') + '#dangky-section')
        if has_pending_org:
            messages.info(request, 'Bạn đã có hồ sơ đang chờ duyệt. Vui lòng đợi quản trị viên xử lý.')
            return redirect(reverse('client:tochuc_list') + '#dangky-section')

        org_form = GuestOrganizationForm(request.POST, request.FILES)
        rep_form = GuestRepresentativeForm(request.POST, request.FILES)

        # Pre-check CCCD trùng để hiển thị field-level error
        # thay vì IntegrityError 500 khi save.
        if org_form.is_valid() and rep_form.is_valid():
            id_card_no = rep_form.cleaned_data.get('id_card_number')
            if id_card_no and OrganizationRepresentative.objects.filter(id_card_number=id_card_no).exists():
                rep_form.add_error(
                    'id_card_number',
                    'Số CCCD/CMND này đã được đăng ký. Vui lòng kiểm tra lại.'
                )

        if org_form.is_valid() and rep_form.is_valid():
            try:
                with transaction.atomic():
                    organization = org_form.save(commit=False)
                    base_slug = slugify(organization.name) or 'to-chuc'
                    candidate = base_slug
                    suffix = 1
                    while Organization.objects.filter(slug=candidate).exists():
                        suffix += 1
                        candidate = f"{base_slug}-{suffix}"
                    organization.slug = candidate
                    organization.kyc_status = 'submitted'
                    organization.kyc_submitted_at = timezone.now()
                    organization.is_verified = False
                    # GẮN MANAGER = USER GỬI FORM. Khi admin duyệt KYC,
                    # user này sẽ tự động thành "tài khoản tổ chức"
                    # (admin views detect qua Organization.manager).
                    organization.manager = user
                    organization.save()

                    representative = rep_form.save(commit=False)
                    representative.organization = organization
                    representative.save()

                    ActivityLog.objects.create(
                        user=user,
                        type='organization_kyc_submitted',
                        description=(
                            f'User {user.username} nộp hồ sơ KYC tổ chức #{organization.id} - {organization.name} '
                            f'(đại diện: {representative.full_name}).'
                        ),
                        ip_address=get_client_ip(request),
                        user_agent=request.META.get('HTTP_USER_AGENT', '')[:1000],
                    )

                messages.success(
                    request,
                    'Hồ sơ đăng ký tổ chức đã được gửi thành công. Quản trị viên sẽ đánh giá và liên hệ lại sớm nhất.'
                )
                return redirect(reverse('client:tochuc_list') + '#hosodangcho')
            except IntegrityError:
                rep_form.add_error(
                    'id_card_number',
                    'Số CCCD/CMND này vừa được đăng ký bởi hồ sơ khác. Vui lòng kiểm tra lại.'
                )
                messages.error(request, 'Hồ sơ đã có xung đột dữ liệu, vui lòng thử lại.')
        else:
            messages.error(request, 'Vui lòng kiểm tra lại các trường đã nhập.')

    organizations_list = Organization.objects.filter(
        is_verified=True, kyc_status='approved'
    ).order_by('name')
    # PRIVACY: Hồ sơ chờ duyệt KHÔNG được public — mỗi user chỉ được xem hồ sơ
    # của chính mình ở section #dangky-section. Quản trị viên xem tất cả
    # ở trang admin (quanlytochuc).

    paginator = Paginator(organizations_list, 12)
    page = request.GET.get('page')
    try:
        organizations = paginator.page(page)
    except PageNotAnInteger:
        organizations = paginator.page(1)
    except EmptyPage:
        organizations = paginator.page(paginator.num_pages)

    # Quick stats cho hero (số tổ chức đã verified, tổng số chiến dịch active...).
    total_orgs = organizations_list.count()
    total_active_campaigns = Campaign.objects.filter(
        organization__in=organizations_list, status='active'
    ).count()

    context = {
        'organizations': organizations,
        'org_form': org_form,
        'rep_form': rep_form,
        'has_form_errors': request.method == 'POST' and (org_form is not None) and (not org_form.is_valid() or not rep_form.is_valid()),
        'total_orgs': total_orgs,
        'total_active_campaigns': total_active_campaigns,
        # Trạng thái tài khoản dùng cho template gating.
        'is_authenticated_user': user is not None,
        'is_web_account': is_web_account,
        'is_google_account': is_google_account,
        'has_approved_org': has_approved_org,
        'has_pending_org': has_pending_org,
        'can_submit_form': can_submit_form,
        'user_existing_org': user_existing_org,
        'user_account_source': user_account_source,
    }
    return render(request, 'client/tochuc_list.html', context)

@login_required(login_url='admin_panel:dangnhap')
def tochuc_edit_pending(request):
    """
    Cho phép chính chủ user (đã login bằng tài khoản web nội bộ) chỉnh sửa
    hồ sơ tổ chức ĐANG CHỜ DUYỆT của mình.

    Quy tắc gating:
      • Phải authenticated.
      • Tài khoản Google → từ chối (redirect về tochuc_list).
      • Phải có Organization với `manager=user` ở status
        ('submitted', 'under_review'). Approved/rejected → không cho sửa.
      • Không được sửa các trường quản trị (kyc_status, is_verified, manager...) —
        chỉ form public reuse `GuestOrganizationForm` + `GuestRepresentativeForm`.
      • Save xong giữ nguyên kyc_status='submitted' để admin tiếp tục thẩm định.
    """
    user = request.user
    profile, _ = UserProfile.objects.get_or_create(user=user)
    if (profile.account_source or 'web') == 'google':
        messages.error(request, 'Tài khoản Google không được phép chỉnh sửa hồ sơ tổ chức.')
        return redirect(reverse('client:tochuc_list') + '#dangky-section')

    organization = Organization.objects.filter(
        manager=user,
        kyc_status__in=['submitted', 'under_review'],
    ).order_by('-created_at').first()
    if not organization:
        messages.warning(request, 'Bạn không có hồ sơ tổ chức nào đang chờ duyệt để chỉnh sửa.')
        return redirect(reverse('client:tochuc_list') + '#dangky-section')

    representative = getattr(organization, 'representative', None)

    if request.method == 'POST':
        org_form = GuestOrganizationForm(request.POST, request.FILES, instance=organization)
        rep_form = GuestRepresentativeForm(request.POST, request.FILES, instance=representative)

        # Pre-check CCCD trùng (chỉ check khi đổi sang số CCCD đã thuộc representative khác).
        if org_form.is_valid() and rep_form.is_valid():
            new_id_card = rep_form.cleaned_data.get('id_card_number')
            if new_id_card:
                conflict_qs = OrganizationRepresentative.objects.filter(id_card_number=new_id_card)
                if representative is not None:
                    conflict_qs = conflict_qs.exclude(pk=representative.pk)
                if conflict_qs.exists():
                    rep_form.add_error(
                        'id_card_number',
                        'Số CCCD/CMND này đã được đăng ký bởi hồ sơ khác. Vui lòng kiểm tra lại.'
                    )

        if org_form.is_valid() and rep_form.is_valid():
            try:
                with transaction.atomic():
                    updated_org = org_form.save(commit=False)
                    # Defensive: KHÔNG cho user đổi các trường quản trị qua form public.
                    updated_org.manager = user
                    updated_org.kyc_status = organization.kyc_status  # giữ nguyên submitted/under_review
                    updated_org.is_verified = False
                    updated_org.kyc_reviewed_at = None
                    updated_org.kyc_reviewed_by = None
                    updated_org.kyc_rejection_reason = None
                    updated_org.save()

                    updated_rep = rep_form.save(commit=False)
                    updated_rep.organization = updated_org
                    updated_rep.save()

                    ActivityLog.objects.create(
                        user=user,
                        type='organization_kyc_updated',
                        description=(
                            f'User {user.username} cập nhật hồ sơ KYC tổ chức #{updated_org.id} - '
                            f'{updated_org.name} (đại diện: {updated_rep.full_name}).'
                        ),
                        ip_address=get_client_ip(request),
                        user_agent=request.META.get('HTTP_USER_AGENT', '')[:1000],
                    )

                messages.success(request, 'Đã cập nhật hồ sơ. Quản trị viên sẽ tiếp tục thẩm định.')
                return redirect(reverse('client:tochuc_list') + '#dangky-section')
            except IntegrityError:
                rep_form.add_error(
                    'id_card_number',
                    'Số CCCD/CMND này vừa được đăng ký bởi hồ sơ khác. Vui lòng kiểm tra lại.'
                )
                messages.error(request, 'Hồ sơ đã có xung đột dữ liệu, vui lòng thử lại.')
        else:
            messages.error(request, 'Vui lòng kiểm tra lại các trường đã nhập.')
    else:
        org_form = GuestOrganizationForm(instance=organization)
        rep_form = GuestRepresentativeForm(instance=representative)

    context = {
        'org_form': org_form,
        'rep_form': rep_form,
        'organization': organization,
        'representative': representative,
        'has_form_errors': request.method == 'POST' and (not org_form.is_valid() or not rep_form.is_valid()),
    }
    return render(request, 'client/tochuc_edit_pending.html', context)


@login_required(login_url='admin_panel:dangnhap')
@require_POST
def tochuc_cancel_pending(request):
    """
    Cho phép chính chủ HỦY hồ sơ tổ chức đang chờ duyệt.

    Quy tắc:
      • Chỉ chính chủ (Organization.manager == user) mới được hủy.
      • Chỉ status `submitted` / `under_review` mới được hủy. Approved →
        đã thành tài khoản tổ chức chính thức, không cho hủy. Rejected →
        đã đóng, hủy thêm cũng vô nghĩa (nhưng vẫn cho phép xóa để user
        đăng ký lại từ đầu).
      • Hủy = xóa Organization + Representative (cascade). Vì hồ sơ chưa được
        duyệt nên không có liên kết on-chain (Campaign chưa tạo, không có
        donation), an toàn để xóa hoàn toàn.
    """
    user = request.user
    organization = Organization.objects.filter(
        manager=user,
        kyc_status__in=['submitted', 'under_review', 'rejected'],
    ).order_by('-created_at').first()
    if not organization:
        messages.warning(request, 'Bạn không có hồ sơ tổ chức nào để hủy.')
        return redirect(reverse('client:tochuc_list') + '#dangky-section')

    # Defensive: chặn hủy nếu tổ chức đã có campaign on-chain (lỡ status sai).
    if organization.is_verified or organization.campaigns.exists():
        messages.error(
            request,
            'Hồ sơ này đã được duyệt hoặc đã có chiến dịch — không thể hủy.'
            ' Vui lòng liên hệ quản trị viên.'
        )
        return redirect(reverse('client:tochuc_list') + '#dangky-section')

    org_id = organization.id
    org_name = organization.name
    with transaction.atomic():
        organization.delete()
        ActivityLog.objects.create(
            user=user,
            type='organization_kyc_cancelled',
            description=(
                f'User {user.username} đã hủy hồ sơ KYC tổ chức #{org_id} - {org_name}.'
            ),
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:1000],
        )

    messages.success(
        request,
        f'Đã hủy hồ sơ "{org_name}". Bạn có thể gửi hồ sơ mới bất cứ lúc nào.'
    )
    return redirect(reverse('client:tochuc_list') + '#dangky-section')


def guest_register_organization(request):
    """
    LEGACY ROUTE: trước đây trang đăng ký tổ chức đứng riêng ở /dang-ky-to-chuc/.

    Hiện tại form đã được mở vào trang /to-chuc/ (anchor #dangky-section)
    để user thấy được các tổ chức đã đăng ký trước khi quyết định nộp hồ sơ.

    Route cũ vẫn redirect 302 để tránh broken link từ bài viết / email đã gửi.
    """
    return redirect(reverse('client:tochuc_list') + '#dangky-section')


def tochuc_detail(request, slug):
    """
    Trang chi tiết thông tin của một tổ chức.
    """
    organization = get_object_or_404(
        Organization, slug=slug, is_verified=True, kyc_status='approved'
    )
    
    # Lấy các chiến dịch thuộc tổ chức này (có thể lọc trạng thái nếu cần)
    campaigns = Campaign.objects.filter(
        organization=organization, status='active'
    ).order_by('-created_at')

    context = {
        'organization': organization,
        'campaigns': campaigns,
    }
    return render(request, 'client/tochuc_detail.html', context)
from django.core.paginator import Paginator

def chiendich_list(request):
    campaign_list = Campaign.objects.filter(status='approved').order_by('-created_at')
    paginator = Paginator(campaign_list, 9)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'client/chiendich_list.html', {
        'campaigns': page_obj,
        'page_obj': page_obj,
        'paginator': paginator,
    })
