/**
 * Smart Police Complaints, AI Handwritten OCR Intake & Administrative Governor Workflow
 * Strictly uses XSS-safe DOM builders (createEl / textContent / replaceChildren) — zero raw HTML injection.
 * Zero native browser modal dialogs (custom inline DOM confirmation only).
 */
(function (global) {
    'use strict';

    // ── Constants & Role/Stage Metadata ──────────────────────────────────────
    const MAX_SCAN_BYTES = 10 * 1024 * 1024; // 10 MB
    const ALLOWED_SCAN_MIMES = new Set(['image/jpeg', 'image/png', 'image/webp', 'application/pdf']);
    const ALLOWED_SCAN_EXTS = ['.jpg', '.jpeg', '.png', '.webp', '.pdf'];

    const PRE_APPROVAL_STAGES = new Set(['draft_scan', 'officer_reviewed', 'governor_rejected']);
    const POST_APPROVAL_STAGES = new Set(['governor_approved', 'governor_modified', 'in_execution']);
    const SECTION_HEAD_ALLOWED_STAGES = new Set([
        'draft_scan',
        'officer_reviewed',
        'pending_section_head',
        'governor_rejected',
        'pending_governor'
    ]);
    const GOVERNOR_ALLOWED_STAGES = new Set([
        'pending_governor',
        'governor_approved',
        'governor_modified',
        'governor_rejected'
    ]);

    const STAGE_META = {
        draft_scan: { label: 'مسودة / مسح جديد', badgeClass: 'pc-stage-draft' },
        officer_reviewed: { label: 'مراجعة الضابط', badgeClass: 'pc-stage-officer' },
        pending_section_head: { label: 'بانتظار رئيس القسم', badgeClass: 'pc-stage-section' },
        pending_governor: { label: 'بانتظار الحاكم الإداري', badgeClass: 'pc-stage-governor' },
        governor_approved: { label: 'معتمدة من الحاكم الإداري', badgeClass: 'pc-stage-approved' },
        governor_modified: { label: 'معتمدة (إجراء معدل)', badgeClass: 'pc-stage-modified' },
        governor_rejected: { label: 'مرفوضة من الحاكم الإداري', badgeClass: 'pc-stage-rejected' },
        in_execution: { label: 'قيد التنفيذ', badgeClass: 'pc-stage-execution' },
        completed: { label: 'منجزة', badgeClass: 'pc-stage-completed' },
        stopped_90_days: { label: 'كف طلب (90 يوماً)', badgeClass: 'pc-stage-stopped' }
    };

    const ROLE_LABELS = {
        admin: 'رئيس القسم',
        officer: 'ضابط',
        governor: 'الحاكم الإداري',
        caller: 'ضابط اتصال'
    };

    const LLM_DEFAULTS = {
        gemini: { model: 'gemini-2.5-flash', baseUrl: 'https://generativelanguage.googleapis.com' },
        openai: { model: 'gpt-4o', baseUrl: 'https://api.openai.com/v1' },
        ollama: { model: 'llama3.2-vision', baseUrl: 'http://localhost:11434' }
    };

    // ── Module State ─────────────────────────────────────────────────────────
    const state = {
        initialized: false,
        currentUser: null,
        complaints: [],
        stats: {},
        currentDetail: null,
        detailActiveScanIndex: 0,
        pendingScanFile: null,
        pendingLocalPreviewUrl: null,
        uploadedScans: [],
        uploadedScanIds: [],
        intakeActiveScanIndex: 0,
        lastAiResult: null,
        isScanning: false,
        isSavingIntake: false,
        isSubmittingOfficerAction: false,
        isSubmittingSectionHead: false,
        isSubmittingGovernor: false,
        isSubmittingFollowup: false,
        isSavingLlmSettings: false,
        isTestingLlmSettings: false,
        stationsLoaded: false,
        stationsDirectory: new Map(),
        officersLoaded: false,
        officersPromise: null,
        pendingAssignedOfficerId: null,
        officersList: [],
        llmSettingsMeta: { provider: 'gemini', api_key_configured: false, is_enabled: true },
        listRequestSeq: 0,
        detailRequestSeq: 0,
        stationMatchSeq: 0,
        listAbortController: null,
        detailAbortController: null,
        stationMatchAbortController: null,
        printCleanupTimer: null,
        printCleanupHandler: null,
        searchDebounceTimer: null,
        stationMatchTimer: null,
        deepLinkHandled: false
    };

    // ── Safe Escaping & DOM Utilities ────────────────────────────────────────

    /**
     * Escape plain text for contexts needing HTML entity encoding.
     * @param {*} value
     * @returns {string}
     */
    function pcEscape(value) {
        if (value === null || value === undefined) return '';
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    /**
     * Build a DOM element safely without HTML string injection.
     * @param {string} tag
     * @param {Object} [attrs]
     * @param {string|Node|Array} [children]
     * @returns {HTMLElement}
     */
    function createEl(tag, attrs, children) {
        const el = document.createElement(tag);
        if (attrs && typeof attrs === 'object') {
            Object.entries(attrs).forEach(([key, val]) => {
                if (val === undefined || val === null || val === false) return;
                if (key === 'className') {
                    el.className = String(val);
                } else if (key === 'textContent' || key === 'text') {
                    el.textContent = String(val);
                } else if (key === 'value') {
                    el.value = String(val);
                } else if (key === 'checked' || key === 'disabled' || key === 'selected' || key === 'readOnly' || key === 'required') {
                    el[key] = Boolean(val);
                } else if (key === 'dataset' && typeof val === 'object') {
                    Object.entries(val).forEach(([dk, dv]) => {
                        if (dv !== undefined && dv !== null) el.dataset[dk] = String(dv);
                    });
                } else if (key === 'style' && typeof val === 'object') {
                    Object.assign(el.style, val);
                } else if (key.startsWith('on') && typeof val === 'function') {
                    el.addEventListener(key.slice(2).toLowerCase(), val);
                } else {
                    el.setAttribute(key, val === true ? '' : String(val));
                }
            });
        }
        appendChildren(el, children);
        return el;
    }

    function appendChildren(parent, children) {
        if (children === undefined || children === null || children === false) return;
        if (Array.isArray(children)) {
            children.forEach((child) => appendChildren(parent, child));
        } else if (children instanceof Node) {
            parent.appendChild(children);
        } else {
            parent.appendChild(document.createTextNode(String(children)));
        }
    }

    function $(id) {
        return document.getElementById(id);
    }

    function pcToast(message, isError = false) {
        const container = $('toastContainer');
        if (!container) return;
        const toast = createEl('div', { className: `toast ${isError ? 'toast-error' : ''}` }, [
            createEl('span', { textContent: isError ? '⚠️' : '🔔' }),
            createEl('div', { style: { flex: '1' }, textContent: String(message || '') })
        ]);
        container.appendChild(toast);
        setTimeout(() => {
            toast.style.opacity = '0';
            setTimeout(() => toast.remove(), 300);
        }, 6000);
    }

    function findButtonByOnclick(container, fnName) {
        if (!container) return null;
        const buttons = Array.from(container.querySelectorAll('button') || []);
        return buttons.find((b) => String((b.getAttribute && b.getAttribute('onclick')) || '').includes(fnName)) || null;
    }

    function pcOpenModal(modalId) {
        if (typeof global.openModal === 'function') {
            global.openModal(modalId);
            return;
        }
        const el = $(modalId);
        if (el) el.classList.add('active', 'show');
    }

    function pcCloseModal(modalId) {
        if (typeof global.closeModal === 'function') {
            global.closeModal(modalId);
            return;
        }
        const el = $(modalId);
        if (el) el.classList.remove('active', 'show');
    }

    function pcGetSavedUserSync() {
        if (typeof currentUser !== 'undefined' && currentUser) {
            state.currentUser = currentUser;
            return currentUser;
        }
        if (state.currentUser) return state.currentUser;
        try {
            const raw = localStorage.getItem('mat_current_user');
            if (raw) {
                const parsed = JSON.parse(raw);
                if (parsed && parsed.username) {
                    state.currentUser = parsed;
                    return parsed;
                }
            }
        } catch (_) {
            // Ignore malformed local storage
        }
        return null;
    }

    async function ensureCurrentUser() {
        const existing = pcGetSavedUserSync();
        if (existing) return existing;
        try {
            const res = await fetch('/api/v1/mat/me');
            if (res.ok) {
                const user = await res.json();
                if (user && user.username) {
                    state.currentUser = user;
                    return user;
                }
            }
        } catch (_) {
            // Network errors handled by callers
        }
        return null;
    }

    function getUserRole(user) {
        return String((user && user.role) || '').trim();
    }

    function isSafeScanUrl(url) {
        const s = String(url || '').trim();
        return (
            s.startsWith('/api/v1/mat/police-complaints/scans/') ||
            s.startsWith('blob:') ||
            /^data:image\/(jpeg|png|webp);base64,/i.test(s)
        );
    }

    function setSelectValueIfOptionExists(selectEl, value) {
        if (!selectEl) return false;
        const target = String(value || '').trim();
        if (!target) {
            selectEl.value = '';
            return false;
        }
        const matched = Array.from(selectEl.options || []).some((opt) => opt.value === target);
        if (matched) {
            selectEl.value = target;
            return true;
        }
        return false;
    }

    function normalizeDigits(str) {
        const arabicIndic = '٠١٢٣٤٥٦٧٨٩';
        return String(str || '').replace(/[٠-٩]/g, (d) => String(arabicIndic.indexOf(d)));
    }

    function normalizeDateForInput(raw) {
        const clean = normalizeDigits(raw).trim();
        if (!clean) return '';
        let match = clean.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$/);
        if (match) {
            return `${match[1]}-${match[2].padStart(2, '0')}-${match[3].padStart(2, '0')}`;
        }
        match = clean.match(/^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$/);
        if (match) {
            return `${match[3]}-${match[2].padStart(2, '0')}-${match[1].padStart(2, '0')}`;
        }
        return '';
    }

    async function readJsonSafe(res) {
        try {
            return await res.json();
        } catch (_) {
            return {};
        }
    }

    // ── Stations Directory & GIS Matching ────────────────────────────────────

    async function ensureStationsDatalistLoaded() {
        if (state.stationsLoaded) return;
        const datalist = $('pcStationsDatalist');
        if (!datalist) return;
        try {
            const res = await fetch('/api/v1/mat/areas');
            if (!res.ok) return;
            const areas = await res.json();
            if (!Array.isArray(areas)) return;

            const stationMap = new Map();
            areas.forEach((area) => {
                if (!area || typeof area !== 'object') return;
                const stationName = String(area.closest || '').trim();
                if (!stationName) return;
                if (!stationMap.has(stationName)) {
                    stationMap.set(stationName, {
                        nearest_station: stationName,
                        police_directorate: String(area.directorate || '').trim(),
                        liwa_name: String(area.liwa || '').trim(),
                        lat: typeof area.lat === 'number' ? area.lat : null,
                        lon: typeof area.lon === 'number' ? area.lon : null
                    });
                }
            });

            state.stationsDirectory = stationMap;
            const uniqueNames = Array.from(stationMap.keys()).sort((a, b) => a.localeCompare(b, 'ar'));
            const frag = document.createDocumentFragment();
            uniqueNames.forEach((name) => {
                frag.appendChild(createEl('option', { value: name }));
            });
            datalist.replaceChildren(frag);
            state.stationsLoaded = true;
        } catch (_) {
            // Non-fatal; user can still type station manually
        }
    }

    async function ensureOfficersLoaded() {
        const select = $('pcAssignedOfficerId');
        if (!select) return;
        if (state.officersLoaded && select.options.length > 1) {
            if (state.pendingAssignedOfficerId !== null) {
                setSelectValueIfOptionExists(select, state.pendingAssignedOfficerId);
            }
            return;
        }
        if (state.officersPromise) {
            return state.officersPromise;
        }

        state.officersPromise = (async () => {
            try {
                const res = await fetch('/api/v1/mat/officers');
                if (!res.ok) return;
                const data = await res.json();
                const officers = (data.officers || data.mat_officers || []).filter(
                    (o) => o && o.is_active && (o.role === 'officer' || o.role === 'admin')
                );
                state.officersList = officers;
                const currentVal = select.value;
                const frag = document.createDocumentFragment();
                frag.appendChild(createEl('option', { value: '', textContent: 'أنا (المستخدم الحالي)' }));
                officers.forEach((o) => {
                    const roleLabel = o.role === 'admin' ? 'رئيس قسم' : 'ضابط';
                    frag.appendChild(createEl('option', {
                        value: String(o.id),
                        textContent: `${o.name} (${roleLabel})`
                    }));
                });
                select.replaceChildren(frag);
                const desiredVal = state.pendingAssignedOfficerId !== null
                    ? state.pendingAssignedOfficerId
                    : currentVal;
                if (desiredVal) setSelectValueIfOptionExists(select, desiredVal);
                else select.value = '';
                state.officersLoaded = true;
            } catch (_) {
                // Non-fatal
            } finally {
                state.officersPromise = null;
            }
        })();

        return state.officersPromise;
    }

    function getFirstRespondentAddressFromForm() {
        const list = $('pcRespondentsList');
        if (!list) return '';
        const inputs = list.querySelectorAll('.pc-party-address');
        for (const inp of inputs) {
            const val = String(inp.value || '').trim();
            if (val) return val;
        }
        return '';
    }

    async function matchStationByAddress(address, options = {}) {
        const cleanAddr = String(address || '').trim();
        if (!cleanAddr) return null;
        const reqSeq = ++state.stationMatchSeq;
        if (state.stationMatchAbortController) {
            try { state.stationMatchAbortController.abort(); } catch (_) {}
        }
        const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
        state.stationMatchAbortController = controller;

        try {
            const fetchOpts = controller ? { signal: controller.signal } : {};
            const res = await fetch(`/api/v1/mat/police-complaints/match-station?address=${encodeURIComponent(cleanAddr)}`, fetchOpts);
            if (reqSeq !== state.stationMatchSeq) return null;
            if (!res.ok) return null;
            const data = await res.json();
            if (reqSeq !== state.stationMatchSeq) return null;
            if (data && data.matched) {
                applyStationMatchToIntakeForm(data);
                if (options.notify) {
                    pcToast(`📍 تم تحديد أقرب مركز أمني: ${data.nearest_station}`);
                }
            } else if (options.notify) {
                pcToast('لم يتم العثور على مطابقة دقيقة في الدليل — يمكنك اختيار المركز يدوياً', true);
            }
            return data;
        } catch (err) {
            if ((err && err.name === 'AbortError') || reqSeq !== state.stationMatchSeq) {
                return null;
            }
            if (options.notify) {
                pcToast('تعذر الاتصال بخدمة تحديد أقرب مركز أمني', true);
            }
            return null;
        } finally {
            if (state.stationMatchAbortController === controller) {
                state.stationMatchAbortController = null;
            }
        }
    }

    function applyStationMatchToIntakeForm(matchData) {
        if (!matchData) return;
        const stInput = $('pcNearestStation');
        const dirInput = $('pcPoliceDirectorate');
        const liwaInput = $('pcLiwaName');
        const latInput = $('pcStationLat');
        const lonInput = $('pcStationLon');

        if (matchData.nearest_station) {
            if (stInput) stInput.value = matchData.nearest_station;
            if (dirInput) dirInput.value = matchData.police_directorate || '';
            if (liwaInput) liwaInput.value = matchData.liwa_name || '';
            if (latInput) latInput.value = matchData.lat !== null && matchData.lat !== undefined ? String(matchData.lat) : '';
            if (lonInput) lonInput.value = matchData.lon !== null && matchData.lon !== undefined ? String(matchData.lon) : '';
        }
    }

    function scheduleAutoStationMatch() {
        clearTimeout(state.stationMatchTimer);
        state.stationMatchTimer = setTimeout(() => {
            const addr = getFirstRespondentAddressFromForm();
            if (addr && addr.length >= 2) {
                matchStationByAddress(addr, { notify: false });
            }
        }, 420);
    }

    async function rematchComplaintStation() {
        const addr = getFirstRespondentAddressFromForm();
        if (!addr) {
            pcToast('يرجى إدخال عنوان المشتكى عليه أولاً لتحديد أقرب مركز أمني', true);
            return;
        }
        await matchStationByAddress(addr, { notify: true });
    }

    function openStationInFinder(complaintObj) {
        let query = '';
        if (complaintObj && typeof complaintObj === 'object') {
            const resp = (complaintObj.parties || []).find((p) => p.party_type === 'مشتكى_عليه' && p.address);
            query = String((resp && resp.address) || complaintObj.nearest_station || '').trim();
            pcCloseModal('modalPoliceComplaintDetail');
        } else {
            query = getFirstRespondentAddressFromForm() || String($('pcNearestStation')?.value || '').trim();
        }

        const iframe = $('stationsIframe');
        const canSwitch = typeof global.switchTab === 'function' && $('tab-stations');

        if (canSwitch && iframe) {
            const targetSrc = `../Police_Station_Finder.html?v=1.46.5${query ? `&q=${encodeURIComponent(query)}` : ''}`;
            const applyQueryIntoFinder = () => {
                if (!query) return;
                try {
                    const doc = iframe.contentDocument || (iframe.contentWindow && iframe.contentWindow.document);
                    if (!doc) return;
                    const inp = doc.getElementById('placeInput') || doc.getElementById('mapAreaSearchInput');
                    if (inp) {
                        inp.value = query;
                        inp.dispatchEvent(new Event('input', { bubbles: true }));
                    }
                } catch (_) {
                    // Cross-origin or iframe still loading
                }
            };

            if (iframe.src && iframe.src.includes('Police_Station_Finder')) {
                global.switchTab('stations');
                applyQueryIntoFinder();
            } else {
                iframe.addEventListener('load', applyQueryIntoFinder, { once: true });
                iframe.src = targetSrc;
                global.switchTab('stations');
            }
            return;
        }

        const finderUrl = `/finder${query ? `?q=${encodeURIComponent(query)}` : ''}`;
        global.open(finderUrl, '_blank', 'noopener,noreferrer');
    }

    // ── Intake Form Party Rows ───────────────────────────────────────────────

    function addComplaintPartyRow(partyType, initialData = {}) {
        const isComplainant = partyType === 'شاكي';
        const container = $(isComplainant ? 'pcComplainantsList' : 'pcRespondentsList');
        if (!container) return null;

        const categories = isComplainant
            ? ['مواطن', 'مؤسسة تجارية', 'مؤسسة حكومية']
            : ['مواطن', 'منشأة'];
        if (initialData.party_category && !categories.includes(initialData.party_category)) {
            categories.push(initialData.party_category);
        }
        const initCat = categories.includes(initialData.party_category)
            ? initialData.party_category
            : categories[0];

        const catSelect = createEl(
            'select',
            { className: 'form-control pc-party-category', 'aria-label': 'صفة الطرف' },
            categories.map((cat) => createEl('option', { value: cat, textContent: cat, selected: cat === initCat }))
        );

        const nameInput = createEl('input', {
            type: 'text',
            className: 'form-control pc-party-name',
            placeholder: isComplainant ? 'الاسم الكامل للمشتكي *' : 'اسم المشتكى عليه / المنشأة *',
            value: initialData.name || ''
        });

        const nationalIdInput = createEl('input', {
            type: 'text',
            className: 'form-control pc-party-national-id',
            placeholder: isComplainant ? 'الرقم الوطني / التجاري' : 'الرقم الوطني (اختياري)',
            value: initialData.national_id || ''
        });

        const phoneInput = createEl('input', {
            type: 'text',
            className: 'form-control pc-party-phone',
            placeholder: 'رقم الهاتف',
            value: initialData.phone || ''
        });

        const addrAttrs = {
            type: 'text',
            className: 'form-control pc-party-address',
            placeholder: isComplainant ? 'العنوان بالتفصيل' : 'العنوان (يحدد أقرب مركز تلقائياً)',
            value: initialData.address || ''
        };
        if (!isComplainant) {
            addrAttrs.onInput = () => scheduleAutoStationMatch();
            addrAttrs.onChange = () => scheduleAutoStationMatch();
        }
        const addressInput = createEl('input', addrAttrs);

        const row = createEl('div', { className: 'pc-party-row', dataset: { partyType } });
        const removeBtn = createEl('button', {
            type: 'button',
            className: 'btn btn-ghost btn-sm pc-party-remove-btn',
            title: 'حذف هذا الطرف',
            textContent: '🗑️',
            onClick: () => {
                if (container.querySelectorAll('.pc-party-row').length <= 1) {
                    [nameInput, nationalIdInput, phoneInput, addressInput].forEach((inp) => { inp.value = ''; });
                    if (!isComplainant) scheduleAutoStationMatch();
                    return;
                }
                row.remove();
                if (!isComplainant) scheduleAutoStationMatch();
            }
        });

        appendChildren(row, [catSelect, nameInput, nationalIdInput, phoneInput, addressInput, removeBtn]);
        container.appendChild(row);
        return row;
    }

    function collectPartiesFromContainer(containerId, partyType) {
        const container = $(containerId);
        if (!container) return [];
        const rows = Array.from(container.querySelectorAll('.pc-party-row'));
        const list = [];
        rows.forEach((row) => {
            const name = String(row.querySelector('.pc-party-name')?.value || '').trim();
            if (!name) return;
            list.push({
                party_type: partyType,
                party_category: String(row.querySelector('.pc-party-category')?.value || 'مواطن').trim() || 'مواطن',
                name,
                national_id: String(row.querySelector('.pc-party-national-id')?.value || '').trim(),
                phone: String(row.querySelector('.pc-party-phone')?.value || '').trim(),
                address: String(row.querySelector('.pc-party-address')?.value || '').trim()
            });
        });
        return list;
    }

    function populatePartyRows(containerId, partyType, items) {
        const container = $(containerId);
        if (!container) return;
        container.replaceChildren();
        const arr = Array.isArray(items) && items.length > 0 ? items : [{}];
        arr.forEach((item) => addComplaintPartyRow(partyType, item));
    }

    // ── Scanner Upload, Preview, & AI Extraction ─────────────────────────────

    function setExtractionStatus(text, badgeVariant = 'badge-blue') {
        const el = $('pcExtractionStatus');
        if (!el) return;
        el.className = `badge ${badgeVariant}`;
        el.textContent = text;
    }

    function revokeLocalPreviewUrl() {
        if (state.pendingLocalPreviewUrl) {
            try {
                URL.revokeObjectURL(state.pendingLocalPreviewUrl);
            } catch (_) {}
            state.pendingLocalPreviewUrl = null;
        }
    }

    function normalizeScanFilename(file) {
        const rawName = String((file && file.name) || '').trim();
        const lower = rawName.toLowerCase();
        if (rawName && ALLOWED_SCAN_EXTS.some((ext) => lower.endsWith(ext))) {
            return rawName;
        }
        const mime = String((file && file.type) || '').toLowerCase();
        const extMap = {
            'image/jpeg': '.jpg',
            'image/png': '.png',
            'image/webp': '.webp',
            'application/pdf': '.pdf'
        };
        const ext = extMap[mime] || '.png';
        const base = rawName ? rawName.replace(/\.[^.]+$/, '') : 'pasted_scan';
        return `${base}${ext}`;
    }

    function validateScanFile(file) {
        if (!file) return 'لم يتم اختيار ملف';
        if (file.size === 0) return 'الملف المختار فارغ';
        if (file.size > MAX_SCAN_BYTES) return 'حجم الملف يتجاوز الحد الأقصى المسموح به (10 ميجابايت)';

        const mime = String(file.type || '').toLowerCase();
        const name = String(file.name || '').toLowerCase();
        const hasAllowedExt = ALLOWED_SCAN_EXTS.some((ext) => name.endsWith(ext));
        const hasAllowedMime = ALLOWED_SCAN_MIMES.has(mime);

        if (!hasAllowedMime && !hasAllowedExt) {
            return 'صيغة الملف غير مدعومة — يُسمح فقط بملفات JPG, PNG, WEBP, PDF';
        }
        return '';
    }

    function renderScanMediaNode(url, mimeType, titleText) {
        if (!isSafeScanUrl(url)) {
            return createEl('div', { className: 'pc-preview-empty', textContent: 'رابط المعاينة غير صالح' });
        }
        const isPdf = String(mimeType || '').toLowerCase() === 'application/pdf' || url.toLowerCase().endsWith('.pdf');
        if (isPdf) {
            return createEl('iframe', {
                src: url,
                title: titleText || 'معاينة ملف PDF'
            });
        }
        return createEl('img', {
            src: url,
            alt: titleText || 'صورة الشكوى الممسوحة'
        });
    }

    function renderIntakePreview(localUrl, localMime, localFilename) {
        const area = $('pcScanPreviewArea');
        if (!area) return;
        area.replaceChildren();

        if (state.uploadedScans.length > 0) {
            const idx = Math.max(0, Math.min(state.intakeActiveScanIndex, state.uploadedScans.length - 1));
            const activeScan = state.uploadedScans[idx];

            if (state.uploadedScans.length > 1) {
                const tabsBar = createEl('div', {
                    style: { display: 'flex', gap: '0.4rem', flexWrap: 'wrap', width: '100%', justifyContent: 'center' }
                });
                state.uploadedScans.forEach((sc, i) => {
                    tabsBar.appendChild(createEl('button', {
                        type: 'button',
                        className: `btn btn-sm ${i === idx ? 'btn-primary' : 'btn-outline'}`,
                        textContent: `صفحة ${i + 1}`,
                        onClick: () => {
                            state.intakeActiveScanIndex = i;
                            renderIntakePreview();
                        }
                    }));
                });
                area.appendChild(tabsBar);
            }

            const scanUrl = activeScan.url || `/api/v1/mat/police-complaints/scans/${encodeURIComponent(activeScan.id)}`;
            area.appendChild(renderScanMediaNode(scanUrl, activeScan.mime_type, activeScan.original_filename));
            area.appendChild(createEl('div', {
                style: { fontSize: '0.78rem', color: 'var(--text-secondary)', marginTop: '0.25rem' },
                textContent: `📄 ${activeScan.original_filename || `وثيقة #${activeScan.id}`}`
            }));
            return;
        }

        if (localUrl) {
            area.appendChild(renderScanMediaNode(localUrl, localMime, localFilename));
            if (localFilename) {
                area.appendChild(createEl('div', {
                    style: { fontSize: '0.78rem', color: 'var(--text-secondary)', marginTop: '0.25rem' },
                    textContent: `📄 ${localFilename}`
                }));
            }
            return;
        }

        area.appendChild(createEl('div', {
            className: 'pc-preview-empty',
            textContent: 'لم يتم اختيار وثيقة ممسوحة بعد — ستظهر المعاينة هنا'
        }));
    }

    function readFileAsDataUrl(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(String(reader.result || ''));
            reader.onerror = () => reject(new Error('تعذر قراءة الملف من المتصفح'));
            reader.readAsDataURL(file);
        });
    }

    async function getJpegExifOrientation(file) {
        try {
            const name = String(file.name || '').toLowerCase();
            const mime = String(file.type || '').toLowerCase();
            if (mime !== 'image/jpeg' && !name.endsWith('.jpg') && !name.endsWith('.jpeg')) {
                return 1;
            }
            const buf = await file.slice(0, 65536).arrayBuffer();
            const view = new DataView(buf);
            if (view.byteLength < 4 || view.getUint16(0, false) !== 0xFFD8) return 1;
            let offset = 2;
            while (offset + 4 <= view.byteLength) {
                const marker = view.getUint16(offset, false);
                offset += 2;
                if (marker === 0xFFE1 && offset + 8 <= view.byteLength) {
                    if (view.getUint32(offset + 2, false) !== 0x45786966) return 1;
                    const tiffStart = offset + 8;
                    if (tiffStart + 8 > view.byteLength) return 1;
                    const little = view.getUint16(tiffStart, false) === 0x4949;
                    const ifdOffset = view.getUint32(tiffStart + 4, little);
                    const dirStart = tiffStart + ifdOffset;
                    if (dirStart + 2 > view.byteLength) return 1;
                    const entries = view.getUint16(dirStart, little);
                    for (let i = 0; i < entries; i++) {
                        const entry = dirStart + 2 + i * 12;
                        if (entry + 10 > view.byteLength) break;
                        if (view.getUint16(entry, little) === 0x0112) {
                            return view.getUint16(entry + 8, little) || 1;
                        }
                    }
                    return 1;
                }
                if ((marker & 0xFF00) !== 0xFF00) break;
                if (offset + 2 > view.byteLength) break;
                offset += view.getUint16(offset, false);
            }
        } catch (_err) {
            return 1;
        }
        return 1;
    }

    async function prepareScanUploadDataUrl(file) {
        const mime = String(file.type || '').toLowerCase();
        const isPdf = mime === 'application/pdf' || String(file.name || '').toLowerCase().endsWith('.pdf');
        if (isPdf || typeof createImageBitmap !== 'function') {
            return readFileAsDataUrl(file);
        }

        try {
            const orientation = await getJpegExifOrientation(file);
            const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
            const maxDim = Math.max(bitmap.width || 0, bitmap.height || 0);
            const MAX_EDGE = 1600;

            if (orientation <= 1 && maxDim <= MAX_EDGE && file.size <= 750000) {
                bitmap.close?.();
                return readFileAsDataUrl(file);
            }

            const scale = maxDim > MAX_EDGE ? (MAX_EDGE / maxDim) : 1;
            const outW = Math.max(1, Math.round(bitmap.width * scale));
            const outH = Math.max(1, Math.round(bitmap.height * scale));
            const canvas = document.createElement('canvas');
            canvas.width = outW;
            canvas.height = outH;
            const ctx = canvas.getContext('2d');
            if (!ctx) {
                bitmap.close?.();
                return readFileAsDataUrl(file);
            }
            ctx.drawImage(bitmap, 0, 0, outW, outH);
            bitmap.close?.();
            return canvas.toDataURL('image/jpeg', 0.90);
        } catch (_err) {
            return readFileAsDataUrl(file);
        }
    }

    function renderAiAnalysisBox(scanResponse, isPdfFile) {
        const box = $('pcAiAnalysisBox');
        if (!box) return;
        box.replaceChildren();

        if (!scanResponse) {
            box.style.display = 'none';
            return;
        }

        const status = scanResponse.status || 'manual_fallback';
        const provider = String(scanResponse.provider || '').toLowerCase();
        const model = String(scanResponse.model || '');
        const analysis = scanResponse.analysis || {};

        box.style.display = 'flex';

        if (status === 'manual_fallback') {
            const isPdfNonGemini = isPdfFile && provider && provider !== 'gemini';
            const noteText = isPdfNonGemini
                ? `تنبيه: استخراج النصوص من ملفات PDF مدعوم عبر مزود Google Gemini فقط (المزود الحالي: ${provider}). تم حفظ الوثيقة الممسوحة ويمكنك إدخال البيانات يدوياً أو تفعيل Gemini من إعدادات الذكاء الاصطناعي.`
                : `تم حفظ الوثيقة بنجاح في النظام وتعذر التحليل الآلي (${scanResponse.message || 'إدخال يدوي'}). يمكنك استكمال حقول الشكوى يدوياً.`;

            box.appendChild(createEl('div', {
                style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.5rem', flexWrap: 'wrap' }
            }, [
                createEl('span', { className: 'badge badge-yellow', textContent: '✍️ إدخال يدوي / وضع احتياطي' }),
                provider ? createEl('small', { className: 'text-muted', textContent: `${provider}${model ? ` / ${model}` : ''}` }) : null
            ]));
            box.appendChild(createEl('div', {
                style: { fontSize: '0.85rem', color: '#92400E', fontWeight: '600' },
                textContent: noteText
            }));
            return;
        }

        const isMinor = analysis.is_minor_police_complaint !== false;
        const rawConfidence = (analysis.ai_confidence !== null && analysis.ai_confidence !== undefined && analysis.ai_confidence !== '')
            ? Number(analysis.ai_confidence)
            : 0.8;
        const confPct = Math.round((Number.isFinite(rawConfidence) ? rawConfidence : 0.8) * 100);

        box.appendChild(createEl('div', {
            style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.5rem', flexWrap: 'wrap' }
        }, [
            createEl('span', {
                className: `badge ${isMinor ? 'badge-green' : 'badge-red'}`,
                textContent: isMinor ? '✅ مشكلة خفيفة تتطلب شرطة' : '⚖️ غير مشمولة / قضائية'
            }),
            createEl('span', {
                className: 'badge badge-purple',
                textContent: `نسبة الثقة: ${confPct}%`
            })
        ]));

        if (provider) {
            box.appendChild(createEl('div', {
                style: { fontSize: '0.76rem', color: 'var(--text-secondary)' },
                textContent: `🤖 محرك التحليل: ${provider}${model ? ` (${model})` : ''}`
            }));
        }

        const fields = [
            { label: 'التكييف الشرطي:', value: analysis.police_necessity_reason },
            { label: 'التحليل الإداري والقانوني:', value: analysis.ai_analysis },
            { label: 'التوصية بالحل:', value: analysis.ai_solution_recommendation },
            { label: 'الإجراء المقترح:', value: analysis.ai_recommended_action }
        ];

        fields.forEach((f) => {
            if (!f.value) return;
            box.appendChild(createEl('div', { style: { fontSize: '0.84rem', lineHeight: '1.5' } }, [
                createEl('strong', { textContent: `${f.label} ` }),
                document.createTextNode(f.value)
            ]));
        });

        const rawTranscript = String((scanResponse && scanResponse.extracted && scanResponse.extracted.raw_transcription) || '').trim();
        if (rawTranscript) {
            const detailsEl = createEl('details', {
                style: { marginTop: '0.35rem', fontSize: '0.8rem' }
            }, [
                createEl('summary', {
                    style: { cursor: 'pointer', fontWeight: '700', color: 'var(--text-secondary)' },
                    textContent: '📝 النص الخام المفرّغ من الوثيقة (للمطابقة)'
                }),
                createEl('div', {
                    style: {
                        whiteSpace: 'pre-wrap',
                        marginTop: '0.35rem',
                        padding: '0.5rem 0.65rem',
                        borderRadius: '8px',
                        background: 'rgba(255, 255, 255, 0.72)',
                        border: '1px solid var(--border-color)',
                        lineHeight: '1.6',
                        color: 'var(--text-primary)'
                    },
                    textContent: rawTranscript
                })
            ]);
            box.appendChild(detailsEl);
        }

        const recAction = String(analysis.ai_recommended_action || '').trim();
        if (recAction) {
            const officerSelect = $('pcIntakeOfficerAction');
            const matchesSelectOption = officerSelect
                && Array.from(officerSelect.options || []).some((opt) => opt.value === recAction);

            if (matchesSelectOption) {
                box.appendChild(createEl('div', { style: { marginTop: '0.25rem' } }, [
                    createEl('button', {
                        type: 'button',
                        className: 'btn btn-outline btn-sm',
                        textContent: `✨ اعتماد الإجراء المقترح (${recAction})`,
                        onClick: () => {
                            if (officerSelect) officerSelect.value = recAction;
                            pcToast(`تم تحديد الإجراء الأولي: ${recAction}`);
                        }
                    })
                ]));
            }
        }
    }

    function applyExtractedComplaintToForm(scanResponse) {
        const extracted = (scanResponse && scanResponse.extracted) || {};
        const analysis = (scanResponse && scanResponse.analysis) || {};

        if (extracted.paper_date) {
            const normDate = normalizeDateForInput(extracted.paper_date);
            if (normDate && $('pcPaperDate')) $('pcPaperDate').value = normDate;
        }
        if (extracted.subject && $('pcSubject')) {
            $('pcSubject').value = extracted.subject;
        }
        if (extracted.summary && $('pcSummary')) {
            $('pcSummary').value = extracted.summary;
        }
        if ($('pcHasSignature') && typeof extracted.has_signature === 'boolean') {
            $('pcHasSignature').checked = extracted.has_signature;
        }
        if ($('pcNoPendingLawsuit') && typeof extracted.no_pending_lawsuit_declared === 'boolean') {
            $('pcNoPendingLawsuit').checked = extracted.no_pending_lawsuit_declared;
        }

        if (Array.isArray(extracted.complainants) && extracted.complainants.length > 0) {
            populatePartyRows('pcComplainantsList', 'شاكي', extracted.complainants);
        }
        if (Array.isArray(extracted.respondents) && extracted.respondents.length > 0) {
            populatePartyRows('pcRespondentsList', 'مشتكى_عليه', extracted.respondents);
        }

        if (scanResponse.station_match && scanResponse.station_match.matched) {
            applyStationMatchToIntakeForm(scanResponse.station_match);
        } else {
            const respAddr = getFirstRespondentAddressFromForm();
            if (respAddr) matchStationByAddress(respAddr, { notify: false });
        }

        const officerSelect = $('pcIntakeOfficerAction');
        if (officerSelect && !officerSelect.value && analysis.ai_recommended_action) {
            setSelectValueIfOptionExists(officerSelect, analysis.ai_recommended_action);
        }
    }

    async function rotatePendingScanFile(degrees = 90) {
        const file = state.pendingScanFile;
        if (!file) {
            pcToast('يرجى اختيار صورة أولاً للتدوير', true);
            return;
        }
        const isPdf = String(file.type || '').toLowerCase() === 'application/pdf'
            || String(file.name || '').toLowerCase().endsWith('.pdf');
        if (isPdf) {
            pcToast('التدوير متاح للصور فقط', true);
            return;
        }
        if (typeof createImageBitmap !== 'function') {
            pcToast('المتصفح لا يدعم تدوير الصور مباشرة', true);
            return;
        }

        try {
            const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
            const rad = ((degrees % 360) * Math.PI) / 180;
            const swapAxes = Math.abs(degrees % 180) === 90;
            const outW = swapAxes ? bitmap.height : bitmap.width;
            const outH = swapAxes ? bitmap.width : bitmap.height;
            const canvas = document.createElement('canvas');
            canvas.width = outW;
            canvas.height = outH;
            const ctx = canvas.getContext('2d');
            if (!ctx) {
                bitmap.close?.();
                pcToast('تعذر تدوير الصورة في المتصفح', true);
                return;
            }
            ctx.translate(outW / 2, outH / 2);
            ctx.rotate(rad);
            ctx.drawImage(bitmap, -bitmap.width / 2, -bitmap.height / 2);
            bitmap.close?.();

            const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.92));
            if (!blob) {
                pcToast('تعذر حفظ الصورة بعد التدوير', true);
                return;
            }
            const cleanName = (normalizeScanFilename(file).replace(/\.[^.]+$/, '') || 'rotated_scan') + '.jpg';
            const rotatedFile = new File([blob], cleanName, { type: 'image/jpeg', lastModified: Date.now() });
            state.pendingScanFile = rotatedFile;
            state.uploadedScans = [];
            state.uploadedScanIds = [];
            revokeLocalPreviewUrl();
            state.pendingLocalPreviewUrl = URL.createObjectURL(rotatedFile);
            renderIntakePreview(state.pendingLocalPreviewUrl, 'image/jpeg', rotatedFile.name);
            setExtractionStatus('جاهز لإعادة التحليل بعد التدوير', 'badge-blue');
            pcToast('تم تدوير الصورة 90° — اضغط «قراءة وتحليل» لإعادة الاستخراج');
        } catch (_err) {
            pcToast('تعذر تدوير الصورة المختارة', true);
        }
    }

    async function handleSelectedScanFile(file, options = {}) {
        const err = validateScanFile(file);
        if (err) {
            pcToast(err, true);
            return;
        }

        state.pendingScanFile = file;
        revokeLocalPreviewUrl();

        const isPdf = String(file.type || '').toLowerCase() === 'application/pdf'
            || String(file.name || '').toLowerCase().endsWith('.pdf');
        const rotateBtn = $('pcRotateScanBtn');
        if (rotateBtn) rotateBtn.style.display = isPdf ? 'none' : 'inline-flex';

        state.pendingLocalPreviewUrl = URL.createObjectURL(file);

        renderIntakePreview(state.pendingLocalPreviewUrl, isPdf ? 'application/pdf' : file.type, file.name);
        setExtractionStatus('جاري تجهيز الوثيقة...', 'badge-blue');

        if (options.autoExtract !== false) {
            await runScanExtraction();
        }
    }

    async function runScanExtraction() {
        if (state.isScanning) return;
        const file = state.pendingScanFile;
        if (!file) {
            pcToast('يرجى اختيار ملف أو سحب صورة الشكوى أولاً', true);
            return;
        }

        const err = validateScanFile(file);
        if (err) {
            pcToast(err, true);
            return;
        }

        state.isScanning = true;
        const analyzeBtn = $('pcScanAnalyzeBtn');
        if (analyzeBtn) analyzeBtn.disabled = true;

        const isPdf = String(file.type || '').toLowerCase() === 'application/pdf'
            || String(file.name || '').toLowerCase().endsWith('.pdf');

        // Show loading spinner cleanly inside AI analysis card & status badge
        setExtractionStatus('جاري قراءة الخط اليدوي وتحليل الشكوى بالذكاء الاصطناعي...', 'badge-purple');
        const aiBox = $('pcAiAnalysisBox');
        if (aiBox) {
            aiBox.style.display = 'flex';
            aiBox.replaceChildren(createEl('div', {
                style: { display: 'flex', alignItems: 'center', gap: '0.6rem', fontWeight: '700', color: 'var(--accent-primary)' }
            }, [
                createEl('span', { className: 'spinner spinner-dark' }),
                createEl('span', { textContent: 'جاري قراءة الخط اليدوي وتحليل الشكوى بالذكاء الاصطناعي...' })
            ]));
        }

        try {
            const dataUrl = await prepareScanUploadDataUrl(file);
            const editingId = String($('pcEditingComplaintId')?.value || '').trim();
            const fileSig = `${file.name}:${file.size}:${file.lastModified || 0}`;
            const existingSigIdx = state.uploadedScans.findIndex((s) => s.fileSig === fileSig);
            const pageOrder = existingSigIdx !== -1
                ? (state.uploadedScans[existingSigIdx].page_order || existingSigIdx + 1)
                : (state.uploadedScans.length + 1);

            const payload = {
                filename: normalizeScanFilename(file),
                file_base64: dataUrl,
                page_order: pageOrder
            };
            if (editingId) payload.complaint_id = Number(editingId);

            const res = await fetch('/api/v1/mat/police-complaints/scan-extract', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await readJsonSafe(res);

            if (!res.ok) {
                setExtractionStatus('تعذر رفع أو تحليل الوثيقة', 'badge-red');
                if (aiBox) aiBox.style.display = 'none';
                pcToast(data.error || 'فشل تحليل الوثيقة الممسوحة', true);
                return;
            }

            if (data.scan_id) {
                const scanObj = data.scan || {
                    id: data.scan_id,
                    original_filename: payload.filename,
                    mime_type: isPdf ? 'application/pdf' : (file.type || 'image/jpeg'),
                    url: `/api/v1/mat/police-complaints/scans/${data.scan_id}`
                };
                scanObj.fileSig = fileSig;
                scanObj.page_order = pageOrder;

                const existingIdx = state.uploadedScans.findIndex((s) => s.fileSig === fileSig || s.id === scanObj.id);
                if (existingIdx !== -1) {
                    state.uploadedScans[existingIdx] = scanObj;
                    state.intakeActiveScanIndex = existingIdx;
                } else {
                    state.uploadedScans.push(scanObj);
                    state.intakeActiveScanIndex = state.uploadedScans.length - 1;
                }
                state.uploadedScanIds = state.uploadedScans.map((s) => s.id);
                renderIntakePreview();
                revokeLocalPreviewUrl();
            }

            state.lastAiResult = data;
            renderAiAnalysisBox(data, isPdf);

            if (data.status === 'ok') {
                applyExtractedComplaintToForm(data);
                setExtractionStatus('✅ تم استخراج البيانات وتحليل الشكوى', 'badge-green');
                pcToast('تم قراءة الشكوى وتفريغ البيانات بالذكاء الاصطناعي بنجاح');
            } else {
                if (data.station_match && data.station_match.matched) {
                    applyStationMatchToIntakeForm(data.station_match);
                }
                setExtractionStatus('✍️ تم حفظ الوثيقة — استكمال يدوي', 'badge-yellow');
                pcToast('تم حفظ الوثيقة الممسوحة — يرجى استكمال البيانات يدوياً');
            }
        } catch (errObj) {
            setExtractionStatus('خطأ أثناء معالجة الوثيقة', 'badge-red');
            if (aiBox) aiBox.style.display = 'none';
            pcToast((errObj && errObj.message) || 'حدث خطأ أثناء معالجة الملف', true);
        } finally {
            state.isScanning = false;
            if (analyzeBtn) analyzeBtn.disabled = false;
        }
    }

    function resetIntakeForm() {
        const form = $('formPoliceComplaintIntake');
        if (form) form.reset();
        if ($('pcEditingComplaintId')) $('pcEditingComplaintId').value = '';
        if ($('pcComplaintNumber')) $('pcComplaintNumber').readOnly = false;
        if ($('pcIntakeOfficerBox')) $('pcIntakeOfficerBox').style.display = '';
        if ($('pcSaveDraftBtn')) $('pcSaveDraftBtn').style.display = '';
        if ($('pcSubmitSectionHeadBtn')) $('pcSubmitSectionHeadBtn').textContent = '📤 حفظ وإرسال لرئيس القسم';
        if ($('pcStationLat')) $('pcStationLat').value = '';
        if ($('pcStationLon')) $('pcStationLon').value = '';
        if ($('pcScanFileInput')) $('pcScanFileInput').value = '';
        if ($('pcCameraFileInput')) $('pcCameraFileInput').value = '';

        state.pendingScanFile = null;
        state.pendingAssignedOfficerId = null;
        if ($('pcRotateScanBtn')) $('pcRotateScanBtn').style.display = 'none';
        revokeLocalPreviewUrl();
        state.uploadedScans = [];
        state.uploadedScanIds = [];
        state.intakeActiveScanIndex = 0;
        state.lastAiResult = null;

        populatePartyRows('pcComplainantsList', 'شاكي', [{}]);
        populatePartyRows('pcRespondentsList', 'مشتكى_عليه', [{}]);
        renderIntakePreview();

        const aiBox = $('pcAiAnalysisBox');
        if (aiBox) {
            aiBox.style.display = 'none';
            aiBox.replaceChildren();
        }
        setExtractionStatus('جاهز لاستقبال الوثيقة', 'badge-blue');
    }

    function toggleScannerIntakePanel(forceOpen) {
        const card = $('scannerIntakeCard');
        if (!card) return;

        const isVisible = card.style.display !== 'none' && card.style.display !== '';
        const shouldOpen = typeof forceOpen === 'boolean' ? forceOpen : !isVisible;

        if (shouldOpen) {
            card.style.display = 'block';
            ensureStationsDatalistLoaded();
            ensureOfficersLoaded();

            const compList = $('pcComplainantsList');
            const respList = $('pcRespondentsList');
            if (compList && compList.querySelectorAll('.pc-party-row').length === 0) {
                addComplaintPartyRow('شاكي');
            }
            if (respList && respList.querySelectorAll('.pc-party-row').length === 0) {
                addComplaintPartyRow('مشتكى_عليه');
            }
            card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        } else {
            card.style.display = 'none';
        }
    }

    async function loadComplaintIntoIntakeForm(detail) {
        if (!detail) return;
        resetIntakeForm();
        toggleScannerIntakePanel(true);

        const targetIdStr = String(detail.id);
        const desiredOfficerVal = detail.assigned_officer_id ? String(detail.assigned_officer_id) : '';
        state.pendingAssignedOfficerId = desiredOfficerVal;

        if ($('pcEditingComplaintId')) $('pcEditingComplaintId').value = targetIdStr;
        if ($('pcPaperDate')) $('pcPaperDate').value = normalizeDateForInput(detail.paper_date || '');
        if ($('pcComplaintNumber')) {
            $('pcComplaintNumber').value = detail.complaint_number || '';
            $('pcComplaintNumber').readOnly = true;
        }
        if ($('pcIntakeOfficerBox')) $('pcIntakeOfficerBox').style.display = 'none';
        if ($('pcSaveDraftBtn')) $('pcSaveDraftBtn').style.display = 'none';
        if ($('pcSubmitSectionHeadBtn')) $('pcSubmitSectionHeadBtn').textContent = '💾 حفظ التعديلات';

        if ($('pcSubject')) $('pcSubject').value = detail.subject || '';
        if ($('pcSummary')) $('pcSummary').value = detail.summary || '';
        if ($('pcHasSignature')) $('pcHasSignature').checked = Boolean(detail.has_signature);
        if ($('pcNoPendingLawsuit')) $('pcNoPendingLawsuit').checked = Boolean(detail.no_pending_lawsuit_declared);

        const complainants = (detail.parties || []).filter((p) => p.party_type === 'شاكي');
        const respondents = (detail.parties || []).filter((p) => p.party_type === 'مشتكى_عليه');
        populatePartyRows('pcComplainantsList', 'شاكي', complainants);
        populatePartyRows('pcRespondentsList', 'مشتكى_عليه', respondents);

        if ($('pcNearestStation')) $('pcNearestStation').value = detail.nearest_station || '';
        if ($('pcPoliceDirectorate')) $('pcPoliceDirectorate').value = detail.police_directorate || '';
        if ($('pcLiwaName')) $('pcLiwaName').value = detail.liwa_name || '';
        if ($('pcStationLat')) $('pcStationLat').value = detail.station_lat != null ? String(detail.station_lat) : '';
        if ($('pcStationLon')) $('pcStationLon').value = detail.station_lon != null ? String(detail.station_lon) : '';

        if (Array.isArray(detail.scans) && detail.scans.length > 0) {
            state.uploadedScans = detail.scans.map((s) => ({
                id: s.id,
                original_filename: s.original_filename,
                mime_type: s.mime_type,
                page_order: s.page_order,
                url: `/api/v1/mat/police-complaints/scans/${s.id}`
            }));
            state.uploadedScanIds = state.uploadedScans.map((s) => s.id);
            state.intakeActiveScanIndex = 0;
            renderIntakePreview();
        }

        setExtractionStatus(`تحرير الشكوى ${detail.complaint_number || `#${detail.id}`}`, 'badge-purple');

        await ensureOfficersLoaded();
        if (String($('pcEditingComplaintId')?.value || '') === targetIdStr) {
            setSelectValueIfOptionExists($('pcAssignedOfficerId'), desiredOfficerVal);
        }
    }

    async function submitComplaintIntake(requestedStage) {
        if (state.isSavingIntake) return;

        const subject = String($('pcSubject')?.value || '').trim();
        if (!subject) {
            pcToast('موضوع الشكوى مطلوب', true);
            $('pcSubject')?.focus();
            return;
        }

        const editingId = String($('pcEditingComplaintId')?.value || '').trim();
        const isEditing = Boolean(editingId);

        if (state.officersPromise) {
            await state.officersPromise;
        }

        const complainants = collectPartiesFromContainer('pcComplainantsList', 'شاكي');
        const respondents = collectPartiesFromContainer('pcRespondentsList', 'مشتكى_عليه');

        const officerAction = String($('pcIntakeOfficerAction')?.value || '').trim();
        const officerNotes = String($('pcIntakeOfficerNotes')?.value || '').trim();
        const assignedVal = String($('pcAssignedOfficerId')?.value || '').trim();

        let submitStage = requestedStage || 'draft_scan';
        if (submitStage === 'draft_scan' && officerAction && officerNotes) {
            submitStage = 'officer_reviewed';
        }

        const payload = {
            paper_date: String($('pcPaperDate')?.value || '').trim(),
            subject,
            summary: String($('pcSummary')?.value || '').trim(),
            complainants,
            respondents,
            has_signature: Boolean($('pcHasSignature')?.checked),
            no_pending_lawsuit_declared: Boolean($('pcNoPendingLawsuit')?.checked),
            nearest_station: String($('pcNearestStation')?.value || '').trim(),
            police_directorate: String($('pcPoliceDirectorate')?.value || '').trim(),
            liwa_name: String($('pcLiwaName')?.value || '').trim(),
            assigned_officer_id: assignedVal ? Number(assignedVal) : null,
            scan_ids: state.uploadedScanIds.slice()
        };

        if (!isEditing) {
            payload.complaint_number = String($('pcComplaintNumber')?.value || '').trim();
            payload.officer_action = officerAction;
            payload.officer_notes = officerNotes;
            payload.submit_stage = submitStage;
        }

        const latRaw = String($('pcStationLat')?.value || '').trim();
        const lonRaw = String($('pcStationLon')?.value || '').trim();
        if (latRaw !== '' && !Number.isNaN(Number(latRaw))) payload.station_lat = Number(latRaw);
        if (lonRaw !== '' && !Number.isNaN(Number(lonRaw))) payload.station_lon = Number(lonRaw);

        if (state.lastAiResult) {
            const ana = state.lastAiResult.analysis || {};
            if (state.lastAiResult.provider) payload.ai_provider = state.lastAiResult.provider;
            if (state.lastAiResult.model) payload.ai_model = state.lastAiResult.model;
            if (state.lastAiResult.extracted) payload.ai_extracted_json = state.lastAiResult.extracted;
            if (typeof ana.is_minor_police_complaint === 'boolean') {
                payload.is_minor_police_complaint = ana.is_minor_police_complaint;
            }
            if (ana.ai_analysis) payload.ai_analysis = ana.ai_analysis;
            if (ana.ai_solution_recommendation) payload.ai_solution_recommendation = ana.ai_solution_recommendation;
            if (ana.ai_recommended_action) payload.ai_recommended_action = ana.ai_recommended_action;
            if (ana.ai_confidence !== undefined && ana.ai_confidence !== null) {
                payload.ai_confidence = Number(ana.ai_confidence);
            }
        }

        const url = isEditing
            ? `/api/v1/mat/police-complaints/${encodeURIComponent(editingId)}`
            : '/api/v1/mat/police-complaints';
        const method = isEditing ? 'PUT' : 'POST';

        state.isSavingIntake = true;
        const draftBtn = $('pcSaveDraftBtn');
        const submitBtn = $('pcSubmitSectionHeadBtn');
        if (draftBtn) draftBtn.disabled = true;
        if (submitBtn) submitBtn.disabled = true;

        try {
            const res = await fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await readJsonSafe(res);
            if (!res.ok) {
                pcToast(data.error || 'تعذر حفظ الشكوى', true);
                return;
            }

            pcToast(
                isEditing
                    ? `تم تحديث بيانات الشكوى (${data.complaint_number || ''}) بنجاح`
                    : (submitStage === 'pending_section_head'
                        ? `تم حفظ الشكوى (${data.complaint_number || ''}) وإرسالها لرئيس القسم`
                        : `تم حفظ مسودة الشكوى (${data.complaint_number || ''}) بنجاح`)
            );

            resetIntakeForm();
            toggleScannerIntakePanel(false);
            await loadPoliceComplaintsTab();
        } catch (_) {
            pcToast('تعذر الاتصال بالخادم لحفظ الشكوى', true);
        } finally {
            state.isSavingIntake = false;
            if (draftBtn) draftBtn.disabled = false;
            if (submitBtn) submitBtn.disabled = false;
        }
    }

    // ── Queue Loading, KPI Pills & Table Rendering ───────────────────────────

    function updateStatsCounters(stats) {
        const s = stats || {};
        const totalEl = $('pcStatTotal');
        const officerEl = $('pcStatPendingOfficer');
        const sectionEl = $('pcStatPendingSection');
        const govEl = $('pcStatPendingGovernor');
        const approvedEl = $('pcStatApprovedExecution');
        const due90El = $('pcStatDue90Days');

        if (totalEl) totalEl.textContent = String(s.total || 0);
        if (officerEl) officerEl.textContent = String((s.draft_scan || 0) + (s.officer_reviewed || 0));
        if (sectionEl) sectionEl.textContent = String(s.pending_section_head || 0);
        if (govEl) govEl.textContent = String(s.pending_governor || 0);
        if (approvedEl) approvedEl.textContent = String(s.approved_in_execution || 0);
        if (due90El) due90El.textContent = String(s.overdue_90 || 0);
    }

    function syncActiveKpiPill() {
        const bar = $('pcStatsBar');
        if (!bar) return;
        const stageVal = String($('pcStageFilter')?.value || '');
        const overdueChecked = Boolean($('pc90DayFilter')?.checked);
        let targetStage = 'all';
        if (overdueChecked) targetStage = 'overdue_90';
        else if (stageVal) targetStage = stageVal;

        bar.querySelectorAll('.pc-kpi-pill').forEach((pill) => {
            pill.classList.toggle('active', pill.dataset.stage === targetStage);
        });
    }

    function getStageMeta(stage) {
        return STAGE_META[stage] || { label: stage || 'غير محدد', badgeClass: 'pc-stage-draft' };
    }

    function get90DayFillClass(nd, workflowStage) {
        if (workflowStage === 'stopped_90_days' || workflowStage === 'completed' || (nd && nd.warning_level === 'closed')) {
            return 'pc-90day-stopped';
        }
        if (nd && (nd.is_due_for_stop || nd.warning_level === 'expired')) return 'pc-90day-overdue';
        if (nd && nd.warning_level === 'warning') return 'pc-90day-warning';
        return 'pc-90day-normal';
    }

    function build90DayCell(c) {
        const nd = c.ninety_day_status || {};
        const elapsed = Number(nd.days_elapsed || 0);
        const pct = Math.min(100, Math.round((elapsed / 90) * 100));
        const fillClass = get90DayFillClass(nd, c.workflow_stage);

        let labelText = `${elapsed} / 90 يوم`;
        if (c.workflow_stage === 'stopped_90_days') labelText = '⛔ كف طلب';
        else if (c.workflow_stage === 'completed') labelText = `✅ منجزة (${elapsed} يوم)`;
        else if (nd.is_due_for_stop) labelText = `⚠️ مستحق لكف الطلب (${elapsed} يوم)`;

        return createEl('td', {}, [
            createEl('div', {
                style: { fontSize: '0.78rem', fontWeight: '700', whiteSpace: 'nowrap' },
                textContent: labelText
            }),
            createEl('div', { className: 'pc-90day-bar' }, [
                createEl('div', {
                    className: `pc-90day-fill ${fillClass}`,
                    style: { width: `${pct}%` }
                })
            ])
        ]);
    }

    function summarizeParties(parties, type) {
        const matches = (parties || []).filter((p) => p.party_type === type);
        if (matches.length === 0) return '—';
        const first = matches[0];
        const suffix = matches.length > 1 ? ` (+${matches.length - 1})` : '';
        return `${first.name || '—'}${suffix}`;
    }

    function renderComplaintsList(complaints, user) {
        const container = $('policeComplaintsListContainer');
        if (!container) return;

        if (!Array.isArray(complaints) || complaints.length === 0) {
            const role = getUserRole(user);
            const canIntake = role === 'officer' || role === 'admin';
            const emptyBox = createEl('div', { className: 'empty-state' }, [
                createEl('div', { className: 'empty-icon', textContent: '⚖️' }),
                createEl('p', { textContent: 'لا توجد شكاوى أمنية مطابقة لمعايير البحث الحالية.' }),
                canIntake
                    ? createEl('button', {
                        type: 'button',
                        className: 'btn btn-primary',
                        textContent: '📷 مسح / إدخال شكوى جديدة',
                        onClick: () => toggleScannerIntakePanel(true)
                    })
                    : null
            ]);
            container.replaceChildren(emptyBox);
            return;
        }

        const headers = [
            'رقم الشكوى والتاريخ',
            'الموضوع والنوع',
            'الأطراف (المشتكي / المشتكى عليه)',
            'المركز الأمني المختص',
            'المرحلة والقرار',
            'عداد الـ 90 يوماً',
            'الإجراء'
        ];

        const thead = createEl('thead', {}, [
            createEl('tr', {}, headers.map((h) => createEl('th', { textContent: h })))
        ]);

        const tbody = createEl('tbody');
        complaints.forEach((c) => {
            const nd = c.ninety_day_status || {};
            let rowClass = 'pc-search-row';
            if (nd.is_due_for_stop) rowClass += ' pc-row-overdue';
            else if (nd.warning_level === 'warning') rowClass += ' pc-row-warning';

            const stageMeta = getStageMeta(c.workflow_stage);
            const decisionText = c.governor_final_action
                || c.section_recommended_action
                || c.officer_action
                || c.ai_recommended_action
                || '—';

            const tr = createEl('tr', {
                className: rowClass,
                style: { cursor: 'pointer' },
                onClick: () => openPoliceComplaintDetail(c.id)
            });

            // 1. Complaint number & date
            const tdNum = createEl('td', {}, [
                createEl('div', { className: 'fw-bold text-primary', textContent: c.complaint_number || `#${c.id}` }),
                createEl('small', {
                    className: 'text-muted',
                    textContent: c.paper_date || (c.created_at ? String(c.created_at).slice(0, 10) : '—')
                }),
                c.priority === 'عاجل'
                    ? createEl('div', { style: { marginTop: '3px' } }, [
                        createEl('span', { className: 'badge badge-red', textContent: '⚡ عاجل' })
                    ])
                    : null,
                Number(c.scan_count || 0) > 0
                    ? createEl('div', { style: { marginTop: '3px' } }, [
                        createEl('span', { className: 'badge badge-blue', textContent: `📄 ${c.scan_count} مرفق` })
                    ])
                    : null
            ]);

            // 2. Subject & summary preview
            const summaryPreview = String(c.summary || '').trim();
            const tdSubject = createEl('td', {}, [
                createEl('div', { className: 'fw-bold', textContent: c.subject || 'بدون موضوع' }),
                summaryPreview
                    ? createEl('small', {
                        className: 'text-muted',
                        textContent: summaryPreview.length > 75 ? `${summaryPreview.slice(0, 75)}...` : summaryPreview
                    })
                    : null
            ]);

            // 3. Parties
            const tdParties = createEl('td', {}, [
                createEl('div', { style: { fontSize: '0.84rem' } }, [
                    createEl('strong', { textContent: 'المشتكي: ' }),
                    document.createTextNode(summarizeParties(c.parties, 'شاكي'))
                ]),
                createEl('div', { style: { fontSize: '0.84rem', marginTop: '2px' } }, [
                    createEl('strong', { textContent: 'المشتكى عليه: ' }),
                    document.createTextNode(summarizeParties(c.parties, 'مشتكى_عليه'))
                ])
            ]);

            // 4. Nearest station
            const tdStation = createEl('td', {}, [
                createEl('div', { className: 'fw-bold', textContent: c.nearest_station || 'غير محدد' }),
                c.police_directorate
                    ? createEl('small', { className: 'text-muted', textContent: c.police_directorate })
                    : null
            ]);

            // 5. Stage & decision
            const tdStage = createEl('td', {}, [
                createEl('span', { className: `pc-stage-badge ${stageMeta.badgeClass}`, textContent: stageMeta.label }),
                createEl('div', {
                    style: { fontSize: '0.78rem', color: 'var(--text-secondary)', marginTop: '4px' },
                    textContent: decisionText
                })
            ]);

            // 6. 90-day cell
            const td90 = build90DayCell(c);

            // 7. Action button
            const tdAction = createEl('td', {}, [
                createEl('button', {
                    type: 'button',
                    className: 'btn btn-outline btn-sm',
                    textContent: 'عرض ومعالجة',
                    onClick: (ev) => {
                        ev.stopPropagation();
                        openPoliceComplaintDetail(c.id);
                    }
                })
            ]);

            appendChildren(tr, [tdNum, tdSubject, tdParties, tdStation, tdStage, td90, tdAction]);
            tbody.appendChild(tr);
        });

        const wrapper = createEl('div', { className: 'table-wrapper' }, [
            createEl('table', {}, [thead, tbody])
        ]);
        container.replaceChildren(wrapper);
    }

    async function loadPoliceComplaintsTab() {
        initPoliceComplaintsBindings();
        const reqSeq = ++state.listRequestSeq;
        if (state.listAbortController) {
            try { state.listAbortController.abort(); } catch (_) {}
        }
        const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
        state.listAbortController = controller;

        const user = await ensureCurrentUser();
        if (reqSeq !== state.listRequestSeq) return;
        const role = getUserRole(user);

        // Ensure role-restricted header controls reflect authenticated role
        const llmBtn = $('pcLlmSettingsBtn');
        if (llmBtn) llmBtn.style.display = role === 'admin' ? 'inline-flex' : 'none';
        const scannerBtn = $('pcToggleScannerBtn');
        if (scannerBtn) scannerBtn.style.display = (role === 'admin' || role === 'officer') ? 'inline-flex' : 'none';

        ensureStationsDatalistLoaded();
        if (role === 'admin' || role === 'officer') ensureOfficersLoaded();

        const container = $('policeComplaintsListContainer');
        if (container) {
            container.replaceChildren(createEl('div', { className: 'text-center p-3' }, [
                createEl('div', { className: 'spinner spinner-dark' }),
                document.createTextNode(' جاري تحميل سجل الشكاوى الأمنية...')
            ]));
        }

        const params = new URLSearchParams();
        const q = String($('pcSearchInput')?.value || '').trim();
        const stage = String($('pcStageFilter')?.value || '').trim();
        const overdue90 = Boolean($('pc90DayFilter')?.checked);

        if (q) params.set('q', q);
        if (stage) params.set('workflow_stage', stage);
        if (overdue90) params.set('overdue_90', '1');
        params.set('limit', '100');

        try {
            const fetchOpts = controller ? { signal: controller.signal } : {};
            const res = await fetch(`/api/v1/mat/police-complaints?${params.toString()}`, fetchOpts);
            if (reqSeq !== state.listRequestSeq) return;
            const data = await readJsonSafe(res);
            if (reqSeq !== state.listRequestSeq) return;
            if (!res.ok) {
                if (container) {
                    container.replaceChildren(createEl('div', {
                        className: 'text-center text-error p-3',
                        textContent: data.error || 'تعذر تحميل قائمة الشكاوى'
                    }));
                }
                return;
            }

            state.complaints = data.complaints || [];
            state.stats = data.stats || {};
            updateStatsCounters(state.stats);
            syncActiveKpiPill();
            renderComplaintsList(state.complaints, user);
        } catch (err) {
            if ((err && err.name === 'AbortError') || reqSeq !== state.listRequestSeq) {
                return;
            }
            if (container) {
                container.replaceChildren(createEl('div', {
                    className: 'text-center text-error p-3',
                    textContent: 'خطأ في الاتصال بالخادم أثناء جلب الشكاوى'
                }));
            }
        } finally {
            if (state.listAbortController === controller) {
                state.listAbortController = null;
            }
        }
    }

    // ── Complaint Detail Modal & Role Workflow Panels ────────────────────────

    function hideStop90ConfirmBar() {
        const bar = $('pcStop90ConfirmBar');
        if (bar) bar.remove();
    }

    function renderDetailScanPane(scans, user) {
        const preview = $('pcDetailScanPreview');
        const zoomBtn = $('pcDetailZoomBtn');
        const role = getUserRole(user || pcGetSavedUserSync());
        const canViewScans = role === 'officer' || role === 'admin' || role === 'governor';

        if (!canViewScans) {
            if (zoomBtn) zoomBtn.style.display = 'none';
            if (preview) {
                preview.replaceChildren(createEl('div', {
                    className: 'pc-preview-empty',
                    textContent: '🔒 معاينة الوثائق الممسوحة غير متاحة لهذا الدور'
                }));
            }
            return;
        }

        if (!preview) return;
        preview.replaceChildren();

        if (!Array.isArray(scans) || scans.length === 0) {
            if (zoomBtn) zoomBtn.style.display = 'none';
            preview.appendChild(createEl('div', { className: 'pc-preview-empty', textContent: 'لا توجد وثيقة مرفقة' }));
            return;
        }

        if (zoomBtn) zoomBtn.style.display = 'inline-flex';
        const idx = Math.max(0, Math.min(state.detailActiveScanIndex, scans.length - 1));
        state.detailActiveScanIndex = idx;
        const activeScan = scans[idx];
        const scanUrl = `/api/v1/mat/police-complaints/scans/${encodeURIComponent(activeScan.id)}`;

        if (scans.length > 1) {
            const pager = createEl('div', {
                style: { display: 'flex', gap: '0.4rem', flexWrap: 'wrap', justifyContent: 'center', width: '100%' }
            });
            scans.forEach((sc, i) => {
                pager.appendChild(createEl('button', {
                    type: 'button',
                    className: `btn btn-sm ${i === idx ? 'btn-primary' : 'btn-outline'}`,
                    textContent: `صفحة ${i + 1}`,
                    onClick: () => {
                        state.detailActiveScanIndex = i;
                        renderDetailScanPane(scans, user);
                    }
                }));
            });
            preview.appendChild(pager);
        }

        preview.appendChild(renderScanMediaNode(scanUrl, activeScan.mime_type, activeScan.original_filename));
        preview.appendChild(createEl('div', {
            style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%', gap: '0.5rem', flexWrap: 'wrap', fontSize: '0.78rem' }
        }, [
            createEl('span', { className: 'text-muted', textContent: activeScan.original_filename || `وثيقة #${activeScan.id}` }),
            createEl('a', {
                href: `${scanUrl}?download=1`,
                className: 'btn btn-ghost btn-sm',
                download: activeScan.original_filename || `scan_${activeScan.id}`,
                textContent: '⬇️ تنزيل الملف'
            })
        ]));
    }

    function openScanLightbox() {
        const role = getUserRole(pcGetSavedUserSync());
        const canViewScans = role === 'officer' || role === 'admin' || role === 'governor';
        if (!canViewScans) {
            pcToast('غير مصرح بعرض الوثائق الممسوحة لهذا الدور', true);
            return;
        }
        const detail = state.currentDetail;
        const scans = (detail && detail.scans) || [];
        if (scans.length === 0) {
            pcToast('لا توجد وثيقة مرفقة للتكبير', true);
            return;
        }
        const idx = Math.max(0, Math.min(state.detailActiveScanIndex, scans.length - 1));
        const activeScan = scans[idx];
        const scanUrl = `/api/v1/mat/police-complaints/scans/${encodeURIComponent(activeScan.id)}`;
        const lightboxContent = $('pcLightboxContent');
        if (lightboxContent) {
            lightboxContent.replaceChildren(renderScanMediaNode(scanUrl, activeScan.mime_type, activeScan.original_filename));
        }
        pcOpenModal('modalScanLightbox');
    }

    function buildDetailPartyTable(title, parties) {
        const card = createEl('div', { className: 'pc-summary-card' });
        card.appendChild(createEl('h4', { style: { marginBottom: '0.6rem', color: 'var(--accent-primary)' }, textContent: title }));

        if (!parties || parties.length === 0) {
            card.appendChild(createEl('div', { className: 'text-muted', style: { fontSize: '0.85rem' }, textContent: 'لا توجد بيانات مسجلة' }));
            return card;
        }

        const headers = ['الصفة', 'الاسم', 'الرقم الوطني / التجاري', 'الهاتف', 'العنوان'];
        const thead = createEl('thead', {}, [
            createEl('tr', {}, headers.map((h) => createEl('th', { textContent: h })))
        ]);
        const tbody = createEl('tbody', {}, parties.map((p) => createEl('tr', {}, [
            createEl('td', { textContent: p.party_category || 'مواطن' }),
            createEl('td', { className: 'fw-bold', textContent: p.name || '—' }),
            createEl('td', { textContent: p.national_id || '—' }),
            createEl('td', { textContent: p.phone || '—' }),
            createEl('td', { textContent: p.address || '—' })
        ])));

        card.appendChild(createEl('div', { className: 'table-wrapper' }, [
            createEl('table', {}, [thead, tbody])
        ]));
        return card;
    }

    function renderDetailSummaryBlock(detail, user) {
        const block = $('pcDetailSummaryBlock');
        if (!block) return;

        const role = getUserRole(user);
        const stage = detail.workflow_stage || 'draft_scan';
        const canEditIntake = (role === 'officer' || role === 'admin') && PRE_APPROVAL_STAGES.has(stage);
        const frag = document.createDocumentFragment();

        // Card 1: Metadata & Jurisdiction
        const metaCard = createEl('div', { className: 'pc-summary-card' });
        const headerRow = createEl('div', {
            style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '0.75rem' }
        }, [
            createEl('h4', { style: { margin: 0, color: 'var(--accent-primary)' }, textContent: '📋 البيانات الأساسية والاختصاص المكاني' }),
            createEl('div', { className: 'pc-no-print', style: { display: 'flex', gap: '0.45rem', flexWrap: 'wrap' } }, [
                createEl('button', {
                    type: 'button',
                    className: 'btn btn-outline btn-sm',
                    textContent: '🗺️ معاينة في دليل المراكز',
                    onClick: () => openStationInFinder(detail)
                }),
                canEditIntake
                    ? createEl('button', {
                        type: 'button',
                        className: 'btn btn-ghost btn-sm',
                        textContent: '✏️ تعديل البيانات',
                        onClick: () => {
                            pcCloseModal('modalPoliceComplaintDetail');
                            loadComplaintIntoIntakeForm(detail);
                        }
                    })
                    : null
            ])
        ]);

        const chips = [
            { label: 'رقم الشكوى', val: detail.complaint_number || `#${detail.id}` },
            { label: 'تاريخ الشكوى الورقي', val: detail.paper_date || '—' },
            { label: 'الأولوية', val: detail.priority || 'عادي' },
            { label: 'توقيع المشتكي', val: detail.has_signature ? '✅ موقع' : '❌ غير موقع' },
            { label: 'عدم وجود قضية منظورة', val: detail.no_pending_lawsuit_declared ? '✅ مصرح به' : '—' },
            { label: 'أقرب مركز أمني', val: detail.nearest_station || 'غير محدد' },
            { label: 'مديرية الشرطة', val: detail.police_directorate || '—' },
            { label: 'اللواء / المنطقة', val: detail.liwa_name || '—' },
            { label: 'الضابط المتابع', val: detail.assigned_officer_name || detail.created_by_name || '—' }
        ];
        const infoGrid = createEl('div', { className: 'pc-info-grid' }, chips.map((ch) => createEl('div', { className: 'pc-info-chip' }, [
            createEl('div', { style: { fontSize: '0.74rem', color: 'var(--text-secondary)' }, textContent: ch.label }),
            createEl('div', { style: { fontWeight: '700', marginTop: '2px' }, textContent: ch.val })
        ])));

        metaCard.appendChild(headerRow);
        metaCard.appendChild(infoGrid);
        frag.appendChild(metaCard);

        // Card 2: Subject, Summary & AI Analysis
        const contentCard = createEl('div', { className: 'pc-summary-card' }, [
            createEl('h4', { style: { marginBottom: '0.4rem', color: 'var(--accent-primary)' }, textContent: `موضوع الشكوى: ${detail.subject || '—'}` }),
            createEl('p', {
                style: { margin: '0 0 0.75rem', whiteSpace: 'pre-wrap', lineHeight: '1.65', fontSize: '0.92rem' },
                textContent: detail.summary || 'لا يوجد ملخص تفصيلي مسجل.'
            })
        ]);

        if (detail.ai_analysis || detail.ai_solution_recommendation || detail.ai_recommended_action) {
            const isMinor = detail.is_minor_police_complaint !== 0 && detail.is_minor_police_complaint !== false;
            const aiPanel = createEl('div', { className: 'pc-ai-box', style: { marginTop: '0.5rem' } }, [
                createEl('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.4rem' } }, [
                    createEl('span', {
                        className: `badge ${isMinor ? 'badge-green' : 'badge-red'}`,
                        textContent: isMinor ? '🤖 تصنيف الذكاء الاصطناعي: مشكلة خفيفة تتطلب شرطة' : '⚖️ تصنيف الذكاء الاصطناعي: غير مشمولة / قضائية'
                    }),
                    detail.ai_provider
                        ? createEl('small', { className: 'text-muted', textContent: `${detail.ai_provider}${detail.ai_model ? ` / ${detail.ai_model}` : ''}` })
                        : null
                ]),
                detail.ai_analysis
                    ? createEl('div', { style: { fontSize: '0.84rem' } }, [
                        createEl('strong', { textContent: 'التحليل: ' }),
                        document.createTextNode(detail.ai_analysis)
                    ])
                    : null,
                detail.ai_solution_recommendation
                    ? createEl('div', { style: { fontSize: '0.84rem' } }, [
                        createEl('strong', { textContent: 'التوصية بالحل: ' }),
                        document.createTextNode(detail.ai_solution_recommendation)
                    ])
                    : null,
                detail.ai_recommended_action
                    ? createEl('div', { style: { fontSize: '0.84rem' } }, [
                        createEl('strong', { textContent: 'الإجراء المقترح آلياً: ' }),
                        document.createTextNode(detail.ai_recommended_action)
                    ])
                    : null
            ]);
            contentCard.appendChild(aiPanel);
        }
        frag.appendChild(contentCard);

        // Card 3 & 4: Complainants & Respondents
        const complainants = (detail.parties || []).filter((p) => p.party_type === 'شاكي');
        const respondents = (detail.parties || []).filter((p) => p.party_type === 'مشتكى_عليه');
        frag.appendChild(buildDetailPartyTable('👥 المشتكون', complainants));
        frag.appendChild(buildDetailPartyTable('⚖️ المشتكى عليهم', respondents));

        // Card 5: Decisions & Linked MAT Tools Summary
        const decisionsCard = createEl('div', { className: 'pc-summary-card' });
        decisionsCard.appendChild(createEl('h4', { style: { marginBottom: '0.6rem', color: 'var(--accent-primary)' }, textContent: '📌 مسار القرارات والربط التلقائي مع الأدوات' }));

        const decisionRows = [
            { title: 'نظر الضابط', val: detail.officer_action, notes: detail.officer_notes, actor: detail.officer_reviewed_by_name },
            { title: 'تنسيب رئيس القسم', val: detail.section_recommended_action, notes: detail.section_head_notes, actor: detail.section_head_name },
            { title: 'قرار الحاكم الإداري', val: detail.governor_decision ? `${detail.governor_decision} — ${detail.governor_final_action || ''}` : '', notes: detail.governor_notes, actor: detail.governor_name }
        ];

        decisionRows.forEach((row) => {
            if (!row.val && !row.notes) return;
            decisionsCard.appendChild(createEl('div', {
                style: { padding: '0.55rem 0.75rem', borderRight: '3px solid var(--accent-primary)', background: '#F8FAFC', borderRadius: '6px', marginBottom: '0.5rem' }
            }, [
                createEl('div', { style: { fontWeight: '800', fontSize: '0.86rem' }, textContent: `${row.title}: ${row.val || '—'}` }),
                row.notes ? createEl('div', { style: { fontSize: '0.84rem', marginTop: '2px' }, textContent: row.notes }) : null,
                row.actor ? createEl('small', { className: 'text-muted', textContent: `بواسطة: ${row.actor}` }) : null
            ]));
        });

        const linkedBadges = createEl('div', { className: 'pc-linked-badges', style: { marginTop: '0.5rem' } });
        if (detail.linked_appointment) {
            const appt = detail.linked_appointment;
            linkedBadges.appendChild(createEl('button', {
                type: 'button',
                className: 'btn btn-outline btn-sm pc-no-print',
                textContent: `📅 موعد اتصال مجدول #${appt.id} (${appt.appointment_date} ${appt.appointment_time}) — ${appt.status}`,
                onClick: () => {
                    if (typeof global.openAppointmentDetail === 'function') {
                        pcCloseModal('modalPoliceComplaintDetail');
                        global.openAppointmentDetail(Number(appt.id));
                    }
                }
            }));
        }
        if (detail.linked_file) {
            linkedBadges.appendChild(createEl('span', {
                className: 'badge badge-purple',
                textContent: `📂 ملف محجوز تلقائياً: ${detail.linked_file.file_number} (${detail.linked_file.officer_name || '—'})`
            }));
        } else if (detail.linked_file_number) {
            linkedBadges.appendChild(createEl('span', {
                className: 'badge badge-purple',
                textContent: `📂 رقم الملف المحجوز: ${detail.linked_file_number}`
            }));
        }
        if (linkedBadges.childNodes.length > 0) {
            decisionsCard.appendChild(linkedBadges);
        }

        const nd = detail.ninety_day_status || {};
        decisionsCard.appendChild(createEl('div', {
            style: { marginTop: '0.6rem', fontSize: '0.82rem', color: 'var(--text-secondary)' },
            textContent: `⏳ مؤشر الـ 90 يوماً: مضى ${nd.days_elapsed ?? 0} يوماً — متبقي ${nd.days_remaining ?? 90} يوماً (آخر متابعة: ${detail.last_followup_at || '—'})`
        }));

        frag.appendChild(decisionsCard);
        block.replaceChildren(frag);
    }

    function renderWorkflowTimeline(workflowLog) {
        const container = $('pcWorkflowLogContainer');
        if (!container) return;
        if (!Array.isArray(workflowLog) || workflowLog.length === 0) {
            container.replaceChildren(createEl('div', { className: 'text-muted', style: { fontSize: '0.85rem' }, textContent: 'لا يوجد سجل إجراءات مسجل بعد' }));
            return;
        }

        const frag = document.createDocumentFragment();
        workflowLog.forEach((entry) => {
            const roleText = ROLE_LABELS[entry.actor_role] || entry.actor_role || '';
            const actorText = entry.actor_name ? `${entry.actor_name} (${roleText})` : roleText;
            const fromLabel = entry.stage_from ? getStageMeta(entry.stage_from).label : 'بدء';
            const toLabel = entry.stage_to ? getStageMeta(entry.stage_to).label : '—';

            frag.appendChild(createEl('div', { className: 'pc-timeline-item' }, [
                createEl('span', { className: 'pc-timeline-dot' }),
                createEl('div', { className: 'pc-timeline-meta' }, [
                    createEl('strong', { textContent: entry.action_taken || 'إجراء' }),
                    createEl('span', { textContent: entry.created_at || '' })
                ]),
                createEl('div', {
                    style: { fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: '0.25rem' },
                    textContent: `بواسطة: ${actorText || '—'} | المسار: ${fromLabel} ← ${toLabel}`
                }),
                entry.notes
                    ? createEl('div', { className: 'pc-timeline-notes', textContent: entry.notes })
                    : null
            ]));
        });
        container.replaceChildren(frag);
    }

    function syncGovernorFinalActionVisibility() {
        const checked = document.querySelector('input[name="pcGovernorDecision"]:checked');
        const wrapper = $('pcGovernorFinalActionWrapper');
        if (!wrapper) return;
        wrapper.style.display = checked && checked.value === 'تغيير_الإجراء' ? 'block' : 'none';
    }

    function configureRoleActionPanels(detail, user) {
        const role = getUserRole(user);
        const stage = detail.workflow_stage || 'draft_scan';

        const officerPanel = $('pcOfficerActionPanel');
        const sectionPanel = $('pcSectionHeadPanel');
        const governorPanel = $('pcGovernorDecisionPanel');

        // 1. Officer Panel
        const showOfficer = (role === 'officer' || role === 'admin')
            && (PRE_APPROVAL_STAGES.has(stage) || POST_APPROVAL_STAGES.has(stage));
        if (officerPanel) {
            officerPanel.style.display = showOfficer ? 'block' : 'none';
            if (showOfficer) {
                const actionSelect = $('pcDetailOfficerAction');
                const notesEl = $('pcDetailOfficerNotes');
                const execWrapper = $('pcDetailExecutionStatusWrapper');
                const execSelect = $('pcDetailExecutionStatus');
                const sendWrapper = $('pcOfficerSendWrapper');
                const sendCheck = $('pcOfficerSendToSectionHead');

                setSelectValueIfOptionExists(actionSelect, detail.officer_action || detail.governor_final_action || '');
                if (notesEl) notesEl.value = detail.officer_notes || '';

                if (POST_APPROVAL_STAGES.has(stage)) {
                    if (execWrapper) execWrapper.style.display = 'block';
                    if (execSelect) execSelect.value = stage === 'completed' ? 'completed' : 'in_execution';
                    if (sendWrapper) sendWrapper.style.display = 'none';
                    if (sendCheck) sendCheck.checked = false;
                } else {
                    if (execWrapper) execWrapper.style.display = 'none';
                    if (sendWrapper) sendWrapper.style.display = 'inline-flex';
                    if (sendCheck) sendCheck.checked = false;
                }
            }
        }

        // 2. Section Head Panel (Admin only)
        const showSection = role === 'admin' && SECTION_HEAD_ALLOWED_STAGES.has(stage);
        if (sectionPanel) {
            sectionPanel.style.display = showSection ? 'block' : 'none';
            if (showSection) {
                if ($('pcSectionHeadNotes')) $('pcSectionHeadNotes').value = detail.section_head_notes || '';
                const recSelect = $('pcSectionRecommendedAction');
                const preferredAction = detail.section_recommended_action || detail.officer_action || detail.ai_recommended_action || '';
                if (!setSelectValueIfOptionExists(recSelect, preferredAction) && recSelect) {
                    recSelect.value = '';
                }
                if ($('pcSectionNearestStation')) $('pcSectionNearestStation').value = detail.nearest_station || '';
                if ($('pcSectionDirectorate')) $('pcSectionDirectorate').value = detail.police_directorate || '';
                if ($('pcSectionLiwa')) $('pcSectionLiwa').value = detail.liwa_name || '';
            }
        }

        // 3. Governor Panel (Governor only)
        const showGovernor = role === 'governor' && GOVERNOR_ALLOWED_STAGES.has(stage);
        if (governorPanel) {
            governorPanel.style.display = showGovernor ? 'block' : 'none';
            if (showGovernor) {
                const radios = Array.from(document.querySelectorAll('input[name="pcGovernorDecision"]'));
                const existingDec = detail.governor_decision;
                const targetVal = ['موافقة', 'تغيير_الإجراء', 'رفض'].includes(existingDec) ? existingDec : 'موافقة';
                radios.forEach((r) => { r.checked = r.value === targetVal; });
                syncGovernorFinalActionVisibility();

                const govFinalSel = $('pcGovernorFinalAction');
                const preferredFinal = detail.governor_final_action || detail.section_recommended_action || '';
                if (!setSelectValueIfOptionExists(govFinalSel, preferredFinal) && govFinalSel) {
                    govFinalSel.value = '';
                }
                if ($('pcGovernorNearestStation')) $('pcGovernorNearestStation').value = detail.nearest_station || '';
                if ($('pcGovernorNotes')) $('pcGovernorNotes').value = detail.governor_notes || '';
            }
        }

        // 4. Footer buttons visibility & state (fail-closed)
        const isClosed = stage === 'completed' || stage === 'stopped_90_days';
        const canManage = role === 'officer' || role === 'admin' || role === 'governor';
        const followupBtn = $('pcFollowupBtn');
        const stop90Btn = $('pcStop90Btn');
        const exportBtn = $('pcExportDocxBtn');

        if (followupBtn) {
            followupBtn.style.display = canManage ? 'inline-flex' : 'none';
            followupBtn.disabled = !canManage || isClosed || stage === 'governor_rejected';
        }
        if (stop90Btn) {
            stop90Btn.style.display = canManage ? 'inline-flex' : 'none';
            stop90Btn.disabled = !canManage || isClosed;
        }
        if (exportBtn) {
            exportBtn.style.display = canManage ? 'inline-flex' : 'none';
        }
    }

    function renderComplaintDetail(detail, user) {
        state.currentDetail = detail;
        hideStop90ConfirmBar();

        const stage = detail.workflow_stage || 'draft_scan';
        const stageMeta = getStageMeta(stage);
        const nd = detail.ninety_day_status || {};
        const elapsed = Number(nd.days_elapsed || 0);

        const titleEl = $('pcDetailHeaderTitle');
        if (titleEl) {
            titleEl.textContent = `⚖️ شكوى ${detail.complaint_number || `#${detail.id}`} — ${detail.subject || ''}`;
        }

        const stageBadge = $('pcDetailStageBadge');
        if (stageBadge) {
            stageBadge.className = `pc-stage-badge ${stageMeta.badgeClass}`;
            stageBadge.textContent = stageMeta.label;
        }

        const badge90 = $('pcDetail90DayBadge');
        if (badge90) {
            if (stage === 'stopped_90_days') {
                badge90.className = 'badge badge-red';
                badge90.textContent = '⛔ كف طلب (90 يوماً)';
            } else if (stage === 'governor_rejected') {
                badge90.className = 'badge badge-red';
                badge90.textContent = `❌ مرفوضة (${elapsed} يوم)`;
            } else if (stage === 'completed') {
                badge90.className = 'badge badge-green';
                badge90.textContent = `✅ منجزة (${elapsed} يوم)`;
            } else if (nd.is_due_for_stop) {
                badge90.className = 'badge badge-red';
                badge90.textContent = `⚠️ مستحق لكف الطلب (${elapsed} / 90 يوم)`;
            } else if (nd.warning_level === 'warning') {
                badge90.className = 'badge badge-yellow';
                badge90.textContent = `⏳ إنذار (${elapsed} / 90 يوم)`;
            } else {
                badge90.className = 'badge badge-green';
                badge90.textContent = `🕒 ${elapsed} / 90 يوم`;
            }
        }

        state.detailActiveScanIndex = 0;
        renderDetailScanPane(detail.scans || [], user);
        renderDetailSummaryBlock(detail, user);
        configureRoleActionPanels(detail, user);
        renderWorkflowTimeline(detail.workflow_log || []);
    }

    async function openPoliceComplaintDetail(id) {
        initPoliceComplaintsBindings();
        const reqSeq = ++state.detailRequestSeq;
        if (state.detailAbortController) {
            try { state.detailAbortController.abort(); } catch (_) {}
        }
        const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
        state.detailAbortController = controller;

        hideStop90ConfirmBar();

        const summaryBlock = $('pcDetailSummaryBlock');
        const scanPreview = $('pcDetailScanPreview');
        const zoomBtn = $('pcDetailZoomBtn');
        const timeline = $('pcWorkflowLogContainer');

        if ($('pcOfficerActionPanel')) $('pcOfficerActionPanel').style.display = 'none';
        if ($('pcSectionHeadPanel')) $('pcSectionHeadPanel').style.display = 'none';
        if ($('pcGovernorDecisionPanel')) $('pcGovernorDecisionPanel').style.display = 'none';
        if (zoomBtn) zoomBtn.style.display = 'none';

        if (summaryBlock) {
            summaryBlock.replaceChildren(createEl('div', { className: 'text-center p-3' }, [
                createEl('div', { className: 'spinner spinner-dark' }),
                document.createTextNode(' جاري تحميل تفاصيل الشكوى...')
            ]));
        }
        if (scanPreview) scanPreview.replaceChildren(createEl('div', { className: 'pc-preview-empty', textContent: 'جاري التحميل...' }));
        if (timeline) timeline.replaceChildren();

        pcOpenModal('modalPoliceComplaintDetail');

        const user = await ensureCurrentUser();
        if (reqSeq !== state.detailRequestSeq) return;
        ensureStationsDatalistLoaded();

        const initRole = getUserRole(user);
        if (initRole === 'caller' || !['officer', 'admin', 'governor'].includes(initRole)) {
            if (scanPreview) {
                scanPreview.replaceChildren(createEl('div', {
                    className: 'pc-preview-empty',
                    textContent: '🔒 معاينة الوثائق الممسوحة غير متاحة لهذا الدور'
                }));
            }
        }

        try {
            const fetchOpts = controller ? { signal: controller.signal } : {};
            const res = await fetch(`/api/v1/mat/police-complaints/${encodeURIComponent(id)}`, fetchOpts);
            if (reqSeq !== state.detailRequestSeq) return;
            const data = await readJsonSafe(res);
            if (reqSeq !== state.detailRequestSeq) return;
            if (!res.ok) {
                if (summaryBlock) {
                    summaryBlock.replaceChildren(createEl('div', {
                        className: 'text-center text-error p-3',
                        textContent: data.error || 'تعذر تحميل تفاصيل الشكوى'
                    }));
                }
                pcToast(data.error || 'تعذر تحميل تفاصيل الشكوى', true);
                return;
            }
            renderComplaintDetail(data, user);
        } catch (err) {
            if ((err && err.name === 'AbortError') || reqSeq !== state.detailRequestSeq) {
                return;
            }
            if (summaryBlock) {
                summaryBlock.replaceChildren(createEl('div', {
                    className: 'text-center text-error p-3',
                    textContent: 'حدث خطأ في الاتصال بالخادم'
                }));
            }
            pcToast('تعذر الاتصال بالخادم', true);
        } finally {
            if (state.detailAbortController === controller) {
                state.detailAbortController = null;
            }
        }
    }

    async function submitOfficerAction() {
        if (state.isSubmittingOfficerAction) return;
        const detail = state.currentDetail;
        if (!detail) return;
        const user = await ensureCurrentUser();

        const officerAction = String($('pcDetailOfficerAction')?.value || '').trim();
        const officerNotes = String($('pcDetailOfficerNotes')?.value || '').trim();
        if (!officerAction) {
            pcToast('يرجى تحديد إجراء الضابط أولاً', true);
            $('pcDetailOfficerAction')?.focus();
            return;
        }
        if (!officerNotes) {
            pcToast('ملاحظات الضابط إلزامية عند تسجيل الإجراء', true);
            $('pcDetailOfficerNotes')?.focus();
            return;
        }

        const stage = detail.workflow_stage || 'draft_scan';
        const payload = { officer_action: officerAction, officer_notes: officerNotes };
        if (POST_APPROVAL_STAGES.has(stage)) {
            payload.execution_status = String($('pcDetailExecutionStatus')?.value || 'in_execution');
        } else {
            payload.send_to_section_head = Boolean($('pcOfficerSendToSectionHead')?.checked);
        }

        const submitBtn = findButtonByOnclick($('pcOfficerActionPanel'), 'submitOfficerAction');
        state.isSubmittingOfficerAction = true;
        if (submitBtn) submitBtn.disabled = true;

        try {
            const res = await fetch(`/api/v1/mat/police-complaints/${encodeURIComponent(detail.id)}/officer-action`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await readJsonSafe(res);
            if (!res.ok) {
                pcToast(data.error || 'تعذر حفظ إجراء الضابط', true);
                return;
            }
            renderComplaintDetail(data, user);
            pcToast(payload.send_to_section_head ? 'تم حفظ إجراء الضابط وإرسال الشكوى لرئيس القسم' : 'تم حفظ إجراء وملاحظات الضابط بنجاح');
            loadPoliceComplaintsTab();
        } catch (_) {
            pcToast('خطأ في الاتصال بالخادم', true);
        } finally {
            state.isSubmittingOfficerAction = false;
            if (submitBtn) submitBtn.disabled = false;
        }
    }

    function appendStationPayloadIfPresent(payload, stationName, dirName, liwaName, existingDetail) {
        const cleanStation = String(stationName || '').trim();
        if (!cleanStation) return;
        payload.nearest_station = cleanStation;
        if (dirName) payload.police_directorate = String(dirName).trim();
        if (liwaName) payload.liwa_name = String(liwaName).trim();

        const dirMeta = state.stationsDirectory.get(cleanStation);
        if (dirMeta) {
            if (!payload.police_directorate && dirMeta.police_directorate) {
                payload.police_directorate = dirMeta.police_directorate;
            }
            if (!payload.liwa_name && dirMeta.liwa_name) {
                payload.liwa_name = dirMeta.liwa_name;
            }
            if (dirMeta.lat !== null && dirMeta.lon !== null) {
                payload.station_lat = dirMeta.lat;
                payload.station_lon = dirMeta.lon;
            }
        } else if (existingDetail && cleanStation === existingDetail.nearest_station) {
            if (existingDetail.station_lat != null) payload.station_lat = existingDetail.station_lat;
            if (existingDetail.station_lon != null) payload.station_lon = existingDetail.station_lon;
        }
    }

    async function submitSectionHeadRecommend() {
        if (state.isSubmittingSectionHead) return;
        const detail = state.currentDetail;
        if (!detail) return;
        const user = await ensureCurrentUser();

        const secNotes = String($('pcSectionHeadNotes')?.value || '').trim();
        const recAction = String($('pcSectionRecommendedAction')?.value || '').trim();
        if (!secNotes) {
            pcToast('مشروحات القسم مطلوبة', true);
            $('pcSectionHeadNotes')?.focus();
            return;
        }
        if (!recAction) {
            pcToast('يرجى تحديد الإجراء المنسب من رئيس القسم', true);
            $('pcSectionRecommendedAction')?.focus();
            return;
        }

        const payload = {
            section_head_notes: secNotes,
            section_recommended_action: recAction
        };
        appendStationPayloadIfPresent(
            payload,
            $('pcSectionNearestStation')?.value,
            $('pcSectionDirectorate')?.value,
            $('pcSectionLiwa')?.value,
            detail
        );

        const submitBtn = findButtonByOnclick($('pcSectionHeadPanel'), 'submitSectionHeadRecommend');
        state.isSubmittingSectionHead = true;
        if (submitBtn) submitBtn.disabled = true;

        try {
            const res = await fetch(`/api/v1/mat/police-complaints/${encodeURIComponent(detail.id)}/section-recommend`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await readJsonSafe(res);
            if (!res.ok) {
                pcToast(data.error || 'تعذر حفظ تنسيب رئيس القسم', true);
                return;
            }
            renderComplaintDetail(data, user);
            pcToast('تم تثبيت تنسيب رئيس القسم ورفع الشكوى للحاكم الإداري بنجاح');
            loadPoliceComplaintsTab();
        } catch (_) {
            pcToast('خطأ في الاتصال بالخادم', true);
        } finally {
            state.isSubmittingSectionHead = false;
            if (submitBtn) submitBtn.disabled = false;
        }
    }

    async function submitGovernorDecision() {
        if (state.isSubmittingGovernor) return;
        const detail = state.currentDetail;
        if (!detail) return;
        const user = await ensureCurrentUser();

        const checked = document.querySelector('input[name="pcGovernorDecision"]:checked');
        const decision = checked ? checked.value : 'موافقة';
        const govNotes = String($('pcGovernorNotes')?.value || '').trim();
        const payload = {
            decision,
            governor_notes: govNotes
        };

        if (decision === 'تغيير_الإجراء') {
            const finalAction = String($('pcGovernorFinalAction')?.value || '').trim();
            if (!finalAction) {
                pcToast('يرجى تحديد الإجراء النهائي البديل عند تغيير الإجراء المنسب', true);
                $('pcGovernorFinalAction')?.focus();
                return;
            }
            payload.governor_final_action = finalAction;
        }

        appendStationPayloadIfPresent(
            payload,
            $('pcGovernorNearestStation')?.value,
            '',
            '',
            detail
        );

        const submitBtn = findButtonByOnclick($('pcGovernorDecisionPanel'), 'submitGovernorDecision');
        state.isSubmittingGovernor = true;
        if (submitBtn) submitBtn.disabled = true;

        try {
            const res = await fetch(`/api/v1/mat/police-complaints/${encodeURIComponent(detail.id)}/governor-decision`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await readJsonSafe(res);
            if (!res.ok) {
                pcToast(data.error || 'تعذر تثبيت قرار الحاكم الإداري', true);
                return;
            }

            renderComplaintDetail(data, user);

            let toastMsg = `تم تثبيت قرار الحاكم الإداري (${data.governor_decision || decision})`;
            if (data.workflow_stage !== 'governor_rejected') {
                if (data.linked_appointment_id) {
                    toastMsg += ' — 📅 تم إنشاء موعد اتصال هاتفي تلقائياً في جدول المواعيد';
                } else if (data.linked_file_number) {
                    toastMsg += ` — 📂 تم حجز رقم الملف تلقائياً (${data.linked_file_number})`;
                    if (data.priority === 'عاجل') toastMsg += ' ⚡ بأولوية عاجل';
                }
            }
            pcToast(toastMsg);
            loadPoliceComplaintsTab();
        } catch (_) {
            pcToast('خطأ في الاتصال بالخادم', true);
        } finally {
            state.isSubmittingGovernor = false;
            if (submitBtn) submitBtn.disabled = false;
        }
    }

    // ── 90-Day Follow-up, Inline Stop Confirmation, DOCX Export & Print ──────

    async function executeFollowupRequest(complaintId, actionType, notes, triggerBtn = null) {
        if (state.isSubmittingFollowup) return false;
        state.isSubmittingFollowup = true;

        const followupBtn = $('pcFollowupBtn');
        const stop90Btn = $('pcStop90Btn');
        if (followupBtn) followupBtn.disabled = true;
        if (stop90Btn) stop90Btn.disabled = true;
        if (triggerBtn) triggerBtn.disabled = true;

        let succeeded = false;
        const user = await ensureCurrentUser();
        try {
            const res = await fetch(`/api/v1/mat/police-complaints/${encodeURIComponent(complaintId)}/followup`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action_type: actionType, notes: notes || '' })
            });
            const data = await readJsonSafe(res);
            if (!res.ok) {
                pcToast(data.error || 'تعذر تنفيذ إجراء المتابعة', true);
                return false;
            }
            succeeded = true;
            renderComplaintDetail(data, user);
            pcToast(
                actionType === 'stop_90_days'
                    ? '⛔ تم تفعيل كف الطلب (90 يوماً) وإغلاق الشكوى'
                    : '🔄 تم تسجيل متابعة الشاكي وإعادة ضبط عداد الـ 90 يوماً'
            );
            loadPoliceComplaintsTab();
            return true;
        } catch (_) {
            pcToast('خطأ في الاتصال بالخادم', true);
            return false;
        } finally {
            state.isSubmittingFollowup = false;
            if (triggerBtn) triggerBtn.disabled = false;
            if (!succeeded && state.currentDetail) {
                configureRoleActionPanels(state.currentDetail, user);
            }
        }
    }

    async function registerComplaintFollowup(actionType) {
        if (state.isSubmittingFollowup) return;
        const detail = state.currentDetail;
        if (!detail) return;

        if (actionType !== 'stop_90_days') {
            hideStop90ConfirmBar();
            await executeFollowupRequest(detail.id, 'followup', '', $('pcFollowupBtn'));
            return;
        }

        // Two-click / inline DOM confirmation bar (zero native browser dialogs)
        const existingBar = $('pcStop90ConfirmBar');
        if (existingBar) {
            hideStop90ConfirmBar();
            return;
        }

        const user = await ensureCurrentUser();
        const role = getUserRole(user);
        const nd = detail.ninety_day_status || {};
        const elapsed = Number(nd.days_elapsed || 0);
        const needsOverrideNote = elapsed < 90;

        if (needsOverrideNote && role !== 'admin' && role !== 'governor') {
            pcToast(`لا يمكن تفعيل كف الطلب قبل مرور 90 يوماً (${elapsed} / 90 يوم) إلا عبر رئيس القسم أو الحاكم الإداري`, true);
            return;
        }

        const modalEl = $('modalPoliceComplaintDetail')?.querySelector('.modal');
        const footer = modalEl?.querySelector('.pc-detail-footer');
        if (!modalEl || !footer) return;

        const promptText = needsOverrideNote
            ? `لم تمر 90 يوماً بعد (${elapsed} / 90 يوم). لتفعيل كف الطلب استثنائياً، أدخل سبب التوقف الإلزامي:`
            : `تأكيد نهائي: تفعيل كف الطلب وإغلاق الشكوى ${detail.complaint_number || `#${detail.id}`} لمرور ${elapsed} يوماً دون متابعة؟`;

        const notesInput = createEl('input', {
            type: 'text',
            id: 'pcStop90NotesInput',
            className: 'form-control',
            style: { flex: '1 1 240px', padding: '0.45rem 0.65rem', fontSize: '0.85rem' },
            placeholder: needsOverrideNote ? 'اكتب سبب تفعيل كف الطلب الاستثنائي (إلزامي)...' : 'ملاحظات كف الطلب (اختياري)...'
        });

        const confirmBtn = createEl('button', {
            type: 'button',
            id: 'pcStopConfirmSubmitBtn',
            className: 'btn btn-sm',
            style: { background: '#DC2626', color: '#FFFFFF', border: '1px solid #B91C1C' },
            textContent: '⛔ تأكيد كف الطلب نهائياً',
            onClick: async () => {
                const noteVal = String(notesInput.value || '').trim();
                if (needsOverrideNote && !noteVal) {
                    pcToast('يرجى كتابة سبب كف الطلب الاستثنائي أولاً', true);
                    notesInput.focus();
                    return;
                }
                confirmBtn.disabled = true;
                try {
                    await executeFollowupRequest(detail.id, 'stop_90_days', noteVal, confirmBtn);
                } finally {
                    confirmBtn.disabled = false;
                }
            }
        });

        const cancelBtn = createEl('button', {
            type: 'button',
            className: 'btn btn-ghost btn-sm',
            textContent: 'تراجع',
            onClick: () => hideStop90ConfirmBar()
        });

        const bar = createEl('div', {
            id: 'pcStop90ConfirmBar',
            className: 'pc-no-print',
            style: {
                padding: '0.85rem 1.25rem',
                background: '#FEF2F2',
                borderTop: '2px solid #FCA5A5',
                display: 'flex',
                flexDirection: 'column',
                gap: '0.55rem'
            }
        }, [
            createEl('div', { style: { fontWeight: '800', fontSize: '0.86rem', color: '#991B1B' }, textContent: promptText }),
            createEl('div', { style: { display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center' } }, [
                notesInput,
                confirmBtn,
                cancelBtn
            ])
        ]);

        modalEl.insertBefore(bar, footer);
        notesInput.focus();
    }

    async function exportComplaintDocx() {
        const detail = state.currentDetail;
        if (!detail) return;

        const btn = $('pcExportDocxBtn');
        if (btn) btn.disabled = true;

        try {
            const res = await fetch(`/api/v1/mat/police-complaints/${encodeURIComponent(detail.id)}/export-docx`);
            if (!res.ok) {
                const errData = await readJsonSafe(res);
                pcToast(errData.error || 'تعذر تصدير ملف Word', true);
                return;
            }
            const blob = await res.blob();
            const disp = res.headers.get('Content-Disposition') || '';
            const fnMatch = disp.match(/filename="?([^";]+)"?/i);
            const fallbackName = `${String(detail.complaint_number || `complaint_${detail.id}`).replace(/[^A-Za-z0-9_-]/g, '_')}.docx`;
            const filename = (fnMatch && fnMatch[1]) || fallbackName;

            const objectUrl = URL.createObjectURL(blob);
            const link = createEl('a', {
                href: objectUrl,
                download: filename,
                style: { display: 'none' }
            });
            document.body.appendChild(link);
            link.click();
            link.remove();
            setTimeout(() => URL.revokeObjectURL(objectUrl), 1500);
            pcToast('📄 تم تجهيز وتنزيل نموذج الشكوى بصيغة Word (.docx)');
        } catch (_) {
            pcToast('حدث خطأ أثناء تصدير ملف Word', true);
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    function printComplaintOfficialSheet() {
        if (!state.currentDetail) return;
        if (state.printCleanupTimer) {
            clearTimeout(state.printCleanupTimer);
            state.printCleanupTimer = null;
        }
        if (state.printCleanupHandler) {
            global.removeEventListener('afterprint', state.printCleanupHandler);
            state.printCleanupHandler = null;
        }
        const cleanup = () => {
            document.body.classList.remove('pc-printing');
            if (state.printCleanupTimer) {
                clearTimeout(state.printCleanupTimer);
                state.printCleanupTimer = null;
            }
            if (state.printCleanupHandler) {
                global.removeEventListener('afterprint', state.printCleanupHandler);
                state.printCleanupHandler = null;
            }
        };
        state.printCleanupHandler = cleanup;
        document.body.classList.add('pc-printing');
        global.addEventListener('afterprint', cleanup, { once: true });
        state.printCleanupTimer = setTimeout(cleanup, 3000);
        global.print();
    }

    // ── Admin LLM Settings Controller ────────────────────────────────────────

    function renderLlmTestResult(ok, text) {
        const box = $('llmTestResultBox');
        if (!box) return;
        box.style.display = 'block';
        box.style.borderColor = ok ? '#A7F3D0' : '#FCA5A5';
        box.style.background = ok ? '#ECFDF5' : '#FEF2F2';
        box.style.color = ok ? '#065F46' : '#991B1B';
        box.textContent = text;
    }

    function updateLlmKeyHint(data) {
        const hint = $('llmKeyStatusHint');
        if (!hint) return;
        const provider = String((data && data.provider) || $('llmProviderSelect')?.value || 'gemini');
        if (data && data.api_key_configured) {
            hint.textContent = `حالة المفتاح: مهيأ ومحفوظ بأمان (${data.api_key_masked || '****'}) — اترك الحقل فارغاً للإبقاء على المفتاح المحفوظ`;
        } else if (provider === 'ollama') {
            hint.textContent = 'حالة المفتاح: مزود Ollama المحلي لا يتطلب مفتاح ربط عادةً';
        } else {
            hint.textContent = 'حالة المفتاح: غير مهيأ بعد — يرجى إدخال مفتاح الربط البرمجي';
        }
    }

    async function openLlmSettingsModal() {
        initPoliceComplaintsBindings();
        const keyInput = $('llmApiKeyInput');
        if (keyInput) keyInput.value = ''; // Never pre-fill stored secrets in DOM

        const testBox = $('llmTestResultBox');
        if (testBox) {
            testBox.style.display = 'none';
            testBox.textContent = '';
        }

        const hint = $('llmKeyStatusHint');
        if (hint) hint.textContent = 'حالة المفتاح: جارٍ التحقق...';

        pcOpenModal('modalLlmSettings');

        try {
            const res = await fetch('/api/v1/mat/llm-settings');
            const data = await readJsonSafe(res);
            if (!res.ok) {
                if (hint) hint.textContent = data.error || 'تعذر قراءة الإعدادات';
                pcToast(data.error || 'تعذر تحميل إعدادات الذكاء الاصطناعي', true);
                return;
            }
            if ($('llmProviderSelect')) $('llmProviderSelect').value = data.provider || 'gemini';
            if ($('llmModelInput')) $('llmModelInput').value = data.model_name || '';
            if ($('llmBaseUrlInput')) $('llmBaseUrlInput').value = data.api_base_url || '';
            if ($('llmEnabledCheckbox')) $('llmEnabledCheckbox').checked = Boolean(Number(data.is_enabled));
            if (keyInput) keyInput.value = '';

            state.llmSettingsMeta = {
                provider: data.provider || 'gemini',
                api_key_configured: Boolean(data.api_key_configured),
                is_enabled: Boolean(Number(data.is_enabled))
            };
            updateLlmKeyHint(data);
        } catch (_) {
            if (hint) hint.textContent = 'حالة المفتاح: تعذر الاتصال بالخادم';
            pcToast('خطأ في الاتصال بالخادم', true);
        }
    }

    function buildLlmSettingsPayload() {
        const provider = String($('llmProviderSelect')?.value || 'gemini').trim().toLowerCase();
        const modelName = String($('llmModelInput')?.value || '').trim();
        const baseUrl = String($('llmBaseUrlInput')?.value || '').trim();
        const isEnabled = $('llmEnabledCheckbox')?.checked ? 1 : 0;
        const apiKey = String($('llmApiKeyInput')?.value || '').trim();

        if (baseUrl && !/^https?:\/\//i.test(baseUrl)) {
            pcToast('رابط الخادم الأساسي يجب أن يبدأ بـ http:// أو https://', true);
            $('llmBaseUrlInput')?.focus();
            return null;
        }

        const payload = {
            provider,
            model_name: modelName,
            api_base_url: baseUrl,
            is_enabled: isEnabled
        };
        if (apiKey) {
            payload.api_key = apiKey;
        }
        return payload;
    }

    async function saveLlmSettings() {
        if (state.isSavingLlmSettings) return;
        const payload = buildLlmSettingsPayload();
        if (!payload) return;

        const saveBtn = findButtonByOnclick($('modalLlmSettings'), 'saveLlmSettings');
        state.isSavingLlmSettings = true;
        if (saveBtn) saveBtn.disabled = true;

        try {
            const res = await fetch('/api/v1/mat/llm-settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await readJsonSafe(res);
            if (!res.ok) {
                renderLlmTestResult(false, `❌ ${data.error || 'فشل حفظ الإعدادات'}`);
                pcToast(data.error || 'تعذر حفظ إعدادات الذكاء الاصطناعي', true);
                return;
            }
            if ($('llmApiKeyInput')) $('llmApiKeyInput').value = '';
            state.llmSettingsMeta = {
                provider: data.provider || payload.provider,
                api_key_configured: Boolean(data.api_key_configured),
                is_enabled: Boolean(Number(data.is_enabled))
            };
            updateLlmKeyHint(data);
            renderLlmTestResult(true, '✅ تم حفظ إعدادات الذكاء الاصطناعي بنجاح');
            pcToast('تم حفظ إعدادات محرك الذكاء الاصطناعي بنجاح');
        } catch (_) {
            renderLlmTestResult(false, '❌ تعذر الاتصال بالخادم');
            pcToast('خطأ في الاتصال بالخادم', true);
        } finally {
            state.isSavingLlmSettings = false;
            if (saveBtn) saveBtn.disabled = false;
        }
    }

    async function testLlmSettings() {
        if (state.isTestingLlmSettings) return;
        const payload = buildLlmSettingsPayload();
        if (!payload) return;

        const testBtn = findButtonByOnclick($('modalLlmSettings'), 'testLlmSettings');
        state.isTestingLlmSettings = true;
        if (testBtn) testBtn.disabled = true;

        const box = $('llmTestResultBox');
        if (box) {
            box.style.display = 'block';
            box.style.borderColor = '#CBD5E1';
            box.style.background = '#F8FAFC';
            box.style.color = 'var(--text-primary)';
            box.replaceChildren(
                createEl('span', { className: 'spinner spinner-dark', style: { marginLeft: '6px' } }),
                document.createTextNode('جاري اختبار الاتصال بمزود الذكاء الاصطناعي...')
            );
        }

        try {
            const res = await fetch('/api/v1/mat/llm-settings/test', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await readJsonSafe(res);
            if (res.ok && data.ok) {
                renderLlmTestResult(true, `✅ ${data.message || 'تم الاتصال بنجاح'}`);
                pcToast(data.message || 'اختبار الاتصال ناجح');
            } else {
                const msg = data.message || data.error || 'فشل اختبار الاتصال';
                renderLlmTestResult(false, `❌ ${msg}`);
                pcToast(msg, true);
            }
        } catch (_) {
            renderLlmTestResult(false, '❌ تعذر الاتصال بالخادم');
            pcToast('خطأ في الاتصال بالخادم', true);
        } finally {
            state.isTestingLlmSettings = false;
            if (testBtn) testBtn.disabled = false;
        }
    }

    // ── Event Binding & Initialization ───────────────────────────────────────

    function bindStationDatalistSync(stationInputId, dirInputId, liwaInputId, latInputId, lonInputId) {
        const stInput = $(stationInputId);
        if (!stInput) return;
        const onStationChange = () => {
            const val = String(stInput.value || '').trim();
            const meta = state.stationsDirectory.get(val);
            if (meta) {
                if (dirInputId && $(dirInputId)) $(dirInputId).value = meta.police_directorate || '';
                if (liwaInputId && $(liwaInputId)) $(liwaInputId).value = meta.liwa_name || '';
                if (latInputId && $(latInputId)) $(latInputId).value = meta.lat != null ? String(meta.lat) : '';
                if (lonInputId && $(lonInputId)) $(lonInputId).value = meta.lon != null ? String(meta.lon) : '';
            } else {
                if (latInputId && $(latInputId)) $(latInputId).value = '';
                if (lonInputId && $(lonInputId)) $(lonInputId).value = '';
            }
        };
        stInput.addEventListener('change', onStationChange);
        stInput.addEventListener('input', onStationChange);
    }

    function initPoliceComplaintsBindings() {
        if (state.initialized) return;
        state.initialized = true;

        // KPI Pills
        const statsBar = $('pcStatsBar');
        if (statsBar) {
            statsBar.querySelectorAll('.pc-kpi-pill').forEach((pill) => {
                pill.addEventListener('click', () => {
                    const stage = pill.dataset.stage || 'all';
                    const stageFilter = $('pcStageFilter');
                    const filter90 = $('pc90DayFilter');

                    if (stage === 'overdue_90') {
                        if (filter90) filter90.checked = true;
                        if (stageFilter) stageFilter.value = '';
                    } else if (stage === 'all') {
                        if (filter90) filter90.checked = false;
                        if (stageFilter) stageFilter.value = '';
                    } else {
                        if (filter90) filter90.checked = false;
                        if (stageFilter) stageFilter.value = stage;
                    }
                    syncActiveKpiPill();
                    loadPoliceComplaintsTab();
                });
            });
        }

        // Search & Filter Toolbar
        const searchInput = $('pcSearchInput');
        if (searchInput) {
            searchInput.addEventListener('input', () => {
                clearTimeout(state.searchDebounceTimer);
                state.searchDebounceTimer = setTimeout(() => loadPoliceComplaintsTab(), 320);
            });
            searchInput.addEventListener('keydown', (ev) => {
                if (ev.key === 'Enter') {
                    ev.preventDefault();
                    clearTimeout(state.searchDebounceTimer);
                    loadPoliceComplaintsTab();
                }
            });
        }

        $('pcStageFilter')?.addEventListener('change', () => {
            syncActiveKpiPill();
            loadPoliceComplaintsTab();
        });

        $('pc90DayFilter')?.addEventListener('change', () => {
            syncActiveKpiPill();
            loadPoliceComplaintsTab();
        });

        // Scanner Inputs, Dropzone, Camera & Paste
        const scanFileInput = $('pcScanFileInput');
        if (scanFileInput) {
            scanFileInput.addEventListener('change', (ev) => {
                const file = ev.target.files && ev.target.files[0];
                ev.target.value = '';
                if (file) handleSelectedScanFile(file, { autoExtract: true });
            });
        }

        const cameraInput = $('pcCameraFileInput');
        if (cameraInput) {
            cameraInput.addEventListener('change', (ev) => {
                const file = ev.target.files && ev.target.files[0];
                ev.target.value = '';
                if (file) handleSelectedScanFile(file, { autoExtract: true });
            });
        }

        $('pcCameraBtn')?.addEventListener('click', () => {
            $('pcCameraFileInput')?.click();
        });

        $('pcRotateScanBtn')?.addEventListener('click', () => {
            rotatePendingScanFile(90);
        });

        $('pcScanAnalyzeBtn')?.addEventListener('click', () => {
            runScanExtraction();
        });

        $('pcResetIntakeBtn')?.addEventListener('click', () => {
            resetIntakeForm();
            pcToast('تم مسح بيانات نموذج المسح');
        });

        const dropZone = $('pcDropZone');
        if (dropZone) {
            dropZone.addEventListener('click', (ev) => {
                if (ev.target.closest('button, input')) return;
                $('pcScanFileInput')?.click();
            });
            ['dragenter', 'dragover'].forEach((evtName) => {
                dropZone.addEventListener(evtName, (ev) => {
                    ev.preventDefault();
                    ev.stopPropagation();
                    dropZone.classList.add('drag-over');
                });
            });
            ['dragleave', 'drop'].forEach((evtName) => {
                dropZone.addEventListener(evtName, (ev) => {
                    ev.preventDefault();
                    ev.stopPropagation();
                    dropZone.classList.remove('drag-over');
                });
            });
            dropZone.addEventListener('drop', (ev) => {
                const file = ev.dataTransfer && ev.dataTransfer.files && ev.dataTransfer.files[0];
                if (file) handleSelectedScanFile(file, { autoExtract: true });
            });
        }

        document.addEventListener('paste', (ev) => {
            const tab = $('tab-police-complaints');
            const intakeCard = $('scannerIntakeCard');
            if (!tab || !tab.classList.contains('active')) return;
            if (!intakeCard || intakeCard.style.display === 'none') return;

            const items = ev.clipboardData && ev.clipboardData.items;
            if (!items) return;
            for (const item of items) {
                if (item.kind === 'file') {
                    const file = item.getAsFile();
                    if (file && (ALLOWED_SCAN_MIMES.has(file.type) || file.type.startsWith('image/'))) {
                        ev.preventDefault();
                        handleSelectedScanFile(file, { autoExtract: true });
                        break;
                    }
                }
            }
        });

        // Intake Form Submission & Draft Save
        $('pcSaveDraftBtn')?.addEventListener('click', () => {
            submitComplaintIntake('draft_scan');
        });

        $('formPoliceComplaintIntake')?.addEventListener('submit', (ev) => {
            ev.preventDefault();
            submitComplaintIntake('pending_section_head');
        });

        // Station Datalist auto-fill sync
        bindStationDatalistSync('pcNearestStation', 'pcPoliceDirectorate', 'pcLiwaName', 'pcStationLat', 'pcStationLon');
        bindStationDatalistSync('pcSectionNearestStation', 'pcSectionDirectorate', 'pcSectionLiwa', null, null);
        bindStationDatalistSync('pcGovernorNearestStation', null, null, null, null);

        // Detail modal lightbox zoom & Governor radio change
        $('pcDetailZoomBtn')?.addEventListener('click', () => openScanLightbox());

        document.querySelectorAll('input[name="pcGovernorDecision"]').forEach((radio) => {
            radio.addEventListener('change', () => syncGovernorFinalActionVisibility());
        });

        // LLM Provider defaults helper on select change
        const llmProviderSel = $('llmProviderSelect');
        if (llmProviderSel) {
            llmProviderSel.addEventListener('change', () => {
                const prov = llmProviderSel.value;
                const modelInput = $('llmModelInput');
                const baseUrlInput = $('llmBaseUrlInput');
                const def = LLM_DEFAULTS[prov] || LLM_DEFAULTS.gemini;
                const knownDefaults = new Set(Object.values(LLM_DEFAULTS).map((d) => d.model));
                if (modelInput && (!modelInput.value.trim() || knownDefaults.has(modelInput.value.trim()))) {
                    modelInput.value = def.model;
                }
                if (baseUrlInput) {
                    baseUrlInput.placeholder = def.baseUrl;
                }
                updateLlmKeyHint({
                    provider: prov,
                    api_key_configured: state.llmSettingsMeta.api_key_configured && prov === state.llmSettingsMeta.provider
                });
            });
        }
    }

    function checkNotificationDeepLink() {
        if (state.deepLinkHandled) return;
        const hashMatch = String(global.location?.hash || '').match(/^#police-complaints-(\d+)$/);
        if (!hashMatch) return;
        state.deepLinkHandled = true;
        const compId = Number(hashMatch[1]);
        let attempts = 0;

        const tryOpen = () => {
            attempts += 1;
            const userReady = typeof currentUser !== 'undefined' && currentUser;
            const switchReady = typeof global.switchTab === 'function';
            if ((userReady && switchReady) || attempts >= 25) {
                setTimeout(() => {
                    if (typeof global.switchTab === 'function') {
                        global.switchTab('police-complaints');
                    }
                    openPoliceComplaintDetail(compId);
                }, 60);
                return;
            }
            setTimeout(tryOpen, 100);
        };
        tryOpen();
    }

    document.addEventListener('DOMContentLoaded', () => {
        initPoliceComplaintsBindings();
        checkNotificationDeepLink();
    });
    global.addEventListener('hashchange', () => {
        state.deepLinkHandled = false;
        checkNotificationDeepLink();
    });

    // ── Global Exports (used by app.html inline handlers & app.js) ───────────
    global.pcEscape = pcEscape;
    global.createEl = createEl;
    global.loadPoliceComplaintsTab = loadPoliceComplaintsTab;
    global.openPoliceComplaintDetail = openPoliceComplaintDetail;
    global.toggleScannerIntakePanel = toggleScannerIntakePanel;
    global.addComplaintPartyRow = addComplaintPartyRow;
    global.rematchComplaintStation = rematchComplaintStation;
    global.openStationInFinder = openStationInFinder;
    global.submitOfficerAction = submitOfficerAction;
    global.submitSectionHeadRecommend = submitSectionHeadRecommend;
    global.submitGovernorDecision = submitGovernorDecision;
    global.registerComplaintFollowup = registerComplaintFollowup;
    global.exportComplaintDocx = exportComplaintDocx;
    global.printComplaintOfficialSheet = printComplaintOfficialSheet;
    global.openLlmSettingsModal = openLlmSettingsModal;
    global.saveLlmSettings = saveLlmSettings;
    global.testLlmSettings = testLlmSettings;
    global.openScanLightbox = openScanLightbox;
})(window);
