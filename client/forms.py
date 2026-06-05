from django import forms
from django.contrib.auth.models import User
from admin_panel.models import UserProfile


class UserProfileForm(forms.ModelForm):
    """
    Form cho user tự chỉnh sửa các thông tin cơ bản trong profile.

    Bao gồm cả các field từ User (first_name, last_name, email) và UserProfile
    (display_name, phone, address, province, bio, avatar_url).
    Các field on-chain (wallet_address, eoa_address, smart_account_address)
    KHÔNG cho user sửa — quản lý qua flow Web3Auth.
    """
    first_name = forms.CharField(
        required=False, max_length=150, label='Họ',
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    last_name = forms.CharField(
        required=False, max_length=150, label='Tên',
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    email = forms.EmailField(
        required=False, label='Email',
        widget=forms.EmailInput(attrs={'class': 'form-control'}),
    )

    class Meta:
        model = UserProfile
        fields = ['display_name', 'phone', 'address', 'province', 'bio', 'avatar']
        labels = {
            'display_name': 'Tên hiển thị',
            'phone': 'Số điện thoại',
            'address': 'Địa chỉ',
            'province': 'Tỉnh / Thành phố',
            'bio': 'Giới thiệu bản thân',
            'avatar': 'Ảnh đại diện (Tải lên)',
        }
        widgets = {
            'display_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '0123456789'}),
            'address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Số nhà, đường, phường/xã, quận/huyện'}),
            'province': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'TP. Hà Nội'}),
            'bio': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Đôi dòng giới thiệu về bạn...'}),
            'avatar': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
        }

    def __init__(self, *args, **kwargs):
        # Cho phép truyền `user` vào để khởi tạo các field từ auth.User.
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields['first_name'].initial = user.first_name
            self.fields['last_name'].initial = user.last_name
            self.fields['email'].initial = user.email
        # display_name bắt buộc để đảm bảo PDF chứng nhận luôn có tên.
        self.fields['display_name'].required = True
        self._user = user

    def save(self, commit=True):
        profile = super().save(commit=False)
        user = self._user or profile.user
        if user is not None:
            # Dùng trực tiếp giá trị cleaned — cho phép user clear first_name/last_name nếu muốn.
            user.first_name = self.cleaned_data.get('first_name', '')
            user.last_name = self.cleaned_data.get('last_name', '')
            email = self.cleaned_data.get('email', '').strip()
            user.email = email
            if commit:
                user.save(update_fields=['first_name', 'last_name', 'email'])
        if commit:
            profile.save()
        return profile
