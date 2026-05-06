from decimal import Decimal
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum


def estimate_gas_per_tx_vnd(eth_vnd_rate, multiplier=2, bc=None):
    """
    Ước tính phí gas cho 1 giao dịch giải ngân tương lai dựa trên gas thực tế gần nhất x2.
    Luồng v2: lấy từ recent donations (bao gồm cả gas A+B của luồng async mới)
    + disbursement history + legacy sendEthToUser.
    Nếu không có dữ liệu thực tế, dùng blockchain gas price ước tính.
    Returns: (estimated_vnd, estimated_wei)
    """
    from admin_panel.models import Donation, DisbursementProposal

    # Luồng mới v2: gas A (recordBankDonation) + gas B (donateOnBehalf)
    recent_a = list(
        Donation.objects.filter(
            bank_record_gas_wei__isnull=False, bank_record_gas_wei__gt=0
        ).order_by('-id')[:10].values_list('bank_record_gas_wei', flat=True)
    )
    recent_b = list(
        Donation.objects.filter(
            donate_onbehalf_gas_wei__isnull=False, donate_onbehalf_gas_wei__gt=0
        ).order_by('-id')[:10].values_list('donate_onbehalf_gas_wei', flat=True)
    )
    # Legacy sendEthToUser (luồng cũ - giữ để tương thích)
    recent_sendeth = list(
        Donation.objects.filter(
            admin_send_eth_gas_fee_wei__isnull=False, admin_send_eth_gas_fee_wei__gt=0
        ).order_by('-id')[:10].values_list('admin_send_eth_gas_fee_wei', flat=True)
    )
    # Disbursement gas
    recent_disburse = list(
        DisbursementProposal.objects.filter(
            disbursement_gas_fee_wei__isnull=False, disbursement_gas_fee_wei__gt=0
        ).order_by('-id')[:10].values_list('disbursement_gas_fee_wei', flat=True)
    )

    all_recent = [int(v) for v in recent_a + recent_b + recent_sendeth + recent_disburse]

    if all_recent:
        max_gas_wei = max(all_recent)
        est_wei = int(max_gas_wei * multiplier)
    else:
        from django.conf import settings as django_settings
        if bc is None:
            from client.blockchain import BlockchainService
            bc = BlockchainService()
        fixed_gwei = getattr(django_settings, 'ADMIN_GAS_PRICE_GWEI', None)
        gas_price = bc.w3.to_wei(fixed_gwei, 'gwei') if fixed_gwei else bc.w3.eth.gas_price
        est_wei = int(gas_price * 200000 * multiplier)

    est_eth = Decimal(str(est_wei)) / Decimal('1000000000000000000')
    est_vnd = est_eth * eth_vnd_rate
    return est_vnd, est_wei


def check_and_execute_proposal(proposal):
    """
    Kiểm tra xem proposal đã đủ điều kiện thực thi chưa.
    Điều kiện:
    1. Tất cả người ủng hộ đã vote VÀ yes > 50%
    2. Hết thời gian vote VÀ yes > 50%

    Returns: (executed: bool, error: str|None)
        - (True, None) = giải ngân thành công trên blockchain + DB
        - (False, None) = chưa đủ điều kiện hoặc bị từ chối
        - (False, error_msg) = đủ điều kiện nhưng blockchain thất bại
    """
    if proposal.status != 'voting':
        return False, None

    from admin_panel.models import ProposalVote

    campaign = proposal.campaign
    voting_powers, total_system_power = campaign.calculate_voting_distribution()

    votes = ProposalVote.objects.filter(proposal=proposal)
    total_yes = votes.filter(is_agree=True).aggregate(t=Sum('voting_power'))['t'] or Decimal('0')
    total_no = votes.filter(is_agree=False).aggregate(t=Sum('voting_power'))['t'] or Decimal('0')
    total_voted = total_yes + total_no

    total_donors = len(voting_powers)
    total_voters = votes.count()

    all_voted = total_voters >= total_donors and total_donors > 0
    time_expired = proposal.end_date and timezone.now() >= proposal.end_date

    if total_voted > 0:
        yes_pct = (total_yes / total_voted) * 100
    else:
        yes_pct = 0

    should_execute = (all_voted or time_expired) and yes_pct > 50
    should_reject = time_expired and yes_pct <= 50

    if should_execute:
        try:
            execute_proposal_disbursement(proposal)
            return True, None
        except Exception as e:
            error_msg = str(e)
            print(f"❌ [DISBURSEMENT] Vote đạt điều kiện nhưng blockchain thất bại: {error_msg}")
            return False, f"Vote đã thông qua nhưng giải ngân blockchain thất bại: {error_msg}"

    if should_reject:
        with transaction.atomic():
            proposal.status = 'rejected'
            proposal.save(update_fields=['status'])
            campaign.locked_amount = max(Decimal('0'), campaign.locked_amount - proposal.amount_requested)
            campaign.save(update_fields=['locked_amount'])
        return False, None

    return False, None


