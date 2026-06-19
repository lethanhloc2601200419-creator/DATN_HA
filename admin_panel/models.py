from django.db import models
from django.contrib.auth.models import AbstractUser
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.search import SearchVectorField
from cloudinary.models import CloudinaryField
import uuid
import hashlib
from django.conf import settings
from decimal import Decimal
# Create your models here.
from django.db import models
from django.contrib.auth.models import User
from django.contrib.postgres.fields import ArrayField
from django.utils.text import slugify
import time
from django.utils import timezone

# =====================================================
# 1. USER PROFILE
# =====================================================
class UserProfile(models.Model):
    # Phân biệt nguồn tài khoản: 'web' = đăng ký bằng form nội bộ
    # (admin_panel:dangky), 'google' = đăng nhập qua OAuth Google /
    # Web3Auth Google. Field này quyết định ai được phép nộp form
    # đăng ký tổ chức ở /to-chuc/#dangky-section.
    ACCOUNT_SOURCE_CHOICES = [
        ('web', 'Tài khoản web nội bộ'),
        ('google', 'Tài khoản Google / Web3Auth'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    display_name = models.CharField(max_length=255, blank=True, null=True)
    username = models.CharField(max_length=150, unique=True, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    province = models.CharField(max_length=100, blank=True, null=True)
    avatar_url = models.TextField(blank=True, null=True)
    avatar = CloudinaryField('image', folder='user_avatars/', blank=True, null=True)
    bio = models.TextField(blank=True, null=True)
    eoa_address = models.CharField(max_length=42, blank=True, null=True)
    smart_account_address = models.CharField(max_length=42, blank=True, null=True)
    wallet_address = models.CharField(max_length=42, blank=True, null=True)
    account_source = models.CharField(
        max_length=20,
        choices=ACCOUNT_SOURCE_CHOICES,
        default='',
        blank=True,
        verbose_name="Nguồn tài khoản",
    )

    is_verified = models.BooleanField(default=False)
    verification_token = models.CharField(max_length=255, blank=True, null=True)
    otp_code = models.CharField(max_length=6, blank=True, null=True)
    otp_expires_at = models.DateTimeField(blank=True, null=True)

    has_mb_account = models.BooleanField(default=False)
    mb_account_number = models.CharField(max_length=50, blank=True, null=True)
    mb_account_name = models.CharField(max_length=255, blank=True, null=True)

    total_donated = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_campaigns_created = models.IntegerField(default=0)
    total_campaigns_supported = models.IntegerField(default=0)

    is_locked = models.BooleanField(default=False)
    locked_reason = models.TextField(blank=True, null=True)
    locked_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.display_name or self.user.username

    class Meta:
        db_table = 'user_profile'

# =====================================================
# 2. CAMPAIGN CATEGORY
# =====================================================
class CampaignCategory(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True, null=True)
    icon_url = models.TextField(blank=True, null=True)
    display_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'campaign_category'
# 2.5 ORGANIZATION (Thêm mới bảng này)
# =====================================================
# =====================================================
# 1. ORGANIZATION (TỔ CHỨC - QUAN TRỌNG NHẤT)
# =====================================================
class Organization(models.Model):
    KYC_STATUS_CHOICES = [
        ('draft', 'Nháp'),
        ('submitted', 'Đã nộp hồ sơ'),
        ('under_review', 'Đang thẩm định'),
        ('approved', 'Đã duyệt KYC'),
        ('rejected', 'Từ chối KYC'),
        ('suspended', 'Tạm khóa'),
    ]

    # Thông tin hiển thị
    name = models.CharField(max_length=255,verbose_name="Tên tổ chức")
    slug = models.SlugField(unique=True, max_length=255)
    description = models.TextField(blank=True, null=True)
    logo_url = models.TextField(blank=True, null=True)
    logo = CloudinaryField('image', folder='organization_logos/', blank=True, null=True)
    website = models.URLField(blank=True, null=True)
    manager = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='managed_organizations', verbose_name="Tài khoản quản lý")
    # Thông tin ngân hàng (Tiền donate sẽ chảy về đây)
    bank_account_number = models.CharField(max_length=50)
    bank_account_name = models.CharField(max_length=255)
    bank_name = models.CharField(max_length=255) # Vd: MB Bank, Vietcombank
    bank_branch = models.CharField(max_length=255, blank=True, null=True)
    qr_code_url = models.TextField(blank=True, null=True)
    wallet_address = models.CharField(max_length=42, blank=True, null=True)
    tax_id = models.CharField(max_length=50, blank=True, null=True, verbose_name="Mã số thuế")

    # Thông tin pháp lý & Xác minh (Admin duyệt)
    operating_license_number = models.CharField(max_length=255, blank=True, null=True, verbose_name="Số giấy phép hoạt động")
    founding_date = models.DateField(blank=True, null=True, verbose_name="Ngày thành lập")
    license_document_url = models.TextField(blank=True, null=True) # Ảnh giấy phép
    # Cờ tương thích với code cũ; Phase 2 sẽ dần chuyển toàn bộ logic sang kyc_status.
    is_verified = models.BooleanField(default=False, verbose_name="Đã xác thực")
    verified_at = models.DateTimeField(blank=True, null=True)
    kyc_status = models.CharField(
        max_length=20,
        choices=KYC_STATUS_CHOICES,
        default='draft',
        verbose_name="Trạng thái KYC",
    )
    kyc_submitted_at = models.DateTimeField(blank=True, null=True)
    kyc_reviewed_at = models.DateTimeField(blank=True, null=True)
    kyc_reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_organization_kyc',
        verbose_name="Admin duyệt KYC",
    )
    kyc_rejection_reason = models.TextField(blank=True, null=True, verbose_name="Lý do từ chối KYC")
    bank_verified_by_admin = models.BooleanField(default=False, verbose_name="Ngân hàng đã xác thực")
    bank_verified_at = models.DateTimeField(blank=True, null=True)
    bank_verified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bank_verified_organizations',
        verbose_name="Admin xác thực ngân hàng",
    )
    wallet_verified_by_admin = models.BooleanField(default=False, verbose_name="Ví đã xác thực")
    wallet_verified_at = models.DateTimeField(blank=True, null=True)
    wallet_verified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='wallet_verified_organizations',
        verbose_name="Admin xác thực ví",
    )

    # Liên hệ
    contact_person = models.CharField(max_length=255, blank=True, null=True)
    contact_phone = models.CharField(max_length=20, blank=True, null=True)
    mission_statement = models.TextField(blank=True, null=True, verbose_name="Tuyên bố sứ mệnh")
    headquarters_address = models.TextField(blank=True, null=True, verbose_name="Địa chỉ trụ sở chính")
    social_media_link = models.URLField(blank=True, null=True, verbose_name="Link mạng xã hội")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'organization'

