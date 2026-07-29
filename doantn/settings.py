"""
Django settings for doantn project.
"""
import json
import mimetypes
import os
from pathlib import Path

import cloudinary
from dotenv import load_dotenv


CSRF_TRUSTED_ORIGINS = [
    'https://web-production-9c2ee.up.railway.app',
    'https://*.up.railway.app',
]

# Railway (và nhiều PaaS khác) terminate TLS ở load balancer rồi forward HTTP
# nội bộ về app. Django cần đọc header X-Forwarded-Proto để nhận biết request
# gốc là HTTPS; nếu thiếu, cookie Secure + CSRF có thể lỗi 403 / redirect loop.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True

# Bắt buộc dùng HTTPS cho Cookie (Railway chạy HTTPS nên cái này là bắt buộc)
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
# Để JS (fetch ở web3auth-bootstrap.js) đọc được csrftoken từ document.cookie
# và gửi qua header X-CSRFToken. Nếu bật HttpOnly, JS không đọc được và các
# endpoint CSRF-protected khác sẽ trả 403.
CSRF_COOKIE_HTTPONLY = False
# SameSite='Lax' là mặc định – đủ cho same-origin fetch từ chính domain Railway.
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'

# Cross-Origin-Opener-Policy (COOP):
# Django 4.0+ mặc định set SECURE_CROSS_ORIGIN_OPENER_POLICY='same-origin',
# header này CẮT liên lạc window.opener/popup.closed giữa trang chính và popup.
# Web3Auth (login Google qua popup) polling popup.closed để biết khi nào OAuth
# xong → với 'same-origin' nó luôn thấy popup.closed=true → tưởng user đóng popup
# → ném 'login popup has been closed by the user' sau 5-6s dù popup vẫn mở.
# 'same-origin-allow-popups' cho phép cửa sổ con (popup OAuth) giữ tham chiếu
# tới opener mà vẫn cô lập các origin khác. ĐÂY là fix cho lỗi login Web3Auth.
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin-allow-popups'
# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / '.env')

mimetypes.add_type("application/javascript", ".js", strict=True)

def env_bool(key, default=False):
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def env_list(key, default=''):
    return [item.strip() for item in os.getenv(key, default).split(',') if item.strip()]


cloudinary.config(
    cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME', ''),
    api_key=os.getenv('CLOUDINARY_API_KEY', ''),
    api_secret=os.getenv('CLOUDINARY_API_SECRET', ''),
    secure=True,
)

SECRET_KEY = os.getenv('SECRET_KEY', 'unsafe-dev-secret-key')
DEBUG = env_bool('DEBUG', False)
# ALLOWED_HOSTS = env_list('ALLOWED_HOSTS', 'localhost,127.0.0.1', '*')
ALLOWED_HOSTS = ['*']

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
	'django.contrib.postgres',
    'admin_panel',
    'client',
    'cloudinary_storage',
    'cloudinary',
]

# Google OAuth settings
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET', '')

# Web3Auth / Embedded Wallet Configuration
WEB3AUTH_CLIENT_ID = os.getenv('WEB3AUTH_CLIENT_ID', '')
WEB3AUTH_NETWORK = os.getenv('WEB3AUTH_NETWORK', 'sapphire_devnet')

# Biconomy Smart Account Configuration
BICONOMY_BUNDLER_URL = os.getenv('BICONOMY_BUNDLER_URL', '')
BICONOMY_PAYMASTER_URL = os.getenv('BICONOMY_PAYMASTER_URL', '')

# PayOS Configuration — TÁCH 2 KÊNH HOÀN TOÀN
# ----------------------------------------------------------------
# Kênh THU (donation / payment-link): credentials cũ, KHÔNG đụng vào.
#   PAYOS_CLIENT_ID / PAYOS_API_KEY / PAYOS_CHECKSUM_KEY
#   → dùng ở client/views.py (PayOS Payment) cho donor pay tiền.
#
# Kênh CHI (payout / chuyển tiền ra ngân hàng tổ chức): credentials
# RIÊNG, lấy từ Kênh Chi đã tạo trên PayOS dashboard.
#   PAYOS_PAYOUT_CLIENT_ID / PAYOS_PAYOUT_API_KEY / PAYOS_PAYOUT_CHECKSUM_KEY
#   → dùng ở client/payos_payout.py::PayosPayoutService và
#     admin_panel/webhook_views.py để verify webhook payout.
# ----------------------------------------------------------------
PAYOS_CLIENT_ID = os.getenv('PAYOS_CLIENT_ID')
PAYOS_API_KEY = os.getenv('PAYOS_API_KEY')
PAYOS_CHECKSUM_KEY = os.getenv('PAYOS_CHECKSUM_KEY')

