# Plan: Campaign Detail Enhancements

The goal is to allow users to enter detailed information for a campaign, including multiple images, and display this information on the campaign detail page.

## 1. UI Enhancements (Admin Panel) - `Ha/admin_panel/templates/admin_panel/quanlychiendich.html` [x]
- Add fields to `addModal`:
    - Beneficiary Name (Họ tên người thụ hưởng) [x]
    - Beneficiary Age (Tuổi/Năm sinh) [x]
    - Detail Story (Câu chuyện chi tiết - `textarea`) [x]
    - Multiple Detail Images (Ảnh chi tiết - `input type="file" multiple`) [x]
- Add fields to `editModal`:
    - Beneficiary Name [x]
    - Beneficiary Age [x]
    - Detail Story [x]
    - Multiple Detail Images [x]
- Add Preview Section for multiple images in both modals [x]
- Add JavaScript to:
    - Preview selected images before upload [x]
    - Fill `editModal` with existing `CampaignDetail` data when clicking "Edit" [x]

## 2. Backend Enhancements (Admin Panel) - `Ha/admin_panel/views.py` [x]
- Update `them_chiendich`:
    - Extract `beneficiary_name`, `beneficiary_age`, `story` from `request.POST` [x]
    - Extract multiple files from `request.FILES.getlist('detail_images')` [x]
    - Create a `CampaignDetail` object associated with the new `Campaign` [x]
    - Upload detail images to Cloudinary and store their URLs in `CampaignDetail.images_urls` [x]
- Update `sua_chiendich`:
    - Update `CampaignDetail` fields [x]
    - Handle new detail images (append or replace? I implemented replace for simplicity). [x]
- Add a helper function to upload multiple files to Cloudinary [x]

## 3. UI Enhancements (Client Detail Page) - `Ha/client/templates/client/chitiet_chiendich.html` [x]
- Double-check if all fields are displayed [x]
- Added display for `start_date`, `end_date`, `target_program`, `occasion`, and full address. [x]

## 4. Verification [x]
- Create a campaign with full details and multiple images [x]
- Verify images and details show up correctly on the detail page [x]
- Edit the campaign and update details/images [x]
- Verify updates reflect correctly [x]
