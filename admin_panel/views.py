from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.views import View
from django.http import HttpResponse, JsonResponse  
from django.db import transaction
from django.contrib.auth import  login, authenticate,  logout
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from types import SimpleNamespace
import random
import requests
import json
from django.utils.text import slugify
import time
import logging
import traceback
from django.db.models import Q, Sum
from .models import (
    CampaignCategory, Organization, TargetProgram, Donation, Campaign,
    CampaignOccasion, DisbursementProposal, ProposalVote, CampaignDisbursement,
    BankStatement, ActivityLog, DisbursementSignature,
)
from .forms import DonationForm
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
import re
import hashlib
import csv
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from django.core.files.storage import FileSystemStorage
from django.utils.html import escape

logger = logging.getLogger(__name__)

# ========================================================
# 🔥 IMPORT BLOCKCHAIN SERVICE (Thêm dòng này)
# ========================================================
from client.blockchain import BlockchainService, get_eth_vnd_rate, invalidate_campaign_cache
from client.blockchain_listener import sync_disbursement_proposal_status
from admin_panel.disbursement_utils import estimate_gas_per_tx_vnd
from admin_panel.blockchain_utils import sync_single_campaign

WEI_IN_ETH = Decimal('1000000000000000000')
# Ngưỡng coi chiến dịch đã giải ngân hết (để cho phép thu hồi gas 1 lần cuối)
FULLY_DISBURSED_THRESHOLD_VND = Decimal('1000')

def _get_user_role(user):
    if not user or not user.is_authenticated:
        return 'user'
    if user.is_superuser:
        return 'admin'
    if user.managed_organizations.exists() or Organization.objects.filter(manager=user).exists():
        return 'partner'
    return 'user'

def _wei_to_vnd(wei, eth_vnd_rate):
    return (Decimal(str(wei)) / WEI_IN_ETH) * eth_vnd_rate

def _round_vnd(value):
    return Decimal(value).quantize(Decimal('1'), rounding=ROUND_HALF_UP)

def _normalize_query(value):
    return (value or '').strip()


def _clean_admin_unit_name(value):
    return re.sub(r'\s+', ' ', value or '').strip()


def _fetch_casso_addresskit(path):
    url = f"https://production.cas.so/address-kit/latest/{path.lstrip('/')}"
    response = requests.get(url, timeout=12)
    response.raise_for_status()
    return response.json()


def _apply_campaign_location(campaign, post_data):
    campaign.beneficiary_province = _clean_admin_unit_name(post_data.get('beneficiary_province')) or None
    campaign.beneficiary_ward = _clean_admin_unit_name(post_data.get('beneficiary_ward')) or None
    campaign.beneficiary_address = _clean_admin_unit_name(post_data.get('beneficiary_address')) or None
    campaign.beneficiary_lat = post_data.get('beneficiary_lat') or None
    campaign.beneficiary_lng = post_data.get('beneficiary_lng') or None


def _reverse_geocode_with_nominatim(lat_value, lng_value):
    response = requests.get(
        'https://nominatim.openstreetmap.org/reverse',
        params={
            'format': 'jsonv2',
            'lat': lat_value,
            'lon': lng_value,
            'zoom': 18,
            'addressdetails': 1,
            'accept-language': 'vi',
        },
        headers={'User-Agent': 'doantn-charity-admin/1.0'},
        timeout=12,
    )
    response.raise_for_status()
    payload = response.json()
    address = payload.get('address') or {}
    province = _clean_admin_unit_name(
        address.get('state') or address.get('city') or address.get('province')
    )
    ward_candidates = [
        address.get('suburb'),
        address.get('quarter'),
        address.get('municipality'),
        address.get('village'),
        address.get('town'),
        address.get('hamlet'),
    ]
    ward = ''
    for candidate in ward_candidates:
        text = _clean_admin_unit_name(candidate)
        if text:
            ward = text
            break
    detail_parts = []
    for value in (
        address.get('house_number'),
        address.get('road'),
        address.get('amenity'),
        address.get('building'),
        payload.get('name'),
    ):
        text = _clean_admin_unit_name(value)
        if text and text not in detail_parts and text not in {province, ward}:
            detail_parts.append(text)

    label = _clean_admin_unit_name(payload.get('display_name'))
    return {
        'province': province,
        'ward': ward,
        'address': ', '.join(detail_parts) or label,
        'formatted_address': label,
        'source': 'nominatim',
    }


def _format_export_value(value):
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'Có' if value else 'Không'
    if hasattr(value, 'strftime'):
        try:
            return timezone.localtime(value).strftime('%d/%m/%Y %H:%M:%S')
        except Exception:
            return value.strftime('%d/%m/%Y %H:%M:%S')
    return str(value)


def _export_table_response(filename_prefix, headers, rows, export_format='csv'):
    ts = timezone.localtime().strftime('%Y%m%d_%H%M%S')
    normalized_rows = [[_format_export_value(cell) for cell in row] for row in rows]

    if export_format == 'excel':
        response = HttpResponse(content_type='application/vnd.ms-excel; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{filename_prefix}_{ts}.xls"'
        html = ['<table border="1"><thead><tr>']
        html.extend([f'<th>{escape(col)}</th>' for col in headers])
        html.append('</tr></thead><tbody>')
        for row in normalized_rows:
            html.append('<tr>')
            html.extend([f'<td>{escape(cell)}</td>' for cell in row])
            html.append('</tr>')
        html.append('</tbody></table>')
        response.write(''.join(html))
        return response

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename_prefix}_{ts}.csv"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(headers)
    writer.writerows(normalized_rows)
    return response


def _get_export_format(request):
    export = (request.GET.get('export') or '').lower()
    if export in ('csv', 'excel', 'xlsx', 'xls'):
        return 'excel' if export in ('excel', 'xlsx', 'xls') else 'csv'
    return ''


def _export_links(request):
    base = request.GET.copy()
    base.pop('export', None)
    csv_q = base.copy()
    excel_q = base.copy()
    csv_q['export'] = 'csv'
    excel_q['export'] = 'excel'
    return f"?{csv_q.urlencode()}", f"?{excel_q.urlencode()}"


def _selected_ids(request):
    ids = []
    for raw in request.POST.getlist('selected_ids'):
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    return ids


def _safe_next_url(request, fallback_name):
    nxt = (request.POST.get('next') or '').strip()
    if nxt.startswith('/'):
        return redirect(nxt)
    return redirect(fallback_name)


def _build_disbursement_web3_config(request):
    wallet_address = ''
    eoa_address = ''
    smart_account_address = ''
    if request.user.is_authenticated and hasattr(request.user, 'profile'):
        smart_account_address = request.user.profile.smart_account_address or ''
        eoa_address = request.user.profile.eoa_address or ''
        wallet_address = smart_account_address or request.user.profile.wallet_address or ''

    alchemy_api_key = ''
    if settings.SEPOLIA_RPC_URL and '/v2/' in settings.SEPOLIA_RPC_URL:
        alchemy_api_key = settings.SEPOLIA_RPC_URL.rsplit('/v2/', 1)[-1].strip()

    return {
        'clientId': settings.WEB3AUTH_CLIENT_ID,
        'network': settings.WEB3AUTH_NETWORK,
        'chainId': '0xaa36a7',
        'rpcTarget': settings.SEPOLIA_RPC_URL,
        'displayName': 'Ethereum Sepolia',
        'ticker': 'ETH',
        'tickerName': 'Ethereum',
        'blockExplorerUrl': 'https://sepolia.etherscan.io',
        'googleClientId': settings.GOOGLE_CLIENT_ID,
        'syncUrl': '/api/auth/wallet-sync/',
        'isAuthenticated': request.user.is_authenticated,
        'walletAddress': wallet_address,
        'eoaAddress': eoa_address,
        'smartAccountAddress': smart_account_address,
        'userEmail': request.user.email if request.user.is_authenticated else '',
        'userName': request.user.get_username() if request.user.is_authenticated else '',
        'biconomyBundlerUrl': settings.BICONOMY_BUNDLER_URL,
        'biconomyPaymasterUrl': settings.BICONOMY_PAYMASTER_URL,
        'alchemyApiKey': alchemy_api_key,
        'alchemyPolicyId': settings.ALCHEMY_POLICY_ID,
        'contractAddress': settings.CONTRACT_ADDRESS,
    }


def _can_manage_campaign_disbursement(user, campaign):
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    my_org = user.managed_organizations.first()
    return bool(my_org and campaign.organization_id == my_org.id)


def _get_user_wallet_identity(user):
    if not user or not user.is_authenticated or not hasattr(user, 'profile'):
        return ''
    return (
        user.profile.smart_account_address
        or user.profile.wallet_address
        or user.profile.eoa_address
        or ''
    )


def _get_disbursement_approver_context(user):
    context = {
        'current_wallet': _get_user_wallet_identity(user),
        'admin_wallet': '',
        'supervisor_wallet': '',
        'approver_role': '',
    }
    try:
        bc = BlockchainService()
        wallets = bc.get_disbursement_approver_wallets()
        context['admin_wallet'] = wallets['admin_wallet']
        context['supervisor_wallet'] = wallets['supervisor_wallet']
        current_wallet = (context['current_wallet'] or '').lower()
        if current_wallet:
            if current_wallet == wallets['admin_wallet'].lower() or user.is_superuser:
                context['approver_role'] = 'admin'
            elif current_wallet == wallets['supervisor_wallet'].lower():
                context['approver_role'] = 'supervisor'
    except Exception:
        if user.is_superuser:
            context['approver_role'] = 'admin'
    return context


def _sync_campaign_to_blockchain(campaign):
    """
    Wrapper backward-compat: delegate sang `sync_single_campaign` (blockchain_utils).

    Logic thực tế đã được tách ra `admin_panel/blockchain_utils.py` để tái sử dụng
    bởi management command và signal `post_save`. Hàm này giữ nguyên signature cũ
    (nhận `campaign` instance, không trả về) để các call-site hiện tại không phải
    sửa; sau khi RPC xong, refresh lại instance từ DB để caller đọc được giá trị
    mới (blockchain_tx_hash, blockchain_sync_error…).
    """
    sync_single_campaign(campaign.id)
    try:
        campaign.refresh_from_db(fields=[
            'is_onchain', 'blockchain_tx_hash',
            'blockchain_synced_at', 'blockchain_sync_error',
        ])
    except Exception:
        # Trường hợp campaign đã bị xóa giữa chừng — bỏ qua refresh.
        pass


def _approve_campaign_with_blockchain(campaign, approver):
    campaign.status = 'active'
    campaign.approved_by = approver
    campaign.approved_at = timezone.now()
    # Tắt auto-sync signal vì call-site này sẽ tự gọi sync đồng bộ ngay bên dưới.
    # Nếu không tắt → signal spawn thread song song với RPC đồng bộ → double-call createCampaign.
    campaign._skip_auto_sync = True
    campaign.save()

    # Đồng bộ on-chain NGAY sau khi duyệt (Admin Relayer pattern).
    _sync_campaign_to_blockchain(campaign)

# --- VIEW TRANG CHỦ ADMIN ---
@login_required(login_url='admin_panel:dangnhap')
def trangchu(request):
    user = request.user
    
    total_campaigns = 0
    total_donations_amount = 0
    total_programs = 0
    total_pending_disbursements = 0
    role = 'user' 

    if user.is_superuser:
        role = 'admin'
        total_campaigns = Campaign.objects.count()
        total_programs = TargetProgram.objects.count()
        total_donations_amount = Donation.objects.filter(status='completed').aggregate(Sum('amount'))['amount__sum'] or 0
        total_pending_disbursements = DisbursementProposal.objects.filter(status='pending').count()

    elif _get_disbursement_approver_context(user).get('approver_role') == 'supervisor':
        role = 'supervisor'
        total_campaigns = Campaign.objects.filter(status='active').count()
        total_programs = TargetProgram.objects.count()
        total_donations_amount = Donation.objects.filter(status='completed').aggregate(Sum('amount'))['amount__sum'] or 0
        total_pending_disbursements = DisbursementProposal.objects.filter(status='pending').count()

    elif Organization.objects.filter(manager=user).exists():
        role = 'partner'
        my_org = user.managed_organizations.first()
        
        if my_org:
            total_campaigns = Campaign.objects.filter(organization=my_org).count()
            total_programs = TargetProgram.objects.filter(organization=my_org).count()
            total_donations_amount = Campaign.objects.filter(organization=my_org).aggregate(Sum('current_amount'))['current_amount__sum'] or 0
    
    else:
        messages.error(request, "Bạn không có quyền truy cập trang quản trị!")
        return redirect('client:trangchu')

    context = {
        'role': role,
        'total_campaigns': total_campaigns,
        'total_programs': total_programs,
        'total_donations_amount': total_donations_amount,
        'total_pending_disbursements': total_pending_disbursements,
        'orgs_count': Organization.objects.count() if role == 'admin' else 0,
        'recent_activities': ActivityLog.objects.order_by('-created_at')[:6] if role in ['admin', 'supervisor'] else ActivityLog.objects.filter(campaign__organization__manager=user).order_by('-created_at')[:6]
    }
    return render(request, 'admin_panel/trangchu.html', context)