# =====================================================
# 1.1 ORGANIZATION REPRESENTATIVE (ĐẠI DIỆN TỔ CHỨC)
# =====================================================
class OrganizationRepresentative(models.Model):
    organization = models.OneToOneField(Organization, on_delete=models.CASCADE, related_name='representative')
    full_name = models.CharField(max_length=255, verbose_name="Họ và tên")
    position = models.CharField(max_length=255, verbose_name="Chức vụ")
    id_card_number = models.CharField(max_length=50, unique=True, verbose_name="Số CCCD/CMND")
    id_card_date = models.DateField(verbose_name="Ngày cấp CCCD/CMND")
    id_card_place = models.CharField(max_length=255, verbose_name="Nơi cấp CCCD/CMND")
    phone = models.CharField(max_length=20, verbose_name="Số điện thoại")
    email = models.EmailField(verbose_name="Email")
    permanent_address = models.TextField(verbose_name="Địa chỉ thường trú")
    # Lưu ý: CloudinaryField không cho phép truyền `verbose_name` kwarg đồng thời với
    # resource_type positional (sẽ raise TypeError multiple values for verbose_name).
    # Verbose name được khai báo trong admin form / fieldsets thay vì ở field cấp model.
    authorization_letter = CloudinaryField('raw', folder='organization_kyc/authorization_letters/', blank=True, null=True)
    id_card_front = CloudinaryField('image', folder='organization_kyc/id_cards/')
    id_card_back = CloudinaryField('image', folder='organization_kyc/id_cards/')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Đại diện của {self.organization.name}: {self.full_name}"

    class Meta:
        db_table = 'organization_representative'
        verbose_name = "Đại diện tổ chức"
        verbose_name_plural = "Đại diện tổ chức"

# =====================================================
# 2. TARGET PROGRAM (CHƯƠNG TRÌNH MỤC TIÊU)
# =====================================================
# Ví dụ: Tổ chức "Quỹ Trò Nghèo" có chương trình con là "Cơm Có Thịt"
class TargetProgram(models.Model):
    # Link tới bảng Organization
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='programs')
    
    # 1. Thông tin cơ bản
    name = models.CharField(max_length=255, verbose_name="Tên chương trình")
    slug = models.SlugField(unique=True, max_length=255)
    
    # --- MỚI 1: Ảnh bìa (Để hiển thị ra trang chủ cho đẹp) ---
    image = models.ImageField(upload_to='programs/', blank=True, null=True, verbose_name="Ảnh bìa")
    
    # --- MỚI 2: Mục tiêu tổng (Để tính % tiến độ tổng thể) ---
    total_target_amount = models.DecimalField(
        max_digits=15, decimal_places=0, default=0, 
        verbose_name="Tổng số tiền cần (VNĐ)"
    )

    description = models.TextField(blank=True, null=True, verbose_name="Mô tả")
    
    is_active = models.BooleanField(default=True, verbose_name="Hiển thị")
    created_at = models.DateTimeField(auto_now_add=True)

    # 2. Thông tin GIS (Địa lý)
    beneficiary_address = models.TextField(
        help_text="Địa chỉ nơi cần giúp đỡ (VD: Điểm trường X, Xã Y, Huyện Z...)",
        verbose_name="Địa chỉ thụ hưởng"
    )
    beneficiary_lat = models.DecimalField(
        max_digits=10, decimal_places=8, blank=True, null=True,
        help_text="Vĩ độ (Latitude)", verbose_name="Vĩ độ"
    )
    beneficiary_lng = models.DecimalField(
        max_digits=11, decimal_places=8, blank=True, null=True,
        help_text="Kinh độ (Longitude)", verbose_name="Kinh độ"
    )
    # [MỚI] Minh chứng pháp lý & Trạng thái duyệt (Admin cần duyệt cái này)
    license_document = models.FileField(upload_to='program_docs/', blank=True, null=True, verbose_name="Hồ sơ minh chứng (PDF/Ảnh)")
    is_verified = models.BooleanField(default=False, verbose_name="Đã được Admin duyệt")

    def __str__(self):
        return self.name
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name) + '-' + str(int(time.time()))
        super(TargetProgram, self).save(*args, **kwargs)

    # --- MỚI 3: Việt hóa tên bảng trong Admin ---
    class Meta:
        db_table = 'target_program'
        verbose_name = "Chương trình mục tiêu"
        verbose_name_plural = "Danh sách Chương trình mục tiêu"

# =====================================================
# 3. CAMPAIGN OCCASION (DỊP GÂY QUỸ)
# =====================================================
# Ví dụ: Sinh nhật, Đám cưới, Tết...
class CampaignOccasion(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, max_length=255)
    description = models.TextField(blank=True, null=True)
    icon_name = models.CharField(max_length=50, blank=True, null=True) # Lưu tên icon fontawesome
    
    display_order = models.IntegerField(default=0) # Để sắp xếp thứ tự hiển thị
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'campaign_occasion'
        ordering = ['display_order']

