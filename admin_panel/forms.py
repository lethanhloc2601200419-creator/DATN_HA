from django import forms

from .models import Donation

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