# --- VIEW ĐĂNG NHẬP ---
def dangnhap(request):
    if request.user.is_authenticated:
        # Supervisor → portal riêng (/admin/giamsat/giaingan/) thay vì trang chủ shared,
        # để 3rd-party thấy ngay không gian làm việc của mình khi login.
        if _get_disbursement_approver_context(request.user).get('approver_role') == 'supervisor':
            return redirect('admin_panel:giamsat_giaingan')
        if request.user.is_superuser or Organization.objects.filter(manager=request.user).exists():
            return redirect('admin_panel:trangchu')
        return redirect('client:trangchu')

    if request.method == 'POST':
        user_input = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()

        if not password:
            messages.error(request, "Vui lòng nhập mật khẩu")
            return redirect('admin_panel:dangnhap')

        user = None
        if '@' in user_input:
            try:
                user_obj = User.objects.get(email=user_input)
                user = authenticate(request, username=user_obj.username, password=password)
            except User.DoesNotExist:
                user = None
        else:
            user = authenticate(request, username=user_input, password=password)

        if user is not None:
            login(request, user)
            if _get_disbursement_approver_context(user).get('approver_role') == 'supervisor':
                return redirect('admin_panel:giamsat_giaingan')
            if user.is_superuser or Organization.objects.filter(manager=user).exists():
                return redirect('admin_panel:trangchu')
            return redirect('client:trangchu')

        messages.error(request, "Tên đăng nhập hoặc mật khẩu không đúng")

    return render(request, 'admin_panel/dangnhap.html', {
        'google_client_id': settings.GOOGLE_CLIENT_ID,
    })

def dangky(request):
    if request.user.is_authenticated:
        return redirect('client:trangchu')

    if request.method == 'POST':
        fullname = request.POST.get('fullname', '').strip()
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '').strip()
        confirm_password = request.POST.get('confirm_password', '').strip()

        if not fullname or not username or not email or not password or not confirm_password:
            messages.error(request, "Vui lòng nhập đầy đủ thông tin")
            return redirect('admin_panel:dangky')

        if len(username) < 4 or not re.match(r'^[a-zA-Z0-9_]+$', username):
            messages.error(request, "Username chỉ được chứa chữ, số và dấu _")
            return redirect('admin_panel:dangky')

        if password != confirm_password:
            messages.error(request, "Mật khẩu nhập lại không khớp")
            return redirect('admin_panel:dangky')

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username đã được sử dụng")
            return redirect('admin_panel:dangky')

        if User.objects.filter(email=email).exists():
            messages.error(request, "Email này đã được sử dụng")
            return redirect('admin_panel:dangky')

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password
        )
        user.first_name = fullname
        user.save()

        messages.success(request, "Đăng ký thành công! Vui lòng đăng nhập")
        return redirect('admin_panel:dangnhap')

    return render(request, 'admin_panel/dangky.html')

def dangxuat(request):
    logout(request)
    return redirect('client:trangchu')


@csrf_exempt
def google_callback(request):
    code = request.GET.get('code')
    if not code:
        messages.error(request, 'Không nhận được mã xác thực từ Google.')
        return redirect('admin_panel:dangnhap')

    if settings.DEBUG:
        redirect_uri = 'http://localhost:8000/accounts/google/login/callback/'
    else:
        redirect_uri = request.build_absolute_uri('/accounts/google/login/callback/')

    token_url = 'https://oauth2.googleapis.com/token'
    data = {
        'code': code,
        'client_id': settings.GOOGLE_CLIENT_ID,
        'client_secret': settings.GOOGLE_CLIENT_SECRET,
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code'
    }

    response = requests.post(token_url, data=data)
    if not response.ok:
        messages.error(request, 'Lỗi xác thực với Google. Vui lòng thử lại.')
        return redirect('admin_panel:dangnhap')

    token_data = response.json()
    access_token = token_data.get('access_token')

    user_info_url = 'https://www.googleapis.com/oauth2/v3/userinfo'
    headers = {'Authorization': f'Bearer {access_token}'}
    user_response = requests.get(user_info_url, headers=headers)

    if not user_response.ok:
        messages.error(request, 'Không lấy được thông tin từ Google.')
        return redirect('admin_panel:dangnhap')

    user_info = user_response.json()
    email = user_info.get('email')

    if not email:
        messages.error(request, 'Không tìm thấy email từ tài khoản Google.')
        return redirect('admin_panel:dangnhap')

    user, created = User.objects.get_or_create(
        email=email,
        defaults={
            'username': email.split('@')[0],
            'first_name': user_info.get('given_name', ''),
            'last_name': user_info.get('family_name', ''),
        }
    )

    login(request, user)
    messages.success(request, f'Chào mừng {user.get_full_name() or user.username}!')

    if user.is_superuser or Organization.objects.filter(manager=user).exists():
        return redirect('admin_panel:trangchu')
    return redirect('client:trangchu')

# --- QUẢN LÝ DANH MỤC ---
def quanlydanhmuc(request):
    q = _normalize_query(request.GET.get('q'))
    status = request.GET.get('status', '')
    categories = CampaignCategory.objects.all()

    if q:
        categories = categories.filter(
            Q(name__icontains=q) |
            Q(slug__icontains=q) |
            Q(description__icontains=q)
        )
    if status == 'active':
        categories = categories.filter(is_active=True)
    elif status == 'inactive':
        categories = categories.filter(is_active=False)

    categories = categories.order_by('display_order', 'name')
    export_format = _get_export_format(request)
    if export_format:
        headers = ['ID', 'Tên danh mục', 'Slug', 'Mô tả', 'Hiển thị', 'Thứ tự', 'Ngày tạo']
        rows = categories.values_list('id', 'name', 'slug', 'description', 'is_active', 'display_order', 'created_at')
        return _export_table_response('danh_muc', headers, rows, export_format)

    stats = {
        'total': CampaignCategory.objects.count(),
        'active': CampaignCategory.objects.filter(is_active=True).count(),
        'inactive': CampaignCategory.objects.filter(is_active=False).count(),
    }

    if request.method == 'POST':
        if request.POST.get('bulk_action'):
            action = request.POST.get('bulk_action')
            ids = _selected_ids(request)
            if not ids:
                messages.warning(request, "Vui lòng chọn ít nhất một dòng để thao tác.")
                return _safe_next_url(request, 'admin_panel:quanlydanhmuc')

            selected_qs = CampaignCategory.objects.filter(id__in=ids)
            if action == 'activate':
                count = selected_qs.update(is_active=True)
                messages.success(request, f"Đã hiển thị {count} danh mục.")
            elif action == 'deactivate':
                count = selected_qs.update(is_active=False)
                messages.success(request, f"Đã ẩn {count} danh mục.")
            elif action == 'delete':
                count = selected_qs.count()
                selected_qs.delete()
                messages.success(request, f"Đã xóa {count} danh mục.")
            else:
                messages.error(request, "Bulk action không hợp lệ.")
            return _safe_next_url(request, 'admin_panel:quanlydanhmuc')

        cat_id = request.POST.get('id')
        name = request.POST.get('name')
        slug = request.POST.get('slug')
        description = request.POST.get('description')
        icon_url = request.POST.get('icon_url')
        display_order = request.POST.get('display_order') or 0

        if not name or not slug:
            messages.error(request, "Tên và slug không được để trống")
            return redirect('admin_panel:quanlydanhmuc')

        if cat_id:
            category = get_object_or_404(CampaignCategory, id=cat_id)
            category.name = name
            category.slug = slug
            category.description = description
            category.icon_url = icon_url
            category.display_order = display_order
            category.save()
            messages.success(request, "Cập nhật danh mục thành công")
        else:
            if CampaignCategory.objects.filter(slug=slug).exists():
                messages.error(request, "Slug đã tồn tại")
                return redirect('admin_panel:quanlydanhmuc')

            CampaignCategory.objects.create(
                name=name,
                slug=slug,
                description=description,
                icon_url=icon_url,
                display_order=display_order
            )
            messages.success(request, "Thêm danh mục thành công")

        return redirect('admin_panel:quanlydanhmuc')

    return render(request, 'admin_panel/quanlydanhmuc.html', {
        'categories': categories,
        'role': _get_user_role(request.user),
        'query': q,
        'selected_status': status,
        'stats': stats,
        'current_url': request.get_full_path(),
        'export_csv_url': _export_links(request)[0],
        'export_excel_url': _export_links(request)[1],
    })

def toggle_category(request, id):
    category = get_object_or_404(CampaignCategory, id=id)
    category.is_active = not category.is_active
    category.save()
    return redirect('admin_panel:quanlydanhmuc')

# --- QUẢN LÝ TỔ CHỨC ---
def quanlytochuc(request):
    if not request.user.is_superuser:
        messages.error(request, "Bạn không có quyền truy cập trang Quản lý Tổ chức!")
        return redirect('admin_panel:trangchu')
    query = _normalize_query(request.GET.get('q'))
    status = request.GET.get('status', '')
    if query:
        orgs = Organization.objects.filter(
            Q(name__icontains=query) | 
            Q(contact_phone__icontains=query) |
            Q(manager__username__icontains=query) |
            Q(bank_name__icontains=query) |
            Q(bank_account_number__icontains=query)
        )
    else:
        orgs = Organization.objects.all()

    if status == 'verified':
        orgs = orgs.filter(is_verified=True)
    elif status == 'locked':
        orgs = orgs.filter(is_verified=False)

    orgs = orgs.order_by('-created_at')
    export_format = _get_export_format(request)
    if export_format:
        headers = ['ID', 'Tên tổ chức', 'Quản lý', 'Số điện thoại', 'Ngân hàng', 'Số tài khoản', 'Ví crypto', 'Đã xác thực', 'Ngày tạo']
        rows = orgs.values_list(
            'id', 'name', 'manager__username', 'contact_phone', 'bank_name', 'bank_account_number',
            'wallet_address', 'is_verified', 'created_at'
        )
        return _export_table_response('to_chuc', headers, rows, export_format)

    if request.method == 'POST' and request.POST.get('bulk_action'):
        action = request.POST.get('bulk_action')
        ids = _selected_ids(request)
        if not ids:
            messages.warning(request, "Vui lòng chọn ít nhất một tổ chức.")
            return _safe_next_url(request, 'admin_panel:quanlytochuc')

        selected_qs = Organization.objects.filter(id__in=ids)
        if action == 'verify':
            count = selected_qs.update(is_verified=True, verified_at=timezone.now())
            messages.success(request, f"Đã duyệt {count} tổ chức.")
        elif action == 'lock':
            count = selected_qs.update(is_verified=False)
            messages.success(request, f"Đã khóa {count} tổ chức.")
        elif action == 'delete':
            count = selected_qs.count()
            selected_qs.delete()
            messages.success(request, f"Đã xóa {count} tổ chức.")
        else:
            messages.error(request, "Bulk action không hợp lệ.")
        return _safe_next_url(request, 'admin_panel:quanlytochuc')

    stats = {
        'total': Organization.objects.count(),
        'verified': Organization.objects.filter(is_verified=True).count(),
        'locked': Organization.objects.filter(is_verified=False).count(),
        'with_wallet': Organization.objects.exclude(wallet_address__isnull=True).exclude(wallet_address='').count(),
    }

    return render(request, 'admin_panel/quanlytochuc.html', {
        'orgs': orgs, 
        'query': query,
        'selected_status': status,
        'role': _get_user_role(request.user),
        'stats': stats,
        'current_url': request.get_full_path(),
        'export_csv_url': _export_links(request)[0],
        'export_excel_url': _export_links(request)[1],
    })

@transaction.atomic
def them_tochuc(request):
    if request.method == 'POST':
        try:
            u_name = request.POST.get('org_username')
            u_pass = request.POST.get('org_password')

            if User.objects.filter(username=u_name).exists():
                messages.error(request, f"Tên đăng nhập '{u_name}' đã tồn tại!")
                return redirect('admin_panel:quanlytochuc')
            
            new_user = User.objects.create_user(username=u_name, password=u_pass)
            new_user.save()

            org = Organization()
            org.manager = new_user
            
            org.name = request.POST.get('name')
            org.contact_phone = request.POST.get('phone')
            org.bank_name = request.POST.get('bank_name')
            org.bank_account_number = request.POST.get('bank_account')
            org.bank_account_name = request.POST.get('account_holder')
            org.description = request.POST.get('description')
            org.wallet_address = request.POST.get('wallet_address')
            org.payos_client_id = request.POST.get('payos_client_id')
            org.payos_api_key = request.POST.get('payos_api_key')
            org.payos_checksum_key = request.POST.get('payos_checksum_key')
            org.slug = slugify(org.name) + '-' + str(int(time.time()))
            
            if 'logo' in request.FILES:
                org.logo_url = request.FILES['logo']

            org.is_verified = True
            org.save()

            messages.success(request, f"Đã thêm '{org.name}' thành công!")

        except Exception as e:
            messages.error(request, f"Lỗi hệ thống: {e}")
            
    return redirect('admin_panel:quanlytochuc')

def sua_tochuc(request, pk):
    if request.method == 'POST':
        try:
            org = get_object_or_404(Organization, pk=pk)
            org.name = request.POST.get('name')
            org.contact_phone = request.POST.get('phone')
            org.bank_name = request.POST.get('bank_name')
            org.bank_account_number = request.POST.get('bank_account')
            org.bank_account_name = request.POST.get('account_holder')
            org.description = request.POST.get('description')
            org.wallet_address = request.POST.get('wallet_address')
            org.payos_client_id = request.POST.get('payos_client_id')
            org.payos_api_key = request.POST.get('payos_api_key')
            org.payos_checksum_key = request.POST.get('payos_checksum_key')

            if 'logo' in request.FILES:
                org.logo_url = request.FILES['logo']
                
            org.save()
            messages.success(request, f"Cập nhật '{org.name}' thành công!")
        except Exception as e:
            messages.error(request, f"Lỗi: {e}")
            
    return redirect('admin_panel:quanlytochuc')

def khoa_tochuc(request, pk):
    try:
        org = get_object_or_404(Organization, pk=pk)
        org.is_verified = not org.is_verified 
        org.save()
        status_text = "MỞ KHÓA" if org.is_verified else "ĐÃ KHÓA"
        messages.warning(request, f"Đã {status_text} tổ chức: {org.name}")
    except Exception as e:
        messages.error(request, f"Lỗi: {e}")
        
    return redirect('admin_panel:quanlytochuc')

