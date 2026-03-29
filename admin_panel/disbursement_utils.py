from decimal import Decimal
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum


def check_and_execute_proposal(proposal):
    """
    Kiểm tra xem proposal đã đủ điều kiện thực thi chưa.
    Điều kiện:
    1. Tất cả người ủng hộ đã vote VÀ yes > 50%
    2. Hết thời gian vote VÀ yes > 50%
    """
    if proposal.status != 'voting':
        return False

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
        execute_proposal_disbursement(proposal)
        return True

    if should_reject:
        with transaction.atomic():
            proposal.status = 'rejected'
            proposal.save(update_fields=['status'])
            campaign.locked_amount = max(Decimal('0'), campaign.locked_amount - proposal.amount_requested)
            campaign.save(update_fields=['locked_amount'])
        return False

    return False


def execute_proposal_disbursement(proposal):
    """
    Thực thi giải ngân sau khi vote thông qua:
    1. Cập nhật proposal status = 'executed'
    2. Tạo CampaignDisbursement
    3. Tạo BankStatement(type='out')
    4. Cập nhật Campaign.disbursed_amount, locked_amount
    5. Gọi blockchain executeDisbursement
    6. Ghi ActivityLog
    """
    from admin_panel.models import (
        CampaignDisbursement, BankStatement, ActivityLog,
    )
    from client.blockchain import BlockchainService, get_eth_vnd_rate

    campaign = proposal.campaign

    with transaction.atomic():
        proposal.status = 'executed'
        proposal.executed_at = timezone.now()
        proposal.save(update_fields=['status', 'executed_at'])

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
            description=f"Giải ngân #{proposal.id}: {proposal.amount_requested:,}đ cho chiến dịch '{campaign.title}' - {proposal.title}",
            campaign=campaign,
        )

    try:
        bc = BlockchainService()
        eth_vnd_rate = get_eth_vnd_rate()
        amount_vnd = Decimal(str(proposal.amount_requested))
        amount_eth = amount_vnd / eth_vnd_rate
        amount_wei = int(amount_eth * Decimal('1000000000000000000'))

        tx_hash = bc.execute_disbursement(
            campaign_id=campaign.id,
            amount_wei=amount_wei,
        )
        proposal.disbursement_eth_tx_hash = tx_hash
        proposal.save(update_fields=['disbursement_eth_tx_hash'])
        if disbursement:
            disbursement.eth_tx_hash = tx_hash
            CampaignDisbursement.objects.filter(pk=disbursement.pk).update(eth_tx_hash=tx_hash)
        print(f"✅ [BLOCKCHAIN] executeDisbursement thành công! Hash: {tx_hash}")
    except Exception as e:
        print(f"❌ [BLOCKCHAIN] Lỗi executeDisbursement: {e}")
