import { createWalletClient, custom, encodeFunctionData, http, parseAbi } from "https://esm.sh/viem@2.31.4?bundle";
import { createBundlerClient, createPaymasterClient } from "https://esm.sh/viem@2.31.4/account-abstraction?bundle";
import { sepolia } from "https://esm.sh/viem@2.31.4/chains?bundle";
import { alchemyTransport } from "https://esm.sh/@alchemy/common?bundle";
import { estimateFeesPerGas } from "https://esm.sh/@alchemy/aa-infra?bundle";
import { toNexusAccount, getMEEVersion, MEEVersion } from "https://esm.sh/@biconomy/abstractjs@1.0.48?bundle";

// Security note: whitelist your production domain in the Alchemy dashboard
// so this browser-side Policy ID cannot be reused from unauthorized origins.

const configNode = document.getElementById("disbursement-proposal-config");
const config = configNode ? JSON.parse(configNode.textContent) : null;
const form = document.getElementById("disbursementProposalForm");

if (!form || !config) {
  // Nothing to initialize on pages that do not render the proposal modal.
} else {
  const submitButton = form.querySelector('button[type="submit"]');
  const statusBox = document.getElementById("disbursementStatusBox");
  const statusText = document.getElementById("disbursementStatusText");
  const campaignInput = form.querySelector('input[name="campaign_id"]');
  const invoiceInput = form.querySelector('input[name="invoice_file"]');
  const ipfsCidInput = form.querySelector('input[name="ipfs_cid"]');
  const ipfsGatewayInput = form.querySelector('input[name="ipfs_gateway_url"]');
  const txHashInput = form.querySelector('input[name="proposal_tx_hash"]');

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

    const response = await fetch(config.ipfsUploadUrl, {
      method: "POST",
      headers: {
        "X-CSRFToken": getCookie("csrftoken"),
      },
      credentials: "same-origin",
      body: payload,
    });

    const result = await response.json();
    if (!response.ok || !result.ok) {
      throw new Error(result.message || "Upload IPFS thất bại.");
    }

    return result;
  }

  async function ensureWeb3Context() {
    if (!window.dcpWeb3?.ensureConnected) {
      throw new Error("Web3Auth chưa sẵn sàng trên trang này.");
    }

    const walletContext = await window.dcpWeb3.ensureConnected();
    const synced = await window.dcpWeb3.syncWalletAddress({
      eoaAddress: walletContext.eoaAddress,
      smartAccountAddress: walletContext.smartAccountAddress,
    });
    window.dcpWeb3.updateWalletBadge(synced.smart_account_address);

    return {
      ...walletContext,
      syncedSmartAccountAddress: synced.smart_account_address,
    };
  }

  async function sendGaslessProposalTx({ provider, eoaAddress, smartAccountAddress, campaignId, ipfsCid }) {
    if (!config.contractAddress) {
      throw new Error("Thiếu CONTRACT_ADDRESS trong cấu hình frontend.");
    }
    if (!config.alchemyApiKey) {
      throw new Error("Không đọc được Alchemy API key từ SEPOLIA_RPC_URL.");
    }
    if (!config.alchemyPolicyId) {
      throw new Error("Thiếu ALCHEMY_POLICY_ID trong cấu hình frontend.");
    }

    const walletClient = createWalletClient({
      account: eoaAddress,
      chain: sepolia,
      transport: custom(provider),
    });

    const account = await toNexusAccount({
      signer: walletClient,
      chainConfiguration: {
        chain: sepolia,
        transport: http(config.rpcTarget),
        version: getMEEVersion(MEEVersion.V2_1_0),
        accountAddress: smartAccountAddress || undefined,
      },
    });

    const transport = alchemyTransport({ apiKey: config.alchemyApiKey });
    const bundlerClient = createBundlerClient({
      account,
      chain: sepolia,
      transport,
      userOperation: {
        estimateFeesPerGas,
      },
      paymaster: createPaymasterClient({ transport }),
      paymasterContext: {
        policyId: config.alchemyPolicyId,
      },
    });

    const callData = encodeFunctionData({
      abi: parseAbi(["function proposeDisbursement(uint256 _campaignId, string _ipfsCid)"]),
      functionName: "proposeDisbursement",
      args: [BigInt(campaignId), ipfsCid],
    });

    const userOpHash = await bundlerClient.sendUserOperation({
      calls: [
        {
          to: config.contractAddress,
          data: callData,
          value: 0n,
        },
      ],
    });

    const receipt = await bundlerClient.waitForUserOperationReceipt({ hash: userOpHash });
    const transactionHash =
      receipt?.receipt?.transactionHash ||
      receipt?.transactionHash ||
      receipt?.hash ||
      "";

    if (!transactionHash) {
      throw new Error("Không lấy được transaction hash từ Alchemy bundler receipt.");
    }

    return {
      userOpHash,
      transactionHash,
      smartAccountAddress: account.address,
    };
  }

  form.addEventListener("submit", async (event) => {
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
      ipfsCidInput.value = uploadResult.cid;
      ipfsGatewayInput.value = uploadResult.gateway_url;

      setStatus("IPFS thành công. Đang kết nối Smart Account và gửi giao dịch gasless...", "info");
      const walletContext = await ensureWeb3Context();
      const txResult = await sendGaslessProposalTx({
        provider: walletContext.provider,
        eoaAddress: walletContext.eoaAddress,
        smartAccountAddress: walletContext.syncedSmartAccountAddress || walletContext.smartAccountAddress,
        campaignId,
        ipfsCid: uploadResult.cid,
      });

      txHashInput.value = txResult.transactionHash;
      window.dcpWeb3.updateWalletBadge(txResult.smartAccountAddress);
      setStatus("Đã ghi đề xuất lên Sepolia. Hệ thống đang lưu hồ sơ vào Django...", "success");
      form.submit();
    } catch (error) {
      const message = error?.message || "Không thể tạo yêu cầu giải ngân gasless.";
      setStatus(message, "danger");
      window.dcpWeb3?.showToast?.(message, "error");
      setSubmittingState(false);
    }
  });
}