def xoa_tochuc(request, pk):
    try:
        org = get_object_or_404(Organization, pk=pk)
        name = org.name
        org.delete() 
        messages.error(request, f"Đã xóa vĩnh viễn tổ chức: {name}")
    except Exception as e:
        messages.error(request, f"Không thể xóa: {e}")
        
    return redirect('admin_panel:quanlytochuc')

# --- QUẢN LÝ CHƯƠNG TRÌNH ---
def quanlychuongtrinh(request):
    query = _normalize_query(request.GET.get('q'))
    status = request.GET.get('status', '')
    org_id = request.GET.get('org', '')
    if query:
        programs = TargetProgram.objects.filter(
            Q(name__icontains=query) |
            Q(organization__name__icontains=query) |
            Q(description__icontains=query) |
            Q(beneficiary_address__icontains=query)
        )
    else:
        programs = TargetProgram.objects.all()

    if org_id:
        programs = programs.filter(organization_id=org_id)
    if status == 'active':
        programs = programs.filter(is_active=True)
    elif status == 'inactive':
        programs = programs.filter(is_active=False)
    elif status == 'verified':
        programs = programs.filter(is_verified=True)
    elif status == 'unverified':
        programs = programs.filter(is_verified=False)

    programs = programs.order_by('-created_at')
    export_format = _get_export_format(request)
    if export_format:
        headers = ['ID', 'Tên chương trình', 'Tổ chức', 'Mục tiêu', 'Hiển thị', 'Đã duyệt', 'Địa chỉ', 'Ngày tạo']
        rows = programs.values_list(
            'id', 'name', 'organization__name', 'total_target_amount',
            'is_active', 'is_verified', 'beneficiary_address', 'created_at'
        )
        return _export_table_response('chuong_trinh', headers, rows, export_format)

    if request.method == 'POST' and request.POST.get('bulk_action'):
        action = request.POST.get('bulk_action')
        ids = _selected_ids(request)
        if not ids:
            messages.warning(request, "Vui lòng chọn ít nhất một chương trình.")
            return _safe_next_url(request, 'admin_panel:quanlychuongtrinh')

        selected_qs = TargetProgram.objects.filter(id__in=ids)
        if action == 'activate':
            count = selected_qs.update(is_active=True)
            messages.success(request, f"Đã hiển thị {count} chương trình.")
        elif action == 'deactivate':
            count = selected_qs.update(is_active=False)
            messages.success(request, f"Đã ẩn {count} chương trình.")
        elif action == 'verify':
            count = selected_qs.update(is_verified=True)
            messages.success(request, f"Đã duyệt {count} chương trình.")
        elif action == 'unverify':
            count = selected_qs.update(is_verified=False)
            messages.success(request, f"Đã bỏ duyệt {count} chương trình.")
        elif action == 'delete':
            count = selected_qs.count()
            selected_qs.delete()
            messages.success(request, f"Đã xóa {count} chương trình.")
        else:
            messages.error(request, "Bulk action không hợp lệ.")
        return _safe_next_url(request, 'admin_panel:quanlychuongtrinh')

    all_orgs = Organization.objects.filter(is_verified=True).order_by('name')
    stats = {
        'total': TargetProgram.objects.count(),
        'active': TargetProgram.objects.filter(is_active=True).count(),
        'inactive': TargetProgram.objects.filter(is_active=False).count(),
        'verified': TargetProgram.objects.filter(is_verified=True).count(),
        'total_target': TargetProgram.objects.aggregate(t=Sum('total_target_amount'))['t'] or 0,
    }

    context = {
        'programs': programs,
        'all_orgs': all_orgs,
        'query': query,
        'selected_status': status,
        'selected_org': org_id,
        'role': _get_user_role(request.user),
        'stats': stats,
        'current_url': request.get_full_path(),
        'export_csv_url': _export_links(request)[0],
        'export_excel_url': _export_links(request)[1],
    }
    return render(request, 'admin_panel/quanlychuongtrinh.html', context)

def them_chuongtrinh(request):
    if request.method == 'POST':
        try:
            prog = TargetProgram()
            org_id = request.POST.get('organization_id')
            prog.organization = Organization.objects.get(id=org_id)
            
            prog.name = request.POST.get('name')
            prog.total_target_amount = request.POST.get('total_target_amount')
            prog.description = request.POST.get('description')
            prog.beneficiary_address = request.POST.get('beneficiary_address')
            prog.beneficiary_lat = request.POST.get('beneficiary_lat') or None
            prog.beneficiary_lng = request.POST.get('beneficiary_lng') or None
            
            from django.utils.text import slugify
            import time
            prog.slug = slugify(prog.name) + '-' + str(int(time.time()))
            
            if 'image' in request.FILES:
                prog.image = request.FILES['image']
                
            prog.is_active = True
            prog.save()
            messages.success(request, f"Đã thêm chương trình: {prog.name}")
        except Exception as e:
            messages.error(request, f"Lỗi: {e}")
            
    return redirect('admin_panel:quanlychuongtrinh')

def sua_chuongtrinh(request, pk):
    if request.method == 'POST':
        try:
            prog = get_object_or_404(TargetProgram, pk=pk)
            org_id = request.POST.get('organization_id')
            prog.organization = Organization.objects.get(id=org_id)
            
            prog.name = request.POST.get('name')
            prog.total_target_amount = request.POST.get('total_target_amount')
            prog.description = request.POST.get('description')
            prog.beneficiary_address = request.POST.get('beneficiary_address')
            prog.beneficiary_lat = request.POST.get('beneficiary_lat') or None
            prog.beneficiary_lng = request.POST.get('beneficiary_lng') or None
            
            if 'image' in request.FILES:
                prog.image = request.FILES['image']
                
            prog.save()
            messages.success(request, "Cập nhật thành công!")
        except Exception as e:
            messages.error(request, f"Lỗi cập nhật: {e}")
            
    return redirect('admin_panel:quanlychuongtrinh')

def khoa_chuongtrinh(request, pk):
    try:
        prog = get_object_or_404(TargetProgram, pk=pk)
        prog.is_active = not prog.is_active
        prog.save()
        status = "Hoạt động" if prog.is_active else "Tạm ẩn"
        messages.warning(request, f"Đã chuyển trạng thái thành: {status}")
    except Exception as e:
        messages.error(request, f"Lỗi: {e}")
    return redirect('admin_panel:quanlychuongtrinh')

def xoa_chuongtrinh(request, pk):
    try:
        prog = get_object_or_404(TargetProgram, pk=pk)
        name = prog.name
        prog.delete()
        messages.error(request, f"Đã xóa vĩnh viễn: {name}")
    except Exception as e:
        messages.error(request, f"Không thể xóa: {e}")
    return redirect('admin_panel:quanlychuongtrinh')


# ========================================================
# --- QUẢN LÝ CHIẾN DỊCH ---
# ========================================================

@login_required(login_url='admin_panel:dangnhap')
def quanlychiendich(request):
    user = request.user
    q = _normalize_query(request.GET.get('q'))
    status_filter = request.GET.get('status', '')
    org_filter = request.GET.get('org', '')
    
    if user.is_superuser:
        role = 'admin'
        campaigns = Campaign.objects.select_related('organization', 'target_program', 'category', 'occasion').all()
        programs = TargetProgram.objects.all()
        orgs = Organization.objects.all()
    elif user.managed_organizations.exists():
        role = 'partner'
        my_org = user.managed_organizations.first()
        campaigns = Campaign.objects.select_related('organization', 'target_program', 'category', 'occasion').filter(organization=my_org)
        programs = TargetProgram.objects.filter(organization=my_org)
        orgs = [my_org]
    else:
        return redirect('client:trangchu')

    if q:
        campaigns = campaigns.filter(
            Q(title__icontains=q) |
            Q(short_description__icontains=q) |
            Q(full_description__icontains=q) |
            Q(organization__name__icontains=q) |
            Q(creator__username__icontains=q)
        )

    if status_filter:
        campaigns = campaigns.filter(status=status_filter)

    if user.is_superuser and org_filter:
        campaigns = campaigns.filter(organization_id=org_filter)

    if request.method == 'POST' and request.POST.get('bulk_action'):
        action = request.POST.get('bulk_action')
        ids = _selected_ids(request)
        if not ids:
            messages.warning(request, "Vui lòng chọn ít nhất một chiến dịch.")
            return _safe_next_url(request, 'admin_panel:quanlychiendich')

        selected_qs = campaigns.filter(id__in=ids)
        if action in ('approve', 'reject') and not user.is_superuser:
            messages.error(request, "Bạn không có quyền duyệt hoặc từ chối chiến dịch.")
            return _safe_next_url(request, 'admin_panel:quanlychiendich')

        if action == 'approve':
            ok = 0
            for camp in selected_qs:
                _approve_campaign_with_blockchain(camp, user)
                ok += 1
            messages.success(request, f"Đã duyệt {ok} chiến dịch.")
        elif action == 'reject':
            count = selected_qs.update(status='rejected')
            messages.success(request, f"Đã từ chối {count} chiến dịch.")
        elif action == 'hide':
            count = selected_qs.update(status='hidden')
            messages.success(request, f"Đã ẩn {count} chiến dịch.")
        elif action == 'delete':
            count = selected_qs.count()
            selected_qs.delete()
            messages.success(request, f"Đã xóa {count} chiến dịch.")
        else:
            messages.error(request, "Bulk action không hợp lệ.")
        return _safe_next_url(request, 'admin_panel:quanlychiendich')

    campaigns = campaigns.order_by('-created_at')
    export_format = _get_export_format(request)
    if export_format:
        headers = ['ID', 'Tên chiến dịch', 'Tổ chức', 'Chương trình', 'Mục tiêu', 'Đã huy động', 'Trạng thái', 'Ngày bắt đầu', 'Ngày kết thúc', 'Ngày tạo']
        rows = campaigns.values_list(
            'id', 'title', 'organization__name', 'target_program__name', 'target_amount',
            'current_amount', 'status', 'start_date', 'end_date', 'created_at'
        )
        return _export_table_response('chien_dich', headers, rows, export_format)

    categories = CampaignCategory.objects.filter(is_active=True)
    occasions = CampaignOccasion.objects.filter(is_active=True)
    stats = {
        'total': campaigns.count(),
        'active': campaigns.filter(status='active').count(),
        'pending': campaigns.filter(status='pending').count(),
        'rejected': campaigns.filter(status='rejected').count(),
        'total_raised': campaigns.aggregate(t=Sum('current_amount'))['t'] or 0,
    }

    context = {
        'campaigns': campaigns,
        'role': role,
        'programs': programs,
        'orgs': orgs,
        'categories': categories,
        'occasions': occasions,
        'query': q,
        'selected_status': status_filter,
        'selected_org': org_filter,
        'stats': stats,
        'current_url': request.get_full_path(),
        'export_csv_url': _export_links(request)[0],
        'export_excel_url': _export_links(request)[1],
    }
    return render(request, 'admin_panel/quanlychiendich.html', context)


@login_required(login_url='admin_panel:dangnhap')
def api_vietnam_provinces(request):
    try:
        data = _fetch_casso_addresskit('provinces')
        provinces = [
            {
                'code': item.get('code'),
                'name': _clean_admin_unit_name(item.get('name')),
            }
            for item in data.get('provinces', [])
        ]
        return JsonResponse({'ok': True, 'provinces': provinces})
    except requests.RequestException as exc:
        return JsonResponse({'ok': False, 'message': f'Không tải được danh sách tỉnh/thành: {exc}'}, status=502)


@login_required(login_url='admin_panel:dangnhap')
def api_vietnam_communes(request, province_code):
    try:
        data = _fetch_casso_addresskit(f'provinces/{province_code}/communes')
        communes = [
            {
                'code': item.get('code'),
                'name': _clean_admin_unit_name(item.get('name')),
            }
            for item in data.get('communes', [])
        ]
        return JsonResponse({'ok': True, 'communes': communes})
    except requests.RequestException as exc:
        return JsonResponse({'ok': False, 'message': f'Không tải được danh sách xã/phường: {exc}'}, status=502)


