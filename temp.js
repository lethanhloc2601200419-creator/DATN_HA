
(function() {
    'use strict';

    // ============================================================
    // 1. DATA + STATE
    // ============================================================
    var ALL = [];
    try {
        var scriptNode = document.getElementById('map-data');
        if (scriptNode) {
            ALL = JSON.parse(scriptNode.textContent);
        }
    } catch (e) {
        console.error('Lỗi parse map-data:', e);
    }

    var state = { q: '', status: 'all', category: 'all', region: 'all' };

    // Fallback image constant
    var DEFAULT_IMG = '/static/client/img/bg_trangchu.jpg';

    var REGION_PROVINCES = {
        bac: ['hà nội','hải phòng','quảng ninh','lạng sơn','cao bằng','bắc kạn',
              'thái nguyên','bắc giang','phú thọ','vĩnh phúc','bắc ninh','hải dương',
              'hưng yên','hà nam','nam định','thái bình','ninh bình','hà giang',
              'tuyên quang','lào cai','yên bái','điện biên','lai châu','sơn la','hòa bình'],
        trung: ['thanh hóa','nghệ an','hà tĩnh','quảng bình','quảng trị','thừa thiên huế','huế',
                'đà nẵng','quảng nam','quảng ngãi','bình định','phú yên','khánh hòa',
                'ninh thuận','bình thuận','kon tum','gia lai','đắk lắk','đắk nông','lâm đồng'],
        nam: ['tp.hcm','tp hcm','hồ chí minh','sài gòn','bình phước','bình dương','đồng nai','tây ninh',
              'bà rịa - vũng tàu','bà rịa','vũng tàu','long an','tiền giang','bến tre','trà vinh','vĩnh long',
              'đồng tháp','an giang','kiên giang','cần thơ','hậu giang','sóc trăng',
              'bạc liêu','cà mau'],
    };

    var REGION_BBOX = {
        bac:   [[20.5, 102.5], [23.5, 108.5]],
        trung: [[12.0, 105.0], [20.5, 109.5]],
        nam:   [[8.0, 104.0],  [12.5, 109.0]],
    };

    // ============================================================
    // 2. UTILS
    // ============================================================
    function escapeHtml(str) {
        if (str == null) return '';
        return String(str)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
    function formatVnd(n) {
        if (!n || n === 0) return '0đ';
        return new Intl.NumberFormat('vi-VN').format(n) + 'đ';
    }
    function debounce(fn, wait) {
        var t;
        return function() {
            var ctx = this, args = arguments;
            clearTimeout(t);
            t = setTimeout(function() { fn.apply(ctx, args); }, wait);
        };
    }
    function normalize(s) {
        return (s || '').toString().toLowerCase()
            .normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    }
    function provinceToRegion(province) {
        var p = (province || '').toLowerCase().trim();
        if (!p) return null;
        for (var key in REGION_PROVINCES) {
            for (var i = 0; i < REGION_PROVINCES[key].length; i++) {
                if (p.indexOf(REGION_PROVINCES[key][i]) !== -1) return key;
            }
        }
        return null;
    }

    // ============================================================
    // 3. MAP + ICONS
    // ============================================================
    var map = L.map('charity_map', {
        zoomControl: true,
        scrollWheelZoom: true,
    }).setView([16.047079, 108.206230], 6);
    map.zoomControl.setPosition('topright');

    L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; OpenStreetMap &copy; CARTO',
        maxZoom: 19,
    }).addTo(map);

    var geojsonData = null;
    var protectedPolygons = L.layerGroup().addTo(map);

    fetch('{% static "client/js/vietnam.geojson" %}')
        .then(response => response.json())
        .then(data => {
            geojsonData = data;
            if(ALL.length > 0) refresh();
        })
        .catch(err => console.error("Lỗi tải GeoJSON:", err));

    function buildIcon(status) {
        var color = status === 'active' ? '#f97316'
                  : status === 'completed' ? '#16a34a'
                  : '#6b7280';
        return L.divIcon({
            className: 'campaign-marker',
            html: '<div class="marker-pin" style="--pin-color:' + color + '">' +
                    '<i class="fas fa-heart"></i>' +
                  '</div>',
            iconSize: [36, 44],
            iconAnchor: [18, 44],
            popupAnchor: [0, -42],
        });
    }

    var clusterGroup = L.markerClusterGroup({
        showCoverageOnHover: false,
        spiderfyOnMaxZoom: true,
        maxClusterRadius: 55,
        iconCreateFunction: function(cluster) {
            return L.divIcon({
                className: 'campaign-cluster',
                html: '<div class="cluster-bubble"><span>' + cluster.getChildCount() + '</span></div>',
                iconSize: [44, 44],
            });
        },
    });
    map.addLayer(clusterGroup);

    var markersById = {};   // id -> Leaflet marker (cho list hiện tại)
    var dataById = {};      // id -> raw object
    ALL.forEach(function(c) { dataById[c.id] = c; });

    // ============================================================
    // 4. POPUP + SIDEBAR TEMPLATES
    // ============================================================
    function buildPopup(c) {
        var statusBadge =
            c.status === 'active'    ? '<span class="popup-badge popup-badge-active">Đang gây quỹ</span>' :
            c.status === 'completed' ? '<span class="popup-badge popup-badge-completed">Hoàn thành</span>' :
                                        '<span class="popup-badge popup-badge-ended">Đã kết thúc</span>';
        var catBadge = c.category_name
            ? '<span class="popup-badge popup-badge-cat">' + escapeHtml(c.category_name) + '</span>'
            : '';
        var orgLine = c.organization_name
            ? '<div class="popup-org"><i class="fas fa-building"></i> ' + escapeHtml(c.organization_name) + '</div>'
            : '';
        var addrText = c.address || c.province || '—';
        var progressUrgent = c.days_left !== null && c.days_left !== undefined && c.days_left <= 7 && c.status === 'active';
        var daysText;
        if (c.days_left === null || c.days_left === undefined) {
            daysText = '<i class="fas fa-clock"></i>Chiến dịch dài hạn';
        } else if (c.days_left > 0) {
            daysText = '<i class="fas fa-clock"></i>Còn <strong>' + c.days_left + '</strong> ngày';
        } else {
            daysText = '<i class="fas fa-clock"></i>Đã hết hạn';
        }

        return '' +
        '<div class="popup-card">' +
            '<img class="popup-img" src="' + escapeHtml(c.image) + '" alt="" ' +
                'onerror="this.onerror=null;this.src=\'' + DEFAULT_IMG + '\'">' +
            '<div class="popup-body">' +
                '<div class="popup-tags">' + statusBadge + catBadge + '</div>' +
                '<h6 class="popup-title">' + escapeHtml(c.title) + '</h6>' +
                orgLine +
                '<div class="popup-addr"><i class="fas fa-map-marker-alt"></i> ' + escapeHtml(addrText) + '</div>' +
                '<div class="popup-progress">' +
                    '<div class="popup-progress-text">' +
                        '<strong>' + formatVnd(c.current_amount) + '</strong>' +
                        '<span>/ ' + formatVnd(c.target_amount) + '</span>' +
                    '</div>' +
                    '<div class="popup-progress-track">' +
                        '<div class="popup-progress-fill ' + (progressUrgent ? 'urgent' : '') + '" style="width:' + c.progress_pct + '%"></div>' +
                    '</div>' +
                    '<div class="popup-progress-meta">' +
                        '<span>' + c.progress_pct + '% mục tiêu</span>' +
                        '<span><i class="fas fa-users"></i> ' + (c.support_count || 0) + ' người</span>' +
                    '</div>' +
                '</div>' +
                '<div class="popup-meta">' + daysText + '</div>' +
                '<div class="popup-actions">' +
                    '<a href="' + c.url_detail + '" class="btn btn-outline-primary">Chi tiết</a>' +
                    (c.status === 'active'
                        ? '<a href="' + c.url_donate + '" class="btn btn-danger">Ủng hộ</a>'
                        : '') +
                '</div>' +
            '</div>' +
        '</div>';
    }

    function buildSidebarCard(c) {
        var statusLabel = escapeHtml(c.status_label || '');
        var orgLine = c.organization_name
            ? '<div class="sb-org"><i class="fas fa-building"></i> ' + escapeHtml(c.organization_name) + '</div>'
            : '';
        var progressUrgent = c.days_left !== null && c.days_left !== undefined && c.days_left <= 7 && c.status === 'active';
        var province = c.province || '—';
        return '' +
        '<div class="sb-card" data-id="' + c.id + '" data-lat="' + c.lat + '" data-lng="' + c.lng + '">' +
            '<div class="sb-img-wrap">' +
                '<img src="' + escapeHtml(c.image) + '" alt="" ' +
                    'onerror="this.onerror=null;this.src=\'' + DEFAULT_IMG + '\'">' +
                '<span class="sb-status sb-status-' + escapeHtml(c.status) + '">' + statusLabel + '</span>' +
            '</div>' +
            '<div class="sb-body">' +
                '<div class="sb-title" title="' + escapeHtml(c.title) + '">' + escapeHtml(c.title) + '</div>' +
                orgLine +
                '<div class="sb-progress-track">' +
                    '<div class="sb-progress-fill ' + (progressUrgent ? 'urgent' : '') + '" style="width:' + c.progress_pct + '%"></div>' +
                '</div>' +
                '<div class="sb-meta">' +
                    '<span><strong>' + c.progress_pct + '%</strong></span>' +
                    '<span><i class="fas fa-map-marker-alt"></i> ' + escapeHtml(province) + '</span>' +
                '</div>' +
            '</div>' +
        '</div>';
    }

    // ============================================================
    // 5. FILTER LOGIC
    // ============================================================
    function applyFilters() {
        var q = normalize(state.q);
        return ALL.filter(function(c) {
            if (state.status !== 'all' && c.status !== state.status) return false;
            if (state.category !== 'all' && String(c.category_id || '') !== String(state.category)) return false;
            if (state.region !== 'all') {
                if (provinceToRegion(c.province) !== state.region) return false;
            }
            if (q) {
                var hay = normalize(c.title) + ' ' +
                          normalize(c.organization_name) + ' ' +
                          normalize(c.address) + ' ' +
                          normalize(c.province) + ' ' +
                          normalize(c.short_description);
                if (hay.indexOf(q) === -1) return false;
            }
            return true;
        });
    }

    // ============================================================
    // 6. RENDER
    // ============================================================
    const MERGED_PROVINCES = {
        'tuyen quang': ['tuyen quang', 'ha giang'],
        'lao cai': ['lao cai', 'yen bai'],
        'thai nguyen': ['thai nguyen', 'bac kan'],
        'phu tho': ['phu tho', 'vinh phuc'],
        'bac ninh': ['bac ninh', 'bac giang'],
        'hung yen': ['hung yen', 'thai binh'],
        'hai phong': ['hai phong', 'hai duong'],
        'ninh binh': ['ninh binh', 'ha nam', 'nam dinh'],
        'quang tri': ['quang tri', 'quang binh'],
        'da nang': ['da nang', 'quang nam'],
        'quang ngai': ['quang ngai', 'binh dinh'],
        'gia lai': ['gia lai', 'kon tum'],
        'khanh hoa': ['khanh hoa', 'ninh thuan', 'phu yen'],
        'lam dong': ['lam dong', 'binh thuan'],
        'dak lak': ['dak lak', 'dak nong'],
        'ho chi minh': ['ho chi minh', 'ba ria', 'vung tau'],
        'tp.hcm': ['ho chi minh', 'ba ria', 'vung tau'],
        'dong nai': ['dong nai', 'binh duong', 'binh phuoc'],
        'tay ninh': ['tay ninh', 'long an'],
        'can tho': ['can tho', 'hau giang'],
        'vinh long': ['vinh long', 'tra vinh', 'ben tre'],
        'dong thap': ['dong thap', 'tien giang'],
        'ca mau': ['ca mau', 'bac lieu'],
        'an giang': ['an giang', 'soc trang', 'kien giang']
    };

    function getMergedProvinceList(provinceName) {
        var baseName = normalize(provinceName).replace(/tinh |thanh pho |tp /g, '').trim();
        if (MERGED_PROVINCES[baseName]) {
            return MERGED_PROVINCES[baseName];
        }
        return [baseName];
    }

    function renderMarkers(list) {
        clusterGroup.clearLayers();
        protectedPolygons.clearLayers();
        markersById = {};
        
        list.forEach(function(c) {
            var color = c.status === 'active' ? '#f97316' : (c.status === 'completed' ? '#16a34a' : '#6b7280');
            var popupHtml = buildPopup(c);
            
            // Nếu bảo vệ người thụ hưởng VÀ có dữ liệu GeoJSON
            if (c.is_protected_beneficiary && geojsonData && c.province) {
                var searchProvList = getMergedProvinceList(c.province);
                
                var matchedFeatures = geojsonData.features.filter(function(f) {
                    var fName = normalize(f.properties.name || '');
                    return searchProvList.some(function(sp) { return fName.indexOf(sp) !== -1; });
                });
                
                if (matchedFeatures.length > 0) {
                    var poly = L.geoJSON(matchedFeatures, {
                        style: {
                            color: color,
                            weight: 2,
                            opacity: 0.8,
                            fillOpacity: 0.15,
                            dashArray: '5, 5'
                        }
                    });
                    poly.bindPopup(popupHtml, { maxWidth: 280, minWidth: 280, autoPanPadding: [50, 50] });
                    poly.getLayers().forEach(function(l) { l.campaignId = c.id; });
                    protectedPolygons.addLayer(poly);
                    markersById[c.id] = poly;
                    return; // Đã vẽ polygon, bỏ qua marker
                }
            }

            // Fallback: vẽ marker bình thường
            var marker = L.marker([c.lat, c.lng], { 
                icon: buildIcon(c.status),
                riseOnHover: true,
                alt: c.title
            });
            marker.bindPopup(popupHtml, { 
                maxWidth: 280, 
                minWidth: 280,
                autoPanPadding: [50, 50]
            });
            marker.campaignId = c.id;
            clusterGroup.addLayer(marker);
            markersById[c.id] = marker;
        });
    }

    function fitToList(list) {
        if (list.length === 0) return;
        var bounds = L.latLngBounds();
        var hasBounds = false;
        
        list.forEach(function(c) {
            var layer = markersById[c.id];
            if (layer) {
                if (layer.getBounds) {
                    // Polygon
                    bounds.extend(layer.getBounds());
                    hasBounds = true;
                } else if (layer.getLatLng) {
                    // Marker
                    bounds.extend(layer.getLatLng());
                    hasBounds = true;
                }
            }
        });
        
        if (hasBounds) {
            if (list.length === 1 && markersById[list[0].id] && markersById[list[0].id].getLatLng) {
                 map.setView(markersById[list[0].id].getLatLng(), 12);
            } else {
                 map.fitBounds(bounds.pad(0.15));
            }
        }
    }

    function refresh(opts) {
        opts = opts || {};
        var list = applyFilters();
        renderMarkers(list);
        renderSidebar(list);
        if (opts.fit !== false) fitToList(list);
    }

    // ============================================================
    // 7. EVENT BINDINGS
    // ============================================================
    var searchInput = document.getElementById('searchInput');
    searchInput.addEventListener('input', debounce(function() {
        state.q = searchInput.value.trim();
        refresh({ fit: false });
    }, 280));

    document.getElementById('statusFilter').addEventListener('change', function() {
        state.status = this.value;
        refresh();
    });
    document.getElementById('categoryFilter').addEventListener('change', function() {
        state.category = this.value;
        refresh();
    });

    document.querySelectorAll('.region-chip').forEach(function(chip) {
        chip.addEventListener('click', function() {
            document.querySelectorAll('.region-chip').forEach(function(c) { c.classList.remove('active'); });
            this.classList.add('active');
            state.region = this.dataset.region;
            // Khi chọn vùng, fly tới bbox vùng để user thấy ngay
            if (state.region !== 'all' && REGION_BBOX[state.region]) {
                map.flyToBounds(REGION_BBOX[state.region], { padding: [30, 30], duration: 0.6 });
                refresh({ fit: false });
            } else {
                refresh();
            }
        });
    });

    document.getElementById('locateMeBtn').addEventListener('click', function() {
        if (!navigator.geolocation) {
            alert('Trình duyệt không hỗ trợ định vị.');
            return;
        }
        var btn = this;
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
        navigator.geolocation.getCurrentPosition(
            function(pos) {
                map.flyTo([pos.coords.latitude, pos.coords.longitude], 12, { duration: 0.8 });
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-location-crosshairs"></i>';
            },
            function() {
                alert('Không lấy được vị trí của bạn.');
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-location-crosshairs"></i>';
            },
            { enableHighAccuracy: true, timeout: 8000 }
        );
    });

    function resetFilters() {
        state.q = '';
        state.status = 'all';
        state.category = 'all';
        state.region = 'all';
        searchInput.value = '';
        document.getElementById('statusFilter').value = 'all';
        document.getElementById('categoryFilter').value = 'all';
        document.querySelectorAll('.region-chip').forEach(function(c) {
            c.classList.toggle('active', c.dataset.region === 'all');
        });
        refresh();
    }
    document.getElementById('resetBtn').addEventListener('click', resetFilters);
    document.getElementById('clearFiltersBtn').addEventListener('click', resetFilters);
    window.__resetMapFilters = resetFilters;

    // Sidebar card click → fly + open popup
    document.getElementById('campaignList').addEventListener('click', function(e) {
        var card = e.target.closest('.sb-card');
        if (!card) return;
        var id = parseInt(card.dataset.id, 10);
        var marker = markersById[id];
        var data = dataById[id];
        if (!marker || !data) return;

        // highlight card
        document.querySelectorAll('.sb-card.active').forEach(function(el) { el.classList.remove('active'); });
        card.classList.add('active');

        if (marker.getBounds) {
            // Đây là Polygon
            map.fitBounds(marker.getBounds(), { padding: [50, 50], maxZoom: 10 });
            // Lấy layer đầu tiên trong GeoJSON group để mở popup
            var layers = marker.getLayers();
            if (layers.length > 0) {
                layers[0].openPopup();
            }
        } else {
            // Đây là Marker bình thường (có thể nằm trong Cluster)
            clusterGroup.zoomToShowLayer(marker, function() {
                marker.openPopup();
            });
        }

        // Mobile: đóng bottom sheet để user thấy map
        if (window.innerWidth < 992) {
            setTimeout(function() {
                document.getElementById('mapSidebar').classList.remove('expanded');
            }, 300);
        }
    });

    // Mobile bottom-sheet handle
    var sidebarEl = document.getElementById('mapSidebar');
    document.getElementById('sidebarHandle').addEventListener('click', function() {
        sidebarEl.classList.toggle('expanded');
    });

    // Mobile filter toggle
    document.getElementById('mobileFilterToggle').addEventListener('click', function() {
        document.querySelector('.toolbar-collapse').classList.toggle('open');
    });

    // ============================================================
    // 8. INITIAL RENDER
    // ============================================================
    if (ALL.length === 0) {
        document.getElementById('campaignList').innerHTML =
            '<div class="sidebar-empty">' +
                '<i class="fas fa-circle-info"></i>' +
                '<p>Chưa có chiến dịch nào có toạ độ bản đồ. Hãy quay lại sau!</p>' +
            '</div>';
        document.getElementById('totalCount').textContent = '0';
        document.getElementById('visibleCount').textContent = '0';
    } else {
        refresh();
    }

    // Resize handler — bản đồ cần invalidateSize sau khi DOM thay đổi
    window.addEventListener('resize', debounce(function() {
        map.invalidateSize();
    }, 200));
})();
