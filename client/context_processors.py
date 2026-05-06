from django.conf import settings


def web3auth_config(request):
    wallet_address = ''
    eoa_address = ''
    smart_account_address = ''
    if request.user.is_authenticated and hasattr(request.user, 'profile'):
        smart_account_address = request.user.profile.smart_account_address or ''
        eoa_address = request.user.profile.eoa_address or ''
        wallet_address = smart_account_address or request.user.profile.wallet_address or ''

    return {
        'web3auth_public_config': {
            'clientId': settings.WEB3AUTH_CLIENT_ID,
            'network': settings.WEB3AUTH_NETWORK,
            'chainId': '0xaa36a7',
            'rpcTarget': settings.SEPOLIA_RPC_URL,
            'displayName': 'Ethereum Sepolia',
            'ticker': 'ETH',
            'tickerName': 'Ethereum',
            'blockExplorerUrl': 'https://sepolia.etherscan.io',
            'googleClientId': settings.GOOGLE_CLIENT_ID,
            'syncUrl': '/api/auth/wallet-sync/',
            'isAuthenticated': request.user.is_authenticated,
            'walletAddress': wallet_address,
            'eoaAddress': eoa_address,
            'smartAccountAddress': smart_account_address,
            'userEmail': request.user.email if request.user.is_authenticated else '',
            'userName': request.user.get_username() if request.user.is_authenticated else '',
            'biconomyBundlerUrl': settings.BICONOMY_BUNDLER_URL,
            'biconomyPaymasterUrl': settings.BICONOMY_PAYMASTER_URL,
        }
    }
