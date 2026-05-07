from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.views import View
from django.http import HttpResponse, JsonResponse  
from django.db import transaction
from django.contrib.auth import  login, authenticate,  logout
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.utils import timezone
import random
import requests
import json
from django.utils.text import slugify
import time
from django.db.models import Q, Sum
from .models import (
    CampaignCategory, Organization, TargetProgram, Donation, Campaign,
    CampaignOccasion, DisbursementProposal, ProposalVote, CampaignDisbursement,
    BankStatement, ActivityLog,
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
    }
    return render(request, 'admin_panel/trangchu.html', context)

# --- VIEW ĐĂNG NHẬP ---
def dangnhap(request):
    if request.user.is_authenticated:
        if request.user.is_superuser or Organization.objects.filter(manager=request.user).exists() or _get_disbursement_approver_context(request.user).get('approver_role') == 'supervisor':
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
            if user.is_superuser or Organization.objects.filter(manager=user).exists() or _get_disbursement_approver_context(user).get('approver_role') == 'supervisor':
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

@login_required(login_url='admin_panel:dangnhap')
def quanly_giaingan(request):
    user = request.user
    q = _normalize_query(request.GET.get('q'))
    approver_context = _get_disbursement_approver_context(user)

    if user.is_superuser:
        role = 'admin'
        proposals_qs = DisbursementProposal.objects.select_related(
            'campaign', 'campaign__organization', 'created_by', 'approved_by'
        ).all()
        campaigns = Campaign.objects.filter(status='active')
    elif approver_context['approver_role'] == 'supervisor':
        role = 'supervisor'
        proposals_qs = DisbursementProposal.objects.select_related(
            'campaign', 'campaign__organization', 'created_by', 'approved_by'
        ).all()
        campaigns = Campaign.objects.none()
    elif user.managed_organizations.exists():
        role = 'partner'
        my_org = user.managed_organizations.first()
        proposals_qs = DisbursementProposal.objects.select_related(
            'campaign', 'campaign__organization', 'created_by', 'approved_by'
        ).filter(campaign__organization=my_org)
        campaigns = Campaign.objects.filter(organization=my_org, status='active')
    else:
        return redirect('client:trangchu')

    # ========================================================
    # LUỒNG V2: Công thức động theo số lần tạo giải ngân
    #   onchain_available = totalFund - totalGasCost - totalDisbursed - totalAdminRecovered
    #   LẦN ĐẦU tạo giải ngân (chưa có proposal nào non-rejected):
    #     net_available = onchain_available - est_disbursement_gas - est_recovery_gas - locked
    #     (dự trù 2 phí: 1 cho tx giải ngân + 1 cho tx thu hồi gas cuối cùng)
    #   LẦN 2 TRỞ ĐI:
    #     net_available = onchain_available - est_disbursement_gas - locked
    #     (chỉ dự trù 1 phí vì est_recovery_gas đã được reserve từ lần đầu)
    #
    #   Nút "Thu hồi gas" chỉ hiện khi: campaign đã hết hạn VÀ onchain_available ≈ 0
    # ========================================================
    campaigns_with_available = []
    bc = None
    eth_vnd_rate = None
    est_disbursement_gas_vnd = Decimal('0')
    est_recovery_gas_vnd = Decimal('0')

    # Breakdown hiển thị - Luồng v2 mới (gas A/B đã recordGasCost vào contract)
    bank_record_gas_map = {
        row['campaign_id']: (row['total'] or Decimal('0'))
        for row in Donation.objects.filter(bank_record_gas_vnd__isnull=False).values('campaign_id').annotate(total=Sum('bank_record_gas_vnd'))
    }
    donate_onbehalf_gas_map = {
        row['campaign_id']: (row['total'] or Decimal('0'))
        for row in Donation.objects.filter(donate_onbehalf_gas_vnd__isnull=False).values('campaign_id').annotate(total=Sum('donate_onbehalf_gas_vnd'))
    }
    # Legacy (luồng cũ) - giữ để tương thích với donation cũ
    admin_sendeth_gas_map = {
        row['campaign_id']: (row['total'] or Decimal('0'))
        for row in Donation.objects.filter(admin_send_eth_gas_fee_vnd__isnull=False).values('campaign_id').annotate(total=Sum('admin_send_eth_gas_fee_vnd'))
    }
    disbursement_gas_map = {
        row['campaign_id']: (row['total'] or Decimal('0'))
        for row in DisbursementProposal.objects.filter(status='executed').values('campaign_id').annotate(total=Sum('disbursement_gas_fee_vnd'))
    }
    # Map: chiến dịch đã có proposal non-rejected chưa? (để xác định lần đầu / lần 2+)
    non_rejected_proposal_ids = set(
        DisbursementProposal.objects.exclude(status='rejected').values_list('campaign_id', flat=True)
    )

    try:
        bc = BlockchainService()
        eth_vnd_rate = get_eth_vnd_rate()
        est_gas_vnd, _est_gas_wei = estimate_gas_per_tx_vnd(eth_vnd_rate, bc=bc)
        est_disbursement_gas_vnd = est_gas_vnd
        est_recovery_gas_vnd = est_gas_vnd  # cùng công thức ước tính (1 tx on-chain)
    except Exception:
        bc = None
        eth_vnd_rate = None

    today = timezone.localdate()  # datetime.date - so sánh với end_date (DateField)
    for c in campaigns:
        gas_bank_record_vnd = bank_record_gas_map.get(c.id, Decimal('0'))
        gas_donate_onbehalf_vnd = donate_onbehalf_gas_map.get(c.id, Decimal('0'))
        gas_admin_sendeth_vnd = admin_sendeth_gas_map.get(c.id, Decimal('0'))  # legacy
        gas_disbursement_actual_vnd = disbursement_gas_map.get(c.id, Decimal('0'))
        gas_onchain_total_cost_vnd = Decimal('0')  # totalGasCost on-chain (đã cộng dồn)
        gas_recovered_vnd = Decimal('0')
        onchain_total_fund_vnd = c.current_amount
        # SQL fallback: CHƯA trừ locked ở đây (locked sẽ trừ 1 lần duy nhất khi tính net_available)
        onchain_available_vnd = max(Decimal('0'), c.current_amount - c.disbursed_amount)

        # Lần đầu tạo giải ngân? (chưa có proposal nào non-rejected cho campaign này)
        is_first_disbursement = c.id not in non_rejected_proposal_ids

        if bc and eth_vnd_rate:
            try:
                stats = bc.get_campaign_onchain_stats(c.id)
                # Dùng total_gas_cost_wei (v2); fallback total_gas_subsidized_wei (alias backward-compat)
                total_gas_cost_wei = stats.get('total_gas_cost_wei', stats.get('total_gas_subsidized_wei', 0))
                # onchain_available = totalFund - totalGasCost - totalDisbursed - totalAdminRecovered
                available_wei = stats['total_fund_wei'] - total_gas_cost_wei - stats['total_disbursed_wei'] - stats['total_admin_recovered_wei']
                gas_onchain_total_cost_vnd = _round_vnd(_wei_to_vnd(total_gas_cost_wei, eth_vnd_rate))
                gas_recovered_vnd = _round_vnd(_wei_to_vnd(stats['total_admin_recovered_wei'], eth_vnd_rate))
                onchain_total_fund_vnd = _round_vnd(_wei_to_vnd(stats['total_fund_wei'], eth_vnd_rate))
                onchain_available_vnd = _round_vnd(_wei_to_vnd(max(0, available_wei), eth_vnd_rate))
            except Exception:
                pass

        # Công thức động:
        #   lần đầu → trừ 2 phí (disbursement + recovery)
        #   lần 2+  → chỉ trừ 1 phí (disbursement)
        if is_first_disbursement:
            reserve_gas_vnd = _round_vnd(est_disbursement_gas_vnd) + _round_vnd(est_recovery_gas_vnd)
        else:
            reserve_gas_vnd = _round_vnd(est_disbursement_gas_vnd)
        net_available = onchain_available_vnd - reserve_gas_vnd - c.locked_amount

        # Nút "Thu hồi gas" chỉ hiện khi campaign đã hết hạn VÀ đã giải ngân hết
        # (onchain_available = 0 nghĩa là không còn tiền để giải ngân tiếp)
        # Lưu ý: c.end_date là DateField (date) nên so với today (date) thay vì now (datetime)
        is_ended = bool(c.end_date) and c.end_date < today
        fully_disbursed = onchain_available_vnd <= FULLY_DISBURSED_THRESHOLD_VND
        can_recover_gas = is_ended and fully_disbursed

        # total_gas_vnd chỉ để hiển thị "tổng phí gas đã chi + dự trù"
        total_gas_display_vnd = gas_onchain_total_cost_vnd + _round_vnd(gas_admin_sendeth_vnd) + _round_vnd(gas_disbursement_actual_vnd) + reserve_gas_vnd
        campaigns_with_available.append({
            'obj': c,
            'total_gas_vnd': _round_vnd(total_gas_display_vnd),
            # Luồng v2 breakdown
            'gas_bank_record_vnd': _round_vnd(gas_bank_record_vnd),
            'gas_donate_onbehalf_vnd': _round_vnd(gas_donate_onbehalf_vnd),
            'gas_onchain_total_cost_vnd': gas_onchain_total_cost_vnd,
            # Legacy
            'gas_admin_sendeth_vnd': _round_vnd(gas_admin_sendeth_vnd),
            'gas_disbursement_actual_vnd': _round_vnd(gas_disbursement_actual_vnd),
            # Gas dự trù (động theo lần)
            'est_disbursement_gas_vnd': _round_vnd(est_disbursement_gas_vnd),
            'est_recovery_gas_vnd': _round_vnd(est_recovery_gas_vnd),
            'reserve_gas_vnd': reserve_gas_vnd,
            'is_first_disbursement': is_first_disbursement,
            # Onchain info
            'onchain_available_vnd': onchain_available_vnd,
            'gas_recovered_vnd': gas_recovered_vnd,
            'onchain_total_fund_vnd': _round_vnd(onchain_total_fund_vnd),
            'net_available': max(Decimal('0'), _round_vnd(net_available)),
            # Điều kiện thu hồi gas
            'can_recover_gas': can_recover_gas,
            'is_ended': is_ended,
            'fully_disbursed': fully_disbursed,
        })

    campaign_filter = request.GET.get('campaign')
    status_filter = request.GET.get('status', '')
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
        proposals_qs = proposals_qs.filter(status=status_filter)

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

    proposals_data = []
    for p in proposals_qs:
        votes = ProposalVote.objects.filter(proposal=p)
        yes_power = votes.filter(is_agree=True).aggregate(t=Sum('voting_power'))['t'] or Decimal('0')
        no_power = votes.filter(is_agree=False).aggregate(t=Sum('voting_power'))['t'] or Decimal('0')
        total_voted = yes_power + no_power
        can_approve = role in ('admin', 'supervisor') and p.status in ('pending', 'approved') and bool(p.ipfs_cid)
        already_approved = False
        if role == 'admin':
            already_approved = bool(p.admin_approval_tx_hash)
        elif role == 'supervisor':
            already_approved = bool(p.supervisor_approval_tx_hash)
        proposals_data.append({
            'obj': p,
            'yes_power': yes_power,
            'no_power': no_power,
            'yes_pct': float(yes_power / total_voted * 100) if total_voted > 0 else 0,
            'no_pct': float(no_power / total_voted * 100) if total_voted > 0 else 0,
            'votes_count': votes.count(),
            'can_approve': can_approve,
            'already_approved': already_approved,
        })

    stats = {
        'pending': proposals_qs.filter(status='pending').count(),
        'voting': proposals_qs.filter(status='voting').count(),
        'approved': proposals_qs.filter(status='approved').count(),
        'executed': proposals_qs.filter(status='executed').count(),
        'rejected': proposals_qs.filter(status='rejected').count(),
        'total_disbursed': proposals_qs.filter(status='executed').aggregate(t=Sum('amount_requested'))['t'] or 0,
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
    }
    return render(request, 'admin_panel/quanly_giaingan.html', context)


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
            campaign_id = request.POST.get('campaign_id')
            campaign = get_object_or_404(Campaign, pk=campaign_id)

            if not _can_manage_campaign_disbursement(request.user, campaign):
                messages.error(request, "Bạn không có quyền tạo yêu cầu giải ngân cho chiến dịch này!")
                return redirect('admin_panel:quanly_giaingan')

            amount_raw = (request.POST.get('amount_requested', '0') or '0').replace(',', '')
            amount = _round_vnd(Decimal(amount_raw))
            total_gas_fees = Decimal('0')

            # Xác định lần tạo giải ngân (lần đầu hay lần 2+)
            is_first_disbursement = not DisbursementProposal.objects.filter(
                campaign=campaign
            ).exclude(status='rejected').exists()

            # Bắt đầu với SQL fallback: onchain_available = current - disbursed (chưa trừ locked)
            onchain_available_vnd = max(Decimal('0'), campaign.current_amount - campaign.disbursed_amount)
            est_per_tx = Decimal('0')
            gas_onchain_cost_vnd = Decimal('0')

            try:
                bc = BlockchainService()
                eth_vnd_rate = get_eth_vnd_rate()
                stats = bc.get_campaign_onchain_stats(campaign.id)
                # V2: dùng total_gas_cost_wei (contract mới, đã cộng dồn gas A+B+C qua recordGasCost)
                total_gas_cost_wei = stats.get('total_gas_cost_wei', stats.get('total_gas_subsidized_wei', 0))
                available_wei = stats['total_fund_wei'] - total_gas_cost_wei - stats['total_disbursed_wei'] - stats['total_admin_recovered_wei']
                est_gas_vnd, _est_wei = estimate_gas_per_tx_vnd(eth_vnd_rate, bc=bc)
                est_per_tx = _round_vnd(est_gas_vnd)
                gas_onchain_cost_vnd = _round_vnd(_wei_to_vnd(total_gas_cost_wei, eth_vnd_rate))
                onchain_available_vnd = _round_vnd(_wei_to_vnd(max(0, available_wei), eth_vnd_rate))
            except Exception:
                pass

            # CÔNG THỨC ĐỘNG (áp dụng cả khi BlockchainService fail để tránh bypass):
            #   lần đầu   → trừ 2 phí dự trù (giải ngân + thu hồi)
            #   lần 2+    → chỉ trừ 1 phí dự trù (giải ngân)
            reserve_gas = est_per_tx * 2 if is_first_disbursement else est_per_tx
            total_gas_fees = gas_onchain_cost_vnd + reserve_gas
            available = onchain_available_vnd - reserve_gas - campaign.locked_amount
            available = _round_vnd(max(Decimal('0'), available))
            if amount > available:
                lan_msg = "lần đầu (dự trù 2 phí: giải ngân + thu hồi gas)" if is_first_disbursement else "lần tiếp theo (chỉ dự trù phí giải ngân)"
                messages.error(request, f"Số tiền vượt quá số dư khả dụng ({int(available):,}đ). Đã trừ phí gas {int(total_gas_fees):,}đ [{lan_msg}].")
                return redirect('admin_panel:quanly_giaingan')

            proposal = DisbursementProposal()
            proposal.campaign = campaign
            proposal.title = request.POST.get('title')
            proposal.amount_requested = amount
            proposal.purpose = request.POST.get('purpose')
            proposal.description = request.POST.get('description')
            proposal.recipient_name = request.POST.get('recipient_name')
            proposal.ipfs_cid = (request.POST.get('ipfs_cid') or '').strip() or None
            proposal.eth_tx_hash = (request.POST.get('proposal_tx_hash') or '').strip() or None
            if not proposal.ipfs_cid or not proposal.eth_tx_hash:
                messages.error(request, "Thiếu IPFS CID hoặc transaction hash gasless. Vui lòng upload lại hóa đơn và ký giao dịch.")
                return redirect('admin_panel:quanly_giaingan')
            proposal.evidence_url = request.POST.get('evidence_url', '')
            ipfs_gateway_url = (request.POST.get('ipfs_gateway_url') or '').strip()
            if proposal.ipfs_cid and not proposal.evidence_url and ipfs_gateway_url:
                proposal.evidence_url = ipfs_gateway_url
            proposal.created_by = request.user
            proposal.status = 'pending'

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