@login_required(login_url='admin_panel:dangnhap')
def api_openmap_reverse_geocode(request):
    lat = request.GET.get('lat')
    lng = request.GET.get('lng')
    if not lat or not lng:
        return JsonResponse({'ok': False, 'message': 'Thiếu tọa độ.'}, status=400)
    if not settings.OPENMAP_API_KEY:
        return JsonResponse({'ok': False, 'message': 'Server chưa cấu hình OPENMAP_API_KEY.'}, status=500)

    try:
        lat_value = float(lat)
        lng_value = float(lng)
    except (TypeError, ValueError):
        return JsonResponse({'ok': False, 'message': 'Tọa độ không hợp lệ.'}, status=400)

    openmap_error = ''
    try:
        response = requests.get(
            'https://mapapis.openmap.vn/v1/geocode/reverse',
            params={
                'point.lat': lat_value,
                'point.lon': lng_value,
                'size': 1,
                'boundary.circle.radius': 1,
                'admin_v2': 'true',
                'apikey': settings.OPENMAP_API_KEY,
            },
            timeout=12,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        openmap_error = str(exc)
        try:
            fallback = _reverse_geocode_with_nominatim(lat_value, lng_value)
            return JsonResponse({
                'ok': True,
                **fallback,
                'lat': lat_value,
                'lng': lng_value,
                'warning': f'OpenMap không dùng được ({openmap_error}); đã dùng Nominatim làm dự phòng.',
            })
        except requests.RequestException as fallback_exc:
            return JsonResponse({
                'ok': False,
                'message': f'Không gọi được OpenMap: {openmap_error}. Fallback Nominatim cũng lỗi: {fallback_exc}',
            }, status=502)

    feature = (payload.get('features') or [{}])[0]
    props = feature.get('properties') or {}
    label = _clean_admin_unit_name(props.get('label') or props.get('address') or '')
    province = _clean_admin_unit_name(props.get('region'))
    ward = _clean_admin_unit_name(props.get('locality'))

    detail_parts = []
    for value in (props.get('name'), props.get('short_address'), props.get('street')):
        text = _clean_admin_unit_name(value)
        if text and text not in detail_parts and text not in {province, ward}:
            detail_parts.append(text)
    detail = ', '.join(detail_parts) or label

    return JsonResponse({
        'ok': True,
        'province': province,
        'ward': ward,
        'address': detail,
        'formatted_address': label,
        'lat': lat_value,
        'lng': lng_value,
        'source': 'openmap',
    })


# ========================================================
# 🔥🔥🔥 HÀM QUAN TRỌNG: THÊM CHIẾN DỊCH + BLOCKCHAIN 🔥🔥🔥
# ========================================================
@login_required
def them_chiendich(request):
    if request.method == 'POST':
        try:
            camp = Campaign()
            camp.title = request.POST.get('title')
            camp.target_amount = request.POST.get('target_amount')
            camp.start_date = request.POST.get('start_date')
            camp.end_date = request.POST.get('end_date')
            camp.short_description = request.POST.get('short_description')
            camp.full_description = request.POST.get('full_description')
            _apply_campaign_location(camp, request.POST)
            
            cat_id = request.POST.get('category_id')
            if cat_id: camp.category_id = cat_id
            
            occ_id = request.POST.get('occasion_id')
            if occ_id: camp.occasion_id = occ_id

            prog_id = request.POST.get('program_id')
            if prog_id: camp.target_program_id = prog_id

            # Xử lý Tổ chức
            if request.user.is_superuser:
                camp.organization_id = request.POST.get('org_id')
                camp.status = 'active'
            else:
                camp.organization = request.user.managed_organizations.first()
                camp.status = 'pending'

            camp.creator = request.user

            fs = FileSystemStorage()
            if 'avatar' in request.FILES:
                file = request.FILES['avatar']
                filename = fs.save(f"campaigns/{file.name}", file)
                camp.avatar_image_url = fs.url(filename)

            if 'cover' in request.FILES:
                file = request.FILES['cover']
                filename = fs.save(f"campaigns/covers/{file.name}", file)
                camp.cover_image_url = fs.url(filename)

            # 1️⃣ LƯU VÀO DATABASE SQL
            # Tắt auto-sync signal nếu ta tự gọi sync đồng bộ ngay bên dưới
            # (tránh double-call createCampaign khi superuser tạo với status='active').
            if camp.status == 'active':
                camp._skip_auto_sync = True
            camp.save()

            # 2️⃣ NẾU SUPERUSER TẠO VỚI STATUS='active' → ĐỒNG BỘ ON-CHAIN NGAY
            # (Admin Relayer pattern — backend gọi createCampaign(cid, org_addr)).
            # Partner tạo với status='pending' thì chờ admin duyệt mới sync.
            if camp.status == 'active':
                _sync_campaign_to_blockchain(camp)
                if camp.blockchain_sync_error:
                    messages.warning(
                        request,
                        f"Chiến dịch '{camp.title}' đã lưu DB nhưng chưa đồng bộ on-chain: {camp.blockchain_sync_error[:200]}"
                    )
                else:
                    messages.success(request, f"Đã tạo chiến dịch '{camp.title}' + đồng bộ on-chain (tx={camp.blockchain_tx_hash}).")
            else:
                messages.success(request, f"Đã tạo chiến dịch '{camp.title}' thành công! (Chờ Admin duyệt để sync blockchain.)")

        except Exception as e:
            messages.error(request, f"Lỗi khi thêm: {e}")

    return redirect('admin_panel:quanlychiendich')


@login_required
def sua_chiendich(request, pk):
    if request.method == 'POST':
        try:
            camp = get_object_or_404(Campaign, pk=pk)
            
            if not request.user.is_superuser:
                my_org = request.user.managed_organizations.first()
                if camp.organization != my_org:
                    messages.error(request, "Bạn không có quyền sửa chiến dịch này!")
                    return redirect('admin_panel:quanlychiendich')

            camp.title = request.POST.get('title')
            camp.target_amount = request.POST.get('target_amount')
            camp.start_date = request.POST.get('start_date')
            camp.end_date = request.POST.get('end_date')
            camp.short_description = request.POST.get('short_description')
            camp.full_description = request.POST.get('full_description')
            _apply_campaign_location(camp, request.POST)

            camp.category_id = request.POST.get('category_id') or None
            camp.occasion_id = request.POST.get('occasion_id') or None
            camp.target_program_id = request.POST.get('program_id') or None
            
            if request.user.is_superuser:
                org_id = request.POST.get('org_id')
                if org_id: camp.organization_id = org_id

            fs = FileSystemStorage()
            if 'avatar' in request.FILES:
                file = request.FILES['avatar']
                filename = fs.save(f"campaigns/{file.name}", file)
                camp.avatar_image_url = fs.url(filename)

            if 'cover' in request.FILES:
                file = request.FILES['cover']
                filename = fs.save(f"campaigns/covers/{file.name}", file)
                camp.cover_image_url = fs.url(filename)

            camp.save()
            messages.success(request, "Đã cập nhật chiến dịch!")

        except Exception as e:
            messages.error(request, f"Lỗi cập nhật: {e}")

    return redirect('admin_panel:quanlychiendich')

@login_required
def duyet_chiendich(request, pk):
    if not request.user.is_superuser: return redirect('admin_panel:quanlychiendich')
    camp = get_object_or_404(Campaign, pk=pk)
    _approve_campaign_with_blockchain(camp, request.user)

    messages.success(request, "Đã duyệt chiến dịch!")
    return redirect('admin_panel:quanlychiendich')

@login_required
def huy_chiendich(request, pk):
    if not request.user.is_superuser: return redirect('admin_panel:quanlychiendich')
    camp = get_object_or_404(Campaign, pk=pk)
    camp.status = 'rejected'
    camp.save()
    messages.warning(request, "Đã từ chối chiến dịch!")
    return redirect('admin_panel:quanlychiendich')

@login_required
def xoa_chiendich(request, pk):
    camp = get_object_or_404(Campaign, pk=pk)
    camp.delete()
    messages.success(request, "Đã xóa chiến dịch.")
    return redirect('admin_panel:quanlychiendich')


@login_required
def nap_pool(request):
    """
    [DEPRECATED ở contract v3]
    Contract DCPManager v3 KHÔNG còn function `depositExchangePool` vì mô hình
    token đã đổi: VNDT được mint theo fiatAmount trực tiếp trong recordDonation,
    không còn ETH pool để swap.
    View này chỉ hiện thông báo, không thực hiện giao dịch nào.
    """
    if not request.user.is_superuser:
        messages.error(request, "Bạn không có quyền nạp Pool.")
        return redirect('admin_panel:quanlychiendich')
    messages.info(
        request,
        "Chức năng 'Nạp Pool ETH' đã gỡ bỏ ở contract v3. "
        "Token VNDT giờ được mint trực tiếp theo số VND donor chuyển — không cần pool swap."
    )
    return redirect('admin_panel:quanlychiendich')

# --- QUẢN LÝ QUYÊN GÓP ---
def quanly_quyengop(request):
    q = _normalize_query(request.GET.get('q'))
    status = request.GET.get('status', '')
    payment_method = request.GET.get('payment_method', '')
    created_from = request.GET.get('from', '')
    created_to = request.GET.get('to', '')

    donations = Donation.objects.select_related('campaign', 'campaign__organization').all()
    if q:
        donations = donations.filter(
            Q(donor_name__icontains=q) |
            Q(donor_email__icontains=q) |
            Q(transaction_id__icontains=q) |
            Q(campaign__title__icontains=q) |
            Q(campaign__organization__name__icontains=q)
        )
    if status:
        donations = donations.filter(status=status)
    if payment_method:
        donations = donations.filter(payment_method=payment_method)
    if created_from:
        donations = donations.filter(created_at__date__gte=created_from)
    if created_to:
        donations = donations.filter(created_at__date__lte=created_to)

    if request.method == 'POST' and request.POST.get('bulk_action'):
        action = request.POST.get('bulk_action')
        ids = _selected_ids(request)
        if not ids:
            messages.warning(request, "Vui lòng chọn ít nhất một giao dịch.")
            return _safe_next_url(request, 'admin_panel:quanly_quyengop')

        selected_qs = donations.filter(id__in=ids)
        if action == 'completed':
            count = selected_qs.update(status='completed')
            messages.success(request, f"Đã duyệt {count} giao dịch.")
        elif action == 'pending':
            count = selected_qs.update(status='pending')
            messages.success(request, f"Đã chuyển {count} giao dịch về chờ xử lý.")
        elif action == 'failed':
            count = selected_qs.update(status='failed')
            messages.success(request, f"Đã đánh dấu thất bại {count} giao dịch.")
        elif action == 'refunded':
            count = selected_qs.update(status='refunded')
            messages.success(request, f"Đã đánh dấu hoàn tiền {count} giao dịch.")
        elif action == 'delete':
            count = selected_qs.count()
            selected_qs.delete()
            messages.success(request, f"Đã xóa {count} giao dịch.")
        else:
            messages.error(request, "Bulk action không hợp lệ.")
        return _safe_next_url(request, 'admin_panel:quanly_quyengop')

    donations = donations.order_by('-created_at')
    export_format = _get_export_format(request)
    if export_format:
        headers = ['ID', 'Người ủng hộ', 'Email', 'Số tiền', 'Chiến dịch', 'Tổ chức', 'Phương thức', 'Trạng thái', 'Mã giao dịch', 'Ngày tạo']
        rows = donations.values_list(
            'id', 'donor_name', 'donor_email', 'amount',
            'campaign__title', 'campaign__organization__name', 'payment_method',
            'status', 'transaction_id', 'created_at'
        )
        return _export_table_response('quyen_gop', headers, rows, export_format)

    stats = {
        'total': donations.count(),
        'completed': donations.filter(status='completed').count(),
        'pending': donations.filter(status='pending').count(),
        'failed': donations.filter(status='failed').count(),
        'refunded': donations.filter(status='refunded').count(),
        'amount_total': donations.filter(status='completed').aggregate(t=Sum('amount'))['t'] or 0,
    }
    return render(request, 'admin_panel/quanly_quyengop.html', {
        'donations': donations,
        'role': _get_user_role(request.user),
        'query': q,
        'selected_status': status,
        'selected_payment_method': payment_method,
        'created_from': created_from,
        'created_to': created_to,
        'stats': stats,
        'current_url': request.get_full_path(),
        'export_csv_url': _export_links(request)[0],
        'export_excel_url': _export_links(request)[1],
    })

def sua_quyengop(request, pk):
    donation = get_object_or_404(Donation, pk=pk)
    
    if request.method == 'POST':
        form = DonationForm(request.POST, instance=donation)
        if form.is_valid():
            form.save()
            messages.success(request, f"Đã cập nhật giao dịch #{donation.id}. Hãy ra Client kiểm tra Hash!")
            return redirect('admin_panel:quanly_quyengop')
    else:
        form = DonationForm(instance=donation)

    return render(request, 'admin_panel/sua_quyengop.html', {
        'form': form,
        'donation': donation,
        'role': _get_user_role(request.user),
    })


# ========================================================
# QUẢN LÝ GIẢI NGÂN
# ========================================================


# =============================================================
# [V3] PUBLIC return/cancel pages cho PayOS Checkout (payout)
# -------------------------------------------------------------
# PayOS trả user về `returnUrl` / `cancelUrl` sau khi thanh toán.
# Các URL này PHẢI PUBLIC (không @login_required) vì:
#   1. PayOS success page có thể prefetch/validate URL — nếu URL trả
#      302 redirect về login → PayOS Next.js page crash
#      ("Application error: a server-side exception has occurred").
#   2. User thanh toán xong có thể session admin đã expired.
# -------------------------------------------------------------
# KHỚP 1:1 với pattern `client:payos_return` / `client:payos_cancel`
# của luồng donation (đang chạy ổn định).
# =============================================================
def v3_payout_return(request, pk):
    """Trang public PayOS redirect về sau khi admin thanh toán xong."""
    proposal = get_object_or_404(
        DisbursementProposal.objects.select_related('campaign', 'campaign__organization'),
        pk=pk,
    )
    status = (request.GET.get('status') or '').upper()
    is_cancelled = (request.GET.get('cancel') or '').lower() == 'true'
    order_code = request.GET.get('orderCode')
    if is_cancelled or status == 'CANCELLED':
        return render(request, 'client/payment_failed.html', {
            'message': f'Đã huỷ thanh toán PayOS cho đề xuất giải ngân #{proposal.id}.',
        })
    org = proposal.campaign.organization
    proposal_view = SimpleNamespace(
        id=proposal.id,
        donor_name=(proposal.recipient_name or (org.name if org else 'Quỹ tổ chức')),
        campaign=proposal.campaign,
        amount=proposal.amount_requested,
        created_at=proposal.created_at,
    )
    return render(request, 'client/payment_success.html', {
        'donation': proposal_view,
        'payment_provider': 'PayOS',
        'payment_status': status or 'PAID',
        'show_blockchain_status': False,
        'message': (
            f'Đã ghi nhận thanh toán giải ngân #{proposal.id}. '
            'Hệ thống sẽ xác nhận chính thức khi PayOS webhook hợp lệ.'
        ),
        'payos_order_code': order_code or '',
    })


def v3_payout_cancel(request, pk):
    """Trang public PayOS redirect về khi user huỷ thanh toán."""
    proposal = get_object_or_404(DisbursementProposal, pk=pk)
    return render(request, 'client/payment_failed.html', {
        'message': f'Bạn đã huỷ thanh toán PayOS cho đề xuất giải ngân #{proposal.id}.',
    })


@login_required(login_url='admin_panel:dangnhap')
def quanly_giaingan(request):
    user = request.user
    # Only allow specific params for filtering to avoid PayOS redirect params interference
    allowed_params = {
        'q': request.GET.get('q', ''),
        'status': request.GET.get('status', '') if request.GET.get('status', '') in [choice[0] for choice in DisbursementProposal.V3_STATUS_CHOICES] else '',
        'campaign': request.GET.get('campaign', ''),
    }
    q = _normalize_query(allowed_params['q'])
    approver_context = _get_disbursement_approver_context(user)

    # Handle PayOS redirect messages (ignore for filtering)
    payos_status = request.GET.get('status', '').upper()
    if payos_status == 'PAID':
        messages.success(request, "Thanh toán PayOS thành công! Hệ thống sẽ xử lý tiếp khi nhận webhook.")
    elif payos_status == 'CANCELLED':
        messages.warning(request, "Đã huỷ thanh toán PayOS.")

    if user.is_superuser:
        role = 'admin'
        proposals_qs = DisbursementProposal.objects.select_related(
            'campaign', 'campaign__organization', 'created_by', 'approved_by'
        ).prefetch_related('offchain_signatures').all()
        campaigns = Campaign.objects.filter(status='active')
    elif approver_context['approver_role'] == 'supervisor':
        role = 'supervisor'
        proposals_qs = DisbursementProposal.objects.select_related(
            'campaign', 'campaign__organization', 'created_by', 'approved_by'
        ).prefetch_related('offchain_signatures').all()
        campaigns = Campaign.objects.none()
    elif user.managed_organizations.exists():
        role = 'partner'
        my_org = user.managed_organizations.first()
        proposals_qs = DisbursementProposal.objects.select_related(
            'campaign', 'campaign__organization', 'created_by', 'approved_by'
        ).prefetch_related('offchain_signatures').filter(campaign__organization=my_org)
        campaigns = Campaign.objects.filter(organization=my_org, status='active')
    else:
        return redirect('client:trangchu')

    # ========================================================
    # V3 MATH — available_amount = current_amount - sum(in-flight V3 proposals).
    # In-flight = mọi proposal CHƯA bị reject / payout_failed (tức đang giữ chỗ
    # trong quỹ, bao gồm cả completed_audited vì tiền đã chuyển khỏi quỹ).
    # Không còn trừ gas/locked như V2 vì Admin trả gas silent ngoài quỹ và
    # không còn cơ chế voting-lock nữa.
    # ========================================================
    V3_IN_FLIGHT_STATUSES = (
        'v3_not_started',      # default cho proposal mới nhưng chưa sign — vẫn giữ chỗ
        'pending_multisig',
        'ready_to_payout',
        'payout_processing',
        'fiat_transferred',
        'completed_audited',
    )
    # 1 query duy nhất: gom SUM(amount_requested) theo campaign_id cho mọi proposal
    # chưa rejected/failed. Tránh N+1 khi picker có nhiều campaign.
    in_flight_map = {
        row['campaign_id']: (row['total'] or Decimal('0'))
        for row in DisbursementProposal.objects
            .exclude(status='rejected')
            .exclude(v3_status='payout_failed')
            .filter(v3_status__in=V3_IN_FLIGHT_STATUSES)
            .values('campaign_id')
            .annotate(total=Sum('amount_requested'))
    }

    campaigns_with_available = []
    for c in campaigns:
        in_flight_amount = in_flight_map.get(c.id, Decimal('0'))
        raw_available = (c.current_amount or Decimal('0')) - in_flight_amount
        available_amount = _round_vnd(max(Decimal('0'), raw_available))
        campaigns_with_available.append({
            'obj': c,
            'in_flight_amount': _round_vnd(in_flight_amount),
            'available_amount': available_amount,
        })

    campaign_filter = allowed_params['campaign']
    status_filter = allowed_params['status']
    if campaign_filter:
        proposals_qs = proposals_qs.filter(campaign_id=campaign_filter)
    if q:
        proposals_qs = proposals_qs.filter(
            Q(title__icontains=q) |
            Q(purpose__icontains=q) |
            Q(recipient_name__icontains=q) |
            Q(campaign__title__icontains=q) |
            Q(campaign__organization__name__icontains=q)
        )
    if status_filter:
        # V3: filter theo v3_status. Gộp 2 state gần nghĩa để UI đỡ rối.
        if status_filter == 'pending_multisig':
            proposals_qs = proposals_qs.filter(
                v3_status__in=('v3_not_started', 'pending_multisig'))
        elif status_filter == 'fiat_transferred':
            proposals_qs = proposals_qs.filter(
                v3_status__in=('payout_processing', 'fiat_transferred'))
        else:
            proposals_qs = proposals_qs.filter(v3_status=status_filter)

    if request.method == 'POST' and request.POST.get('bulk_action'):
        action = request.POST.get('bulk_action')
        ids = _selected_ids(request)
        if not ids:
            messages.warning(request, "Vui lòng chọn ít nhất một đề xuất.")
            return _safe_next_url(request, 'admin_panel:quanly_giaingan')

        selected_qs = proposals_qs.filter(id__in=ids).select_related('campaign')
        if action == 'approve':
            if not user.is_superuser:
                messages.error(request, "Bạn không có quyền duyệt đề xuất.")
                return _safe_next_url(request, 'admin_panel:quanly_giaingan')
            voting_days = int(request.POST.get('bulk_voting_days') or 7)
            approved_count = 0
            for proposal in selected_qs:
                if proposal.status != 'pending':
                    continue
                proposal.status = 'voting'
                proposal.approved_by = request.user
                proposal.approved_at = timezone.now()
                proposal.voting_days = voting_days
                proposal.end_date = timezone.now() + timedelta(days=voting_days)
                proposal.save(update_fields=['status', 'approved_by', 'approved_at', 'voting_days', 'end_date'])

                campaign = proposal.campaign
                campaign.locked_amount += proposal.amount_requested
                campaign.save(update_fields=['locked_amount'])
                approved_count += 1
            messages.success(request, f"Đã duyệt {approved_count} đề xuất và mở bỏ phiếu.")
        elif action == 'reject':
            rejected_count = 0
            for proposal in selected_qs:
                if proposal.status not in ('pending', 'voting'):
                    continue
                if proposal.status == 'voting':
                    campaign = proposal.campaign
                    campaign.locked_amount = max(Decimal('0'), campaign.locked_amount - proposal.amount_requested)
                    campaign.save(update_fields=['locked_amount'])
                proposal.status = 'rejected'
                proposal.save(update_fields=['status'])
                rejected_count += 1
            messages.success(request, f"Đã từ chối {rejected_count} đề xuất.")
        elif action == 'delete':
            count = selected_qs.count()
            selected_qs.delete()
            messages.success(request, f"Đã xóa {count} đề xuất.")
        else:
            messages.error(request, "Bulk action không hợp lệ.")
        return _safe_next_url(request, 'admin_panel:quanly_giaingan')

    proposals_qs = proposals_qs.order_by('-created_at')
    export_format = _get_export_format(request)
    if export_format:
        headers = ['ID', 'Chiến dịch', 'Tiêu đề', 'Số tiền yêu cầu', 'Mục đích', 'Đơn vị thụ hưởng', 'Trạng thái', 'Người tạo', 'Ngày tạo']
        rows = proposals_qs.values_list(
            'id', 'campaign__title', 'title', 'amount_requested', 'purpose',
            'recipient_name', 'status', 'created_by__username', 'created_at'
        )
        return _export_table_response('giai_ngan', headers, rows, export_format)

    # ========================================================
    # V3 Row metadata: signature progress + role-eligibility per proposal.
    # Organization: chỉ được ký proposal thuộc campaign của org mình.
    # Supervisor / Admin: ký được mọi proposal.
    # ========================================================
    current_wallet = (approver_context.get('current_wallet') or '').lower()
    my_org_id = None
    if not user.is_superuser:
        _my_org = user.managed_organizations.first() if user.is_authenticated else None
        my_org_id = _my_org.id if _my_org else None

    proposals_data = []
    for p in proposals_qs:
        sigs_by_role = {s.role: s for s in p.offchain_signatures.all()}
        sig_count = len(sigs_by_role)
        sig_roles_have = sorted(sigs_by_role.keys())

        # Determine the V3 role user can sign for on THIS proposal.
        can_sign_as = None
        if role == 'admin':
            can_sign_as = 'admin'
        elif role == 'supervisor':
            can_sign_as = 'supervisor'
        elif role == 'partner' and my_org_id and p.campaign.organization_id == my_org_id:
            # Org manager of the campaign's org — sign as organization.
            can_sign_as = 'organization'

        already_signed = can_sign_as is not None and can_sign_as in sigs_by_role
        # Only show sign button in pre-relay phases.
        can_sign = (
            can_sign_as is not None
            and not already_signed
            and p.v3_status in ('v3_not_started', 'pending_multisig')
            and bool(p.ipfs_cid)
        )
        relay_pending = (p.payout_error or '').startswith('multisig relay pending:')
        # Admin relay button visible only when 3 sigs collected and not yet relayed.
        can_relay_multisig = (
            role == 'admin'
            and sig_count >= 3
            and not p.multisig_confirmed_tx_hash
            and not relay_pending
            and p.v3_status in ('pending_multisig', 'ready_to_payout')
        )
        # Admin payout trigger when ready_to_payout.
        can_trigger_payout = (
            role == 'admin' and p.v3_status == 'ready_to_payout'
            and bool(p.multisig_confirmed_tx_hash)
        )

        item = {
            'obj': p,
            'sig_count': sig_count,
            'sig_roles_have': sig_roles_have,
            'has_org_sig': 'organization' in sigs_by_role,
            'has_supervisor_sig': 'supervisor' in sigs_by_role,
            'has_admin_sig': 'admin' in sigs_by_role,
            'can_sign': can_sign,
            'can_sign_as': can_sign_as,
            'already_signed': already_signed,
            'relay_pending': relay_pending,
            'can_relay_multisig': can_relay_multisig,
            'can_trigger_payout': can_trigger_payout,
            'can_reject': (role == 'admin' and p.v3_status in ('v3_not_started', 'pending_multisig')),
        }

        # =============================================================
        # [V3 LUONG MOI - PayOS PAYOUT API]
        # KHONG tao PayOS Checkout Link nua - do la luong CU (donor quet
        # QR thanh toan). Luong giai ngan V3 dung PayOS PAYOUT API
        # (chuyen fiat tu dong tu escrow Kenh Chi -> bank Org), duoc trigger
        # qua nut "Thuc thi PayOS" -> endpoint v3_trigger_payos_payout ->
        # PayosPayoutService.create_payout(). Khong co buoc scan QR thu cong.
        # =============================================================

        proposals_data.append(item)

    has_live_v3_pending = any(
        item['relay_pending']
        or item['obj'].v3_status in ('payout_processing', 'fiat_transferred')
        for item in proposals_data
    )

    # V3 stats dashboard (count by v3_status, not legacy status).
    stats = {
        'pending_multisig': proposals_qs.filter(
            v3_status__in=('v3_not_started', 'pending_multisig')
        ).count(),
        'ready_to_payout': proposals_qs.filter(v3_status='ready_to_payout').count(),
        'fiat_transferred': proposals_qs.filter(
            v3_status__in=('payout_processing', 'fiat_transferred')
        ).count(),
        'completed_audited': proposals_qs.filter(v3_status='completed_audited').count(),
        'payout_failed': proposals_qs.filter(v3_status='payout_failed').count(),
        'total_disbursed': proposals_qs.filter(v3_status='completed_audited').aggregate(
            t=Sum('amount_requested'))['t'] or 0,
        'total_requested': proposals_qs.aggregate(t=Sum('amount_requested'))['t'] or 0,
    }

    context = {
        'proposals': proposals_data,
        'campaigns': campaigns,
        'campaigns_available': campaigns_with_available,
        'role': role,
        'selected_campaign': campaign_filter,
        'selected_status': status_filter,
        'query': q,
        'stats': stats,
        'current_url': request.get_full_path(),
        'export_csv_url': _export_links(request)[0],
        'export_excel_url': _export_links(request)[1],
        'approver_context': approver_context,
        'disbursement_web3_config': _build_disbursement_web3_config(request),
        'has_live_v3_pending': has_live_v3_pending,
    }
    return render(request, 'admin_panel/quanly_giaingan.html', context)


# ============================================================
# [V3] CỔNG THÔNG TIN DÀNH RIÊNG CHO GIÁM SÁT VIÊN (3rd PARTY)
# ------------------------------------------------------------
# Khác biệt so với `quanly_giaingan` (admin + partner + supervisor share):
#   - Hard-restricted: chỉ user có ví khớp `supervisorWallet()` on-chain
#     mới vào được. Admin bị block (có portal riêng), partner bị block.
#   - Read-only UI: KHÔNG có "Tạo yêu cầu giải ngân", KHÔNG có "Relay
#     multisig" hay "Thực thi PayOS" (đã là đặc quyền admin).
#   - Focused queryset: chia proposals thành "cần tôi ký" (uưu tiên) và
#     "đã ký / đã qua" để giám sát viên tập trung vào task ngần nhất.
#   - Cảnh báo khi profile.wallet_address bỏ trống (supervisor không
#     verify được sig nếu không có địa chỉ ví lên DB).
# ============================================================
@login_required(login_url='admin_panel:dangnhap')
def giamsat_giaingan(request):
    user = request.user
    approver_context = _get_disbursement_approver_context(user)
    if approver_context.get('approver_role') != 'supervisor':
        messages.error(
            request,
            "Trang này chỉ dành cho Giám sát viên. Ví đăng nhập của bạn không khớp "
            "với supervisorWallet on-chain.",
        )
        return redirect('admin_panel:trangchu')

    # ------------------------------------------------------------------
    # 1. Supervisor wallet sanity: cảnh báo nếu profile thiếu wallet_address.
    # Supervisor verify sig bằng `recover_eip712_signer()` → cần ví trong DB
    # để FE auto-fill tài khoản MetaMask nên dialog ký khứng.
    # ------------------------------------------------------------------
    wallet_configured = bool(
        hasattr(user, 'profile') and (
            (user.profile.smart_account_address or '').strip()
            or (user.profile.wallet_address or '').strip()
            or (user.profile.eoa_address or '').strip()
        )
    )

    q = _normalize_query(request.GET.get('q'))
    # Supervisor thấy mọi proposal (third-party audit scope là global),
    # không filter theo organization nào cả.
    proposals_qs = (
        DisbursementProposal.objects
        .select_related('campaign', 'campaign__organization', 'created_by')
        .prefetch_related('offchain_signatures')
        .all()
    )
    if q:
        proposals_qs = proposals_qs.filter(
            Q(title__icontains=q)
            | Q(purpose__icontains=q)
            | Q(recipient_name__icontains=q)
            | Q(campaign__title__icontains=q)
            | Q(campaign__organization__name__icontains=q)
        )

    # Supervisor chỉ quan tâm pre-payout phases — sau khi đủ 3 sig + relay
    # lên chain, trach nhiệm chuyển sang admin. Default filter = all V3 state
    # để supervisor vẫn audit được lịch sử; có tab "Cần tôi ký" ở FE.
    status_filter = request.GET.get('status', '')
    if status_filter == 'pending_multisig':
        proposals_qs = proposals_qs.filter(
            v3_status__in=('v3_not_started', 'pending_multisig')
        )
    elif status_filter == 'needs_me':
        # Pseudo-filter: pending multisig AND supervisor chưa ký. `.exclude()`
        # qua reverse relation sinh NOT EXISTS subquery trong Django. Thêm
        # `.distinct()` defensively để tránh JOIN duplication edge case.
        proposals_qs = proposals_qs.filter(
            v3_status__in=('v3_not_started', 'pending_multisig'),
        ).exclude(offchain_signatures__role='supervisor').distinct()
    elif status_filter:
        proposals_qs = proposals_qs.filter(v3_status=status_filter)

    proposals_qs = proposals_qs.order_by('-created_at')

    # Pagination: supervisor thấy mọi proposal from all orgs → cần cap để tránh
    # render 500+ card DOM. Stats vẫn tính trên FULL queryset (chưa slice).
    from django.core.paginator import Paginator
    full_qs = proposals_qs  # giữ reference cho stats dưới.
    paginator = Paginator(proposals_qs, 20)
    page_number = request.GET.get('page') or 1
    page_obj = paginator.get_page(page_number)

    # ------------------------------------------------------------------
    # 2. Per-row metadata — giữ cutting surface vừa đủ cho supervisor:
    #   * sig_count / has_*_sig — hiển thị progress x/3.
    #   * can_sign / already_signed — control nút "Ký duyệt".
    #   * is_waiting_me — ưu tiên tô sáng nếu proposal đang chờ ký.
    # ------------------------------------------------------------------
    proposals_data = []
    for p in page_obj.object_list:
        sigs_by_role = {s.role: s for s in p.offchain_signatures.all()}
        sig_count = len(sigs_by_role)
        already_signed = 'supervisor' in sigs_by_role
        is_pre_relay = p.v3_status in ('v3_not_started', 'pending_multisig')
        can_sign = is_pre_relay and not already_signed and bool(p.ipfs_cid)
        is_waiting_me = can_sign  # UI accent
        proposals_data.append({
            'obj': p,
            'sig_count': sig_count,
            'has_org_sig': 'organization' in sigs_by_role,
            'has_supervisor_sig': 'supervisor' in sigs_by_role,
            'has_admin_sig': 'admin' in sigs_by_role,
            'can_sign': can_sign,
            'already_signed': already_signed,
            'is_waiting_me': is_waiting_me,
        })

    # Stats: tính trên FULL queryset (full_qs) chứ không phải page. Khắc phục
    # việc vars needs_me_count/already_signed_count vừa loop chỉ tính page hiện tại.
    needs_me_total = full_qs.filter(
        v3_status__in=('v3_not_started', 'pending_multisig'),
    ).exclude(offchain_signatures__role='supervisor').distinct().count()
    already_signed_total = full_qs.filter(offchain_signatures__role='supervisor').distinct().count()
    stats = {
        'needs_me': needs_me_total,
        'already_signed': already_signed_total,
        'completed_audited': full_qs.filter(v3_status='completed_audited').count(),
        'total_requested': full_qs.aggregate(t=Sum('amount_requested'))['t'] or 0,
    }

    context = {
        'proposals': proposals_data,
        'page_obj': page_obj,
        'paginator': paginator,
        'role': 'supervisor',
        'stats': stats,
        'query': q,
        'selected_status': status_filter,
        'wallet_configured': wallet_configured,
        'approver_context': approver_context,
        'disbursement_web3_config': _build_disbursement_web3_config(request),
        'current_url': request.get_full_path(),
    }
    return render(request, 'admin_panel/giamsat_giaingan.html', context)


@login_required
def ipfs_upload_view(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'message': 'Method not allowed.'}, status=405)

    campaign_id = request.POST.get('campaign_id')
    if not campaign_id:
        return JsonResponse({'ok': False, 'message': 'Thiếu campaign_id.'}, status=400)

    campaign = get_object_or_404(Campaign, pk=campaign_id)
    if not _can_manage_campaign_disbursement(request.user, campaign):
        return JsonResponse({'ok': False, 'message': 'Bạn không có quyền upload hóa đơn cho chiến dịch này.'}, status=403)

    invoice_file = request.FILES.get('invoice_file')
    if not invoice_file:
        return JsonResponse({'ok': False, 'message': 'Vui lòng chọn hóa đơn/chứng từ để upload.'}, status=400)

    if not settings.PINATA_API_KEY or not settings.PINATA_API_SECRET:
        return JsonResponse({'ok': False, 'message': 'Thiếu cấu hình Pinata trong server.'}, status=500)

    try:
        response = requests.post(
            'https://api.pinata.cloud/pinning/pinFileToIPFS',
            headers={
                'pinata_api_key': settings.PINATA_API_KEY,
                'pinata_secret_api_key': settings.PINATA_API_SECRET,
            },
            files={
                'file': (invoice_file.name, invoice_file, invoice_file.content_type or 'application/octet-stream'),
            },
            data={
                'pinataMetadata': (
                    '{"name":"%s","keyvalues":{"campaignId":"%s","uploadedBy":"%s"}}'
                    % (invoice_file.name, campaign.id, request.user.id)
                ),
            },
            timeout=60,
        )
    except requests.RequestException as exc:
        return JsonResponse({'ok': False, 'message': f'Không thể kết nối Pinata: {exc}'}, status=502)

    if response.status_code >= 400:
        try:
            error_payload = response.json()
        except ValueError:
            error_payload = {'error': response.text[:200]}
        return JsonResponse(
            {
                'ok': False,
                'message': 'Pinata từ chối upload.',
                'details': error_payload,
            },
            status=502,
        )

    payload = response.json()
    cid = payload.get('IpfsHash')
    if not cid:
        return JsonResponse({'ok': False, 'message': 'Pinata không trả về CID.'}, status=502)

    return JsonResponse(
        {
            'ok': True,
            'cid': cid,
            'gateway_url': f'https://gateway.pinata.cloud/ipfs/{cid}',
            'file_name': invoice_file.name,
            'pin_size': payload.get('PinSize'),
            'timestamp': payload.get('Timestamp'),
        }
    )


