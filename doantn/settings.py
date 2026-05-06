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
    'https://web-production-e589d.up.railway.app',
]

# Bắt buộc dùng HTTPS cho Cookie (Railway chạy HTTPS nên cái này là bắt buộc)
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
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
DEBUG = True
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

# PayOS Configuration
PAYOS_CLIENT_ID = os.getenv('PAYOS_CLIENT_ID')
PAYOS_API_KEY = os.getenv('PAYOS_API_KEY')
PAYOS_CHECKSUM_KEY = os.getenv('PAYOS_CHECKSUM_KEY')

# Blockchain Configuration (Ethereum Sepolia)
SEPOLIA_RPC_URL = os.getenv('SEPOLIA_RPC_URL')
CONTRACT_ADDRESS = os.getenv('CONTRACT_ADDRESS')
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

# Media / uploaded files
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

# =====================================================
# BLOCKCHAIN CONFIGURATION (Updated for Sepolia)
# =====================================================
# Gas price cố định (Gwei) - dùng cho mọi giao dịch blockchain + tính phí hiển thị
# 0.1 Gwei ≈ vài trăm VND mỗi giao dịch (đủ cho Sepolia testnet)
# Nếu giao dịch bị pending/kẹt, tăng giá trị này lên (VD: 1 hoặc 2)
ADMIN_GAS_PRICE_GWEI = 0.1

# 1. Địa chỉ Smart Contract
SMART_CONTRACT_ADDRESS = CONTRACT_ADDRESS

# 2. Private Key ví Admin
WALLET_PRIVATE_KEY = ADMIN_PRIVATE_KEY

# 3. Địa chỉ ví Admin (derived from private key if needed)
WALLET_ADDRESS = os.getenv('WALLET_ADDRESS', '')

# 4. Đường dẫn mạng Sepolia (RPC URL)
WEB3_PROVIDER_URL = SEPOLIA_RPC_URL

# 5. Mã ABI (loaded from file)
ABI_FILE_PATH = BASE_DIR / 'blockchain_assets' / 'contract_abi.json'
with open(ABI_FILE_PATH, 'r') as f:
    SMART_CONTRACT_ABI = json.load(f)




# Ép Django trả đúng định dạng JS, chống lỗi MIME text/plain trên Arch Linux
import mimetypes
mimetypes.add_type("application/javascript", ".js", True)