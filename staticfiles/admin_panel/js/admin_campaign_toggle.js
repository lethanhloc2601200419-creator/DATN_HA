(function($) {
    'use strict';
    $(function() {
        var $protectedCheckbox = $('#id_is_protected_beneficiary');
        var $wardRow = $('.field-beneficiary_ward');
        var $addressRow = $('.field-beneficiary_address');

        function togglePrivacyFields() {
            if ($protectedCheckbox.is(':checked')) {
                // Hide and disable Ward and Specific Address
                $wardRow.hide();
                $addressRow.hide();
                $('#id_beneficiary_ward').prop('disabled', true);
                $('#id_beneficiary_address').prop('disabled', true);
            } else {
                // Show and enable
                $wardRow.show();
                $addressRow.show();
                $('#id_beneficiary_ward').prop('disabled', false);
                $('#id_beneficiary_address').prop('disabled', false);
            }
        }

        // Initialize state
        togglePrivacyFields();

        // Listen for changes
        $protectedCheckbox.on('change', function() {
            togglePrivacyFields();
        });
    });
})(django.jQuery);