@login_required
@csrf_exempt
def sync_disbursement_approval(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'message': 'Method not allowed.'}, status=405)

    approver_context = _get_disbursement_approver_context(request.user)
    approver_role = approver_context.get('approver_role')
    if approver_role not in ('admin', 'supervisor'):
        return JsonResponse({'ok': False, 'message': 'Bạn không có quyền đồng bộ chữ ký duyệt.'}, status=403)

    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'message': 'Payload JSON không hợp lệ.'}, status=400)

    proposal_id = payload.get('proposal_id')
    tx_hash = (payload.get('tx_hash') or '').strip()
    if not proposal_id or not tx_hash:
        return JsonResponse({'ok': False, 'message': 'Thiếu proposal_id hoặc tx_hash.'}, status=400)

    proposal = get_object_or_404(DisbursementProposal.objects.select_related('campaign'), pk=proposal_id)
    if proposal.status not in ('pending', 'approved'):
        return JsonResponse({'ok': False, 'message': 'Đề xuất này không còn ở trạng thái chờ duyệt.'}, status=409)

    try:
        bc = BlockchainService()
        campaign_meta = bc.get_campaign_disbursement_meta(proposal.campaign_id)
    except Exception as exc:
        return JsonResponse({'ok': False, 'message': f'Không đọc được trạng thái on-chain: {exc}'}, status=502)

    if proposal.ipfs_cid and campaign_meta.get('ipfs_cid') and proposal.ipfs_cid != campaign_meta['ipfs_cid']:
        return JsonResponse({'ok': False, 'message': 'CID on-chain không khớp với proposal đang duyệt.'}, status=409)

    now = timezone.now()
    updated_fields = ['approval_count', 'last_approval_synced_at', 'status']
    proposal.approval_count = max(int(proposal.approval_count or 0), int(campaign_meta.get('approvals', 0)))
    proposal.last_approval_synced_at = now
    if approver_role == 'supervisor':
        proposal.supervisor_approved_at = proposal.supervisor_approved_at or now
        proposal.supervisor_approval_tx_hash = proposal.supervisor_approval_tx_hash or tx_hash
        updated_fields.extend(['supervisor_approved_at', 'supervisor_approval_tx_hash'])
    else:
        proposal.admin_approved_at = proposal.admin_approved_at or now
        proposal.admin_approval_tx_hash = proposal.admin_approval_tx_hash or tx_hash
        proposal.approved_by = request.user
        proposal.approved_at = proposal.approved_at or now
        updated_fields.extend(['admin_approved_at', 'admin_approval_tx_hash', 'approved_by', 'approved_at'])

    proposal.status = 'approved' if proposal.approval_count >= 2 else 'pending'
    proposal.save(update_fields=list(dict.fromkeys(updated_fields)))

    ActivityLog.objects.create(
        user=request.user,
        type='disbursement_approval_synced',
        description=f'Đồng bộ chữ ký {approver_role} cho proposal #{proposal.id}. approvals={proposal.approval_count}, tx={tx_hash}',
        campaign=proposal.campaign,
    )

    return JsonResponse(
        {
            'ok': True,
            'proposal_id': proposal.id,
            'proposal_status': proposal.status,
            'approval_count': proposal.approval_count,
            'approver_role': approver_role,
            'tx_hash': tx_hash,
            'supervisor_approved': bool(proposal.supervisor_approval_tx_hash),
            'admin_approved': bool(proposal.admin_approval_tx_hash),
        }
    )


