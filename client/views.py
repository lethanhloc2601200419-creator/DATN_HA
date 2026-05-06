from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponseRedirect, JsonResponse
from admin_panel.models import (
    UserProfile, Campaign, Donation, TargetProgram, BankStatement, ActivityLog,
    DisbursementProposal, ProposalVote, Organization,
)
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
from django.db import transaction
from django.db.models import F
import hashlib
import hmac
import urllib.parse
import json
from decimal import Decimal
from datetime import datetime, timedelta
import pytz
import re
import requests as http_requests
from web3 import Web3

# Import Service Blockchain đã viết
from .blockchain import BlockchainService, get_eth_vnd_rate
from .blockchain_processor import start_blockchain_thread

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
    profile.save(update_fields=[
        'display_name',
        'eoa_address',
        'smart_account_address',
        'wallet_address',
        'updated_at',
    ])

    return user, profile


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
            if request.user.is_authenticated:
                donation.donor = request.user
                if hasattr(request.user, 'profile'):
                    donation.donor_name = request.user.profile.display_name
                    donation.donor_wallet_address = (
                        request.user.profile.smart_account_address
                        or request.user.profile.wallet_address
                        or None
                    )
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


@login_required(login_url='admin_panel:dangnhap')
@require_POST
def api_wallet_sync(request):
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'message': 'Invalid JSON payload.'}, status=400)

    wallet_address = (payload.get('wallet_address') or '').strip()
    eoa_address = (payload.get('eoa_address') or '').strip()
    smart_account_address = (payload.get('smart_account_address') or '').strip()
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
    profile, _created = UserProfile.objects.get_or_create(user=request.user)
    profile.eoa_address = checksum_eoa or None
    profile.smart_account_address = checksum_smart
    profile.wallet_address = checksum_smart
    profile.save(update_fields=[
        'eoa_address',
        'smart_account_address',
        'wallet_address',
        'updated_at',
    ])

    ActivityLog.objects.create(
        user=request.user,
        type='wallet_sync',
        description=f'Đồng bộ Smart Account {checksum_smart} từ {provider}' + (f' | EOA {checksum_eoa}' if checksum_eoa else ''),
    )

    return JsonResponse({
        'ok': True,
        'wallet_address': checksum_smart,
        'eoa_address': checksum_eoa,
        'smart_account_address': checksum_smart,
        'provider': provider,
    })
    

# client/views.py