PAYOS_PAYOUT_CLIENT_ID = os.getenv('PAYOS_PAYOUT_CLIENT_ID')
PAYOS_PAYOUT_API_KEY = os.getenv('PAYOS_PAYOUT_API_KEY')
PAYOS_PAYOUT_CHECKSUM_KEY = os.getenv('PAYOS_PAYOUT_CHECKSUM_KEY')

PAYOS_PAYOUT_MOCK = False

# Blockchain Configuration (Ethereum Sepolia)
SEPOLIA_RPC_URL = os.getenv('SEPOLIA_RPC_URL')
# CONTRACT_ADDRESS = địa chỉ smart2.sol (DCPManager + Soulbound Badge).
# VNDT_TOKEN_ADDRESS = địa chỉ smart1.sol (VNDT ERC20). Manager của smart1 phải
# trỏ về smart2 để recordDonation có thể gọi vndt.mint(...) thành công.
# Default fallback = các contract đã deploy sẵn trên Sepolia (2026-03 release).
CONTRACT_ADDRESS = os.getenv('CONTRACT_ADDRESS', '0x4F36121cC411c2e6Bea4e4a66C4BE78F3cc048E7')
VNDT_TOKEN_ADDRESS = os.getenv('VNDT_TOKEN_ADDRESS', '0x05D913ECd54aC20401b096B10d0F4202098B38a4')
ADMIN_PRIVATE_KEY = os.getenv('ADMIN_PRIVATE_KEY')

# Paymaster Configuration
ALCHEMY_POLICY_ID = os.getenv('ALCHEMY_POLICY_ID')

# IPFS / Pinata Configuration
PINATA_API_KEY = os.getenv('PINATA_API_KEY', '')
PINATA_API_SECRET = os.getenv('PINATA_API_SECRET', '')

# Platform Configuration
PLATFORM_FEE = int(os.getenv('PLATFORM_FEE', 0))
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'doantn.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
            'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'client.context_processors.web3auth_config',
            ],
        },
    },
]

WSGI_APPLICATION = 'doantn.wsgi.application'


# Database
# https://docs.djangoproject.com/en/4.1/ref/settings/#databases

# settings.py
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME', 'postgres'),
        'USER': os.getenv('DB_USER', 'postgres'),
        'PASSWORD': os.getenv('DB_PASSWORD', ''),
        'HOST': os.getenv('DB_HOST', 'localhost'),
        'PORT': os.getenv('DB_PORT', '5432'),
    }
}

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
        'LOCATION': 'doantn_cache_table',
    }
}


# Password validation
# https://docs.djangoproject.com/en/4.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/4.1/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.1/howto/static-files/

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [
    BASE_DIR / 'client' / 'static',
]
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Media / uploaded files
DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
# https://docs.djangoproject.com/en/4.1/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL = '/admin/dangnhap/'
LOGIN_REDIRECT_URL = '/admin/trangchu/'
LOGOUT_REDIRECT_URL = '/admin/dangnhap/'


# settings.py

# =====================================================
# VNPAY CONFIGURATION (Sandbox)
# =====================================================
VNPAY_TMN_CODE = os.getenv('VNPAY_TMN_CODE', '')
VNPAY_HASH_SECRET = os.getenv('VNPAY_HASH_SECRET', '')
VNPAY_URL = os.getenv('VNPAY_URL', 'https://sandbox.vnpayment.vn/paymentv2/vpcpay.html')
SITE_URL = os.getenv('SITE_URL', 'http://localhost:8000')

# =====================================================
# CASSO / SEPAY WEBHOOK SECRET
# =====================================================
CASSO_SECRET_KEY = os.getenv('CASSO_SECRET_KEY', '')

# OpenMap.vn reverse geocoding for admin campaign map picker.
OPENMAP_API_KEY = os.getenv('OPENMAP_API_KEY', '')

# =====================================================
# BLOCKCHAIN CONFIGURATION (HARDCODED FOR TESTING)
# =====================================================