@login_required
def sync_disbursement_onchain(request, pk):
    if not request.user.is_superuser:
        messages.error(request, "Bạn không có quyền đồng bộ giải ngân on-chain.")
        return redirect('admin_panel:quanly_giaingan')

    proposal = get_object_or_404(
        DisbursementProposal.objects.select_related('campaign', 'campaign__organization'),
        pk=pk,
    )

    try:
        result = sync_disbursement_proposal_status(proposal)
    except Exception as exc:
        messages.error(request, f"Lỗi đồng bộ sự kiện DisbursedAndBurned: {exc}")
        return redirect('admin_panel:quanly_giaingan')

    if result.get('synced'):
        if result.get('already_synced'):
            messages.info(request, f"Đề xuất đã được sync trước đó. Tx: {result['tx_hash']}")
        else:
            messages.success(
                request,
                f"Đã xác nhận DisbursedAndBurned và trigger mock bank transfer. Tx: {result['tx_hash']}",
            )
    else:
        messages.warning(request, result.get('message') or 'Chưa tìm thấy sự kiện giải ngân trong các block gần đây.')

    return redirect('admin_panel:quanly_giaingan')


@login_required
def tao_yeucau_giaingan(request):
    if request.method == 'POST':
        try:
            campaign_id = (request.POST.get('campaign_id') or '').strip()
            # Guard fail-fast: nếu UI quên sync hidden input thì backend trả
            # message rõ ràng thay vì để Django raise ValueError thô
            # ("Field 'id' expected a number but got ''.").
            if not campaign_id or not campaign_id.isdigit():
                messages.error(request, "Vui lòng chọn một chiến dịch trước khi gửi yêu cầu.")
                return redirect('admin_panel:quanly_giaingan')
            campaign = get_object_or_404(Campaign, pk=int(campaign_id))

            if not _can_manage_campaign_disbursement(request.user, campaign):
                messages.error(request, "Bạn không có quyền tạo yêu cầu giải ngân cho chiến dịch này!")
                return redirect('admin_panel:quanly_giaingan')

            amount_raw = (request.POST.get('amount_requested', '0') or '0').replace(',', '')
            amount = _round_vnd(Decimal(amount_raw))

            # V3 MATH: available = current_amount - sum(amount_requested for in-flight V3 proposals).
            # Khớp với logic của campaigns_with_available ở trang danh sách.
            V3_IN_FLIGHT_STATUSES = (
                'v3_not_started', 'pending_multisig', 'ready_to_payout',
                'payout_processing', 'fiat_transferred', 'completed_audited',
            )
            in_flight_sum = DisbursementProposal.objects.filter(
                campaign=campaign,
                v3_status__in=V3_IN_FLIGHT_STATUSES,
            ).exclude(status='rejected').exclude(v3_status='payout_failed').aggregate(
                t=Sum('amount_requested'))['t'] or Decimal('0')
            available = _round_vnd(max(Decimal('0'), (campaign.current_amount or Decimal('0')) - in_flight_sum))

            if amount > available:
                messages.error(request,
                               f"Số tiền vượt quá số dư khả dụng ({int(available):,}đ). "
                               f"(Đã trừ {int(in_flight_sum):,}đ đang ở các đề xuất V3 chưa hoàn tất.)")
                return redirect('admin_panel:quanly_giaingan')

            proposal = DisbursementProposal()
            proposal.campaign = campaign
            proposal.title = request.POST.get('title')
            proposal.amount_requested = amount
            proposal.purpose = request.POST.get('purpose')
            proposal.description = request.POST.get('description')
            proposal.recipient_name = request.POST.get('recipient_name')
            # V3: Phase 1 là OFF-CHAIN thuần. KHÔNG còn yêu cầu eth_tx_hash /
            # gasless propose on-chain — smart3 chỉ ghi nhận khi đủ 3 sig EIP-712
            # ở Phase 3a (relay multisig). IPFS CID vẫn yêu cầu vì là minh chứng
            # bắt buộc được hash vào typed-data của chữ ký.
            proposal.ipfs_cid = (request.POST.get('ipfs_cid') or '').strip() or None
            if not proposal.ipfs_cid:
                messages.error(request, "Thiếu IPFS CID. Vui lòng upload lại hóa đơn / chứng từ.")
                return redirect('admin_panel:quanly_giaingan')
            proposal.evidence_url = request.POST.get('evidence_url', '')
            ipfs_gateway_url = (request.POST.get('ipfs_gateway_url') or '').strip()
            if proposal.ipfs_cid and not proposal.evidence_url and ipfs_gateway_url:
                proposal.evidence_url = ipfs_gateway_url
            proposal.created_by = request.user
            proposal.status = 'pending'
            # V3: đẩy thẳng vào trạng thái chờ ký multisig — bỏ qua luồng V2
            # 'voting'/'approved'. Dashboard sẽ hiển thị nút "Ký duyệt" cho
            # 3 approver ngay lập tức.
            proposal.v3_status = 'pending_multisig'

            fs = FileSystemStorage()
            proof_urls = []
            for f in request.FILES.getlist('proof_files'):
                filename = fs.save(f"disbursements/{f.name}", f)
                proof_urls.append(fs.url(filename))
            if proof_urls:
                proposal.proof_images = proof_urls

            proposal.save()
            messages.success(request, "Đã tạo yêu cầu giải ngân! Chờ Admin duyệt.")

        except Exception as e:
            messages.error(request, f"Lỗi: {e}")

    return redirect('admin_panel:quanly_giaingan')


