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
const buttons = document.querySelectorAll(".js-disbursement-approve");

if (config && buttons.length) {
  function setButtonBusy(button, isBusy) {
    if (!button) return;
    if (isBusy) {
      button.dataset.originalLabel = button.innerHTML;
      button.disabled = true;
      button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Đang xử lý';
    } else if (button.dataset.originalLabel) {
      button.innerHTML = button.dataset.originalLabel;
    }
  }

  async function ensureApproverWallet(expectedRole) {
    if (!window.dcpWeb3?.ensureConnected) {
      throw new Error("Web3Auth chưa sẵn sàng để ký duyệt.");
    }

    const walletContext = await window.dcpWeb3.ensureConnected();
    const synced = await window.dcpWeb3.syncWalletAddress({
      eoaAddress: walletContext.eoaAddress,
      smartAccountAddress: walletContext.smartAccountAddress,
    });
    const smartAccountAddress = synced.smart_account_address || walletContext.smartAccountAddress;
    const expectedWallet = config.approverWallets?.[expectedRole] || "";

    if (expectedWallet && smartAccountAddress.toLowerCase() !== expectedWallet.toLowerCase()) {
      throw new Error(`Smart Account hiện tại không khớp ví ${expectedRole} trên contract.`);
    }

    return {
      provider: walletContext.provider,
      eoaAddress: walletContext.eoaAddress,
      smartAccountAddress,
    };
  }

  async function sendApprovalUserOperation({ provider, eoaAddress, smartAccountAddress, campaignId }) {
    if (!config.contractAddress) {
      throw new Error("Thiếu CONTRACT_ADDRESS trong cấu hình frontend.");
    }
    if (!config.alchemyApiKey) {
      throw new Error("Không đọc được Alchemy API key từ SEPOLIA RPC.");
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
      abi: parseAbi(["function approveDisbursement(uint256 _campaignId)"]),
      functionName: "approveDisbursement",
      args: [BigInt(campaignId)],
    });

    const userOpHash = await bundlerClient.sendUserOperation({
      calls: [{ to: config.contractAddress, data: callData, value: 0n }],
    });
    const receipt = await bundlerClient.waitForUserOperationReceipt({ hash: userOpHash });
    const transactionHash =
      receipt?.receipt?.transactionHash ||
      receipt?.transactionHash ||
      receipt?.hash ||
      "";

    if (!transactionHash) {
      throw new Error("Không lấy được transaction hash từ approval receipt.");
    }

    return {
      userOpHash,
      transactionHash,
      smartAccountAddress: account.address,
    };
  }

  async function syncApproval({ proposalId, txHash }) {
    const response = await fetch(config.disbursementApprovalSyncUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": document.cookie.split("; ").find((row) => row.startsWith("csrftoken="))?.split("=")[1] || "",
      },
      credentials: "same-origin",
      body: JSON.stringify({
        proposal_id: proposalId,
        tx_hash: txHash,
      }),
    });

    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || "Không thể đồng bộ chữ ký duyệt về Django.");
    }
    return payload;
  }

  async function handleApprovalClick(button) {
    const proposalId = button.dataset.proposalId;
    const campaignId = button.dataset.campaignId;
    const title = button.dataset.title || `proposal #${proposalId}`;
    const expectedRole = button.dataset.role || config.currentApproverRole;

    if (!expectedRole) {
      throw new Error("Không xác định được vai trò approver của tài khoản hiện tại.");
    }

    setButtonBusy(button, true);
    try {
      window.dcpWeb3?.showToast?.(`Đang chuẩn bị ký gasless cho ${title}...`, "info");
      const walletContext = await ensureApproverWallet(expectedRole);
      const txResult = await sendApprovalUserOperation({
        provider: walletContext.provider,
        eoaAddress: walletContext.eoaAddress,
        smartAccountAddress: walletContext.smartAccountAddress,
        campaignId,
      });

      const syncPayload = await syncApproval({
        proposalId,
        txHash: txResult.transactionHash,
      });

      window.dcpWeb3?.updateWalletBadge(txResult.smartAccountAddress);
      window.dcpWeb3?.showToast?.(
        `Đã đồng bộ chữ ký ${syncPayload.approver_role}. approvals=${syncPayload.approval_count}/2`,
        "success",
      );
      window.setTimeout(() => window.location.reload(), 800);
    } catch (error) {
      window.dcpWeb3?.showToast?.(error.message || "Duyệt gasless thất bại.", "error");
      setButtonBusy(button, false);
      return;
    }
  }

  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      handleApprovalClick(button);
    });
  });
}