# =====================================================
# 4. CAMPAIGN (CHIẾN DỊCH - CẬP NHẬT MỚI)
# =====================================================
class Campaign(models.Model):
    # --- 1. TRẠNG THÁI (Giữ nguyên của bạn vì quá đầy đủ) ---
    STATUS_CHOICES = [
        ('pending','Chờ duyệt'), # User tạo xong sẽ vào đây
        ('active','Đang gây quỹ'), # Admin duyệt sẽ sang đây
        ('completed','Đã hoàn thành'),
        ('ended','Đã kết thúc'),
        ('paused','Tạm dừng'),
        ('rejected','Bị từ chối'),
        ('hidden','Đã ẩn'),
        ('deleted','Đã xóa')
    ]

    # --- 2. LIÊN KẾT (Quan trọng cho logic GIS) ---
    creator = models.ForeignKey(User, on_delete=models.CASCADE, related_name='campaigns')
    
    category = models.ForeignKey('CampaignCategory', on_delete=models.SET_NULL, null=True, blank=True)
    organization = models.ForeignKey(Organization, on_delete=models.SET_NULL, null=True, blank=True, related_name='campaigns')
    
    # [QUAN TRỌNG] Đây là mỏ neo để lấy tọa độ GIS nếu User không nhập
    target_program = models.ForeignKey(TargetProgram, on_delete=models.SET_NULL, null=True, blank=True, related_name='campaigns')
    
    occasion = models.ForeignKey(CampaignOccasion, on_delete=models.SET_NULL, null=True, blank=True, related_name='campaigns')
    # --- MỚI: QUẢN LÝ KÉT SẮT (ESCROW) ---
    locked_amount = models.DecimalField(max_digits=15, decimal_places=0, default=0) # Tiền đang chờ Vote
    disbursed_amount = models.DecimalField(max_digits=15, decimal_places=0, default=0) # Tiền đã chi thực tế
    
    # --- MỚI: THAM SỐ ĐỒNG THUẬN ---
    approval_threshold_pct = models.IntegerField(default=51) # Cần >51% đồng ý
    voting_power_cap_pct = models.IntegerField(default=30) # Cập 30% chống cá mập
    
    is_protected_beneficiary = models.BooleanField(default=False, verbose_name="Bảo vệ người thụ hưởng")
    status = models.CharField(max_length=20, default='pending')


    # --- 3. THÔNG TIN CƠ BẢN ---
    title = models.CharField(max_length=500, verbose_name="Tên chiến dịch")
    slug = models.SlugField(unique=True, max_length=500, blank=True) # Để blank=True để code tự sinh
    short_description = models.TextField(blank=True, null=True)
    full_description = models.TextField(blank=True, null=True)

    avatar_image_url = models.TextField(blank=True, null=True) # Hoặc dùng ImageField nếu muốn upload
    avatar_image = CloudinaryField('image', folder='campaigns/avatars/', null=True, blank=True)
    cover_image_url = models.TextField(blank=True, null=True)
    cover_image = CloudinaryField('image', folder='campaigns/covers/', null=True, blank=True)

    # --- 4. TÀI CHÍNH & TIẾN ĐỘ ---
    target_amount = models.DecimalField(max_digits=15, decimal_places=0, verbose_name="Mục tiêu")
    current_amount = models.DecimalField(max_digits=15, decimal_places=0, default=0, verbose_name="Đã đạt")

    start_date = models.DateField()
    end_date = models.DateField()

    # --- 5. GIS & ĐỊA ĐIỂM (LOGIC THÔNG MINH) ---
    # Vẫn giữ các trường này để User có thể nhập địa chỉ riêng nếu muốn
    beneficiary_province = models.CharField(max_length=100, blank=True, null=True)
    beneficiary_ward = models.CharField(max_length=100, blank=True, null=True)
    beneficiary_address = models.TextField(blank=True, null=True)
    beneficiary_lat = models.DecimalField(max_digits=15, decimal_places=8, blank=True, null=True) # Tăng digits lên cho an toàn
    beneficiary_lng = models.DecimalField(max_digits=15, decimal_places=8, blank=True, null=True)

    # --- 6. QUẢN TRỊ ---
    charity_account_number = models.CharField(max_length=50, blank=True, null=True)
    charity_account_name = models.CharField(max_length=255, blank=True, null=True)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    view_count = models.IntegerField(default=0)
    support_count = models.IntegerField(default=0) # Số lượt quyên góp
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    rejection_reason = models.TextField(blank=True, null=True)
    is_featured = models.BooleanField(default=False)
    featured_order = models.IntegerField(default=0)
    
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_campaigns')
    approved_at = models.DateTimeField(blank=True, null=True)

    # --- 6.5 ĐỒNG BỘ BLOCKCHAIN (DCPManager v3) ---
    # Được set khi admin duyệt campaign → backend gọi createCampaign(_cid, org_addr).
    # Nếu tx thành công: blockchain_tx_hash + blockchain_synced_at được set, is_onchain=True.
    # Nếu revert/fail: blockchain_sync_error chứa reason, is_onchain=False (để thử lại).
    is_onchain = models.BooleanField(default=False, verbose_name="Đã tạo trên blockchain")
    blockchain_tx_hash = models.CharField(max_length=100, blank=True, null=True, verbose_name="TxHash createCampaign")
    blockchain_synced_at = models.DateTimeField(blank=True, null=True, verbose_name="Thời điểm đồng bộ on-chain")
    blockchain_sync_error = models.TextField(blank=True, null=True, verbose_name="Lỗi đồng bộ blockchain (nếu có)")

    # --- 7. POSTGRESQL SPECIFIC ---
    share_count = models.IntegerField(default=0)
    comment_count = models.IntegerField(default=0)
    tags = ArrayField(models.TextField(), blank=True, null=True) # Giữ nguyên vì bạn dùng Postgres
    documents_urls = ArrayField(models.TextField(), blank=True, null=True)

    def __str__(self):
        return self.title

    # --- HÀM XỬ LÝ LOGIC ---

    def clean(self):
        from django.core.exceptions import ValidationError
        super().clean()
        
        # Nếu bật bảo vệ người thụ hưởng, xóa sạch thông tin Phường/Xã và Địa chỉ cụ thể
        if self.is_protected_beneficiary:
            self.beneficiary_ward = None
            self.beneficiary_address = None
            # Lưu ý: Tọa độ GIS vẫn có thể giữ lại ở mức Tỉnh/Thành phố hoặc xóa nếu cần
            # Ở đây ta chỉ xóa các trường văn bản chi tiết theo yêu cầu.

    # 1. Tự động tạo Slug nếu chưa có
    def save(self, *args, **kwargs):
        # Đảm bảo clean() được gọi trước khi save để xử lý dữ liệu nhạy cảm
        self.clean()
        
        if not self.slug:
            # Tạo slug từ title + timestamp để tránh trùng lặp tuyệt đối
            self.slug = slugify(self.title) + '-' + str(int(time.time()))
        
        # LOGIC GIS TỰ ĐỘNG:
        # Nếu User không nhập tọa độ, mà có chọn Chương trình mục tiêu -> Lấy tọa độ của Chương trình đắp vào
        if not self.beneficiary_lat and self.target_program and self.target_program.beneficiary_lat:
             self.beneficiary_lat = self.target_program.beneficiary_lat
             self.beneficiary_lng = self.target_program.beneficiary_lng
             
        # Tương tự với địa chỉ text
        if not self.beneficiary_address and self.target_program:
             self.beneficiary_address = self.target_program.beneficiary_address

        super(Campaign, self).save(*args, **kwargs)

    # 2. Hàm tính % tiến độ (để vẽ thanh Progress Bar ngoài HTML)
    def get_percentage(self):
        if self.target_amount > 0:
            percent = (self.current_amount / self.target_amount) * 100
            return min(percent, 100)
        return 0
    
    # 3. Hàm kiểm tra xem đã hết hạn chưa
    @property
    def days_left(self):
        """Hàm tính số ngày còn lại đến end_date"""
        today = timezone.now().date()
        if self.end_date:
            delta = self.end_date - today
            # Trả về số ngày (nếu âm thì trả về 0)
            return max(delta.days, 0)
        return 0

    def calculate_voting_distribution(self):
        from django.db.models import Sum
        total_actual_raised = self.current_amount or Decimal('0')
        cap = total_actual_raised * Decimal('0.3')

        donations = self.donations.filter(
            status='completed', donor__isnull=False
        ).values('donor').annotate(total=Sum('amount'))

        voting_powers = []
        total_system_power = Decimal('0')

        for d in donations:
            power = min(d['total'], cap)
            voting_powers.append({'user_id': d['donor'], 'power': power})
            total_system_power += power

        for vp in voting_powers:
            if total_system_power > 0:
                vp['percentage'] = float(vp['power'] / total_system_power * 100)
            else:
                vp['percentage'] = 0

        return voting_powers, total_system_power

    class Meta:
        db_table = 'campaign'
        ordering = ['-created_at']

