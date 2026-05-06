### Phase 0: Initialization [DONE]
- Analyzed existing Django project structure with models, views, and templates.
- Confirmed frontend uses Vanilla JS in Django templates (not React/Next.js).
- Database schema exists in admin_panel/models.py with extensive blockchain fields.
- Identified existing VNPay integration to be replaced with PayOS.
- Updated REQUIRED_FROM_USER section based on actual codebase needs.

### Phase 1: Smart Contracts Core & Deployment [DONE]
- Write and finalize Solidity code (`VNDT` Token and `DCPManager` with 3-part flow logic).
- Deploy contracts to Ethereum Sepolia testnet.
- Store Contract ABI and Address securely in the project environment (`blockchain_assets/contract_abi.json`).

### Phase 2: Money IN Bridge - Web2 Backend Integration [DONE]
- Implement strict KYC and manual approval workflow in Django Admin for Organizations and bank accounts.
- Replace existing VNPay with PayOS webhook integration (VietQR generation and fiat deposit handling).
- Add PayOS webhook handler in Django for signature verification and auto-reconciliation.
- Integrate `recordDonation` smart contract call for VNDT minting at 1:1 ratio.
- Implement automatic token transfer to Campaign Contract with configurable platform fee deduction.
- Build Quadratic Funding algorithm integration for vote calculation and matching funds.

### Phase 3: Roles & Identity - Web3 Frontend Integration [DONE]
- Implement Web2 login system for Donors, Organizations, and Supervisors using Google/Email.
- Integrate Web3Auth/Biconomy for automatic Smart Account assignment and management.
- Configure ERC-4337 account abstraction with Paymaster for gasless transactions.
- Hide blockchain complexity behind standard UI buttons for all signature/approval actions.

### Phase 4: Money OUT Bridge & Anti-Sybil [DONE]
- Develop IPFS upload functionality (Pinata) for disbursement invoices and record CIDs on-chain.
- Implement `proposeDisbursement` for Organization signature (Step 1).
- Build approval workflow for Supervisor and Admin (`approveDisbursement`, Step 2).
- Integrate 3-of-3 Multisig logic for automatic VNDT token burning upon consensus.
- Implement blockchain event listening for `DisbursedAndBurned` to trigger real VND transfers via bank API.
- Implement FingerprintJS on backend and IP tracking to flag Sybil attacks.
- Enhance admin panel with anti-Sybil flagging.
- Final integration testing across existing Web2 and new Web3 components.

## Implementation Notes
- Each phase must be completed and marked as [DONE] in this file before proceeding.
- All phases will integrate into the existing Django + Vanilla JS application.
- Existing models (Campaign, Donation, etc.) will be extended, not replaced.
- Existing templates will be updated with Web3 features.
- Existing views will be modified to support new flows.
- Code will follow existing conventions and best practices.
- Platform fee configurable via `platformFee` variable (default 0% for 1:1 VND:VNDT ratio).
- Security audit remediation passed: secrets centralized in `.env`, paymaster settings scoped to admin disbursement pages, and the deployment target is Production-Ready.