def execute_proposal_disbursement(proposal):
    """
    Thực thi giải ngân sau khi vote thông qua:
    1. Gọi blockchain executeDisbursement TRƯỚC
    2. Chờ xác nhận giao dịch on-chain
    3. Nếu thành công → cập nhật DB (status, amounts, records)
    4. Nếu thất bại → raise exception, KHÔNG đổi DB
    """
    from admin_panel.models import (
        CampaignDisbursement, BankStatement, ActivityLog,
    )
    from client.blockchain import BlockchainService, get_eth_vnd_rate, invalidate_campaign_cache

    campaign = proposal.campaign

    # ===== BƯỚC 1: GỌI BLOCKCHAIN TRƯỚC =====
    bc = BlockchainService()
    eth_vnd_rate = get_eth_vnd_rate()
    amount_vnd = Decimal(str(proposal.amount_requested))
    amount_eth = amount_vnd / eth_vnd_rate
    amount_wei = int(amount_eth * Decimal('1000000000000000000'))

    print(f"🚀 [BLOCKCHAIN] Đang giải ngân {amount_vnd:,.0f} VNĐ = {amount_eth:.10f} ETH cho chiến dịch #{campaign.id}...")
    tx_hash = bc.execute_disbursement(
        campaign_id=campaign.id,
        amount_wei=amount_wei,
    )

    receipt = bc.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if not receipt or receipt.get('status') != 1:
        raise Exception(f"Giao dịch giải ngân bị revert trên blockchain. Tx: {tx_hash}")

    invalidate_campaign_cache(campaign.id)
    print(f"✅ [BLOCKCHAIN] executeDisbursement thành công! Hash: {tx_hash}")

    # ===== BƯỚC 2: BLOCKCHAIN OK → CẬP NHẬT DB =====
    with transaction.atomic():
        proposal.status = 'executed'
        proposal.executed_at = timezone.now()
        proposal.disbursement_eth_tx_hash = tx_hash
        proposal.save(update_fields=['status', 'executed_at', 'disbursement_eth_tx_hash'])

        campaign.locked_amount = max(Decimal('0'), campaign.locked_amount - proposal.amount_requested)
        campaign.disbursed_amount = campaign.disbursed_amount + proposal.amount_requested
        campaign.save(update_fields=['locked_amount', 'disbursed_amount'])

        from django.contrib.auth.models import User
        fallback_reporter = proposal.created_by or proposal.approved_by or User.objects.filter(is_superuser=True).first()

        disbursement = CampaignDisbursement.objects.create(
            campaign=campaign,
            proposal=proposal,
            reporter=fallback_reporter,
            amount=proposal.amount_requested,
            title=proposal.title,
            description=proposal.description,
            recipient_name=proposal.recipient_name or '',
            proof_images=proposal.proof_images,
            status='verified',
            eth_tx_hash=tx_hash,
        )

        BankStatement.objects.create(
            campaign=campaign,
            transaction_date=timezone.now(),
            transaction_type='out',
            amount=proposal.amount_requested,
            description=f"Giải ngân: {proposal.title} - {proposal.recipient_name or campaign.organization.name if campaign.organization else ''}",
            source='manual',
        )

        ActivityLog.objects.create(
            type='disbursement_executed',
            description=f"Giải ngân #{proposal.id}: {proposal.amount_requested:,}đ cho chiến dịch '{campaign.title}' - {proposal.title}. Tx: {tx_hash}",
            campaign=campaign,
        )

    # ===== BƯỚC 3: LƯU GAS FEE (không critical) =====
    try:
        gas_info = bc.get_transaction_gas_fee(tx_hash)
        proposal.disbursement_gas_fee_wei = gas_info['gas_fee_wei']
        proposal.disbursement_gas_fee_vnd = int(gas_info['gas_fee_eth'] * eth_vnd_rate)
        proposal.save(update_fields=['disbursement_gas_fee_wei', 'disbursement_gas_fee_vnd'])
        print(f"⛽ [DISBURSEMENT GAS] {gas_info['gas_used']} units × {gas_info['gas_price_gwei']} Gwei = {gas_info['gas_fee_eth']:.10f} ETH = {proposal.disbursement_gas_fee_vnd:,} VNĐ")
    except Exception as ge:
        print(f"⚠️ Không thể lưu gas fee giải ngân: {ge}")
