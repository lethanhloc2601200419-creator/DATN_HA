from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from admin_panel.models import ActivityLog, CampaignDisbursement
from client.blockchain import BlockchainService


EVENT_LOOKBACK_BLOCKS = 5000


def trigger_fiat_bank_transfer(org_bank_account, amount):
    account_no = org_bank_account.get('account_number') or 'unknown'
    bank_name = org_bank_account.get('bank_name') or 'unknown'
    account_name = org_bank_account.get('account_name') or 'unknown'
    transfer_ref = f"MOCKBANK-{timezone.now().strftime('%Y%m%d%H%M%S')}"
    print(
        f"[MOCK BANK] Transfer success -> bank={bank_name}, "
        f"account={account_no}, holder={account_name}, amount={amount}, ref={transfer_ref}"
    )
    return {
        'success': True,
        'reference': transfer_ref,
        'message': 'Mock bank transfer completed.',
    }


def _match_disbursement_event(events, proposal):
    for event in reversed(events):
        args = event.get('args', {})
        event_cid = args.get('ipfsCid') or ''
        if proposal.ipfs_cid and event_cid != proposal.ipfs_cid:
            continue
        return event
    return None


def sync_disbursement_proposal_status(proposal, lookback_blocks=EVENT_LOOKBACK_BLOCKS):
    bc = BlockchainService()
    latest_block = bc.w3.eth.block_number
    from_block = max(0, latest_block - int(lookback_blocks))
    events = bc.get_disbursed_and_burned_events(
        campaign_id=proposal.campaign_id,
        from_block=from_block,
        to_block=latest_block,
    )
    matched_event = _match_disbursement_event(events, proposal)
    if not matched_event:
        return {
            'synced': False,
            'message': f'Không tìm thấy sự kiện DisbursedAndBurned trong {lookback_blocks} block gần nhất.',
            'latest_block': latest_block,
            'from_block': from_block,
        }

    event_args = matched_event.get('args', {})
    tx_hash = matched_event['transactionHash'].hex()
    amount_burned = Decimal(str(event_args.get('amountBurned', 0)))
    event_cid = event_args.get('ipfsCid') or ''

    if proposal.status == 'executed' and proposal.disbursement_eth_tx_hash == tx_hash:
        return {
            'synced': True,
            'already_synced': True,
            'tx_hash': tx_hash,
            'amount_burned': amount_burned,
            'ipfs_cid': event_cid,
        }

    with transaction.atomic():
        proposal = proposal.__class__.objects.select_for_update().select_related('campaign', 'campaign__organization').get(pk=proposal.pk)
        campaign = proposal.campaign
        organization = campaign.organization

        if proposal.status != 'executed':
            campaign.disbursed_amount = (campaign.disbursed_amount or Decimal('0')) + proposal.amount_requested
            campaign.locked_amount = max(Decimal('0'), (campaign.locked_amount or Decimal('0')) - proposal.amount_requested)
            campaign.save(update_fields=['disbursed_amount', 'locked_amount'])

        proposal.status = 'executed'
        proposal.executed_at = proposal.executed_at or timezone.now()
        proposal.disbursement_eth_tx_hash = tx_hash
        proposal.save(update_fields=['status', 'executed_at', 'disbursement_eth_tx_hash'])

        mock_transfer = trigger_fiat_bank_transfer(
            {
                'bank_name': organization.bank_name if organization else '',
                'account_number': organization.bank_account_number if organization else '',
                'account_name': organization.bank_account_name if organization else '',
            },
            proposal.amount_requested,
        )

        CampaignDisbursement.objects.get_or_create(
            proposal=proposal,
            defaults={
                'campaign': campaign,
                'reporter': proposal.created_by or campaign.creator,
                'amount': proposal.amount_requested,
                'title': proposal.title,
                'description': proposal.description,
                'recipient_name': proposal.recipient_name or (organization.name if organization else 'Unknown'),
                'proof_document_url': proposal.evidence_url,
                'eth_tx_hash': tx_hash,
                'status': 'on_chain',
                'admin_note': f"Mock bank transfer ref: {mock_transfer['reference']}",
            },
        )

        ActivityLog.objects.create(
            user=proposal.approved_by,
            type='disbursement_burn_synced',
            description=(
                f'Sync DisbursedAndBurned cho proposal #{proposal.id}. '
                f'tx={tx_hash}, amountBurned={amount_burned}, ipfsCid={event_cid}, '
                f'bankRef={mock_transfer["reference"]}'
            ),
            campaign=campaign,
        )

    return {
        'synced': True,
        'tx_hash': tx_hash,
        'amount_burned': amount_burned,
        'ipfs_cid': event_cid,
        'latest_block': latest_block,
        'from_block': from_block,
    }
