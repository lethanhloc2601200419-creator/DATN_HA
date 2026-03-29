from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponseRedirect, JsonResponse
from admin_panel.models import (
    UserProfile, Campaign, Donation, TargetProgram, BankStatement, ActivityLog,
    DisbursementProposal, ProposalVote, Organization,
)
from admin_panel.disbursement_utils import check_and_execute_proposal
from django.contrib import messages
from django.db.models import Sum, Count, F, Q
from django.conf import settings
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db import transaction
import hashlib
import hmac
import urllib.parse
import json
from decimal import Decimal
from datetime import datetime, timedelta
import pytz
import re
import requests as http_requests

# Import Service Blockchain đã viết
from .blockchain import BlockchainService, get_eth_vnd_rate

# =====================================================
# VNPAY HELPER FUNCTIONS
# =====================================================
vietnam_tz = pytz.timezone('Asia/Ho_Chi_Minh')

def create_vnpay_signature(params, secret_key):
    """Tạo chữ ký VNPay (HMAC-SHA512)"""
    filtered_params = {k: v for k, v in params.items() if k != 'vnp_SecureHash' and v is not None and str(v) != ''}
    sorted_params = sorted(filtered_params.items())
    query_parts = [f"{k}={urllib.parse.quote(str(v), safe='')}" for k, v in sorted_params]
    sign_data = "&".join(query_parts)
    h = hmac.new(secret_key.encode('utf-8'), sign_data.encode('utf-8'), hashlib.sha512)
    return h.hexdigest()

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
            # 1. Lấy dữ liệu từ form
            amount = request.POST.get('amount').replace(',', '') # Xóa dấu phẩy
            message = request.POST.get('message')
            payment_method = request.POST.get('payment_method')
            donor_wallet_address = request.POST.get('donor_wallet_address')
            
            # 2. Tạo đối tượng Donation
            donation = Donation()
            donation.campaign = campaign
            donation.amount = amount
            donation.message = message
            donation.payment_method = payment_method
            donation.donor_wallet_address = donor_wallet_address or None
            
            # 3. Xử lý User (Đăng nhập hay vãng lai)
            if request.user.is_authenticated:
                donation.donor = request.user
                if hasattr(request.user, 'profile'):
                    donation.donor_name = request.user.profile.display_name 
                    if donation.donor_wallet_address:
                        request.user.profile.wallet_address = donation.donor_wallet_address
                        request.user.profile.save(update_fields=['wallet_address'])
                else:
                    donation.donor_name = request.user.username
                donation.donor_email = request.user.email
            else:
                donation.donor_name = request.POST.get('donor_name')
                donation.donor_email = request.POST.get('donor_email')
                donation.is_anonymous = True

            if payment_method == 'vnpay' and not donation.donor_wallet_address:
                messages.error(request, "Vui lòng kết nối MetaMask trước khi thanh toán VNPay.")
                return redirect('client:ungho', pk=campaign.id)
            if payment_method == 'vnpay' and donation.donor_wallet_address and donation.donor_wallet_address.lower() == settings.WALLET_ADDRESS.lower():
                messages.error(request, "Ví MetaMask đang là ví Admin. Vui lòng đổi sang ví người dùng trước khi thanh toán.")
                return redirect('client:ungho', pk=campaign.id)

            # 4. Lưu vào DB SQL trước
            donation.save()
            
            # ======================================================
            # CODE DEBUG GHI BLOCKCHAIN (Dành cho Tiền mặt/Chuyển khoản)
            # ======================================================
            if payment_method != 'vnpay':
                campaign.current_amount += int(amount)
                campaign.save()
                messages.success(request, "Cảm ơn tấm lòng vàng của bạn!")
                return redirect('client:camon', pk=donation.id)
            
            # --- XỬ LÝ NẾU LÀ VNPAY ---
            # Build VNPay params và redirect sang cổng thanh toán
            vn_now = datetime.now(vietnam_tz)
            
            vnpay_params = {
                'vnp_Version': '2.1.0',
                'vnp_Command': 'pay',
                'vnp_TmnCode': settings.VNPAY_TMN_CODE,
                'vnp_Amount': int(amount) * 100,
                'vnp_BankCode': 'VNBANK',
                'vnp_CreateDate': vn_now.strftime('%Y%m%d%H%M%S'),
                'vnp_CurrCode': 'VND',
                'vnp_IpAddr': get_client_ip(request),
                'vnp_Locale': 'vn',
                'vnp_OrderInfo': f'Ung-ho-chien-dich-{campaign.id}',
                'vnp_OrderType': 'other',
                'vnp_ReturnUrl': request.build_absolute_uri(reverse('client:vnpay_return')),
                'vnp_TxnRef': str(donation.id),
                'vnp_ExpireDate': (vn_now + timedelta(minutes=15)).strftime('%Y%m%d%H%M%S'),
            }
            
            signature = create_vnpay_signature(vnpay_params, settings.VNPAY_HASH_SECRET)
            vnpay_params['vnp_SecureHash'] = signature
            
            query_string = urllib.parse.urlencode(vnpay_params, quote_via=urllib.parse.quote)
            vnpay_url = f"{settings.VNPAY_URL}?{query_string}"
            
            print(f"\n🚀 [VNPAY] Redirecting to VNPay...")
            print(f"🔗 URL: {vnpay_url[:100]}...")
            
            return HttpResponseRedirect(vnpay_url)

        except Exception as e:
            messages.error(request, f"Lỗi xử lý: {e}")
            print(f"Lỗi hệ thống: {e}")

    return render(request, 'client/ungho.html', {
        'campaign': campaign,
        'admin_wallet_address': settings.WALLET_ADDRESS,
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

# ==========================================
# PHẦN MỚI: XỬ LÝ VNPAY RETURN + BLOCKCHAIN
# ==========================================

def vnpay_return(request):
    """
    Hàm này chạy khi User thanh toán xong trên VNPay và tự động quay về Web
    """
    input_data = request.GET.dict()
    if not input_data:
        return render(request, "client/payment_failed.html", {"message": "Không có dữ liệu trả về từ VNPay"})

    print("\n" + "="*50)
    print("[VNPAY RETURN] Callback Received")
    for key, value in input_data.items():
        print(f"  {key}: {value}")
    print("="*50)

    # 1. Lấy dữ liệu VNPay trả về
    vnp_SecureHash = input_data.get('vnp_SecureHash')
    vnp_ResponseCode = input_data.get('vnp_ResponseCode')
    vnp_TxnRef = input_data.get('vnp_TxnRef')  # ID của Donation
    vnp_Amount = input_data.get('vnp_Amount')
    vnp_OrderInfo = input_data.get('vnp_OrderInfo')

    if not all([vnp_SecureHash, vnp_TxnRef, vnp_ResponseCode]):
        return render(request, "client/payment_failed.html", {"message": "Dữ liệu VNPay trả về không hợp lệ"})

    # 2. Verify chữ ký (dùng cùng hàm create_vnpay_signature từ doan4)
    verify_params = {k: v for k, v in input_data.items() if k != 'vnp_SecureHash'}
    expected_hash = create_vnpay_signature(verify_params, settings.VNPAY_HASH_SECRET)

    print(f"[VNPAY] Expected Hash: {expected_hash[:30]}...")
    print(f"[VNPAY] Received Hash: {vnp_SecureHash[:30]}...")

    # 3. So sánh Hash
    if vnp_SecureHash.lower() != expected_hash.lower():
        print("[VNPAY] ❌ Signature mismatch!")
        return render(request, "client/payment_failed.html", {"message": "Sai chữ ký bảo mật (Checksum failed)"})

    print("[VNPAY] ✅ Signature verified!")

    if vnp_ResponseCode == "00":
        # Thanh toán thành công
        try:
            donation = Donation.objects.get(id=vnp_TxnRef)
            
            # Kiểm tra nếu chưa xử lý (tránh F5 cộng tiền 2 lần)
            if donation.status == 'pending':
                # Cập nhật thông tin VNPay vào donation
                donation.vnpay_transaction_no = input_data.get('vnp_TransactionNo', '')
                donation.status = 'completed'
                
                # Cộng tiền vào chiến dịch
                campaign = donation.campaign
                campaign.current_amount += donation.amount
                campaign.save()
                
                # --- TẠO BANKSTATEMENT TỰ ĐỘNG TỪ VNPAY ---
                try:
                    BankStatement.objects.create(
                        campaign=campaign,
                        donation=donation,
                        transaction_date=donation.created_at,
                        transaction_type='in',
                        amount=donation.amount,
                        reference_number=donation.vnpay_transaction_no,
                        description=f"VNPay: {donation.donor_name or 'Ẩn danh'} ủng hộ chiến dịch {campaign.title}",
                        sender_name=donation.donor_name,
                        source='vnpay',
                    )
                    print(f"✅ [BANKSTATEMENT] Đã tạo sao kê từ VNPay cho Donation #{donation.id}")
                except Exception as e:
                    print(f"❌ [BANKSTATEMENT] Lỗi tạo sao kê: {e}")

                # --- GỌI SMART CONTRACT CẤP ETH CHO USER ---
                blockchain_error = None
                try:
                    bc = BlockchainService()
                    if bc.admin_has_pending_tx():
                        raise Exception("Ví Admin đang có giao dịch pending. Vui lòng đợi xác nhận hoặc Speed Up trong MetaMask.")
                    if not bc.is_campaign_active(donation.campaign.id):
                        org = donation.campaign.organization
                        if not org or not org.wallet_address:
                            raise Exception("Chiến dịch chưa được khởi tạo on-chain và tổ chức chưa có ví.")
                        bc.init_campaign(
                            campaign_id=donation.campaign.id,
                            org_name=org.name,
                            org_address=org.wallet_address,
                        )

                    if not donation.donor_wallet_address:
                        raise Exception("Thiếu địa chỉ ví MetaMask của người dùng.")

                    eth_vnd_rate = get_eth_vnd_rate()
                    amount_vnd = Decimal(str(donation.amount))
                    amount_e_eth = amount_vnd / eth_vnd_rate
                    amount_e_wei = int(amount_e_eth * Decimal('1000000000000000000'))

                    try:
                        gas_limit = bc.contract.functions.donate(donation.campaign.id).estimate_gas({
                            'from': bc.w3.to_checksum_address(donation.donor_wallet_address),
                            'value': amount_e_wei,
                        })
                    except Exception:
                        gas_limit = 120000

                    gas_price = bc.w3.eth.gas_price
                    # Buffer 30% de tranh bien dong gas
                    amount_g_wei = int(gas_limit * gas_price * 1.3)

                    tx_hash = bc.send_eth_to_user(
                        campaign_id=donation.campaign.id,
                        user_address=donation.donor_wallet_address,
                        amount_e_wei=amount_e_wei,
                        amount_g_wei=amount_g_wei,
                    )

                    donation.send_eth_tx_hash = tx_hash
                    donation.donated_eth_wei = amount_e_wei
                    donation.gas_subsidy_wei = amount_g_wei

                    gas_fee_eth = Decimal(str(amount_g_wei)) / Decimal('1000000000000000000')
                    donation.gas_fee_eth = gas_fee_eth
                    donation.gas_fee_vnd = int(gas_fee_eth * eth_vnd_rate)
                    donation.net_amount = max(0, int(donation.amount) - int(donation.gas_fee_vnd or 0))

                    print(f"✅ Đã cấp ETH cho user: {tx_hash}")
                except Exception as e:
                    blockchain_error = str(e)
                    print(f"❌ Lỗi Blockchain: {blockchain_error}")
                
                donation.save()
                print(f"✅ [VNPAY] Donation #{donation.id} thanh toán thành công!")
            
            return render(request, "client/payment_success.html", {
                "donation": donation,
                "tx_hash": donation.eth_tx_hash,
                "send_eth_tx_hash": donation.send_eth_tx_hash,
                "amount_e_wei": str(donation.donated_eth_wei) if donation.donated_eth_wei is not None else '',
                "gas_g_wei": str(donation.gas_subsidy_wei) if donation.gas_subsidy_wei is not None else '',
                "wallet_address": donation.donor_wallet_address,
                "contract_address": settings.SMART_CONTRACT_ADDRESS,
                "contract_abi": json.dumps([{
                    "inputs": [{"internalType": "uint256", "name": "_cid", "type": "uint256"}],
                    "name": "donate",
                    "outputs": [],
                    "stateMutability": "payable",
                    "type": "function",
                }]),
                "blockchain_error": blockchain_error,
            })

        except Donation.DoesNotExist:
            return render(request, "client/payment_failed.html", {"message": "Không tìm thấy giao dịch"})
    else:
        print(f"[VNPAY] ❌ Payment failed with code: {vnp_ResponseCode}")
        return render(request, "client/payment_failed.html", {"message": f"Giao dịch bị hủy hoặc lỗi tại ngân hàng (Mã: {vnp_ResponseCode})"})
    

# client/views.py

def chitiet_chiendich(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    donations = Donation.objects.filter(campaign=campaign).order_by('-created_at')

    # Tính tổng phí gas của chiến dịch
    total_gas_vnd = Donation.objects.filter(
        campaign=campaign, gas_fee_vnd__isnull=False
    ).aggregate(total=Sum('gas_fee_vnd'))['total'] or Decimal('0')
    net_receivable = campaign.current_amount - total_gas_vnd

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

    check_and_execute_proposal(proposal)

    vote_text = 'đồng ý' if is_agree else 'từ chối'
    messages.success(request, f'Đã bỏ phiếu {vote_text} thành công!')
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
