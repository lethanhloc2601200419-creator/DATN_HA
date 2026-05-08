// ============================================================
// V3 CREATE-DISBURSEMENT FORM — OFF-CHAIN ONLY
// ------------------------------------------------------------
// Phase 1 của workflow V3 đã thuần off-chain. Modal "Tạo yêu cầu
// giải ngân" chỉ cần:
//   1) Upload hóa đơn/chứng từ lên Pinata → nhận IPFS CID.
//   2) Điền CID + gateway URL vào hidden inputs.
//   3) Submit form natively cho Django lưu DisbursementProposal
//      với v3_status='pending_multisig'.
//
// KHÔNG còn gọi Biconomy Nexus / Alchemy bundler / proposeDisbursement
// on-chain ở bước này — 3 approver sẽ ký EIP-712 ở Phase 2 qua
// v3-disbursement-sign.js, và smart3 chỉ ghi nhận khi đủ 3 sig.
// ============================================================

const configNode = document.getElementById("disbursement-proposal-config");
const config = configNode ? JSON.parse(configNode.textContent) : null;
const form = document.getElementById("disbursementProposalForm");

console.log("[V3 Disbursement] proposal JS loaded", { hasForm: !!form, hasConfig: !!config, ipfsUploadUrl: config?.ipfsUploadUrl });

if (form && config) {
  const submitButton = form.querySelector('button[type="submit"]');
  const statusBox = document.getElementById("disbursementStatusBox");
  const statusText = document.getElementById("disbursementStatusText");
  const campaignInput = form.querySelector('input[name="campaign_id"]');
  const invoiceInput = form.querySelector('input[name="invoice_file"]');
  const ipfsCidInput = form.querySelector('input[name="ipfs_cid"]');
  const ipfsGatewayInput = form.querySelector('input[name="ipfs_gateway_url"]');

  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) {
      return parts.pop().split(";").shift();
    }
    return "";
  }

  function setSubmittingState(isSubmitting, label = "Gửi yêu cầu") {
    if (!submitButton) return;
    submitButton.disabled = isSubmitting;
    submitButton.innerHTML = isSubmitting
      ? '<i class="fas fa-spinner fa-spin"></i> Đang xử lý'
      : `<i class="fas fa-paper-plane"></i> ${label}`;
  }

  function setStatus(message, type = "info") {
    if (statusBox) {
      statusBox.className = `alert alert-${type}`;
      statusBox.classList.remove("d-none");
    }
    if (statusText) {
      statusText.textContent = message;
    }
  }

  function clearStatus() {
    if (statusBox) {
      statusBox.className = "alert alert-info d-none";
    }
    if (statusText) {
      statusText.textContent = "";
    }
  }

  function getSelectedCampaignId() {
    const checked = form.querySelector(".campaign-radio:checked");
    if (checked) return checked.value;
    return campaignInput?.value || "";
  }

  async function uploadInvoice(campaignId) {
    if (!invoiceInput?.files?.length) {
      throw new Error("Vui lòng chọn hóa đơn hoặc chứng từ trước khi gửi.");
    }

    const payload = new FormData();
    payload.append("campaign_id", campaignId);
    payload.append("invoice_file", invoiceInput.files[0]);

    console.log("[V3 Disbursement] Uploading to Pinata via", config.ipfsUploadUrl, "file:", invoiceInput.files[0]?.name);
    const response = await fetch(config.ipfsUploadUrl, {
      method: "POST",
      headers: {
        "X-CSRFToken": getCookie("csrftoken"),
      },
      credentials: "same-origin",
      body: payload,
    });

    let result;
    try {
      result = await response.json();
    } catch (parseErr) {
      console.error("[V3 Disbursement] Pinata endpoint returned non-JSON:", parseErr);
      throw new Error("Server IPFS trả response không hợp lệ (HTTP " + response.status + ").");
    }
    console.log("[V3 Disbursement] Pinata response:", { httpStatus: response.status, result });
    if (!response.ok || !result.ok) {
      throw new Error(result.message || "Upload IPFS thất bại (HTTP " + response.status + ").");
    }
    if (!result.cid) {
      throw new Error("Pinata không trả về CID.");
    }

    return result;
  }

  // Guard flag để tránh vòng lặp vô hạn khi form.submit() được gọi
  // lại chương trình sau khi đã upload IPFS xong.
  let submittingNatively = false;

  form.addEventListener("submit", async (event) => {
    if (submittingNatively) {
      // Native submit pass — cho browser xử lý bình thường.
      return;
    }

    event.preventDefault();
    clearStatus();

    const campaignId = getSelectedCampaignId();
    if (!campaignId) {
      setStatus("Vui lòng chọn chiến dịch trước khi tạo yêu cầu giải ngân.", "warning");
      return;
    }

    if (campaignInput) {
      campaignInput.value = campaignId;
    }

    setSubmittingState(true);

    try {
      setStatus("Đang upload hóa đơn lên IPFS qua Pinata...", "info");
      const uploadResult = await uploadInvoice(campaignId);
      if (ipfsCidInput) ipfsCidInput.value = uploadResult.cid || "";
      if (ipfsGatewayInput) ipfsGatewayInput.value = uploadResult.gateway_url || "";
      console.log("[V3 Disbursement] CID populated into hidden inputs. Submitting form natively. cid=", uploadResult.cid);

      setStatus("Upload IPFS thành công. Đang lưu yêu cầu vào hệ thống...", "success");
      submittingNatively = true;
      form.submit();
    } catch (error) {
      console.error("[V3 Disbursement] submit failed:", error);
      const message = error?.message || "Không thể tạo yêu cầu giải ngân.";
      setStatus(message, "danger");
      if (window.dcpWeb3?.showToast) {
        window.dcpWeb3.showToast(message, "error");
      }
      setSubmittingState(false);
    }
  });
}