def chitiet_chiendich(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
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
        # V2: dùng total_gas_cost_wei (contract mới); fallback total_gas_subsidized_wei
        total_gas_cost_wei = stats.get('total_gas_cost_wei', stats.get('total_gas_subsidized_wei', 0))
        gas_subsidized_vnd = _wei_to_vnd(total_gas_cost_wei, eth_vnd_rate)
        gas_recovered_vnd = _wei_to_vnd(stats['total_admin_recovered_wei'], eth_vnd_rate)
        onchain_total_fund_vnd = _wei_to_vnd(stats['total_fund_wei'], eth_vnd_rate)
        onchain_total_disbursed_vnd = _wei_to_vnd(stats['total_disbursed_wei'], eth_vnd_rate)
        est_per_tx_gas_vnd, _est_wei = estimate_gas_per_tx_vnd(eth_vnd_rate, bc=bc)
        # Chỉ cần 1 phí dự trù duy nhất: 1 lần executeDisbursement chuyển ETH contract→tổ chức
        est_disbursement_gas_vnd = est_per_tx_gas_vnd
        est_recovery_gas_vnd = Decimal('0')  # KHÔNG cộng double, chỉ hiển thị nếu cần
        # onchain_available: số tiền còn có thể giải ngân = totalFund - totalGasCost - totalDisbursed - totalAdminRecovered - gas dự trù
        est_disbursement_wei = int((est_disbursement_gas_vnd / eth_vnd_rate) * Decimal('1000000000000000000')) if eth_vnd_rate else 0
        onchain_available_wei = max(
            0,
            stats['total_fund_wei']
            - total_gas_cost_wei
            - stats['total_disbursed_wei']
            - stats['total_admin_recovered_wei']
            - est_disbursement_wei,
        )
        onchain_available_vnd = _wei_to_vnd(onchain_available_wei, eth_vnd_rate)
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
    # 2. Lấy dữ liệu từ TargetProgram
    programs = TargetProgram.objects.filter(
        is_active=True, 
        beneficiary_lat__isnull=False, 
        beneficiary_lng__isnull=False
    )

    map_data = []
    for p in programs:
        # Xử lý ảnh (nếu không có ảnh thì dùng ảnh mặc định)
        img_url = p.image.url if p.image else '/static/images/default_program.jpg' 
        
        map_data.append({
            'name': p.name,
            # Chuyển Decimal/Float sang float của Python để JSON hiểu
            'lat': float(p.beneficiary_lat),
            'lng': float(p.beneficiary_lng),
            'address': p.beneficiary_address,
            # Link tới trang chi tiết (bạn kiểm tra lại đúng url chưa nhé)
            'url': f"/chuong-trinh/{p.id}/", 
            'image': img_url,
            'money': float(p.total_target_amount) if p.total_target_amount else 0
        })

    context = {
        'map_data_json': json.dumps(map_data)
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
    return JsonResponse({"error": 0, "message": "Ok", "data": None})
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    signature = payload.get('signature')
    data = payload.get('data') or {}
    if not signature or not data:
        return JsonResponse({'error': 'Missing signature or data'}, status=400)

    if not _verify_payos_signature(data, signature):
        return JsonResponse({'error': 'Invalid signature'}, status=400)

    order_code = data.get('orderCode')
    if not order_code:
        return JsonResponse({'error': 'Missing orderCode'}, status=400)

    try:
        donation = Donation.objects.select_related('campaign', 'donor').get(order_code=order_code)
    except Donation.DoesNotExist:
        return JsonResponse({'error': 'Donation not found'}, status=404)

    donation.payos_webhook_received_at = timezone.now()
    donation.payos_payment_link_id = data.get('paymentLinkId') or donation.payos_payment_link_id
    donation.payos_reference = data.get('reference') or donation.payos_reference
    donation.payos_transaction_id = data.get('transactionId') or data.get('reference') or donation.payos_transaction_id
    donation.save(update_fields=[
        'payos_webhook_received_at',
        'payos_payment_link_id',
        'payos_reference',
        'payos_transaction_id',
        'updated_at',
    ])

    if payload.get('success') and data.get('code') == '00':
        with transaction.atomic():
            donation = Donation.objects.select_for_update().get(pk=donation.pk)
            created = _mark_payos_donation_completed(donation, data)
        tx_hash = donation.eth_tx_hash
        blockchain_triggered = False
        if created:
            try:
                donation = Donation.objects.select_related('campaign', 'donor').get(pk=donation.pk)
                tx_hash = _trigger_record_donation_bridge(donation)
                blockchain_triggered = True
            except Exception as exc:
                donation = Donation.objects.get(pk=donation.pk)
                donation.blockchain_status = 'failed'
                donation.blockchain_completed_at = timezone.now()
                donation.blockchain_error = str(exc)[:500]
                donation.save(update_fields=[
                    'blockchain_status',
                    'blockchain_completed_at',
                    'blockchain_error',
                    'updated_at',
                ])
        return JsonResponse({
            'success': True,
            'orderCode': order_code,
            'updated': created,
            'blockchain_triggered': blockchain_triggered,
            'tx_hash': tx_hash,
        })

    return JsonResponse({
        'success': True,
        'orderCode': order_code,
        'updated': False,
        'message': data.get('desc') or payload.get('desc') or 'Webhook received without successful payment state.',
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