# =====================================================
# 4. CAMPAIGN MEDIA
# =====================================================
class CampaignMedia(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='media')
    media_type = models.CharField(max_length=20)
    media_url = models.TextField()
    thumbnail_url = models.TextField(blank=True, null=True)
    caption = models.TextField(blank=True, null=True)
    display_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Media {self.id} - {self.media_type}"

    class Meta:
        db_table = 'campaign_media'

# =====================================================
# 5. CAMPAIGN UPDATE
# =====================================================
class CampaignUpdate(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='updates')
    creator = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=500, blank=True, null=True)
    content = models.TextField()
    images_urls = ArrayField(models.TextField(), blank=True, null=True)
    videos_urls = ArrayField(models.TextField(), blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title or f"Update {self.id}"

    class Meta:
        db_table = 'campaign_update'

# =====================================================
# 6. DONATION
# =====================================================
class Donation(models.Model):
    STATUS_CHOICES = [('pending','Pending'),('completed','Completed'),('failed','Failed'),('refunded','Refunded')]
    PAYMENT_CHOICES = [('payos','PayOS'),('vietqr','VietQR'),('bank_transfer','Bank Transfer')]

    # --- 1. CÁC TRƯỜNG DỮ LIỆU CŨ CỦA BẠN (GIỮ NGUYÊN) ---
    campaign = models.ForeignKey('Campaign', on_delete=models.CASCADE, related_name='donations')
    donor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    amount = models.DecimalField(max_digits=15, decimal_places=0) # Mình đổi thành 0 số lẻ cho đẹp tiền Việt
    message = models.TextField(blank=True, null=True)
    is_anonymous = models.BooleanField(default=False)
    # --- MỚI: PHÍ GAS THỰC TẾ TỪ ETHERSCAN ---
    gas_fee_eth = models.DecimalField(max_digits=20, decimal_places=10, null=True, blank=True)
    gas_fee_vnd = models.DecimalField(max_digits=15, decimal_places=0, null=True, blank=True)
    # Gas tx admin trả khi gọi sendEthToUser
    admin_send_eth_gas_fee_wei = models.DecimalField(max_digits=30, decimal_places=0, null=True, blank=True)
    admin_send_eth_gas_fee_vnd = models.DecimalField(max_digits=15, decimal_places=0, null=True, blank=True)
    net_amount = models.DecimalField(max_digits=15, decimal_places=0, null=True, blank=True) # Tiền vào quỹ sau khi trừ gas

    payment_method = models.CharField(max_length=20, choices=PAYMENT_CHOICES, default='bank_transfer')
    transaction_id = models.CharField(max_length=255, unique=True, blank=True, null=True)
    order_code = models.BigIntegerField(blank=True, null=True, unique=True, verbose_name="PayOS orderCode")
    payos_transaction_id = models.CharField(max_length=255, blank=True, null=True, verbose_name="PayOS transaction ID")
    payos_payment_link_id = models.CharField(max_length=255, blank=True, null=True, verbose_name="PayOS payment link ID")
    payos_reference = models.CharField(max_length=255, blank=True, null=True, verbose_name="PayOS reference")
    payos_qr_code = models.TextField(blank=True, null=True, verbose_name="PayOS QR code")
    payos_checkout_url = models.TextField(blank=True, null=True, verbose_name="PayOS checkout URL")
    payos_webhook_received_at = models.DateTimeField(blank=True, null=True, verbose_name="Thời điểm nhận webhook PayOS")
    payos_paid_at = models.DateTimeField(blank=True, null=True, verbose_name="Thời điểm PayOS xác nhận thanh toán")
    bank_transaction_no = models.CharField(max_length=255, blank=True, null=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    donor_name = models.CharField(max_length=255, blank=True, null=True)
    donor_email = models.EmailField(blank=True, null=True)
    donor_phone = models.CharField(max_length=20, blank=True, null=True)
    donor_wallet_address = models.CharField(max_length=42, blank=True, null=True)
    device_fingerprint = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    is_sybil = models.BooleanField(default=False)
    sybil_flag_reason = models.TextField(blank=True, null=True)

    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # --- 2. CÁC TRƯỜNG BLOCKCHAIN ---
    previous_hash = models.CharField(max_length=64, default='0')
    hash = models.CharField(max_length=64, blank=True, null=True)
    admin_funding_status = models.CharField(max_length=20, default='pending', blank=True)
    init_campaign_tx_hash = models.CharField(max_length=100, blank=True, null=True, verbose_name="TxHash initCampaign")

    # --- TRẠNG THÁI BLOCKCHAIN ASYNC ---
    # pending: chưa bắt đầu; processing: đang gọi smart contract; confirmed: đã mine; failed: lỗi
    BLOCKCHAIN_STATUS_CHOICES = [
        ('pending', 'Chờ xử lý'),
        ('processing', 'Đang xử lý blockchain'),
        ('confirmed', 'Đã xác nhận trên blockchain'),
        ('failed', 'Thất bại'),
    ]
    blockchain_status = models.CharField(max_length=20, choices=BLOCKCHAIN_STATUS_CHOICES, default='pending', verbose_name="Trạng thái blockchain")
    blockchain_error = models.TextField(blank=True, null=True, verbose_name="Lỗi blockchain gần nhất")
    blockchain_started_at = models.DateTimeField(blank=True, null=True)
    blockchain_completed_at = models.DateTimeField(blank=True, null=True)
    blockchain_retry_count = models.IntegerField(default=0)

    # --- BỔ SUNG CHO BLOCKCHAIN HYBRID ---
    # Đây là mã hash trả về từ mạng Sepolia (VD: 0xabc...)
    # Dùng để tạo link: https://sepolia.etherscan.io/tx/{eth_tx_hash}
    eth_tx_hash = models.CharField(max_length=100, blank=True, null=True, verbose_name="Mã giao dịch Blockchain")
    send_eth_tx_hash = models.CharField(max_length=100, blank=True, null=True, verbose_name="Tx Admin cap ETH (legacy)")
    donated_eth_wei = models.DecimalField(max_digits=30, decimal_places=0, null=True, blank=True)
    gas_subsidy_wei = models.DecimalField(max_digits=30, decimal_places=0, null=True, blank=True)

    # --- LUỒNG MỚI (async v2) ---
    # Giao dịch A: ghi sao kê ngân hàng lên blockchain
    bank_record_tx_hash = models.CharField(max_length=100, blank=True, null=True, verbose_name="Tx recordBankDonation")
    bank_record_gas_wei = models.DecimalField(max_digits=30, decimal_places=0, null=True, blank=True)
    bank_record_gas_vnd = models.DecimalField(max_digits=15, decimal_places=0, null=True, blank=True)
    # Giao dịch B: admin tự động nạp ETH thay user (donateOnBehalf)
    donate_onbehalf_tx_hash = models.CharField(max_length=100, blank=True, null=True, verbose_name="Tx donateOnBehalf")
    donate_onbehalf_gas_wei = models.DecimalField(max_digits=30, decimal_places=0, null=True, blank=True)
    donate_onbehalf_gas_vnd = models.DecimalField(max_digits=15, decimal_places=0, null=True, blank=True)
    # Giao dịch C1 (trong luồng ủng hộ): ghi gas A+B lên contract để trừ khi giải ngân
    record_gascost_tx_hash = models.CharField(max_length=100, blank=True, null=True, verbose_name="Tx recordGasCost")
    # Tổng gas A+B (admin đã chi cho giao dịch này) - để tổng hợp khi giải ngân
    total_admin_gas_wei = models.DecimalField(max_digits=30, decimal_places=0, null=True, blank=True)
    total_admin_gas_vnd = models.DecimalField(max_digits=15, decimal_places=0, null=True, blank=True)

    # Trạng thái ghi blockchain (Để nhỡ mạng lag thì chạy job ghi lại sau)
    is_blockchain_synced = models.BooleanField(default=False, verbose_name="Đã ghi lên Etherscan")

    class Meta:
        db_table = 'donation'

    def __str__(self):
        return f"Donation #{self.id} - {self.amount}"

    # --- 3. LOGIC BLOCKCHAIN CHỐNG SỬA ĐỔI ---

    def calculate_hash(self):
        """
        Hàm tính Hash: Gom các dữ liệu quan trọng lại để băm.
        Lưu ý: Dùng str() để tránh lỗi nếu dữ liệu là None.
        """
        # Gom dữ liệu: Tên người gửi + Số tiền + Thời gian tạo + Hash cũ
        # Mẹo: amount phải chuyển về string cẩn thận để tránh lệch số
        amount_str = str(int(self.amount)) if self.amount else "0"
        
        # Chuỗi dữ liệu thô
        data_string = f"{self.donor_name}{amount_str}{str(self.created_at)}{self.previous_hash}"
        
        # Trả về mã SHA-256
        return hashlib.sha256(data_string.encode('utf-8')).hexdigest()

    def save(self, *args, **kwargs):
        """
        Quy tắc vàng: CHỈ TÍNH HASH KHI TẠO MỚI (Create).
        KHI SỬA (Update) -> KHÔNG TÍNH LẠI HASH.
        """
        if not self.pk:
            # --- TRƯỜNG HỢP 1: TẠO MỚI ---
            
            # B1: Tìm Hash của giao dịch trước đó (xích lại)
            last_txn = Donation.objects.order_by('-id').first()
            if last_txn and last_txn.hash:
                self.previous_hash = last_txn.hash
            else:
                self.previous_hash = '0' * 64 # Genesis block

            # B2: Lưu lần 1 để hệ thống sinh ra ID và created_at
            super(Donation, self).save(*args, **kwargs)
            
            # B3: Có ID và thời gian rồi, giờ mới tính Hash cho chính nó
            self.hash = self.calculate_hash()
            
            # B4: Lưu lần 2 (Chỉ cập nhật cột hash)
            kwargs['force_insert'] = False 
            super(Donation, self).save(update_fields=['hash'])
            
        else:
            # --- TRƯỜNG HỢP 2: ADMIN SỬA / CẬP NHẬT ---
            # Chỉ lưu dữ liệu bình thường, TUYỆT ĐỐI KHÔNG tính lại Hash.
            # Kết quả: Tiền mới (5.000) nhưng Hash vẫn là Hash cũ (của 50.000)
            # => Gây ra lệch Hash => BÁO ĐỎ.
            super(Donation, self).save(*args, **kwargs)

    @property
    def is_valid(self):
        """
        Kiểm tra xem dữ liệu có bị hack không.
        """
        # Tính lại hash dựa trên dữ liệu hiện tại (có thể đã bị sửa)
        recalculated_hash = self.calculate_hash()
        
        # So sánh với hash gốc trong DB
        return self.hash == recalculated_hash
class DisbursementProposal(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Chờ duyệt'),
        ('voting', 'Đang bỏ phiếu'),
        ('approved', 'Đã thông qua'),
        ('rejected', 'Bị từ chối'),
        ('executed', 'Đã giải ngân'),
    ]

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='proposals')
    title = models.CharField(max_length=255, verbose_name='Tiêu đề')
    amount_requested = models.DecimalField(max_digits=15, decimal_places=0, verbose_name='Số tiền yêu cầu')
    purpose = models.CharField(max_length=500, blank=True, null=True, verbose_name='Mục đích giải ngân')
    description = models.TextField(verbose_name='Mô tả chi tiết')
    recipient_name = models.CharField(max_length=255, blank=True, null=True, verbose_name='Đơn vị thụ hưởng')
    ipfs_cid = models.CharField(max_length=255, blank=True, null=True, verbose_name='IPFS CID hóa đơn')
    evidence_url = models.TextField(blank=True, null=True, verbose_name='Link minh chứng')
    proof_images = ArrayField(models.TextField(), blank=True, null=True, verbose_name='Ảnh minh chứng')

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_proposals', verbose_name='Người tạo')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_proposals', verbose_name='Người duyệt')
    approved_at = models.DateTimeField(blank=True, null=True)
    voting_days = models.IntegerField(default=7, verbose_name='Số ngày bỏ phiếu')

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    end_date = models.DateTimeField(blank=True, null=True, verbose_name='Hạn bỏ phiếu')

    blockchain_proposal_id = models.IntegerField(blank=True, null=True)
    eth_tx_hash = models.CharField(max_length=100, blank=True, null=True, verbose_name='TxHash tạo proposal')
    approval_count = models.PositiveSmallIntegerField(default=0, verbose_name='Số chữ ký đã đồng bộ')
    supervisor_approved_at = models.DateTimeField(blank=True, null=True)
    supervisor_approval_tx_hash = models.CharField(max_length=100, blank=True, null=True, verbose_name='TxHash duyệt của Supervisor')
    admin_approved_at = models.DateTimeField(blank=True, null=True)
    admin_approval_tx_hash = models.CharField(max_length=100, blank=True, null=True, verbose_name='TxHash duyệt của Admin')
    last_approval_synced_at = models.DateTimeField(blank=True, null=True)
    disbursement_eth_tx_hash = models.CharField(max_length=100, blank=True, null=True, verbose_name='TxHash giải ngân')
    disbursement_gas_fee_wei = models.DecimalField(max_digits=30, decimal_places=0, null=True, blank=True, verbose_name='Gas admin trả cho executeDisbursement')
    disbursement_gas_fee_vnd = models.DecimalField(max_digits=15, decimal_places=0, null=True, blank=True, verbose_name='Phí gas giải ngân (VNĐ)')

    # =====================================================
    # V3 — LUỒNG MỚI: EIP-712 MULTISIG + PAYOS PAYOUT + BURN WITH BANK TX
    # =====================================================
    # Layer-1 workflow (song song với luồng cũ trên smart2):
    #   pending_multisig → ready_to_payout → fiat_transferred → completed_audited
    # Mỗi step được đánh dấu bằng timestamp + tx_hash riêng để audit rõ ràng.
    V3_STATUS_CHOICES = [
        ('v3_not_started', 'Chưa dùng luồng V3'),
        ('pending_multisig', 'Chờ đủ 3 chữ ký EIP-712'),
        ('ready_to_payout', 'Đã đủ 3 chữ ký - chờ chuyển fiat'),
        ('payout_processing', 'Đang xử lý PayOS payout'),
        ('fiat_transferred', 'Fiat đã chuyển - chờ burn VNDT'),
        ('completed_audited', 'Hoàn tất + đã burn on-chain'),
        ('payout_failed', 'PayOS payout thất bại'),
    ]
    v3_status = models.CharField(
        max_length=30, choices=V3_STATUS_CHOICES, default='v3_not_started',
        verbose_name='Trạng thái luồng V3 (EIP-712 + PayOS)'
    )
    # Phase 3a: MultisigConfirmed on smart3
    multisig_confirmed_at = models.DateTimeField(blank=True, null=True,
                                                 verbose_name='Thời điểm đủ 3 sig')
    multisig_confirmed_tx_hash = models.CharField(max_length=100, blank=True, null=True,
                                                  verbose_name='TxHash recordMultisigApproval')
    signature_deadline = models.BigIntegerField(blank=True, null=True,
                                                verbose_name='Unix deadline cho các chữ ký EIP-712')
    # Phase 3b + 4: PayOS payout + on-chain burn
    payos_payout_id = models.CharField(max_length=255, blank=True, null=True,
                                       verbose_name='PayOS Payout ID')
    payos_payout_requested_at = models.DateTimeField(blank=True, null=True)
    bank_tx_id = models.CharField(max_length=255, blank=True, null=True,
                                  verbose_name='Bank Transaction ID (từ PayOS webhook)')
    fiat_transferred_at = models.DateTimeField(blank=True, null=True,
                                               verbose_name='Thời điểm fiat đã chuyển')
    burn_tx_hash = models.CharField(max_length=100, blank=True, null=True,
                                    verbose_name='TxHash finalizeBurnWithBankTx')
    burn_completed_at = models.DateTimeField(blank=True, null=True)
    payout_error = models.TextField(blank=True, null=True,
                                     verbose_name='Lỗi PayOS/burn gần nhất')
    payos_checkout_url = models.TextField(blank=True, null=True,
                                          verbose_name='PayOS Checkout URL (cached)')
    payos_payment_link_id = models.CharField(max_length=255, blank=True, null=True,
                                             verbose_name='PayOS Payment Link ID')
    payos_order_code = models.BigIntegerField(blank=True, null=True,
                                              verbose_name='PayOS Order Code (for webhook lookup)')

    post_proof_general_desc = models.TextField(blank=True, null=True, verbose_name='Mô tả chung minh chứng sau giải ngân')
    post_proof_data = models.JSONField(blank=True, null=True, verbose_name='Dữ liệu ảnh và mô tả từng ảnh')
    post_proof_ipfs_cid = models.CharField(max_length=255, blank=True, null=True, verbose_name='IPFS CID minh chứng sau giải ngân')

    executed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} - {self.amount_requested:,}đ"

    class Meta:
        db_table = 'disbursement_proposal'
        verbose_name = 'Đề xuất giải ngân'
        verbose_name_plural = 'Danh sách đề xuất giải ngân'
        ordering = ['-created_at']

