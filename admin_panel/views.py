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
from datetime import timedelta
from decimal import Decimal
from django.core.files.storage import FileSystemStorage

# ========================================================
# 🔥 IMPORT BLOCKCHAIN SERVICE (Thêm dòng này)
# ========================================================
from client.blockchain import BlockchainService 

# --- VIEW TRANG CHỦ ADMIN ---
@login_required(login_url='admin_panel:dangnhap')
def trangchu(request):
    user = request.user
    
    total_campaigns = 0
    total_donations_amount = 0
    total_programs = 0
    role = 'user' 

    if user.is_superuser:
        role = 'admin'
        total_campaigns = Campaign.objects.count()
        total_programs = TargetProgram.objects.count()
        total_donations_amount = Donation.objects.filter(status='completed').aggregate(Sum('amount'))['amount__sum'] or 0

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
    }
    return render(request, 'admin_panel/trangchu.html', context)

# --- VIEW ĐĂNG NHẬP ---
def dangnhap(request):
    if request.user.is_authenticated:
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
    categories = CampaignCategory.objects.all().order_by('display_order')

    if request.method == 'POST':
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
        'categories': categories
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
    query = request.GET.get('q', '')
    if query:
        orgs = Organization.objects.filter(
            Q(name__icontains=query) | 
            Q(contact_phone__icontains=query) |
            Q(manager__username__icontains=query)
        ).order_by('-created_at')
    else:
        orgs = Organization.objects.all().order_by('-created_at')

    return render(request, 'admin_panel/quanlytochuc.html', {
        'orgs': orgs, 
        'query': query
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
    query = request.GET.get('q', '')
    if query:
        programs = TargetProgram.objects.filter(
            Q(name__icontains=query) | Q(organization__name__icontains=query)
        ).order_by('-created_at')
    else:
        programs = TargetProgram.objects.all().order_by('-created_at')

    all_orgs = Organization.objects.filter(is_verified=True) 

    context = {
        'programs': programs,
        'all_orgs': all_orgs,
        'query': query
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
    
    if user.is_superuser:
        role = 'admin'
        campaigns = Campaign.objects.all().order_by('-created_at')
        programs = TargetProgram.objects.all()
        orgs = Organization.objects.all()
    elif user.managed_organizations.exists():
        role = 'partner'
        my_org = user.managed_organizations.first()
        campaigns = Campaign.objects.filter(organization=my_org).order_by('-created_at')
        programs = TargetProgram.objects.filter(organization=my_org)
        orgs = [my_org]
    else:
        return redirect('client:trangchu')

    categories = CampaignCategory.objects.filter(is_active=True)
    occasions = CampaignOccasion.objects.filter(is_active=True)

    context = {
        'campaigns': campaigns,
        'role': role,
        'programs': programs,
        'orgs': orgs,
        'categories': categories,
        'occasions': occasions
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
            camp.save()

            messages.success(request, f"Đã tạo chiến dịch '{camp.title}' thành công!")

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
    camp.status = 'active'
    camp.approved_by = request.user
    camp.approved_at = timezone.now()
    camp.save()

    # 🔥 GỌI initCampaign LÊN BLOCKCHAIN KHI DUYỆT
    try:
        print(f"🚀 [BLOCKCHAIN] Đang khởi tạo chiến dịch #{camp.id} trên Blockchain...")
        if not camp.organization or not camp.organization.wallet_address:
            raise Exception("Tổ chức chưa có địa chỉ ví Crypto (MetaMask).")
        bc = BlockchainService()
        tx_hash = bc.init_campaign(
            campaign_id=camp.id,
            org_name=camp.organization.name if camp.organization else "Unknown",
            org_address=camp.organization.wallet_address if camp.organization else "0x0000000000000000000000000000000000000000",
        )
        print(f"✅ [BLOCKCHAIN] initCampaign thành công! Hash: {tx_hash}")
    except Exception as e:
        print(f"❌ [BLOCKCHAIN ERROR] Lỗi initCampaign: {e}")
        print("⚠️ Chiến dịch vẫn được duyệt trên SQL, nhưng chưa init trên Blockchain.")

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
    if not request.user.is_superuser:
        messages.error(request, "Bạn không có quyền nạp Pool.")
        return redirect('admin_panel:quanlychiendich')

    if request.method != 'POST':
        return redirect('admin_panel:quanlychiendich')

    amount_eth = request.POST.get('amount_eth')

    try:
        if not amount_eth:
            raise Exception("Thiếu số ETH.")

        amount_wei = int(Decimal(str(amount_eth)) * Decimal('1000000000000000000'))
        bc = BlockchainService()
        if bc.admin_has_pending_tx():
            messages.error(request, "Ví Admin đang có giao dịch pending. Vui lòng đợi xác nhận hoặc Speed Up trong MetaMask.")
            return redirect('admin_panel:quanlychiendich')
        try:
            chain_id = bc.w3.eth.chain_id
            balance = bc.w3.eth.get_balance(settings.WALLET_ADDRESS)
            print(f"ℹ️ [POOL] RPC: {settings.WEB3_PROVIDER_URL} | chainId: {chain_id}")
            print(f"ℹ️ [POOL] Admin: {settings.WALLET_ADDRESS} | balance: {balance} wei")
        except Exception:
            pass
        tx_hash = bc.deposit_exchange_pool(amount_wei)
        print(f"✅ [POOL] Da gui tx nap Pool: {tx_hash}")
        try:
            receipt = bc.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            if receipt and receipt.get('status') == 1:
                print(f"✅ [POOL] Tx nap Pool thanh cong: {tx_hash}")
                messages.success(request, f"Đã nạp {amount_eth} ETH vào Pool chung. Tx: {tx_hash}")
            else:
                print(f"❌ [POOL] Tx nap Pool bi revert: {tx_hash}")
                messages.error(request, f"Giao dịch nạp Pool thất bại (revert). Tx: {tx_hash}")
        except Exception:
            print(f"⏳ [POOL] Tx nap Pool dang cho xac nhan: {tx_hash}")
            messages.warning(request, f"Đã gửi giao dịch nạp Pool, đang chờ xác nhận. Tx: {tx_hash}")
    except Exception as e:
        messages.error(request, f"Lỗi nạp Pool: {e}")

    return redirect('admin_panel:quanlychiendich')

# --- QUẢN LÝ QUYÊN GÓP ---
def quanly_quyengop(request):
    donations = Donation.objects.all().order_by('-created_at')
    return render(request, 'admin_panel/quanly_quyengop.html', {'donations': donations})

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

    return render(request, 'admin_panel/sua_quyengop.html', {'form': form, 'donation': donation})


# ========================================================
# QUẢN LÝ GIẢI NGÂN
# ========================================================

@login_required(login_url='admin_panel:dangnhap')
def quanly_giaingan(request):
    user = request.user

    if user.is_superuser:
        role = 'admin'
        proposals_qs = DisbursementProposal.objects.select_related(
            'campaign', 'campaign__organization', 'created_by', 'approved_by'
        ).all()
        campaigns = Campaign.objects.filter(status='active')
    elif user.managed_organizations.exists():
        role = 'partner'
        my_org = user.managed_organizations.first()
        proposals_qs = DisbursementProposal.objects.select_related(
            'campaign', 'campaign__organization', 'created_by', 'approved_by'
        ).filter(campaign__organization=my_org)
        campaigns = Campaign.objects.filter(organization=my_org, status='active')
    else:
        return redirect('client:trangchu')

    # Tính số tiền khả dụng thực tế (đã trừ phí gas) cho mỗi chiến dịch
    campaigns_with_available = []
    for c in campaigns:
        total_gas = Donation.objects.filter(
            campaign=c, gas_fee_vnd__isnull=False
        ).aggregate(total=Sum('gas_fee_vnd'))['total'] or Decimal('0')
        net_available = c.current_amount - total_gas - c.disbursed_amount - c.locked_amount
        campaigns_with_available.append({
            'obj': c,
            'total_gas_vnd': total_gas,
            'net_available': max(Decimal('0'), net_available),
        })

    campaign_filter = request.GET.get('campaign')
    if campaign_filter:
        proposals_qs = proposals_qs.filter(campaign_id=campaign_filter)

    proposals_qs = proposals_qs.order_by('-created_at')

    proposals_data = []
    for p in proposals_qs:
        votes = ProposalVote.objects.filter(proposal=p)
        yes_power = votes.filter(is_agree=True).aggregate(t=Sum('voting_power'))['t'] or Decimal('0')
        no_power = votes.filter(is_agree=False).aggregate(t=Sum('voting_power'))['t'] or Decimal('0')
        total_voted = yes_power + no_power
        proposals_data.append({
            'obj': p,
            'yes_power': yes_power,
            'no_power': no_power,
            'yes_pct': float(yes_power / total_voted * 100) if total_voted > 0 else 0,
            'no_pct': float(no_power / total_voted * 100) if total_voted > 0 else 0,
            'votes_count': votes.count(),
        })

    stats = {
        'pending': proposals_qs.filter(status='pending').count(),
        'voting': proposals_qs.filter(status='voting').count(),
        'executed': proposals_qs.filter(status='executed').count(),
        'total_disbursed': proposals_qs.filter(status='executed').aggregate(t=Sum('amount_requested'))['t'] or 0,
    }

    context = {
        'proposals': proposals_data,
        'campaigns': campaigns,
        'campaigns_available': campaigns_with_available,
        'role': role,
        'selected_campaign': campaign_filter,
        'stats': stats,
    }
    return render(request, 'admin_panel/quanly_giaingan.html', context)


@login_required
def tao_yeucau_giaingan(request):
    if request.method == 'POST':
        try:
            campaign_id = request.POST.get('campaign_id')
            campaign = get_object_or_404(Campaign, pk=campaign_id)

            if not request.user.is_superuser:
                my_org = request.user.managed_organizations.first()
                if campaign.organization != my_org:
                    messages.error(request, "Bạn không có quyền tạo yêu cầu giải ngân cho chiến dịch này!")
                    return redirect('admin_panel:quanly_giaingan')

            amount = Decimal(request.POST.get('amount_requested', '0'))
            total_gas_fees = Donation.objects.filter(
                campaign=campaign, gas_fee_vnd__isnull=False
            ).aggregate(total=Sum('gas_fee_vnd'))['total'] or Decimal('0')
            net_receivable = campaign.current_amount - total_gas_fees
            available = net_receivable - campaign.disbursed_amount - campaign.locked_amount
            if amount > available:
                messages.error(request, f"Số tiền vượt quá số dư khả dụng ({int(available):,}đ). Đã trừ phí gas {int(total_gas_fees):,}đ.")
                return redirect('admin_panel:quanly_giaingan')

            proposal = DisbursementProposal()
            proposal.campaign = campaign
            proposal.title = request.POST.get('title')
            proposal.amount_requested = amount
            proposal.purpose = request.POST.get('purpose')
            proposal.description = request.POST.get('description')
            proposal.recipient_name = request.POST.get('recipient_name')
            proposal.evidence_url = request.POST.get('evidence_url', '')
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