# Gas pricing:
# - KHÔNG hardcode gasPrice nữa. Khi biến này bị unset/rỗng/0, blockchain.py
#   sẽ tự động dùng EIP-1559 động (maxFeePerGas = 2*baseFee + priorityFee)
#   → Sepolia tự điều chỉnh theo tải mạng, tránh tx bị stuck vì underpriced.
# - Chỉ bật lại (ví dụ 1.5) nếu cần override thủ công khi node Sepolia gặp vấn đề.
_admin_gwei_raw = (os.getenv('ADMIN_GAS_PRICE_GWEI') or '').strip()
try:
    _admin_gwei_val = float(_admin_gwei_raw) if _admin_gwei_raw else 0.0
except ValueError:
    _admin_gwei_val = 0.0
ADMIN_GAS_PRICE_GWEI = _admin_gwei_val if _admin_gwei_val > 0 else None

# 1. Token VNDT (smart1.sol)
VNDT_TOKEN_ADDRESS = '0x97323b2b4a76f2AeF61b5d86817E82C93160d16B'

# 2. DCP Manager (smart2.sol)
CONTRACT_ADDRESS = '0xD52527f592c200cBf4897De2A494959CF29ec20D'
SMART_CONTRACT_ADDRESS = CONTRACT_ADDRESS

# 3. Disbursement Executor V3 (smart3.sol)
SMART3_CONTRACT_ADDRESS = '0x613A3BB56f16a0742A509c50a2aAC998C52822D9'

# 4. Private Key ví Admin
WALLET_PRIVATE_KEY = ADMIN_PRIVATE_KEY

# 5. Địa chỉ ví Admin (derived from private key if needed)
WALLET_ADDRESS = os.getenv('WALLET_ADDRESS', '')

# 6. Đường dẫn mạng Sepolia (RPC URL)
WEB3_PROVIDER_URL = SEPOLIA_RPC_URL

# 7. Mã ABI (loaded from file)
# - SMART_CONTRACT_ABI : ABI của DCPManager (smart2.sol) — quản lý campaign + SBT.
# - VNDT_ABI           : ABI của VNDT ERC20 (smart1.sol) — chỉ để đọc balance/totalSupply
#                        từ Django (write-path đi qua DCPManager.recordDonation).
ABI_FILE_PATH = BASE_DIR / 'blockchain_assets' / 'contract_abi.json'
with open(ABI_FILE_PATH, 'r') as f:
    SMART_CONTRACT_ABI = json.load(f)

VNDT_ABI_FILE_PATH = BASE_DIR / 'blockchain_assets' / 'vndt_abi.json'
try:
    with open(VNDT_ABI_FILE_PATH, 'r') as f:
        VNDT_ABI = json.load(f)
except FileNotFoundError:
    # Trong một số môi trường legacy có thể chưa có file này; để None để app vẫn boot,
    # BlockchainService sẽ skip vndt_contract khi VNDT_ABI is None.
    VNDT_ABI = None

# =====================================================
# [V3] DisbursementExecutor (smart3.sol) — EIP-712 multisig relayer
# -----------------------------------------------------
# Deploy smart3.sol riêng, rồi set 2 env:
#   SMART3_CONTRACT_ADDRESS: address của smart3 trên Sepolia.
#   SMART3_ABI_FILE        : đường dẫn tới ABI JSON (build từ Hardhat/Remix).
# Nếu chưa deploy → giữ None để code V3 gate bằng check `if smart3_contract`.
# =====================================================
# Default fallback = smart3 đã deploy trên Sepolia (2026-03 release).
# Owner = WALLET_ADDRESS (backend relayer) nên recordMultisigApproval +
# finalizeBurnWithBankTx (onlyOwner) sẽ pass.
_smart3_abi_path = BASE_DIR / 'blockchain_assets' / 'smart3_abi.json'
try:
    with open(_smart3_abi_path, 'r') as f:
        SMART3_CONTRACT_ABI = json.load(f)
except FileNotFoundError:
    SMART3_CONTRACT_ABI = None


# sdfdsfdsf

# Logging configuration for Railway console output
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'admin_panel.views': {
            'handlers': ['console'],
            'level': 'INFO',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}

# Ép Django trả đúng định dạng JS, chống lỗi MIME text/plain trên Arch Linux
import mimetypes
mimetypes.add_type("application/javascript", ".js", True)
