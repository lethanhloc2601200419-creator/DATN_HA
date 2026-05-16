/**
 * v3-disbursement-sign.js — EIP-712 off-chain signing for 3-party multisig.
 *
 * Luồng UX (GASLESS cho approver):
 *   1. Approver (Org / Supervisor / Admin) bấm "Ký off-chain" trên 1 proposal.
 *   2. FE call GET /admin/api/v3/disbursement/<pk>/sign-payload/?role=...
 *      → nhận EIP-712 typed-data.
 *   3. FE gọi window.ethereum.request({method:'eth_signTypedData_v4', params:[from, data]})
 *      → MetaMask popup, user ký, 0 gas.
 *   4. FE POST signature về /admin/api/v3/disbursement/submit-signature/.
 *   5. Backend verify + lưu DB. Khi đủ 3 sig → admin có thể bấm
 *      "Relay lên chain" để submit 1 tx duy nhất lên smart3.
 *
 * Expose: window.V3Disbursement.signAs(proposalId, role)
 */
(function () {
  'use strict';

  const CSRF_TOKEN = (document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/) || [])[1] || '';
  let refreshTimer = null;

  function schedulePageRefresh(delayMs) {
    if (refreshTimer) window.clearTimeout(refreshTimer);
    refreshTimer = window.setTimeout(() => {
      if (document.hidden) {
        schedulePageRefresh(2000);
        return;
      }
      window.location.reload();
    }, delayMs);
  }

  async function getMetaMaskAccount() {
    if (!window.ethereum) {
      throw new Error('Không tìm thấy MetaMask. Vui lòng cài đặt extension và kết nối.');
    }
    const accounts = await window.ethereum.request({ method: 'eth_requestAccounts' });
    if (!accounts || !accounts.length) {
      throw new Error('MetaMask chưa mở ví.');
    }
    return accounts[0];
  }

  async function fetchSignPayload(proposalId, role) {
    const res = await fetch(`/admin/api/v3/disbursement/${proposalId}/sign-payload/?role=${encodeURIComponent(role)}`, {
      method: 'GET',
      credentials: 'same-origin',
      headers: { 'Accept': 'application/json' },
    });
    console.log('Response text for sign-payload:', await res.clone().text());
    const data = await res.json();
    if (!res.ok || !data.ok) {
      throw new Error(data.message || `GET sign-payload failed (${res.status})`);
    }
    // Ensure chainId and name are explicitly set
    if (data.typed_data && data.typed_data.domain) {
      data.typed_data.domain.chainId = 11155111;
      data.typed_data.domain.name = 'DisbursementExecutor';
      data.typed_data.domain.version = '1';
    }
    return data;
  }

  async function submitSignatureToBackend(proposalId, body) {
    const url = "/admin/api/v3/disbursement/" + proposalId + "/submit-signature/";
    console.log(">>> CALLING URL:", url);
    const res = await fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': CSRF_TOKEN,
      },
      body: JSON.stringify(body),
    });
    console.log('Response text for submit-signature:', await res.clone().text());
    const data = await res.json();
    if (!res.ok || !data.ok) {
      throw new Error(data.message || `POST submit-signature failed (${res.status})`);
    }
    return data;
  }

  async function readJsonResponse(res, actionLabel) {
    const text = await res.text();
    try {
      return text ? JSON.parse(text) : {};
    } catch (err) {
      const preview = text.trim().slice(0, 240) || `HTTP ${res.status}`;
      throw new Error(`${actionLabel} không trả JSON hợp lệ: ${preview}`);
    }
  }

  /**
   * Main entry: user bấm "Ký off-chain" trên proposal.
   * role ∈ {'organization', 'supervisor', 'admin'}.
   */
  async function signAs(proposalId, role) {
    try {
      const account = await getMetaMaskAccount();
      const payload = await fetchSignPayload(proposalId, role);
      // typed_data phải truyền dưới dạng JSON string tới MetaMask.
      const typedDataStr = JSON.stringify(payload.typed_data);
      const signature = await window.ethereum.request({
        method: 'eth_signTypedData_v4',
        params: [account, typedDataStr],
      });
      const result = await submitSignatureToBackend(proposalId, {
        role,
        signer_address: account,
        signature,
        nonce: payload.nonce,
        deadline: payload.deadline,
        amount_raw: payload.amount_raw,
        recipient: payload.recipient,
        ipfs_cid: payload.ipfs_cid,
      });
      if (typeof window.showToast === 'function') {
        window.showToast(`✅ Ký thành công (${role}). Tổng chữ ký: ${result.total_sigs}/3`, 'success');
      } else {
        alert(`✅ Ký thành công (${role}). Tổng chữ ký: ${result.total_sigs}/3. v3_status=${result.v3_status}`);
      }
      if (result.ready_to_relay) {
        setTimeout(() => window.location.reload(), 900);
      }
      return result;
    } catch (err) {
      console.error('[V3-sign] error', err);
      alert('❌ Ký thất bại: ' + (err.message || err));
      throw err;
    }
  }

  /** Admin relayer: submit 3 sigs lên smart3. */
  async function relayMultisig(proposalId) {
    if (!confirm('Bạn sẽ submit 3 chữ ký lên smart3 (ví Admin trả gas). Tiếp tục?')) return;
    try {
      const res = await fetch(`/admin/api/v3/disbursement/${proposalId}/relay-multisig/`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Accept': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
      });
      const data = await readJsonResponse(res, 'Relay');
      if (!res.ok || !data.ok) throw new Error(data.message || `HTTP ${res.status}`);
      if (data.pending_confirmation) {
        alert(`✅ Đã gửi relay tx lên chain. tx=${data.tx_hash}\nHệ thống sẽ tự cập nhật khi Sepolia confirm.`);
        schedulePageRefresh(2500);
      } else {
        alert(`✅ MultisigConfirmed on-chain. tx=${data.tx_hash}`);
        window.location.reload();
      }
    } catch (err) {
      alert('❌ Relay thất bại: ' + (err.message || err));
    }
  }

  /** Admin trigger PayOS payout (mock). */
  async function triggerPayout(proposalId) {
    if (!confirm('Gửi lệnh chuyển tiền PayOS? (mock hoặc real tuỳ config)')) return;
    try {
      const res = await fetch(`/admin/api/v3/disbursement/${proposalId}/trigger-payout/`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Accept': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
      });
      const data = await readJsonResponse(res, 'PayOS payout');
      if (!res.ok || !data.ok) throw new Error(data.message || `HTTP ${res.status}`);
      alert(`✅ Đã gửi lệnh PayOS. payout_id=${data.payout_id}${data.mock ? ' (MOCK)' : ''}`);
      schedulePageRefresh(2500);
    } catch (err) {
      alert('❌ Trigger payout thất bại: ' + (err.message || err));
    }
  }

  /** [DEV] Simulate webhook success để test pipeline burn. */
  async function simulateWebhook(proposalId) {
    if (!confirm('[DEV] Giả PayOS webhook success → sẽ trigger burn on-chain?')) return;
    try {
      const res = await fetch(`/admin/api/v3/disbursement/${proposalId}/simulate-webhook/`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'X-CSRFToken': CSRF_TOKEN },
      });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.message || `HTTP ${res.status}`);
      alert(`✅ Mock webhook OK. bank_tx_id=${data.bank_tx_id}. Đang burn on-chain ở background…`);
      setTimeout(() => window.location.reload(), 1500);
    } catch (err) {
      alert('❌ Simulate webhook thất bại: ' + (err.message || err));
    }
  }

  window.V3Disbursement = { signAs, relayMultisig, triggerPayout, simulateWebhook };

  const autoRefresh = window.V3_DISBURSEMENT_AUTO_REFRESH || {};
  if (autoRefresh.enabled) {
    schedulePageRefresh(Number(autoRefresh.intervalMs) || 5000);
  }
})();