class DisbursementSignature(models.Model):
    """
    Lưu chữ ký EIP-712 off-chain của 1 trong 3 approver (organization /
    supervisor / admin) cho 1 DisbursementProposal. Backend thu thập đủ 3 sig
    rồi đóng gói gửi lên smart3.recordMultisigApproval() trong 1 tx duy nhất.

    - Approver ký typed-data qua MetaMask (eth_signTypedData_v4) → KHÔNG tốn gas.
    - Backend verify lại chữ ký bằng eth_account.messages.encode_typed_data
      trước khi lưu để tránh DB chứa sig rác.
    - `nonce` là số ngẫu nhiên per-signer, chống replay cross-proposal.
    """
    ROLE_CHOICES = [
        ('organization', 'Tổ chức'),
        ('supervisor', 'Giám sát viên'),
        ('admin', 'Admin'),
    ]

    proposal = models.ForeignKey(
        DisbursementProposal, on_delete=models.CASCADE, related_name='offchain_signatures'
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    signer_address = models.CharField(max_length=42, verbose_name='Địa chỉ ví đã ký')
    signature = models.TextField(verbose_name='Signature (hex 0x...)')
    nonce = models.DecimalField(max_digits=78, decimal_places=0,
                                verbose_name='Nonce (uint256)')
    deadline = models.BigIntegerField(verbose_name='Unix deadline')
    # Snapshot các trường đã ký — để backend tái dựng digest khi relay.
    signed_amount = models.DecimalField(max_digits=78, decimal_places=0,
                                        verbose_name='Amount đã ký (uint256, raw 18 decimals)')
    signed_recipient = models.CharField(max_length=42)
    signed_ipfs_cid = models.CharField(max_length=255)
    signed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'disbursement_signature'
        unique_together = ('proposal', 'role')
        verbose_name = 'Chữ ký EIP-712 giải ngân'
        verbose_name_plural = 'Chữ ký EIP-712 giải ngân'

    def __str__(self):
        return f"Sig[{self.role}] proposal={self.proposal_id} by={self.signer_address[:10]}..."


class ProposalVote(models.Model):
    proposal = models.ForeignKey(DisbursementProposal, on_delete=models.CASCADE, related_name='votes')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    is_agree = models.BooleanField(default=True)
    
    # Trọng số tại thời điểm vote (đã áp dụng Cap 30%)
    voting_power = models.DecimalField(max_digits=15, decimal_places=0, null=True, blank=True)
    voted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('proposal', 'user')
        db_table = 'proposal_vote'
# =====================================================
# 6.5 CAMPAIGN DISBURSEMENT (BÁO CÁO GIẢI NGÂN / CHI TIÊU)
# =====================================================
class CampaignDisbursement(models.Model):
    # Trạng thái xử lý
    STATUS_CHOICES = [
        ('pending', 'Chờ kiểm duyệt'),    # Tổ chức vừa tạo báo cáo
        ('verified', 'Đã xác thực'),      # Admin đã check hóa đơn là thật
        ('rejected', 'Từ chối'),          # Hóa đơn mờ, sai, không hợp lệ
        ('on_chain', 'Đã ghi Blockchain') # Đã lưu bằng chứng lên Etherscan
    ]

    # Liên kết
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='disbursements')
    proposal = models.OneToOneField(DisbursementProposal, on_delete=models.CASCADE, null=True, blank=True)
    # Người tạo báo cáo (Thường là Quản lý của Tổ chức)
    reporter = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Người báo cáo")
    # --- MỚI: GIS THỰC ĐỊA ---
    actual_lat = models.DecimalField(max_digits=15, decimal_places=8, null=True, blank=True)
    actual_lng = models.DecimalField(max_digits=15, decimal_places=8, null=True, blank=True)
    location_name = models.CharField(max_length=255, null=True, blank=True)
    # Thông tin chi tiêu
    amount = models.DecimalField(max_digits=15, decimal_places=0, verbose_name="Số tiền đã chi")
    title = models.CharField(max_length=255, verbose_name="Khoản chi (VD: Mua 100 bao gạo)")
    description = models.TextField(verbose_name="Chi tiết chi tiêu")
    
    # Quan trọng: Tiền chi cho ai? (Minh bạch dòng tiền ra)
    recipient_name = models.CharField(max_length=255, verbose_name="Đơn vị thụ hưởng (VD: Cty Gạo A)")
    recipient_contact = models.CharField(max_length=255, blank=True, null=True, verbose_name="Liên hệ thụ hưởng")

    # Bằng chứng Off-chain (Hóa đơn đỏ, Sao kê ngân hàng, Ảnh chụp trao quà...)
    proof_images = ArrayField(models.TextField(), blank=True, null=True, verbose_name="Ảnh hóa đơn/Chứng từ")
    proof_document_url = models.TextField(blank=True, null=True, verbose_name="Link file PDF/Excel (nếu có)")

    # Bằng chứng On-chain (Blockchain)
    # Admin xác thực xong -> Hệ thống tự động ghi giao dịch này lên Blockchain
    eth_tx_hash = models.CharField(max_length=100, blank=True, null=True, verbose_name="TxHash Blockchain")
    
    # Quản trị
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    admin_note = models.TextField(blank=True, null=True, verbose_name="Ghi chú của Admin")
    
    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_disbursements')
    verified_at = models.DateTimeField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Chi: {self.amount} - {self.title}"

    class Meta:
        db_table = 'campaign_disbursement'
        verbose_name = "Báo cáo Giải ngân"
        verbose_name_plural = "Danh sách Giải ngân"