@login_required
def duyet_giaingan(request, pk):
    if not request.user.is_superuser:
        return redirect('admin_panel:quanly_giaingan')

    proposal = get_object_or_404(DisbursementProposal, pk=pk)

    if proposal.status != 'pending':
        messages.warning(request, "Yêu cầu này không ở trạng thái chờ duyệt.")
        return redirect('admin_panel:quanly_giaingan')

    if request.method == 'POST':
        voting_days = int(request.POST.get('voting_days', 7))

        proposal.status = 'voting'
        proposal.approved_by = request.user
        proposal.approved_at = timezone.now()
        proposal.voting_days = voting_days
        proposal.end_date = timezone.now() + timedelta(days=voting_days)

        campaign = proposal.campaign
        campaign.locked_amount += proposal.amount_requested
        campaign.save(update_fields=['locked_amount'])

        proposal.save()
        messages.success(request, f"Đã duyệt! Bắt đầu bỏ phiếu trong {voting_days} ngày.")

    return redirect('admin_panel:quanly_giaingan')


@login_required
def huy_giaingan(request, pk):
    if not request.user.is_superuser:
        return redirect('admin_panel:quanly_giaingan')

    proposal = get_object_or_404(DisbursementProposal, pk=pk)

    if proposal.status not in ('pending', 'voting'):
        messages.warning(request, "Không thể hủy yêu cầu này.")
        return redirect('admin_panel:quanly_giaingan')

    if proposal.status == 'voting':
        campaign = proposal.campaign
        campaign.locked_amount = max(Decimal('0'), campaign.locked_amount - proposal.amount_requested)
        campaign.save(update_fields=['locked_amount'])

    proposal.status = 'rejected'
    proposal.save()
    messages.warning(request, "Đã từ chối yêu cầu giải ngân.")
    return redirect('admin_panel:quanly_giaingan')


@login_required
def thu_hoi_gas(request):
    """
    [DEPRECATED ở contract v3]
    Contract DCPManager v3 KHÔNG còn function `withdrawGasRecovery` —
    Admin Relayer pattern: ví Admin tự trả gas từ ETH Sepolia riêng,
    không cộng gas vào currentAmount và không thu hồi ngược.
    View này chỉ hiện thông báo, không thực hiện giao dịch nào.
    """
    if not request.user.is_superuser:
        messages.error(request, "Bạn không có quyền thực hiện.")
        return redirect('admin_panel:quanly_giaingan')
    messages.info(
        request,
        "Chức năng 'Thu hồi gas' đã gỡ bỏ ở contract v3. "
        "Admin Relayer pattern: ví Admin tự trả gas phí Sepolia, không cộng vào currentAmount campaign."
    )
    return redirect('admin_panel:quanly_giaingan')


# ============================================================
# [V3] 2-LAYER DISBURSEMENT WORKFLOW — EIP-712 MULTISIG + PAYOS + BURN
# ------------------------------------------------------------
# Phase 1: off-chain proposal + IPFS (đã có ở tao_yeucau_giaingan).
# Phase 2: 3 bên ký EIP-712 qua MetaMask → gom vào DB.
# Phase 3a: Admin submit 3 sigs lên smart3 → MultisigConfirmed.
# Phase 3b: Admin trigger PayOS Payout (real bank transfer).
# Phase 4: PayOS webhook → backend gọi finalizeBurnWithBankTx on-chain.
# ============================================================
import threading
import secrets as _secrets
from django.db import connection as _db_connection
from client.payos_payout import verify_webhook_signature as _payos_verify_webhook
# Tái sử dụng hằng số 18-decimals từ blockchain service, tránh duplicate.
from client.blockchain import _VNDT_DECIMALS as _VNDT_DECIMALS_EXP


def _get_proposal_v3_eip712_payload(proposal, role, nonce=None, deadline=None):
    """
    Build payload EIP-712 typed-data cho 1 approver ký. Trả về dict JSON-safe
    để frontend nạp thẳng vào `eth_signTypedData_v4`.
    """
    if role not in ('organization', 'supervisor', 'admin'):
        raise ValueError(f"role không hợp lệ: {role}")
    bc = BlockchainService()
    campaign = proposal.campaign
    org = campaign.organization
    if not org or not org.wallet_address:
        raise ValueError("Organization chưa có wallet_address — không build được payload.")
    recipient = org.wallet_address  # multisig vault = org wallet theo convention V4
    amount_raw = int(Decimal(str(proposal.amount_requested)) * _VNDT_DECIMALS_EXP)
    # ------------------------------------------------------------------
    # Deadline phải DETERMINISTIC xuyên suốt 3 approvers vì smart3 yêu cầu
    # cả 3 sig cùng payload (incl. deadline). Nếu dùng `time.time() + 7d`
    # mỗi call GET → mỗi approver lấy deadline khác nhau → on-chain revert.
    # Giải pháp: derive từ proposal.created_at (bất biến, không cần DB write).
    # ------------------------------------------------------------------
    default_deadline = int((proposal.created_at + timedelta(days=7)).timestamp())
    deadline = int(deadline or proposal.signature_deadline or default_deadline)
    if nonce is None:
        # 128-bit random — đủ entropy, fits uint256.
        nonce = int.from_bytes(_secrets.token_bytes(16), 'big')
    typed_data = bc.build_eip712_typed_data(
        proposal_id=proposal.id,
        campaign_id=campaign.id,
        amount_raw=amount_raw,
        recipient=recipient,
        ipfs_cid=proposal.ipfs_cid or '',
        deadline=deadline,
        nonce=nonce,
        role=role,
    )
    return {
        'typed_data': typed_data,
        'nonce': str(nonce),
        'deadline': deadline,
        'amount_raw': str(amount_raw),
        'recipient': recipient,
        'ipfs_cid': proposal.ipfs_cid or '',
        'role': role,
    }


def sign_payload_v3(request, pk):
    """GET: trả về EIP-712 typed-data để frontend ký qua MetaMask."""
    try:
        logger.info(f">>> [V3 SIGN] Request nhận được: PK={pk}, User={request.user}, Role={request.GET.get('role')}")

        if not request.user.is_authenticated:
            return JsonResponse({'ok': False, 'message': 'Session expired. Please login again.'}, status=401)

        proposal = DisbursementProposal.objects.filter(pk=pk).first()
        if not proposal:
            logger.warning(f"!!! [V3 SIGN] Không tìm thấy Proposal ID={pk}")
            return JsonResponse({'ok': False, 'message': f'Proposal {pk} not found.'}, status=404)

        role = request.GET.get('role', '').strip()
        if role not in ('organization', 'supervisor', 'admin'):
            return JsonResponse({'ok': False, 'message': 'role không hợp lệ.'}, status=400)

        payload = _get_proposal_v3_eip712_payload(proposal, role)
        logger.info(f">>> [V3 SIGN] Typed data: {payload['typed_data']}")
        logger.info(f"✅ [V3 SIGN] Trả về payload thành công cho PK={pk}")
        return JsonResponse({'ok': True, **payload})
    except Exception as e:
        logger.error(f"XXX [V3 SIGN] CRASH: {traceback.format_exc()}")
        return JsonResponse({'ok': False, 'message': f'Internal error: {str(e)}'}, status=500)


def submit_signature_v3(request, pk):
    """
    POST JSON body: {role, signer_address, signature, nonce,
                     deadline, amount_raw, recipient, ipfs_cid}.
    Backend recover signer từ typed-data + chữ ký → nếu khớp signer_address
    thì lưu vào DisbursementSignature (unique per (proposal, role)).
    Khi đủ 3 sig → chuyển v3_status='ready_to_payout'.
    """
    try:
        logger.info(f">>> [V3 SUBMIT] Body: {request.body}")

        if not request.user.is_authenticated:
            return JsonResponse({'ok': False, 'message': 'Session expired. Please login again.'}, status=401)

        if request.method != 'POST':
            return JsonResponse({'ok': False, 'message': 'Method not allowed.'}, status=405)

        data = json.loads(request.body or '{}')

        proposal = DisbursementProposal.objects.filter(pk=pk).first()
        if not proposal:
            return JsonResponse({'ok': False, 'message': f'Proposal {pk} not found.'}, status=404)

        role = data.get('role')
        signer = (data.get('signer_address') or '').strip()
        signature = (data.get('signature') or '').strip()
        nonce = data.get('nonce')
        deadline = data.get('deadline')
        recipient = (data.get('recipient') or '').strip()
        amount_raw = data.get('amount_raw')
        ipfs_cid = (data.get('ipfs_cid') or proposal.ipfs_cid or '').strip()
        if not all([role, signer, signature, nonce is not None, deadline, recipient, amount_raw]):
            return JsonResponse({'ok': False, 'message': 'Thiếu field bắt buộc.'}, status=400)

        # Deadline validation: từ chối sig đã hết hạn ngay từ backend, không để DB rác.
        # Contract sẽ revert sau này, nhưng fail-fast ở backend rẻ hơn.
        if int(deadline) <= int(time.time()):
            return JsonResponse({'ok': False,
                                 'message': f'Signature deadline đã hết hạn ({deadline}). '
                                            'Người ký cần reload trang để lấy payload mới.'},
                                status=400)

        logger.info(">>> [V3 SUBMIT] Đang verify chữ ký...")

        bc = BlockchainService()
        typed_data = bc.build_eip712_typed_data(
            proposal_id=proposal.id, campaign_id=proposal.campaign_id,
            amount_raw=int(amount_raw), recipient=recipient, ipfs_cid=ipfs_cid,
            deadline=int(deadline), nonce=int(nonce), role=role,
        )
        logger.info(f">>> [V3 SUBMIT] Typed data: {typed_data}")
        recovered = bc.recover_eip712_signer(typed_data, signature)

        if recovered.lower() != signer.lower():
            logger.error(f"!!! [V3 SUBMIT] Signer mismatch: Rec={recovered}, Claimed={signer}")
            return JsonResponse({'ok': False,
                                 'message': f'Signer không khớp. Recovered={recovered}, claimed={signer}'},
                                status=400)

        # Verify signer_address đúng role on-chain.
        wallets = bc.get_disbursement_approver_wallets()
        logger.info(f"DEBUG WALLETS: Admin={wallets['admin_wallet']}, Sup={wallets['supervisor_wallet']}")
        expected = {
            'organization': (proposal.campaign.organization.wallet_address or '').lower(),
            'supervisor': wallets['supervisor_wallet'].lower(),
            'admin': wallets['admin_wallet'].lower(),
        }[role]
        if expected and recovered.lower() != expected:
            return JsonResponse(
                {'ok': False,
                 'message': f'Ví {recovered} không phải role {role} (expect {expected}).'},
                status=403,
            )

        sig_obj, created = DisbursementSignature.objects.update_or_create(
            proposal=proposal, role=role,
            defaults={
                'signer_address': recovered,
                'signature': signature,
                'nonce': Decimal(str(nonce)),
                'deadline': int(deadline),
                'signed_amount': Decimal(str(amount_raw)),
                'signed_recipient': recipient,
                'signed_ipfs_cid': ipfs_cid,
                'signed_by': request.user if request.user.is_authenticated else None,
            },
        )

        total_sigs = proposal.offchain_signatures.count()
        if total_sigs >= 3 and proposal.v3_status in ('v3_not_started', 'pending_multisig'):
            proposal.v3_status = 'ready_to_payout'
        elif proposal.v3_status == 'v3_not_started':
            proposal.v3_status = 'pending_multisig'
        proposal.save(update_fields=['v3_status'])

        return JsonResponse({
            'ok': True,
            'created': created,
            'total_sigs': total_sigs,
            'v3_status': proposal.v3_status,
            'ready_to_relay': total_sigs >= 3,
        })
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'message': 'Body JSON không hợp lệ.'}, status=400)
    except Exception as e:
        return JsonResponse({'ok': False, 'message': f'Internal error: {str(e)}'}, status=500)


