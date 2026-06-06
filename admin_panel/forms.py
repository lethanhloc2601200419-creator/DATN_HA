from django import forms
from django.forms import DateInput
from .models import Donation, Organization, OrganizationRepresentative

class DonationForm(forms.ModelForm):
    class Meta:
        model = Donation
        # Cho phép Admin sửa: Tên, Số tiền, Lời nhắn, Trạng thái
        fields = ['donor_name', 'amount', 'message', 'status', 'payment_method']
        widgets = {
            'donor_name': forms.TextInput(attrs={'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control text-danger fw-bold'}), # Màu đỏ cho dễ thấy tiền
            'message': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'payment_method': forms.Select(attrs={'class': 'form-select'}),
        }


class GuestOrganizationForm(forms.ModelForm):
    """Form public cho Guest đăng ký tổ chức.

    Loại bỏ các trường quản trị (manager, kyc_status, is_verified, các cờ
    bank/wallet_verified...) — Admin sẽ duyệt sau qua trang quản trị.
    """
    class Meta:
        model = Organization
        fields = [
            'name', 'description', 'logo', 'website',
            'bank_account_number', 'bank_account_name', 'bank_name', 'bank_branch',
            'qr_code_url', 'wallet_address', 'tax_id',
            'operating_license_number', 'founding_date', 'license_document_url',
            'contact_person', 'contact_phone', 'mission_statement',
            'headquarters_address', 'social_media_link',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'VD: Quỹ Trò Nghèo Vùng Cao'}),
            'logo': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'license_document_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'Link ảnh/PDF giấy phép (Drive/Dropbox public)'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Giới thiệu ngắn về tổ chức'}),
            'website': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://example.org'}),
            'bank_account_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Số tài khoản nhận quỹ'}),
            'bank_account_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Chủ tài khoản (CHỮ HOA, không dấu)'}),
            'bank_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'VD: Vietcombank, MB Bank...'}),
            'bank_branch': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Chi nhánh (nếu có)'}),
            'qr_code_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'Link ảnh QR (nếu có)'}),
            'wallet_address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '0x... (Ethereum/Sepolia)'}),
            'tax_id': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Mã số thuế (nếu có)'}),
            'operating_license_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Số giấy phép hoạt động'}),
            'founding_date': DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'contact_person': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Người liên hệ'}),
            'contact_phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Số điện thoại liên hệ'}),
            'mission_statement': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Sứ mệnh của tổ chức'}),
            'headquarters_address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Địa chỉ trụ sở chính'}),
            'social_media_link': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'Link Facebook/Zalo OA...'}),
        }


class GuestRepresentativeForm(forms.ModelForm):
    """Form public cho Guest khai thông tin người đại diện tổ chức.

    Loại bỏ trường organization (sẽ gán ở view sau khi tạo Organization).
    """
    class Meta:
        model = OrganizationRepresentative
        exclude = ['organization', 'created_at', 'updated_at']
        widgets = {
            'full_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Họ và tên đầy đủ'}),
            'position': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'VD: Chủ tịch, Giám đốc...'}),
            'id_card_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Số CCCD/CMND'}),
            'id_card_date': DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'id_card_place': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nơi cấp CCCD/CMND'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Số điện thoại'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@example.com'}),
            'permanent_address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Địa chỉ thường trú'}),
            'id_card_front': forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'id_card_back': forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'authorization_letter': forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': 'image/*,.pdf'}),
        }