# =====================================================
# 7 → 17: CÁC BẢNG PHỤ
# =====================================================

class BankStatement(models.Model):
    SOURCE_CHOICES = [
        ('vnpay', 'VNPay'),
        ('casso', 'Casso Webhook'),
        ('mock', 'Mock/Test'),
        ('manual', 'Nhập tay'),
    ]

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE)
    donation = models.ForeignKey(Donation, on_delete=models.SET_NULL, null=True, blank=True)
    transaction_date = models.DateTimeField()
    transaction_type = models.CharField(max_length=20)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    balance = models.DecimalField(max_digits=15, decimal_places=2, blank=True, null=True)
    reference_number = models.CharField(max_length=255, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    sender_account = models.CharField(max_length=255, blank=True, null=True)
    sender_name = models.CharField(max_length=255, blank=True, null=True)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='manual')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Statement {self.id}"

    def save(self, *args, **kwargs):
        from django.core.exceptions import PermissionDenied
        if self.pk:
            raise PermissionDenied("Không được phép sửa BankStatement sau khi tạo.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied("Không được phép xóa BankStatement.")

    class Meta:
        db_table = 'bank_statement'
        verbose_name = 'Sao kê ngân hàng'
        verbose_name_plural = 'Danh sách Sao kê ngân hàng'

class CampaignFollower(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    notification_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'campaign_follower'
        unique_together = ('campaign','user')

    def __str__(self):
        return f"{self.user} follows {self.campaign}"

class ViolationReport(models.Model):
    STATUS_CHOICES = [('pending','Pending'),('reviewing','Reviewing'),('resolved','Resolved'),('rejected','Rejected')]
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE)
    reporter = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    reason = models.TextField()
    description = models.TextField(blank=True, null=True)
    evidence_urls = ArrayField(models.TextField(), blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    admin_note = models.TextField(blank=True, null=True)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_reports')
    reviewed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Report {self.id}"

    class Meta:
        db_table = 'violation_report'

class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    type = models.CharField(max_length=50)
    title = models.CharField(max_length=255)
    content = models.TextField(blank=True, null=True)
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, null=True, blank=True)
    donation = models.ForeignKey(Donation, on_delete=models.CASCADE, null=True, blank=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

    class Meta:
        db_table = 'notification'

class HumanitarianLocation(models.Model):
    name = models.CharField(max_length=500)
    type = models.CharField(max_length=50)
    description = models.TextField(blank=True, null=True)
    province = models.CharField(max_length=100, blank=True, null=True)
    district = models.CharField(max_length=100, blank=True, null=True)
    ward = models.CharField(max_length=100, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=8, blank=True, null=True)
    longitude = models.DecimalField(max_digits=11, decimal_places=8, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    website = models.TextField(blank=True, null=True)
    is_verified = models.BooleanField(default=False)
    verified_by = models.CharField(max_length=255, blank=True, null=True)
    verified_at = models.DateTimeField(blank=True, null=True)
    images_urls = ArrayField(models.TextField(), blank=True, null=True)
    operating_hours = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'humanitarian_location'

class SupportTicket(models.Model):
    STATUS_CHOICES = [('open','Open'),('in_progress','In Progress'),('resolved','Resolved'),('closed','Closed')]
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    subject = models.CharField(max_length=500)
    message = models.TextField()
    category = models.CharField(max_length=100, blank=True, null=True)
    contact_name = models.CharField(max_length=255, blank=True, null=True)
    contact_email = models.EmailField(blank=True, null=True)
    contact_phone = models.CharField(max_length=20, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_tickets')
    admin_response = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return self.subject

    class Meta:
        db_table = 'support_ticket'

class FAQ(models.Model):
    category = models.CharField(max_length=100)
    question = models.TextField()
    answer = models.TextField()
    display_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    view_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.question

    class Meta:
        db_table = 'faq'

class QRCode(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, null=True, blank=True)
    type = models.CharField(max_length=50)
    qr_data = models.TextField()
    qr_image_url = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"QR {self.id}"

    class Meta:
        db_table = 'qr_code'

class ActivityLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    type = models.CharField(max_length=50)
    description = models.TextField(blank=True, null=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True, null=True)
    campaign = models.ForeignKey(Campaign, on_delete=models.SET_NULL, null=True, blank=True)
    donation = models.ForeignKey(Donation, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Activity {self.type}"

    class Meta:
        db_table = 'activity_log'

class UserPreference(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    preferred_categories = ArrayField(models.BigIntegerField(), blank=True, null=True)
    feature_vector = ArrayField(models.FloatField(), blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Preference {self.user.username}"

    class Meta:
        db_table = 'user_preference'

class CampaignDetail(models.Model):
    campaign = models.OneToOneField(Campaign, on_delete=models.CASCADE, related_name='detail', verbose_name="Chiến dịch")
    beneficiary_name = models.CharField(max_length=255, verbose_name="Tên thật người thụ hưởng")
    beneficiary_age = models.IntegerField(null=True, blank=True, verbose_name="Tuổi/Năm sinh")
    story = models.TextField(verbose_name="Câu chuyện chi tiết")
    images_urls = ArrayField(models.URLField(), blank=True, default=list, verbose_name="Danh sách link ảnh hoàn cảnh")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Chi tiết hoàn cảnh: {self.campaign.title}"

    class Meta:
        db_table = 'campaign_detail'
        verbose_name = "Chi tiết hoàn cảnh"
        verbose_name_plural = "Chi tiết hoàn cảnh"

class SystemConfig(models.Model):
    key = models.CharField(max_length=100, unique=True)
    value = models.TextField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.key

    class Meta:
        db_table = 'system_config'