@login_required
def v3_execute_multisig_relayer(request, pk):
    """
    POST: Admin gom 3 chữ ký từ DB → gọi smart3.recordMultisigApproval() trong
    1 tx duy nhất. Admin trả gas, 3 approvers KHÔNG tốn gas.
    """
    if not request.user.is_superuser:
        return JsonResponse({'ok': False, 'message': 'Chỉ admin được relay.'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'message': 'Method not allowed.'}, status=405)
    proposal = get_object_or_404(DisbursementProposal, pk=pk)
    sigs = {s.role: s for s in proposal.offchain_signatures.all()}
    missing = [r for r in ('organization', 'supervisor', 'admin') if r not in sigs]
    if missing:
        return JsonResponse({'ok': False, 'message': f'Thiếu chữ ký: {missing}'}, status=400)
    # Sanity: cả 3 sig phải cùng amount/recipient/deadline/ipfs.
    first = sigs['organization']
    for r in ('supervisor', 'admin'):
        s = sigs[r]
        if (s.signed_amount != first.signed_amount or
                s.signed_recipient.lower() != first.signed_recipient.lower() or
                s.deadline != first.deadline or
                s.signed_ipfs_cid != first.signed_ipfs_cid):
            return JsonResponse(
                {'ok': False,
                 'message': f'Sig của {r} không khớp payload với organization — có thể đã bị tampering.'},
                status=409,
            )
    try:
        logger.info(f"Relay multisig for proposal {pk}, campaign {proposal.campaign_id}")
        bc = BlockchainService()
        result = bc.record_multisig_approval(
            proposal_id=proposal.id,
            campaign_id=proposal.campaign_id,
            amount_raw=int(first.signed_amount),
            recipient=first.signed_recipient,
            ipfs_cid=first.signed_ipfs_cid,
            deadline=first.deadline,
            org_sig=sigs['organization'].signature,
            supervisor_sig=sigs['supervisor'].signature,
            admin_sig=sigs['admin'].signature,
            org_nonce=int(sigs['organization'].nonce),
            supervisor_nonce=int(sigs['supervisor'].nonce),
            admin_nonce=int(sigs['admin'].nonce),
            wait_for_receipt=False,
        )
    except Exception as exc:
        proposal.payout_error = f'multisig relay fail: {exc}'[:1000]
        proposal.save(update_fields=['payout_error'])
        return JsonResponse({'ok': False, 'message': str(exc)}, status=502)

    tx_hash = result.get('tx_hash')
    proposal.payout_error = f'multisig relay pending: {tx_hash}'[:1000]
    proposal.save(update_fields=['payout_error'])

    t = threading.Thread(
        target=_run_confirm_multisig_relay_safe,
        args=(proposal.id, tx_hash),
        name=f'v3-relay-confirm-{proposal.id}',
        daemon=True,
    )
    transaction.on_commit(t.start)

    return JsonResponse({
        'ok': True,
        'tx_hash': tx_hash,
        'v3_status': proposal.v3_status,
        'pending_confirmation': True,
        'message': 'Đã gửi transaction relay lên chain. Hệ thống sẽ cập nhật khi tx được mine.',
    })


def _run_confirm_multisig_relay_safe(proposal_id, tx_hash):
    """Background worker: wait relay receipt, then mark proposal ready_to_payout."""
    from admin_panel.models import DisbursementProposal as _DP

    try:
        bc = BlockchainService()
        receipt = bc.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        p = _DP.objects.get(pk=proposal_id)
        if int(receipt.status) != 1:
            p.payout_error = f'multisig relay fail: tx reverted ({tx_hash})'[:1000]
            p.save(update_fields=['payout_error'])
            print(f"❌ [V3/RELAY] proposal={proposal_id} tx reverted: {tx_hash}", flush=True)
            return

        p.multisig_confirmed_tx_hash = tx_hash
        p.multisig_confirmed_at = timezone.now()
        p.v3_status = 'ready_to_payout'
        p.payout_error = ''
        p.save(update_fields=[
            'multisig_confirmed_tx_hash',
            'multisig_confirmed_at',
            'v3_status',
            'payout_error',
        ])
        print(f"✅ [V3/RELAY] proposal={proposal_id} confirmed tx={tx_hash}", flush=True)
    except Exception as exc:
        import traceback as _tb
        _tb.print_exc()
        try:
            p = _DP.objects.get(pk=proposal_id)
            p.payout_error = f'multisig relay confirm fail: {exc}'[:1000]
            p.save(update_fields=['payout_error'])
        except Exception:
            pass
    finally:
        try:
            _db_connection.close()
        except Exception:
            pass


@login_required
def v3_trigger_payos_payout(request, pk):
    """
    [V3 LUONG MOI] Admin bam "Thuc thi PayOS" -> goi PayOS Payout API
    (Kenh Chi) -> tien fiat tu dong chuyen tu escrow PayOS sang bank Org.

    Khac voi luong CU (mock-only, da xoa):
      * Kiem tra so du Kenh Chi truoc (PayosPayoutService.check_balance).
      * Goi POST /v1/payouts THAT su (khong mock) khi PAYOS_PAYOUT_MOCK=False.
      * Idempotent: neu da co payos_payout_id thi skip.
      * Headers x-client-id / x-api-key dung PAYOS_PAYOUT_* (Kenh Chi).

    Endpoint nay van giu de admin co the retry thu cong khi auto signal
    bi tat (V3_AUTO_TRIGGER_PAYOUT=False) hoac payout_failed.
    """
    if not request.user.is_superuser:
        return JsonResponse({'ok': False, 'message': 'Chi admin duoc trigger payout.'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'message': 'Method not allowed.'}, status=405)
    proposal = get_object_or_404(
        DisbursementProposal.objects.select_related('campaign', 'campaign__organization'), pk=pk
    )
    if proposal.v3_status != 'ready_to_payout':
        return JsonResponse({'ok': False,
                             'message': f'v3_status={proposal.v3_status}, can ready_to_payout.'},
                            status=409)
    # Idempotent guard: neu da co payos_payout_id thi khong goi lai PayOS
    # (tranh double-spend khi admin spam click hoac auto-trigger song song).
    if proposal.payos_payout_id:
        return JsonResponse({'ok': True, 'payout_id': proposal.payos_payout_id,
                             'skipped': True, 'reason': 'already_requested',
                             'v3_status': proposal.v3_status})
    # Delegate sang Celery task (co fallback threading neu khong co worker).
    # Task da tu xu ly: check_balance -> create_payout -> save payos_payout_id.
    # Set v3_status='payout_processing' NGAY de UX phan hoi tuc thoi.
    # Task se override sang 'payout_failed' neu PayOS API reject; thanh
    # cong thi gi nguyen 'payout_processing' cho den khi webhook cap nhat.
    proposal.v3_status = 'payout_processing'
    proposal.save(update_fields=['v3_status'])
    try:
        from admin_panel.tasks.disbursement_tasks import trigger_payos_payout
        trigger_payos_payout.delay(proposal.id)
    except Exception as exc:
        logger.error(f'[V3] trigger_payos_payout dispatch fail: {exc}')
        proposal.payout_error = f'dispatch fail: {exc}'[:1000]
        proposal.v3_status = 'payout_failed'
        proposal.save(update_fields=['payout_error', 'v3_status'])
        return JsonResponse({'ok': False, 'message': str(exc)}, status=502)
    # Refresh tu DB de lay trang thai moi nhat (neu task chay sync mode).
    proposal.refresh_from_db()
    return JsonResponse({'ok': True,
                         'payout_id': proposal.payos_payout_id or '',
                         'v3_status': proposal.v3_status,
                         'message': 'Da gui lenh PayOS Payout. He thong se cap nhat khi co webhook.'})


def _run_finalize_burn_safe(proposal_id):
    """Background worker: gọi smart3.finalizeBurnWithBankTx. Không raise."""
    from admin_panel.models import DisbursementProposal as _DP
    try:
        p = _DP.objects.select_related('campaign', 'campaign__organization').get(pk=proposal_id)
    except _DP.DoesNotExist:
        print(f"⚠️ [V3/BURN] Proposal {proposal_id} not found")
        return
    try:
        bc = BlockchainService()
        vault = p.campaign.organization.wallet_address
        res = bc.finalize_burn_with_bank_tx(p.id, vault, p.bank_tx_id)
        p.burn_tx_hash = res.get('tx_hash')
        p.burn_completed_at = timezone.now()
        p.v3_status = 'completed_audited'
        p.save(update_fields=['burn_tx_hash', 'burn_completed_at', 'v3_status'])
        print(f"🔥 [V3/BURN] proposal={p.id} burn tx={res.get('tx_hash')}")
    except Exception as exc:
        import traceback as _tb
        _tb.print_exc()
        p.payout_error = f'burn fail: {exc}'[:1000]
        p.save(update_fields=['payout_error'])
    finally:
        try:
            _db_connection.close()
        except Exception:
            pass


@csrf_exempt
def v3_payos_payout_webhook(request):
    """
    Endpoint PayOS gọi khi bank transfer xong. Backend verify sig → lưu
    bank_tx_id + fiat_transferred_at → spawn thread burn on-chain.
    Trả 200 ngay để PayOS không retry.
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'message': 'Method not allowed.'}, status=405)
    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'message': 'Body JSON không hợp lệ.'}, status=400)

    try:
        # PayOS payout webhook has nested structure: data['data']['orderCode']
        data = json.loads(request.body or '{}')
        if 'data' not in data or not data['data'].get('orderCode'):
            # Check if it's a test ping
            if data.get('data', {}).get('description') == 'Ma test Webhook':
                return JsonResponse({"success": True, "message": "Test webhook received"}, status=200)
            raise ValueError('orderCode missing in data.data')
        order_code = data['data']['orderCode']
        proposal = DisbursementProposal.objects.get(payos_order_code=order_code)

        # Get organization's PayOS checksum key for verification
        org = proposal.campaign.organization
        checksum_key = org.payos_checksum_key
        if not checksum_key:
            raise ValueError('Organization PayOS checksum key not configured.')

        # Idempotency: PayOS có thể retry webhook (network blip hay qua standard policy).
        # Nếu proposal đã ở state “fiat_transferred” hoặc “completed_audited” thì
        # bỏ qua — smart3 cũng sẽ revert, nhưng fail-fast tiết kiệm 1 RPC + 1 thread.
        if proposal.v3_status in ('fiat_transferred', 'completed_audited'):
            return JsonResponse({'ok': True, 'note': 'webhook already processed',
                                 'v3_status': proposal.v3_status})

        sig = data.get('signature') or request.headers.get('X-PayOS-Signature', '')
        if not _payos_verify_webhook(data['data'], sig, checksum_key):
            raise ValueError('Invalid signature.')

        tx_id = data['data'].get('reference') or data['data'].get('bankTransactionId') or "UNKNOWN"
        proposal.bank_tx_id = tx_id
        proposal.fiat_transferred_at = timezone.now()
        proposal.v3_status = 'fiat_transferred'
        proposal.save(update_fields=['bank_tx_id', 'fiat_transferred_at', 'v3_status'])

        # Phase 4: trigger burn on-chain trong background (tránh block webhook).
        t = threading.Thread(target=_run_finalize_burn_safe, args=(proposal.id,),
                             name=f'v3-burn-{proposal.id}', daemon=True)
        transaction.on_commit(t.start)
        return JsonResponse({'ok': True, 'bank_tx_id': tx_id})
    except Exception as e:
        # For PayOS test pings or errors, return success to allow URL configuration
        print(f"Webhook Ping or Error: {e}", flush=True)
        return JsonResponse({"success": True, "message": "Webhook verified"}, status=200)


@login_required
def v3_simulate_webhook(request, pk):
    """[DEV-ONLY] Admin giả PayOS webhook success để test pipeline burn."""
    if not request.user.is_superuser:
        return JsonResponse({'ok': False, 'message': 'Chỉ admin.'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'message': 'Method not allowed.'}, status=405)
    from client.payos_payout import simulate_webhook_success
    proposal = get_object_or_404(DisbursementProposal, pk=pk)
    payload = simulate_webhook_success(proposal)
    # Dùng thẳng handler với payload mock — bỏ qua CSRF vì đã login_required.
    from django.test import RequestFactory
    rf = RequestFactory()
    fake_req = rf.post('/fake', data=json.dumps(payload), content_type='application/json')
    return v3_payos_payout_webhook(fake_req)
