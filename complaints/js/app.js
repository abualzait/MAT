// ── MAT Project Configuration ──────────────────────────────
const matConfig = {
    name: 'MAT',
    arabicName: 'حقيبة الأدوات المساعدة',
    fullName: 'Modular Assistant Toolkit',
    apiPrefix: '/api/v1/mat/v1/mat'
};
/**
 * نظام دليل المراكز الأمنية وجدولة المواعيد — JS
 */

let currentUser = null;

// ── CSRF Setup ──────────────────────────────────────────────
const originalFetch = window.fetch;
window.fetch = async function(resource, config = {}) {
    const csrfMatch = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
    if (csrfMatch && csrfMatch[1]) {
        config.headers = {
            ...config.headers,
            'X-CSRF-Token': csrfMatch[1]
        };
    }
    return originalFetch(resource, config);
};

// ── Initialization ──────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    // Check Authentication
    const user = await checkAuth();
    if (!user) {
        window.location.href = '/login';
        return;
    }

    currentUser = user;
    renderUserInfo();

    // Set initial date filter values
    const todayStr = new Date().toISOString().split('T')[0];
    if (document.getElementById('apptFilterFrom')) {
        document.getElementById('apptFilterFrom').value = todayStr;
    }

    // Default tab: Dashboard for all users
    switchTab('dashboard');
    
    // Start notifications & online users polling
    startNotificationsPolling();
    loadOnlineUsers();
    setInterval(loadOnlineUsers, 10000);

    // Setup Sidebar Hover Expansion for Collapsed State
    const sidebarEl = document.getElementById('mainSidebar');
    if (sidebarEl) {
        sidebarEl.addEventListener('mouseenter', () => {
            if (sidebarEl.classList.contains('collapsed')) {
                sidebarEl.classList.add('hover-expanded');
            }
        });
        sidebarEl.addEventListener('mouseleave', () => {
            sidebarEl.classList.remove('hover-expanded');
        });
    }
});

// ── Auth & Navigation ───────────────────────────────────────
async function checkAuth() {
    try {
        const res = await fetch('/api/v1/mat/me');
        if (res.ok) {
            return await res.json();
        }
    } catch (e) {
        console.error('Auth check failed:', e);
    }
    return null;
}

function renderUserInfo() {
    if (!currentUser) return;
    const userNameTop = document.getElementById('userName');
    if (userNameTop) userNameTop.textContent = currentUser.name;

    const roleLabels = {
        'admin': 'رئيس القسم (مشرف)',
        'officer': 'ضابط / مستخدم مواعيد',
        'caller': 'ضابط اتصالات'
    };
    let roleText = roleLabels[currentUser.role] || currentUser.role;
    if (currentUser.username === 'orwa') {
        roleText = 'رئيس قسم الشكاوي';
    }

    const userRoleBadgeTop = document.getElementById('userRoleBadge');
    if (userRoleBadgeTop) userRoleBadgeTop.textContent = roleText;

    const userNameSidebar = document.getElementById('userNameSidebar');
    if (userNameSidebar) userNameSidebar.textContent = currentUser.name;

    const userRoleBadgeSidebar = document.getElementById('userRoleBadgeSidebar');
    if (userRoleBadgeSidebar) userRoleBadgeSidebar.textContent = roleText;

    // Toggle Chat Button Top Bar based on permission
    const topChatBtn = document.getElementById('meetingRoomTopBtn');
    if (topChatBtn) {
        const hasChatAccess = currentUser.role === 'admin' || (currentUser.accessible_tools || '').includes('chat');
        topChatBtn.style.display = hasChatAccess ? 'inline-flex' : 'none';
    }

    // Admin Mode Styling Check
    if (localStorage.getItem('adminModeActive') === 'true') {
        const topBar = document.querySelector('.top-bar');
        const sidebar = document.querySelector('.sidebar');
        if (topBar) topBar.style.background = 'linear-gradient(135deg, #7A1F3D 0%, #4A001A 100%)';
        if (sidebar) sidebar.style.background = 'linear-gradient(180deg, #6B1633 0%, #3D0014 100%)';
        
        const badge = document.getElementById('userRoleBadge');
        if (badge) {
            badge.innerHTML = '👑 وضع المشرف السري';
            badge.style.background = '#FFD700';
            badge.style.color = '#000000';
        }
        if (userRoleBadgeSidebar) {
            userRoleBadgeSidebar.innerHTML = '👑 وضع المشرف السري';
            userRoleBadgeSidebar.style.background = '#FFD700';
            userRoleBadgeSidebar.style.color = '#000000';
        }
    }

    if (currentUser.role === 'admin') {
        const adminBtn = document.getElementById('officersTabBtn');
        if (adminBtn) adminBtn.style.display = 'flex';
    }

    let tools = currentUser.accessible_tools || [];
    if (typeof tools === 'string') {
        tools = tools.split(',').map(t => t.trim());
    }
    const isAdmin = currentUser.role === 'admin' || localStorage.getItem('adminModeActive') === 'true';

    renderDynamicNavigation(tools, isAdmin, currentUser.role);
}

function renderDynamicNavigation(tools, isAdmin, role) {
    const navMenu = document.getElementById('dynamicSidebarMenu');
    if (!navMenu) return;

    if (typeof tools === 'string') {
        tools = tools.split(',').map(t => t.trim());
    }

    const hasDashboard = isAdmin || tools.includes('dashboard');
    const hasComplaints = isAdmin || tools.includes('complaints') || tools.includes('mat_complaints');
    const hasFinder = isAdmin || tools.includes('finder') || tools.includes('stations');
    const hasFiles = isAdmin || tools.includes('file_reservations') || tools.includes('reservations') || role === 'officer';
    const hasChat = isAdmin || tools.includes('chat');
    const hasAdminPerms = isAdmin || tools.includes('admin_permissions') || localStorage.getItem('adminModeActive') === 'true';

    let html = '';
    let toolsCount = 0;
    let toolsListHtml = '';

    // Group 0: Dashboard (Top Level)
    if (hasDashboard) {
        html += `
            <div class="nav-group">
                <div class="nav-sub-menu" style="display:flex;">
                    <button class="nav-item active" onclick="switchTab('dashboard')" title="لوحة التحكم والملخص">
                        <span class="nav-icon">📊</span><span class="nav-text">لوحة التحكم والملخص</span>
                    </button>
                </div>
            </div>`;
    }

    // Group 1: Appointments (Expanded by default so sub-items and icons are visible)
    if (hasComplaints) {
        toolsCount++;
        toolsListHtml += `<li class="tool-card"><strong>${toolsCount}. نظام المواعيد</strong> 📅</li>`;

        let apptSubItems = [
            { icon: '📅', text: 'جدولة المواعيد والقضايا', onclick: "switchTab('appointments')", active: false },
            { icon: '🗓️', text: 'العرض اليومي (بطاقات)', onclick: "switchTab('daily-view')", active: role === 'caller' },
            { icon: '📆', text: 'التقويم الشهري', onclick: "switchTab('calendar-view')", active: false }
        ];

        let subItemsHtml = apptSubItems.map(item => `
            <button class="nav-item ${item.active ? 'active' : ''}" onclick="${item.onclick}" title="${item.text}">
                <span class="nav-icon">${item.icon}</span><span class="nav-text">${item.text}</span>
            </button>`).join('');

        html += `
            <div class="nav-group expanded">
                <button class="nav-group-header" onclick="toggleNavGroup(this)" title="نظام المواعيد">
                    <div class="nav-header-left"><span class="nav-icon">📅</span><span class="nav-text">نظام المواعيد</span></div>
                    <span class="nav-chevron">▼</span>
                </button>
                <div class="nav-sub-menu">${subItemsHtml}</div>
            </div>`;
    }

    // Group 2: Geographic Tools
    if (hasFinder) {
        toolsCount++;
        toolsListHtml += `<li class="tool-card"><strong>${toolsCount}. دليل المراكز الأمنية</strong> 🗺️</li>`;
        html += `
            <div class="nav-group">
                <div class="nav-sub-menu" style="display:flex;">
                    <button class="nav-item" onclick="switchTab('stations')" title="دليل المراكز الأمنية">
                        <span class="nav-icon">🗺️</span><span class="nav-text">دليل المراكز الأمنية</span>
                    </button>
                </div>
            </div>`;
    } else {
        const topSearchedCard = document.querySelector('#topSearchedAreasContainer')?.closest('.card');
        if (topSearchedCard) topSearchedCard.style.display = 'none';
    }

    // Group 2.5: Tracking Tools / File Reservations
    if (hasFiles) {
        toolsCount++;
        toolsListHtml += `<li class="tool-card"><strong>${toolsCount}. أداة حجز الملفات</strong> 🔒</li>`;
        html += `
            <div class="nav-group">
                <div class="nav-sub-menu" style="display:flex;">
                    <button class="nav-item" onclick="switchTab('reservations')" title="حجز وإدارة الملفات">
                        <span class="nav-icon">📂</span><span class="nav-text">حجز وإدارة الملفات</span>
                    </button>
                </div>
            </div>`;
    }

    // Group 3: Settings & System Administration (Expanded by default when present)
    if (hasAdminPerms) {
        let adminSubItems = [];
        if (isAdmin || role === 'admin') {
            adminSubItems.push({ icon: '⚙️', text: 'الإعدادات والصلاحيات', onclick: "switchTab('officers')" });
        }
        if (hasAdminPerms) {
            adminSubItems.push({ icon: '👑', text: 'الصلاحيات المتقدمة', onclick: "switchTab('admin_permissions')" });
        }

        if (adminSubItems.length === 1) {
            const item = adminSubItems[0];
            html += `
                <div class="nav-group">
                    <div class="nav-sub-menu" style="display:flex;">
                        <button class="nav-item" onclick="${item.onclick}" title="${item.text}">
                            <span class="nav-icon">${item.icon}</span><span class="nav-text">${item.text}</span>
                        </button>
                    </div>
                </div>`;
        } else if (adminSubItems.length > 1) {
            let subItemsHtml = adminSubItems.map(item => `
                <button class="nav-item" onclick="${item.onclick}" title="${item.text}">
                    <span class="nav-icon">${item.icon}</span><span class="nav-text">${item.text}</span>
                </button>`).join('');

            html += `
                <div class="nav-group expanded">
                    <button class="nav-group-header" onclick="toggleNavGroup(this)" title="إدارة النظام">
                        <div class="nav-header-left"><span class="nav-icon">🛡️</span><span class="nav-text">إدارة النظام</span></div>
                        <span class="nav-chevron">▼</span>
                    </button>
                    <div class="nav-sub-menu">${subItemsHtml}</div>
                </div>`;
        }
    }

    // Standalone Item: غرفة الاجتماعات
    if (hasChat) {
        toolsCount++;
        toolsListHtml += `<li class="tool-card"><strong>${toolsCount}. غرفة الاجتماعات</strong> 💬</li>`;
        html += `
            <div style="margin-top: 0.75rem; padding-top: 0.75rem; border-top: 1px solid rgba(255,255,255,0.12);">
                <button class="nav-item standalone-meeting-btn" onclick="toggleChatPane(true)" style="width: 100%; display: flex; align-items: center; justify-content: space-between; padding: 0.75rem 1rem; background: rgba(255, 255, 255, 0.08); border: 1px solid rgba(255, 255, 255, 0.2); border-radius: var(--radius-md); color: #ffffff !important; font-weight: 700; font-size: 0.9rem; cursor: pointer; transition: all 0.2s ease;">
                    <div style="display:flex; align-items:center; gap:8px;">
                        <span class="nav-icon" style="font-size: 1.1rem;">💬</span>
                        <span class="nav-text">غرفة الاجتماعات</span>
                    </div>
                    <span id="onlineUsersCount" class="badge" style="background:#22c55e; color:#ffffff; font-weight:800; font-size:0.75rem; padding:2px 8px; border-radius:10px; box-shadow: 0 0 6px rgba(34,197,94,0.5);">0</span>
                </button>
            </div>`;
    }

    navMenu.innerHTML = html;

    // Update Tools Widget
    const toolsBadge = document.getElementById('toolsCountBadge');
    const toolsList = document.getElementById('availableToolsList');
    if (toolsBadge && toolsList) {
        toolsBadge.textContent = toolsCount;
        toolsList.innerHTML = toolsListHtml;
    }
}

async function logout() {
    try {
        await fetch('/api/v1/mat/logout', { method: 'POST' });
    } catch (e) {}
    window.location.href = '/login';
}

function toggleNavGroup(headerElem) {
    const group = headerElem.closest('.nav-group');
    if (!group) return;
    const isExpanded = group.classList.contains('expanded');

    // Single Accordion Open: collapse all other groups first
    document.querySelectorAll('#dynamicSidebarMenu .nav-group').forEach(g => {
        g.classList.remove('expanded');
    });

    if (!isExpanded) {
        group.classList.add('expanded');
    }
}

function switchTab(tabId) {
    document.querySelectorAll('.nav-item, .tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

    const activeBtn = Array.from(document.querySelectorAll('.nav-item, .tab')).find(b => b.getAttribute('onclick')?.includes(tabId));
    if (activeBtn) {
        activeBtn.classList.add('active');
        const parentGroup = activeBtn.closest('.nav-group');
        if (parentGroup) {
            parentGroup.classList.add('expanded');
        }
    }

    const contentElem = document.getElementById(`tab-${tabId}`);
    if (contentElem) contentElem.classList.add('active');

    // Automatically collapse sidebar on tab selection (Requirement: ضم القائمة عند اختيار احد الصفحات)
    const sidebar = document.getElementById('mainSidebar');
    if (sidebar) {
        sidebar.classList.add('collapsed');
        sidebar.classList.remove('hover-expanded');
    }

    // Auto close drawer on mobile view when switching tabs
    if (window.innerWidth <= 992) {
        closeSidebarDrawer();
    }

    // Trigger tab-specific data load
    if (tabId === 'stations') {
        const iframe = document.getElementById('stationsIframe');
        if (iframe && (!iframe.src || iframe.src === 'about:blank' || !iframe.src.includes('police-stations'))) {
            iframe.src = '/police-stations?embedded=true';
        }
    } else if (tabId === 'appointments') {
        loadSimpleAppointments();
    } else if (tabId === 'daily-view') {
        loadDailyView();
    } else if (tabId === 'calendar-view') {
        loadCalendarView();
    } else if (tabId === 'dashboard') {
        loadSimpleDashboard();
    } else if (tabId === 'officers') {
        loadOfficersTable();
    } else if (tabId === 'admin_permissions') {
        loadAdminPermissions();
    } else if (tabId === 'reservations') {
        loadReservations();
    }
}

// ── Admin Permissions ───────────────────────────────────────
async function loadAdminPermissions() {
    const tbody = document.getElementById('permissionsTableBody');
    if (!tbody) return;
    
    tbody.innerHTML = '<tr><td colspan="7" class="text-center"><div class="spinner spinner-dark"></div> جاري تحميل الصلاحيات...</td></tr>';
    
    try {
        const res = await fetch('/api/v1/mat/officers');
        if (!res.ok) throw new Error('Failed to fetch officers');
        const data = await res.json();
        
        // Filter out disabled/inactive users so they do NOT appear on the permissions page
        const activeOfficers = ((data.officers || data.mat_officers) || []).filter(o => o.is_active);

        if (activeOfficers.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="text-center">لا يوجد مستخدمين فعّالين لعرضهم</td></tr>';
            return;
        }
        
        let html = '';
        activeOfficers.forEach(o => {
            const tools = o.accessible_tools || '';
            const hasDashboard = tools.includes('dashboard');
            const hasAppointments = tools.includes('complaints');
            const hasStations = tools.includes('finder');
            const hasFiles = tools.includes('file_reservations');
            const hasChat = tools.includes('chat');
            
            html += `
                <tr>
                    <td class="fw-bold">${o.name} <br><small class="text-light">(${o.username})</small></td>
                    <td>
                        <label class="switch">
                            <input type="checkbox" onchange="togglePermission(${o.id}, 'dashboard', this.checked)" ${hasDashboard ? 'checked' : ''}>
                            <span class="slider round"></span>
                        </label>
                    </td>
                    <td>
                        <label class="switch">
                            <input type="checkbox" onchange="togglePermission(${o.id}, 'complaints', this.checked)" ${hasAppointments ? 'checked' : ''}>
                            <span class="slider round"></span>
                        </label>
                    </td>
                    <td>
                        <label class="switch">
                            <input type="checkbox" onchange="togglePermission(${o.id}, 'finder', this.checked)" ${hasStations ? 'checked' : ''}>
                            <span class="slider round"></span>
                        </label>
                    </td>
                    <td>
                        <label class="switch">
                            <input type="checkbox" onchange="togglePermission(${o.id}, 'file_reservations', this.checked)" ${hasFiles ? 'checked' : ''}>
                            <span class="slider round"></span>
                        </label>
                    </td>
                    <td>
                        <label class="switch">
                            <input type="checkbox" onchange="togglePermission(${o.id}, 'chat', this.checked)" ${hasChat ? 'checked' : ''}>
                            <span class="slider round"></span>
                        </label>
                    </td>
                    <td><span class="badge badge-success">فعّال</span></td>
                </tr>
            `;
        });
        
        tbody.innerHTML = html;
        
    } catch (e) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center text-error">خطأ في جلب بيانات الصلاحيات</td></tr>';
    }
}

async function togglePermission(officerId, toolName, isChecked) {
    try {
        const res = await fetch('/api/v1/mat/officers');
        const data = await res.json();
        const officersList = data.officers || data.mat_officers || [];
        const officer = officersList.find(o => o.id === officerId);
        if (!officer) return;
        
        let toolsArray = officer.accessible_tools ? officer.accessible_tools.split(',').map(t => t.trim()).filter(Boolean) : [];
        if (isChecked && !toolsArray.includes(toolName)) {
            toolsArray.push(toolName);
        } else if (!isChecked && toolsArray.includes(toolName)) {
            toolsArray = toolsArray.filter(t => t !== toolName);
        }
        
        const updatedTools = toolsArray.join(',');
        
        const updateRes = await fetch(`/api/v1/mat/officers/${officerId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                accessible_tools: updatedTools
            })
        });
        
        if (updateRes.ok) {
            showToast('تم تحديث الصلاحيات بنجاح', false);
        } else {
            showToast('حدث خطأ أثناء تحديث الصلاحيات', true);
            loadAdminPermissions(); // reload to reset toggle
        }
    } catch (e) {
        showToast('خطأ في الاتصال بالخادم', true);
        loadAdminPermissions();
    }
}


// ── Toast Notifications ─────────────────────────────────────
function showToast(message, isError = false, apptId = null, isOverdue = false) {
    const container = document.getElementById('toastContainer');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast ${isError ? 'toast-error' : ''}`;
    if (apptId) {
        toast.style.cursor = 'pointer';
        toast.title = isOverdue ? 'انقر لتحديث حالة الموعد وإدخال النتيجة والملاحظات' : 'انقر لمشاهدة التفاصيل';
        toast.onclick = () => {
            if (isOverdue) {
                openOverdueUpdateModal(apptId);
            } else {
                openAppointmentDetail(apptId);
            }
        };
    }
    toast.innerHTML = `<span>${isError ? '⏰' : '🔔'}</span> <div style="flex:1;">${message}</div> ${apptId && isOverdue ? '<span class="badge badge-purple" style="font-size:0.75rem; margin-right:6px;">تحديث الآن</span>' : ''}`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 7000);
}

// ── Modals ──────────────────────────────────────────────────
function openModal(modalId) {
    const el = document.getElementById(modalId);
    if (el) {
        el.classList.add('active', 'show');
    }
}

function closeModal(modalId) {
    const el = document.getElementById(modalId);
    if (el) {
        el.classList.remove('active', 'show');
    }
}

// ── SIMPLE APPOINTMENTS MANAGEMENT ─────────────────────────

async function loadSimpleAppointments() {
    const container = document.getElementById('simpleAppointmentsTableContainer');
    if (!container) return;

    const fromDate = document.getElementById('apptFilterFrom')?.value || '';
    const toDate = document.getElementById('apptFilterTo')?.value || '';
    const status = document.getElementById('apptFilterStatus')?.value || '';

    container.innerHTML = '<div class="text-center p-3"><div class="spinner spinner-dark"></div> جاري تحميل جدول المواعيد...</div>';

    try {
        let url = `/api/v1/mat/simple-appointments?from=${encodeURIComponent(fromDate)}`;
        if (toDate) url += `&to=${encodeURIComponent(toDate)}`;
        if (status) url += `&status=${encodeURIComponent(status)}`;

        const res = await fetch(url);
        if (!res.ok) return;
        const data = await res.json();

        if (!data.appointments || data.appointments.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">📅</div>
                    <p>لا يوجد مواعيد محددة مسجلة في هذا النطاق الزمني.</p>
                    <button class="btn btn-primary" onclick="openNewSimpleAppointmentModal()">➕ حجز موعد جديد الآن</button>
                </div>`;
            return;
        }

        let html = `
            <div class="table-wrapper data-grid-wrapper">
                <table class="data-grid-table">
                    <thead>
                        <tr>
                            <th>رقم القضية / المعاملة</th>
                            <th>اسم المراجع / الرقم</th>
                            <th>رقم الهاتف</th>
                            <th>طالب الاتصال / بواسطة</th>
                            <th>تاريخ ووقت الموعد</th>
                            <th>الحالة</th>
                            <th>الملاحظات / الصادر الداخلي</th>
                            <th class="actions-cell">إجراءات</th>
                        </tr>
                    </thead>
                    <tbody>`;

        data.appointments.forEach(a => {
            let parentBadge = '';
            if (a.parent_info) {
                parentBadge = `<br><span class="badge badge-pending" style="font-size:0.75rem; margin-top:5px;">فرع من موعد ${a.parent_info.appointment_date}</span>`;
            }
            let requestedBy = `${a.requested_by_name || 'غير محدد'} / ${a.created_by_name || 'غير محدد'}`;
            const maskClass = getApptMaskClass(a.status, a.appointment_date, a.appointment_time, !!(a.parent_info || a.parent_appointment_id));

            html += `
                <tr class="${maskClass}" style="cursor:pointer;" onclick="openAppointmentDetail(${a.id})">
                    <td><span class="fw-bold text-primary" style="font-size:1.05rem;">📄 ${a.case_number}</span>${parentBadge}</td>
                    <td><span class="fw-bold">${a.visitor_name}</span> ${a.national_id ? `<br><small class="text-light">ر.و: ${a.national_id}</small>` : ''}</td>
                    <td><a href="tel:${a.phone}" class="fw-bold" style="color:var(--primary); text-decoration:none;" onclick="event.stopPropagation()">📱 ${a.phone || 'بدون رقم'}</a></td>
                    <td>${requestedBy}</td>
                    <td><span class="fw-bold">📅 ${a.appointment_date} <br>⏱️ ${a.appointment_time}</span></td>
                    <td onclick="event.stopPropagation()">
                        <select class="form-control" style="padding:0.25rem 0.5rem; font-size:0.82rem; font-weight:700; width:auto;" onchange="updateSimpleAppointmentStatus(${a.id}, this.value)">
                            <option value="مُجدول" ${a.status === 'مُجدول' ? 'selected' : ''}>⏳ مُجدول</option>
                            <option value="مُؤجل" ${a.status === 'مُؤجل' ? 'selected' : ''}>🔄 مُؤجل</option>
                            <option value="تم الحضور" ${a.status === 'تم الحضور' ? 'selected' : ''}>✅ تم الحضور</option>
                            <option value="لم يحضر" ${a.status === 'لم يحضر' ? 'selected' : ''}>❌ لم يحضر</option>
                            <option value="لم يجيبوا" ${a.status === 'لم يجيبوا' ? 'selected' : ''}>📵 لم يجيبوا (معلق)</option>
                            <option value="ملغى" ${a.status === 'ملغى' ? 'selected' : ''}>🚫 ملغى</option>
                        </select>
                    </td>
                    <td><span class="text-light" style="font-size:0.85rem;">${a.notes || '—'}</span></td>
                    <td onclick="event.stopPropagation()">
                        <button class="btn btn-outline btn-sm mb-1" onclick="branchAppointment(${a.id})" title="تأجيل وحجز موعد جديد متعلق بهذا الموعد">🔄 تأجيل/فرع</button><br>
                        <button class="btn btn-ghost btn-sm" onclick="deleteSimpleAppointment(${a.id})" title="حذف الموعد">🗑️ حذف</button>
                    </td>
                </tr>`;
        });
        window.currentAppointmentsData = data.appointments;

        html += `</tbody></table></div>`;
        container.innerHTML = html;

    } catch (e) {
        console.error('Error loading simple appointments:', e);
        container.innerHTML = '<div class="text-danger text-center p-3">حدث خطأ أثناء تحميل جدول المواعيد.</div>';
    }
}

function openNewSimpleAppointmentModal(parentAppt = null) {
    const form = document.getElementById('formNewSimpleAppointment');
    if (form) form.reset();
    document.getElementById('editSimpleApptId').value = '';
    document.getElementById('parentAppointmentId').value = parentAppt ? parentAppt.id : '';

    if (parentAppt) {
        document.getElementById('simpleCaseNumber').value = parentAppt.case_number || '';
        document.getElementById('simpleVisitorName').value = parentAppt.visitor_name || '';
        document.getElementById('simplePhone').value = parentAppt.phone || '';
        if (parentAppt.requested_by_id) {
            document.getElementById('simpleRequestedBy').value = parentAppt.requested_by_id;
        }
    }

    // Default date & time: tomorrow at 10:00 AM
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    document.getElementById('simpleDate').value = tomorrow.toISOString().split('T')[0];
    document.getElementById('simpleTime').value = '10:00';

    loadOfficersForDropdown();
    openModal('modalNewSimpleAppointment');
}

async function loadOfficersForDropdown() {
    const select = document.getElementById('simpleRequestedBy');
    if (!select) return;
    try {
        const res = await fetch('/api/v1/mat/officers');
        if (res.ok) {
            const data = await res.json();
            const currentVal = select.value;
            select.innerHTML = '<option value="me">أنا (المستخدم الحالي)</option><option value="" disabled>-- أو اختر من قائمة الموظفين --</option>';
            data.officers.filter(o => o.is_active).forEach(o => {
                const opt = document.createElement('option');
                opt.value = o.id;
                opt.textContent = o.name + (o.role === 'admin' ? ' (مشرف)' : '');
                select.appendChild(opt);
            });
            if (currentVal) select.value = currentVal;
        }
    } catch(e) {}
}

async function submitNewSimpleAppointment(e) {
    e.preventDefault();

    let requestedById = document.getElementById('simpleRequestedBy').value;
    if (requestedById === 'me' && currentUser) {
        requestedById = currentUser.id;
    } else if (!requestedById) {
        requestedById = null;
    }

    const payload = {
        case_number: document.getElementById('simpleCaseNumber').value.trim(),
        visitor_name: document.getElementById('simpleVisitorName').value.trim(),
        phone: document.getElementById('simplePhone').value.trim(),
        appointment_date: document.getElementById('simpleDate').value,
        appointment_time: document.getElementById('simpleTime').value,
        status: document.getElementById('simpleStatus').value,
        notes: document.getElementById('simpleNotes').value.trim(),
        requested_by_id: requestedById,
        parent_appointment_id: document.getElementById('parentAppointmentId').value || null
    };

    try {
        const res = await fetch('/api/v1/mat/simple-appointments', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const data = await res.json();
        if (res.ok && data.success) {
            closeModal('modalNewSimpleAppointment');
            showToast('تم حفظ الموعد بنجاح!');
            loadSimpleAppointments();
            loadSimpleDashboard();
        } else {
            showToast(data.error || 'حدث خطأ أثناء حفظ الموعد', true);
        }
    } catch (err) {
        showToast('تعذر الاتصال بالخادم المحلي', true);
    }
}

async function updateSimpleAppointmentStatus(apptId, newStatus) {
    try {
        let notes = prompt(`تحديث حالة الموعد إلى: ${newStatus}\nالرجاء إدخال تفاصيل الإجراء أو الملاحظات (اختياري):`);
        if (notes === null) return; // User cancelled

        let bodyData = { status: newStatus };
        if (notes.trim()) {
            bodyData.notes = notes.trim();
        }

        const res = await fetch(`/api/v1/mat/simple-appointments/${apptId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(bodyData)
        });

        if (res.ok) {
            showToast(`تم تحديث حالة الموعد إلى (${newStatus})`);
            loadSimpleDashboard();
        } else {
            showToast('فشل تحديث حالة الموعد', true);
        }
    } catch (e) {
        showToast('تعذر الاتصال بالخادم', true);
    }
}

async function deleteSimpleAppointment(apptId) {
    if (!confirm('هل أنت تأكد من رغبتك بحذف هذا الموعد؟')) return;

    try {
        const res = await fetch(`/api/v1/mat/simple-appointments/${apptId}`, {
            method: 'DELETE'
        });

        if (res.ok) {
            showToast('تم حذف الموعد بنجاح');
            loadSimpleAppointments();
            loadSimpleDashboard();
        } else {
            showToast('فشل حذف الموعد', true);
        }
    } catch (e) {
        showToast('تعذر الاتصال بالخادم', true);
    }
}

// ── DAILY VIEW (CARDS) ──────────────────────────────────────

async function loadDailyView() {
    const container = document.getElementById('dailyCardsContainer');
    const datePicker = document.getElementById('dailyViewDatePicker');
    
    if (!container || !datePicker) return;

    if (!datePicker.value) {
        const todayStr = new Date().toISOString().split('T')[0];
        datePicker.value = todayStr;
    }

    const selectedDate = datePicker.value;
    container.innerHTML = '<div class="text-center p-3" style="grid-column: 1 / -1;"><div class="spinner spinner-dark"></div> جاري تحميل مواعيد اليوم...</div>';

    try {
        const res = await fetch(`/api/v1/mat/simple-appointments?from=${encodeURIComponent(selectedDate)}&to=${encodeURIComponent(selectedDate)}`);
        if (!res.ok) return;
        const data = await res.json();

        if (!data.appointments || data.appointments.length === 0) {
            container.innerHTML = `
                <div class="empty-state" style="grid-column: 1 / -1;">
                    <div class="empty-icon">🏖️</div>
                    <p>لا توجد مواعيد مسجلة في هذا اليوم.</p>
                </div>`;
            return;
        }

        let html = '';
        data.appointments.forEach(a => {
            const maskClass = getApptMaskClass(a.status, a.appointment_date, a.appointment_time, !!(a.parent_info || a.parent_appointment_id));
            html += `
                <div class="appointment-card ${maskClass}" style="cursor:pointer;" onclick="openAppointmentDetail(${a.id})">
                    <div class="app-card-header">
                        <span class="app-case-number">📄 ${a.case_number}</span>
                        <span class="app-time-badge">⏱️ ${a.appointment_time}</span>
                    </div>
                    <div class="app-card-body">
                        <p><strong>اسم المراجع:</strong> ${a.visitor_name}</p>
                        <p><strong>رقم الهاتف:</strong> <a href="tel:${a.phone}" style="color:var(--primary);" onclick="event.stopPropagation()">${a.phone || '—'}</a></p>
                        <p><strong>طالب الاتصال:</strong> ${a.requested_by_name || 'غير محدد'}</p>
                        <p><strong>بواسطة:</strong> ${a.created_by_name || 'غير محدد'}</p>
                        <p><strong>الحالة:</strong> <span class="badge ${getSimpleBadgeClass(a.status)}">${a.status}</span></p>
                    </div>
                    <div class="app-card-actions" onclick="event.stopPropagation()">
                        <button class="btn btn-outline btn-sm flex-1" onclick="updateSimpleAppointmentStatus(${a.id}, 'تم الحضور'); loadDailyView();">✅ حضور</button>
                        <button class="btn btn-outline btn-sm flex-1" onclick="updateSimpleAppointmentStatus(${a.id}, 'لم يحضر'); loadDailyView();">❌ لم يحضر</button>
                    </div>
                </div>
            `;
        });
        
        container.innerHTML = html;
    } catch (e) {
        console.error('Error loading daily view:', e);
        container.innerHTML = '<div class="text-danger text-center p-3" style="grid-column: 1 / -1;">حدث خطأ أثناء تحميل البيانات.</div>';
    }
}

// ── DASHBOARD SUMMARY ───────────────────────────────────────

async function loadSimpleDashboard() {
    try {
        const filterEl = document.getElementById('dashboardTimeFilter');
        const filter = filterEl ? filterEl.value : 'today';

        // 1. Instantly update card labels, badges & footers on UI interaction
        let filterLabel = 'اليوم';
        let filterFooter = 'إجمالي مواعيد اليوم';
        let postponedBadgeText = 'اليوم';
        let postponedFooterText = 'مواعيد تم تأجيلها لليوم';
        let noShowBadgeText = 'اليوم';
        let noShowFooterText = 'تخلف المراجعين عن الحضور لليوم';

        if (filter === 'week') {
            filterLabel = 'هذا الأسبوع';
            filterFooter = 'إجمالي مواعيد هذا الأسبوع';
            postponedBadgeText = 'هذا الأسبوع';
            postponedFooterText = 'مواعيد تم تأجيلها هذا الأسبوع';
            noShowBadgeText = 'هذا الأسبوع';
            noShowFooterText = 'تخلف المراجعين عن الحضور هذا الأسبوع';
        } else if (filter === 'month') {
            filterLabel = 'هذا الشهر';
            filterFooter = 'إجمالي مواعيد هذا الشهر';
            postponedBadgeText = 'هذا الشهر';
            postponedFooterText = 'مواعيد تم تأجيلها هذا الشهر';
            noShowBadgeText = 'هذا الشهر';
            noShowFooterText = 'تخلف المراجعين عن الحضور هذا الشهر';
        } else if (filter === 'all') {
            filterLabel = 'كل الوقت';
            filterFooter = 'إجمالي المواعيد المسجلة بالكامل';
            postponedBadgeText = 'كل الوقت';
            postponedFooterText = 'إجمالي المواعيد المؤجلة كلياً';
            noShowBadgeText = 'كل الوقت';
            noShowFooterText = 'إجمالي الحالات المتخلفة عن الحضور كلياً';
        }

        if (document.getElementById('statPeriodBadge'))
            document.getElementById('statPeriodBadge').textContent = filterLabel;
        if (document.getElementById('statPeriodFooterText'))
            document.getElementById('statPeriodFooterText').textContent = filterFooter;

        if (document.getElementById('statPeriodBadgePostponed'))
            document.getElementById('statPeriodBadgePostponed').textContent = postponedBadgeText;
        if (document.getElementById('statPeriodFooterTextPostponed'))
            document.getElementById('statPeriodFooterTextPostponed').textContent = postponedFooterText;

        if (document.getElementById('statPeriodBadgeNoShow'))
            document.getElementById('statPeriodBadgeNoShow').textContent = noShowBadgeText;
        if (document.getElementById('statPeriodFooterTextNoShow'))
            document.getElementById('statPeriodFooterTextNoShow').textContent = noShowFooterText;

        // 2. Fetch statistics from API
        const res = await fetch(`/api/v1/mat/simple-dashboard?filter=${filter}`);
        if (!res.ok) return;
        const data = await res.json();

        // Check Permissions for Dynamic Dashboard UI Pruning
        const tools = currentUser ? (currentUser.accessible_tools || '') : '';
        const isAdmin = currentUser && currentUser.role === 'admin';
        
        // Stats and Appointments widgets
        const hasAppts = isAdmin || tools.includes('complaints') || (currentUser && currentUser.role === 'caller');
        const statsGrid = document.querySelector('.stats-grid');
        if (statsGrid) statsGrid.style.display = 'grid';
        
        const todayWidget = document.getElementById('dashboardTodaySimpleAppointmentsList')?.closest('.card');
        if (todayWidget) todayWidget.style.display = hasAppts ? 'block' : 'none';
        
        // Reserved Files widget
        const hasFiles = isAdmin || tools.includes('file_reservations') || (currentUser && currentUser.role === 'officer');
        const filesWidget = document.getElementById('dashboardReservedFilesList')?.closest('.card');
        if (filesWidget) filesWidget.style.display = hasFiles ? 'block' : 'none';

        const filteredTotal = data.stats.filtered_total !== undefined ? data.stats.filtered_total : (data.stats.today_appointments || 0);
        const filteredPostponed = data.stats.filtered_postponed !== undefined ? data.stats.filtered_postponed : (data.stats.postponed_today || 0);
        const filteredNoShow = data.stats.filtered_noshow !== undefined ? data.stats.filtered_noshow : (data.stats.noshow_today || 0);

        if (document.getElementById('statFilteredTotalAppts'))
            document.getElementById('statFilteredTotalAppts').textContent = filteredTotal;
        if (document.getElementById('statFilteredPostponedAppts'))
            document.getElementById('statFilteredPostponedAppts').textContent = filteredPostponed;
        if (document.getElementById('statFilteredNoShowAppts'))
            document.getElementById('statFilteredNoShowAppts').textContent = filteredNoShow;

        // Render Reserved Files
        const reservedContainer = document.getElementById('dashboardReservedFilesList');
        if (reservedContainer) {
            if (!data.my_reserved_files || data.my_reserved_files.length === 0) {
                reservedContainer.innerHTML = `<div style="grid-column: 1 / -1; text-align: center; color: var(--text-muted); padding: 20px;">لا يوجد ملفات محجوزة حالياً بعهدتك</div>`;
            } else {
                let html = '';
                data.my_reserved_files.forEach(r => {
                    html += `
                        <div class="smart-card">
                            <div class="smart-card-header">
                                <span class="fw-bold">📄 ${r.file_number}</span>
                            </div>
                            <div style="font-size: 0.9rem; margin-bottom: 0.5rem;">${r.notes || '—'}</div>
                            <div class="text-light" style="font-size: 0.85rem; margin-top: auto;">🕒 ${r.reserved_at}</div>
                        </div>
                    `;
                });
                reservedContainer.innerHTML = html;
            }
        }

        // Render No Answer / Suspended List
        const noAnswerWrapper = document.getElementById('dashboardNoAnswerWrapper');
        const noAnswerContainer = document.getElementById('dashboardNoAnswerList');
        if (noAnswerWrapper && noAnswerContainer) {
            if (!data.no_answer_appointments || data.no_answer_appointments.length === 0) {
                noAnswerWrapper.style.display = 'none';
            } else {
                noAnswerWrapper.style.display = 'block';
                let html = '';
                data.no_answer_appointments.forEach(a => {
                    const maskClass = getApptMaskClass(a.status, a.appointment_date, a.appointment_time, !!(a.parent_info || a.parent_appointment_id));
                    html += `
                        <div class="smart-card ${maskClass}" style="cursor:pointer; border-right: 4px solid #e74c3c;" onclick="openAppointmentDetail(${a.id})">
                            <div class="smart-card-header">
                                <span class="fw-bold text-danger">⏱️ ${a.appointment_time}</span>
                                <span class="badge badge-noanswer">${a.status}</span>
                            </div>
                            <div style="font-size: 0.95rem; font-weight: bold; margin-bottom: 0.25rem;">📄 ${a.case_number}</div>
                            <div style="font-size: 0.85rem; margin-bottom: 0.25rem;">🧑 ${a.visitor_name}</div>
                            <div style="font-size: 0.85rem; margin-bottom: 0.25rem;"><small class="text-light">اتصال: ${a.requested_by_name || '-'} | بواسطة: ${a.created_by_name || '-'}</small></div>
                            <div style="font-size: 0.85rem; margin-bottom: 0.5rem; color:#e74c3c; font-weight:bold;">📱 <a href="tel:${a.phone}" style="color:inherit; text-decoration:none;" onclick="event.stopPropagation()">${a.phone || 'بدون رقم'}</a></div>
                            <div class="smart-card-actions" onclick="event.stopPropagation()">
                                <button class="btn btn-sm flex-1" style="background: var(--accent-secondary); color: white; border: none; width: 100%; padding: 0.5rem;" onclick="quickUpdateSimpleApptStatus(${a.id}, 'تم الحضور')">✅ حضر</button>
                                <button class="btn btn-sm flex-1" style="background: var(--accent-primary); color: white; border: none; width: 100%; padding: 0.5rem;" onclick="quickUpdateSimpleApptStatus(${a.id}, 'مُجدول')">🔄 إعادة جدولة</button>
                            </div>
                        </div>`;
                });
                noAnswerContainer.innerHTML = html;
            }
        }

        // Render Today's Appointments List
        const todayContainer = document.getElementById('dashboardTodaySimpleAppointmentsList');
        if (todayContainer) {
            if (!data.today_appointments || data.today_appointments.length === 0) {
                todayContainer.innerHTML = `<div style="grid-column: 1 / -1; text-align: center; color: var(--text-muted); padding: 20px;">لا يوجد مواعيد مقررة بتاريخ اليوم</div>`;
            } else {
                let html = '';
                data.today_appointments.forEach(a => {
                    let parentBadge = a.parent_info ? `<span class="badge badge-pending" style="font-size:0.7rem; margin-top:3px;">فرع: ${a.parent_info.appointment_date}</span>` : '';
                    const maskClass = getApptMaskClass(a.status, a.appointment_date, a.appointment_time, !!(a.parent_info || a.parent_appointment_id));

                    html += `
                        <div class="smart-card ${maskClass}" style="cursor:pointer;" onclick="openAppointmentDetail(${a.id})">
                            <div class="smart-card-header">
                                <span class="fw-bold text-primary">⏱️ ${a.appointment_time}</span>
                                <span class="badge ${getSimpleBadgeClass(a.status)}">${a.status}</span>
                            </div>
                            <div style="font-size: 0.95rem; font-weight: bold; margin-bottom: 0.25rem;">📄 ${a.case_number}</div>
                            <div style="font-size: 0.85rem; margin-bottom: 0.25rem;">🧑 ${a.visitor_name}</div>
                            <div style="font-size: 0.85rem; margin-bottom: 0.25rem;"><small class="text-light">اتصال: ${a.requested_by_name || '-'} | بواسطة: ${a.created_by_name || '-'}</small></div>
                            <div style="font-size: 0.85rem; margin-bottom: 0.5rem;">📱 ${a.phone || 'بدون رقم'}</div>
                            ${parentBadge}
                            <div class="smart-card-actions" onclick="event.stopPropagation()">
                                <button class="btn btn-sm flex-1" style="background: var(--accent-secondary); color: white; border: none; width: 100%; padding: 0.5rem;" onclick="quickUpdateSimpleApptStatus(${a.id}, 'تم الحضور')">✅ حضر</button>
                                <button class="btn btn-sm flex-1" style="background: var(--accent-warning); color: white; border: none; width: 100%; padding: 0.5rem;" onclick="quickUpdateSimpleApptStatus(${a.id}, 'لم يحضر')">❌ لم يحضر</button>
                            </div>
                        </div>`;
                });
                todayContainer.innerHTML = html;
            }
        }

        // Render Top Searched Areas List
        const areasContainer = document.getElementById('topSearchedAreasContainer');
        if (areasContainer) {
            if (!data.top_searched_areas || data.top_searched_areas.length === 0) {
                areasContainer.innerHTML = `
                    <div style="text-align: center; color: var(--text-muted); padding: 20px; width: 100%;">
                        <div style="font-size: 2rem;">📍</div>
                        <p>لا يوجد بيانات بحث مسجلة حتى الآن.</p>
                    </div>`;
            } else {
                let html = '';
                data.top_searched_areas.forEach(item => {
                    html += `
                        <div class="area-card">
                            <div class="area-card-header">
                                <strong class="text-primary" style="font-size:1rem;">🏙️ ${item.area_name}</strong>
                                <span class="badge badge-scheduled" style="font-size:0.75rem;">🔍 ${item.search_count} بحث</span>
                            </div>
                            <div class="area-card-body" style="margin-top: 8px;">
                                <div style="display:flex; justify-content:space-between; align-items:center; font-size: 0.9rem;">
                                    <span class="fw-bold">🚔 ${item.closest_station}</span>
                                    <span class="text-light" style="font-size:0.8rem; opacity:0.8;">🏛️ ${item.directorate}</span>
                                </div>
                            </div>
                        </div>`;
                });
                areasContainer.innerHTML = html;
            }
        }

    } catch (e) {
        console.error('Error loading dashboard:', e);
    }
}


async function quickUpdateSimpleApptStatus(id, newStatus) {
    let notes = prompt(`هل أنت متأكد من تحديث حالة الموعد إلى: ${newStatus}؟\nيمكنك إدخال ملاحظات أو تفاصيل الإجراء هنا (اختياري):`);
    if (notes === null) return;

    let bodyData = { status: newStatus };
    if (notes.trim()) bodyData.notes = notes.trim();

    try {
        const res = await fetch('/api/v1/mat/simple-appointments/' + id, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(bodyData)
        });
        if (res.ok) {
            loadSimpleDashboard();
            if (typeof loadSimpleAppointments === 'function') {
                loadSimpleAppointments();
            }
        }
    } catch (e) {
        console.error('Error updating status:', e);
    }
}

function getSimpleBadgeClass(status) {
    switch (status) {
        case 'تم الحضور': return 'badge-green';
        case 'مُجدول': return 'badge-blue';
        case 'مُؤجل': return 'badge-purple';
        case 'لم يحضر': return 'badge-red';
        case 'لم يجيبوا': return 'badge-noanswer';
        case 'ملغى': return 'badge-yellow';
        default: return 'badge-blue';
    }
}

function getRowStatusClass(status) {
    switch (status) {
        case 'تم الحضور': return 'row-completed';
        case 'مُؤجل': return 'row-postponed';
        case 'لم يحضر': return 'row-cancelled';
        case 'لم يجيبوا': return 'row-noanswer';
        case 'ملغى': return 'row-postponed';
        default: return '';
    }
}

function isApptPast(apptDateStr, apptTimeStr) {
    if (!apptDateStr) return false;
    const now = new Date();
    
    let year, month, day;
    if (apptDateStr.includes('T')) {
        const d = new Date(apptDateStr);
        year = d.getFullYear();
        month = d.getMonth() + 1;
        day = d.getDate();
    } else {
        const parts = apptDateStr.split('-');
        year = parseInt(parts[0], 10);
        month = parseInt(parts[1], 10);
        day = parseInt(parts[2], 10);
    }
    
    let hours = 23, minutes = 59;
    if (apptTimeStr && apptTimeStr.includes(':')) {
        const tParts = apptTimeStr.split(':');
        hours = parseInt(tParts[0], 10);
        minutes = parseInt(tParts[1], 10);
    }
    
    const apptDate = new Date(year, month - 1, day, hours, minutes, 0, 0);
    return apptDate < now;
}

function getApptMaskClass(status, apptDateStr, apptTimeStr) {
    const isPast = isApptPast(apptDateStr, apptTimeStr);
    
    if (status === 'مُؤجل') {
        return 'card-masked status-postponed-masked';
    } else if (status === 'تم الحضور') {
        return 'card-masked status-attended-masked';
    } else if (status === 'لم يحضر') {
        return 'card-masked status-noshow-masked';
    } else if (status === 'لم يجيبوا') {
        return 'card-masked status-noanswer-masked';
    } else if (status === 'ملغى') {
        return 'card-masked status-cancelled-masked';
    } else if (status === 'مُجدول') {
        if (!isPast) {
            // Scheduled AND after current time -> EXCEPT for scheduled appointments after current time (NO MASK)
            return 'status-scheduled-upcoming';
        } else {
            // Scheduled BUT past current time -> Masked with past/overdue shade
            return 'card-masked status-scheduled-past';
        }
    }
    return 'card-masked';
}

// ── NOTIFICATIONS ───────────────────────────────────────────
let notifiedAppointments = new Set();
let notifiedOverdueAppointments = new Set();

function startNotificationsPolling() {
    // Check every 60 seconds
    setInterval(pollUpcomingAppointments, 60000);
    // Initial check
    setTimeout(pollUpcomingAppointments, 2000);
}

async function pollUpcomingAppointments() {
    const todayStr = new Date().toISOString().split('T')[0];
    try {
        const res = await fetch(`/api/v1/mat/simple-appointments?from=${todayStr}&to=${todayStr}`);
        if (!res.ok) return;
        const data = await res.json();
        if (!data.appointments) return;
        
        const now = new Date();
        let upcomingList = [];
        
        // Collect parent appointment IDs to filter out postponed parent records
        const parentIds = new Set(data.appointments.map(x => x.parent_appointment_id).filter(Boolean));
        
        data.appointments.forEach(a => {
            if (a.status !== 'مُجدول') return;
            if (parentIds.has(a.id)) return;
            if (!a.appointment_time) return;
            
            const [hours, minutes] = a.appointment_time.split(':');
            const apptTime = new Date();
            apptTime.setHours(parseInt(hours, 10), parseInt(minutes, 10), 0, 0);
            
            const diffMs = apptTime - now;
            const diffMins = diffMs / 60000;
            
            // ── CHECK 1: Notify if appointment is within next 30 minutes ──
            if (diffMins > 0 && diffMins <= 30 && !notifiedAppointments.has(a.id)) {
                notifiedAppointments.add(a.id);
                showToast(`🔔 موعد قريب: المراجع ${a.visitor_name} في قضية ${a.case_number} خلال ${Math.round(diffMins)} دقيقة.`, false, a.id);
            }

            // ── CHECK 2: Notify & Prompt if appointment time has passed today (Overdue & still 'مُجدول') ──
            if (diffMins <= 0 && diffMins >= -12 * 60 && !notifiedOverdueAppointments.has(a.id)) {
                notifiedOverdueAppointments.add(a.id);
                showToast(`⏰ انقضى وقت الموعد للمراجع (${a.visitor_name}) قضية: ${a.case_number}. يرجى إدخال الملاحظات وتحديث الحالة.`, true, a.id, true);
                openOverdueUpdateModal(a.id);
            }

            // Collect active upcoming appointments for today (-60 mins to +24 hours)
            if (diffMins > -60 && diffMins < 24*60) {
                upcomingList.push({ ...a, diffMins });
            }
        });

        // Deduplicate by visitor_name + case_number to keep only latest active appointment
        const activeMap = new Map();
        upcomingList.forEach(item => {
            const key = `${item.case_number}_${item.visitor_name}`;
            if (!activeMap.has(key) || activeMap.get(key).id < item.id) {
                activeMap.set(key, item);
            }
        });
        upcomingList = Array.from(activeMap.values());

        // Update UI Panel
        const badge = document.getElementById('notificationBadge');
        const listContainer = document.getElementById('notificationList');
        
        if (badge && listContainer) {
            if (upcomingList.length > 0) {
                badge.textContent = upcomingList.length;
                badge.style.display = 'inline-block';
                
                let html = '';
                upcomingList.sort((a,b) => a.diffMins - b.diffMins).forEach(a => {
                    let timeText = a.diffMins > 0 ? `بعد ${Math.round(a.diffMins)} دقيقة` : `قبل ${Math.abs(Math.round(a.diffMins))} دقيقة`;
                    if (a.diffMins > 60) timeText = `الساعة ${a.appointment_time}`;
                    
                    html += `
                        <div style="padding: 10px; border-bottom: 1px solid #eee; cursor: pointer; transition: background 0.2s;" 
                             onclick="openAppointmentDetail(${a.id}); toggleNotificationPanel();" 
                             onmouseover="this.style.background='#f1f5f9'" 
                             onmouseout="this.style.background='transparent'">
                            <div style="font-weight: bold; font-size: 0.9rem; color:#0f172a;">${a.visitor_name}</div>
                            <div style="font-size: 0.8rem; color: var(--text-secondary);">قضية: ${a.case_number}</div>
                            <div style="font-size: 0.75rem; color: var(--accent-primary); margin-top: 4px; font-weight: 700;">⏱️ ${timeText} | 📋 معاينة التفاصيل</div>
                        </div>
                    `;
                });
                listContainer.innerHTML = html;
            } else {
                badge.style.display = 'none';
                listContainer.innerHTML = '<div style="padding: 1rem; text-align: center; color: var(--text-muted); font-size: 0.9rem;">لا توجد مواعيد مجدولة قريبة</div>';
            }
        }
    } catch (e) {
        console.error('Notifications poll failed', e);
    }
}

function toggleNotificationPanel() {
    const panel = document.getElementById('notificationPanel');
    if (panel) {
        panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
    }
}

// Close notification panel when clicking outside
document.addEventListener('click', (e) => {
    const panel = document.getElementById('notificationPanel');
    const btn = document.getElementById('notificationToggleBtn');
    if (panel && btn && !panel.contains(e.target) && !btn.contains(e.target)) {
        panel.style.display = 'none';
    }
});


// ── GLOBAL SEARCH ───────────────────────────────────────────

let searchDebounceTimer;
function handleGlobalSearch(e) {
    clearTimeout(searchDebounceTimer);
    const query = e.target.value.trim();

    if (query.length < 2) {
        closeSearchResults();
        return;
    }

    searchDebounceTimer = setTimeout(() => performSearch(query), 300);
}

function focusSearch() {
    const input = document.getElementById('globalSearchInput');
    if (input) {
        input.focus();
        input.scrollIntoView({ behavior: 'smooth' });
    }
}

async function performSearch(query) {
    const container = document.getElementById('searchResultsContainer');
    const body = document.getElementById('searchResultsBody');
    if (!container || !body) return;

    body.innerHTML = '<div class="text-center p-4"><div class="spinner spinner-dark mb-2"></div><br>جاري البحث الشامل في المواعيد، الملفات المحجوزة، الملاحظات، والمناطق...</div>';
    container.classList.add('active');
    container.style.display = 'block';

    try {
        const res = await fetch(`/api/v1/mat/search?q=${encodeURIComponent(query)}`);
        if (!res.ok) return;
        const data = await res.json();

        const hasAppts = data.simple_appointments && data.simple_appointments.length > 0;
        const hasFiles = data.files && data.files.length > 0;
        const hasLocations = data.locations && data.locations.length > 0;
        const hasPersons = data.persons && data.persons.length > 0;
        const hasComplaints = data.complaints && data.complaints.length > 0;

        if (!hasAppts && !hasFiles && !hasLocations && !hasPersons && !hasComplaints) {
            body.innerHTML = `<div class="empty-state p-4 text-center"><div class="empty-icon" style="font-size: 2rem;">🔍</div><p>لم يتم العثور على أي نتائج مطابقة لـ: "<strong>${query}</strong>"</p></div>`;
            return;
        }

        let html = '<div class="search-results-content" style="display: flex; flex-direction: column; gap: 20px; text-align: right;">';

        // 1. Simple Appointments & Visits
        if (hasAppts) {
            html += `
                <div class="search-section">
                    <h4 style="color: var(--primary-color); border-bottom: 2px solid var(--primary-color); padding-bottom: 6px; margin-bottom: 10px; display: flex; align-items: center; gap: 8px;">
                        📅 جدول المواعيد والزيارات (${data.simple_appointments.length})
                    </h4>
                    <div class="table-wrapper">
                        <table>
                            <thead>
                                <tr>
                                    <th>رقم القضية / الصادر</th>
                                    <th>اسم المراجع</th>
                                    <th>الهاتف / الهوية</th>
                                    <th>التاريخ والوقت</th>
                                    <th>المركز / الملاحظات</th>
                                    <th>الحالة</th>
                                </tr>
                            </thead>
                            <tbody>`;
            data.simple_appointments.forEach(a => {
                const maskClass = getApptMaskClass(a.status, a.appointment_date, a.appointment_time, !!(a.parent_info || a.parent_appointment_id));
                html += `
                    <tr class="${maskClass}" style="cursor:pointer;" onclick="closeSearchResults(); openAppointmentDetail(${a.id});">
                        <td><strong class="text-primary">📄 ${a.case_number}</strong></td>
                        <td><strong>${a.visitor_name}</strong></td>
                        <td>${a.phone || a.national_id || '—'}</td>
                        <td>📅 ${a.appointment_date} <small>(${a.appointment_time || ''})</small></td>
                        <td>${a.station_name || 'قسم المواعيد'} ${a.notes ? `| <small class="text-muted">${a.notes}</small>` : ''}</td>
                        <td><span class="badge ${getSimpleBadgeClass ? getSimpleBadgeClass(a.status) : 'badge-scheduled'}">${a.status}</span></td>
                    </tr>`;
            });
            html += `</tbody></table></div></div>`;
        }

        // 2. Reserved Files (نظام الملفات)
        if (hasFiles) {
            html += `
                <div class="search-section">
                    <h4 style="color: #e67e22; border-bottom: 2px solid #e67e22; padding-bottom: 6px; margin-bottom: 10px; display: flex; align-items: center; gap: 8px;">
                        🔒 الملفات المحجوزة والعهدة (${data.files.length})
                    </h4>
                    <div class="table-wrapper">
                        <table>
                            <thead>
                                <tr>
                                    <th>رقم الملف</th>
                                    <th>حامل العهدة الحالي</th>
                                    <th>تاريخ الحجز</th>
                                    <th>ملاحظات الملف</th>
                                </tr>
                            </thead>
                            <tbody>`;
            data.files.forEach(f => {
                html += `
                    <tr>
                        <td><strong class="text-primary" style="font-size: 1.1rem;">📄 ${f.file_number}</strong></td>
                        <td><strong>👤 ${f.officer_name}</strong></td>
                        <td><small>${f.reserved_at}</small></td>
                        <td>${f.notes || '—'}</td>
                    </tr>`;
            });
            html += `</tbody></table></div></div>`;
        }

        // 3. Map Locations & Stations (دليل الخريطة والمناطق)
        if (hasLocations) {
            html += `
                <div class="search-section">
                    <h4 style="color: #27ae60; border-bottom: 2px solid #27ae60; padding-bottom: 6px; margin-bottom: 10px; display: flex; align-items: center; gap: 8px;">
                        🗺️ المناطق والمراكز الأمنية (${data.locations.length})
                    </h4>
                    <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px;">`;
            data.locations.forEach(loc => {
                html += `
                    <div style="background: var(--bg-secondary); padding: 12px; border-radius: 8px; border: 1px solid var(--border-color);">
                        <div style="font-weight: bold; color: var(--primary-color); font-size: 1.05rem;">📍 ${loc.name}</div>
                        <div style="font-size: 0.88rem; margin-top: 4px;"><strong>المركز الأمني الأقرب:</strong> ${loc.closest}</div>
                        <div style="font-size: 0.82rem; color: var(--text-light); margin-top: 2px;">${loc.directorate} (${loc.liwa})</div>
                    </div>`;
            });
            html += `</div></div>`;
        }

        // 4. Persons & Parties (أطراف المراجعين)
        if (hasPersons) {
            html += `
                <div class="search-section">
                    <h4 style="color: #2980b9; border-bottom: 2px solid #2980b9; padding-bottom: 6px; margin-bottom: 10px; display: flex; align-items: center; gap: 8px;">
                        👥 مراجعين وأطراف قضايا مسجلين (${data.persons.length})
                    </h4>
                    <div style="display: flex; flex-direction: column; gap: 8px;">`;
            data.persons.forEach(p => {
                html += `
                    <div style="background: var(--bg-secondary); padding: 10px 14px; border-radius: 6px; border-left: 4px solid #2980b9;">
                        <strong>👤 ${p.name}</strong> - 📞 ${p.phone || 'بدون رقم'} ${p.national_id ? `| 🆔 ${p.national_id}` : ''}
                        <div style="font-size: 0.85rem; color: var(--text-light); margin-top: 4px;">مرتبط بـ ${p.complaints ? p.complaints.length : 0} قضايا/شكاوى</div>
                    </div>`;
            });
            html += `</div></div>`;
        }

        // 5. Complaints (الشكاوى الرئيسية)
        if (hasComplaints) {
            html += `
                <div class="search-section">
                    <h4 style="color: #8e44ad; border-bottom: 2px solid #8e44ad; padding-bottom: 6px; margin-bottom: 10px; display: flex; align-items: center; gap: 8px;">
                        📋 الشكاوى والمحاضر الرئيسية (${data.complaints.length})
                    </h4>
                    <div class="table-wrapper">
                        <table>
                            <thead>
                                <tr>
                                    <th>رقم الشكوى</th>
                                    <th>الموضوع</th>
                                    <th>الضابط المتابع</th>
                                    <th>الحالة</th>
                                </tr>
                            </thead>
                            <tbody>`;
            data.complaints.forEach(c => {
                html += `
                    <tr>
                        <td><strong>${c.complaint_number}</strong></td>
                        <td>${c.subject}</td>
                        <td>${c.officer_name || 'غير محدد'}</td>
                        <td><span class="badge badge-scheduled">${c.status}</span></td>
                    </tr>`;
            });
            html += `</tbody></table></div></div>`;
        }

        html += '</div>';
        body.innerHTML = html;

    } catch (e) {
        console.error('Error searching:', e);
        body.innerHTML = '<div class="text-danger text-center p-3">حدث خطأ أثناء البحث.</div>';
    }
}

function closeSearchResults() {
    const container = document.getElementById('searchResultsContainer');
    const input = document.getElementById('globalSearchInput');
    if (container) {
        container.classList.remove('active');
        container.style.display = 'none';
    }
    if (input) input.value = '';
}

// ── OFFICERS MANAGEMENT (ADMIN) ─────────────────────────────
async function loadOfficersTable() {
    if (currentUser?.role !== 'admin') return;

    const tbody = document.getElementById('officersTableBody');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="6" class="text-center"><div class="spinner spinner-dark"></div> جاري التحميل...</td></tr>';

    try {
        const res = await fetch('/api/v1/mat/officers');
        if (!res.ok) return;
        const data = await res.json();

        let html = '';
        data.officers.forEach(o => {
            const roleLabels = { 'admin': 'مشرف (صلاحيات كاملة)', 'officer': 'مستخدم / ضابط مواعيد', 'caller': 'ضابط اتصالات' };
            let roleTitle = roleLabels[o.role] || o.role;
            if (o.username === 'orwa') {
                roleTitle = 'رئيس قسم الشكاوي';
            }
            html += `
                <tr>
                    <td><span class="fw-bold">${o.name}</span></td>
                    <td><code>${o.username}</code></td>
                    <td><span class="badge badge-scheduled">${roleTitle}</span></td>
                    <td><small>${(o.accessible_tools || '').split(',').map(t => {
                        const toolNamesMap = { 'dashboard': 'لوحة التحكم', 'complaints': 'نظام المواعيد', 'finder': 'دليل المراكز', 'file_reservations': 'أداة حجز الملفات', 'chat': 'غرفة الاجتماعات' };
                        return toolNamesMap[t.trim()] || t.trim();
                    }).join('، ')}</small></td>
                    <td><span class="badge ${o.is_active ? 'badge-completed' : 'badge-cancelled'}">${o.is_active ? 'فعال' : 'معطل'}</span></td>
                    <td>
                        <button class="btn btn-ghost btn-sm" onclick="toggleOfficerActive(${o.id}, ${o.is_active ? 0 : 1})">
                            ${o.is_active ? 'تعطيل' : 'تفعيل'}
                        </button>
                    </td>
                </tr>`;
        });

        tbody.innerHTML = html;

    } catch (e) {
        console.error('Error loading officers table:', e);
    }
}

function openNewOfficerModal() {
    const form = document.getElementById('formNewOfficer');
    if (form) form.reset();
    openModal('modalNewOfficer');
}

async function submitNewOfficer(e) {
    e.preventDefault();

    const checkedTools = Array.from(document.querySelectorAll('input[name="accessible_tool"]:checked')).map(cb => cb.value);

    const payload = {
        name: document.getElementById('officerName').value.trim(),
        username: document.getElementById('officerUsername').value.trim(),
        password: document.getElementById('officerPassword').value,
        role: document.getElementById('officerRole').value,
        accessible_tools: checkedTools.join(',')
    };

    try {
        const res = await fetch('/api/v1/mat/officers', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const data = await res.json();
        if (res.ok && data.success) {
            closeModal('modalNewOfficer');
            showToast('تم إنشاء حساب المستخدم بنجاح!');
            loadOfficersTable();
        } else {
            showToast(data.error || 'فشل إنشاء الحساب', true);
        }
    } catch (err) {
        showToast('تعذر الاتصال بالخادم', true);
    }
}

async function toggleOfficerActive(officerId, newActiveStatus) {
    try {
        const res = await fetch(`/api/v1/mat/officers/${officerId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_active: newActiveStatus })
        });

        if (res.ok) {
            showToast('تم تغيير حالة المستخدم بنجاح');
            loadOfficersTable();
        } else {
            showToast('فشل تعديل حالة المستخدم', true);
        }
    } catch (e) {
        showToast('تعذر الاتصال بالخادم', true);
    }
}

function branchAppointment(apptId) {
    if(!window.currentAppointmentsData) return;
    const appt = window.currentAppointmentsData.find(a => a.id === apptId);
    if(appt) {
        openNewSimpleAppointmentModal(appt);
        showToast('تم تجهيز البيانات، الرجاء تحديد موعد الفرع الجديد');
    }
}

function toggleAccessibleTools() {
    const role = document.getElementById('officerRole').value;
    const toolsGroup = document.getElementById('accessibleToolsGroup');
    if(role === 'admin') {
        Array.from(toolsGroup.querySelectorAll('input')).forEach(cb => cb.checked = true);
    }
}

// ── LIVE CHAT (POLLING) ──────────────────────────────────────

let chatPollActive = false;
let lastMessageId = 0;
let onlineUsersInterval = null;
let currentPollController = null;

async function toggleChatPane(forceOpen = false) {
    if (currentUser && currentUser.role !== 'admin' && !(currentUser.accessible_tools || '').includes('chat')) {
        showToast('ليس لديك صلاحية الوصول لغرفة الاجتماعات (المحادثة)', true);
        return;
    }
    const pane = document.getElementById('chatPane');
    if (!pane) return;
    
    if (typeof closeSidebarDrawer === 'function') {
        closeSidebarDrawer();
    }
    
    if (forceOpen === true) {
        pane.classList.add('show');
    } else {
        pane.classList.toggle('show');
    }
    
    const isShown = pane.classList.contains('show');
    
    if (isShown) {
        chatPollActive = true;
        loadOnlineUsers(true);
        await loadInitialChatMessages();
        pollChatMessages();
        if (!onlineUsersInterval) {
            onlineUsersInterval = setInterval(() => loadOnlineUsers(true), 15000); // Poll active chat users every 15s
        }
        setTimeout(() => {
            const chatInput = document.getElementById('chatInput');
            if (chatInput) chatInput.focus();
            const container = document.getElementById('chatMessages');
            if (container) container.scrollTop = container.scrollHeight;
        }, 150);
    } else {
        chatPollActive = false;
        if (currentPollController) {
            currentPollController.abort();
            currentPollController = null;
        }
        if (onlineUsersInterval) {
            clearInterval(onlineUsersInterval);
            onlineUsersInterval = null;
        }
        loadOnlineUsers(false);
    }
}

async function loadOnlineUsers(isChatActive = false) {
    try {
        const isActive = isChatActive || chatPollActive;
        const res = await fetch('/api/v1/mat/chat/online_users' + (isActive ? '?chat_active=1' : ''));
        if (!res.ok) return;
        const data = await res.json();
        const activeCount = data.online_users ? data.online_users.length : 0;

        // Update sidebar chat pane count
        const countSpan = document.getElementById('onlineUsersCount');
        if (countSpan) countSpan.textContent = activeCount;

        // Update top-bar meeting room count badge
        const topCount = document.getElementById('chatActiveUsersCountTop');
        if (topCount) topCount.textContent = activeCount;

        // Update active users list container inside meeting room
        const listContainer = document.getElementById('onlineUsersList');
        if (listContainer) {
            if (activeCount === 0) {
                listContainer.innerHTML = '<span style="color:var(--text-muted); font-size:0.75rem;">لا يوجد متواجدون حالياً بالغرفة</span>';
            } else {
                listContainer.innerHTML = data.online_users.map(u =>
                    `<span title="${u.role}" style="display:inline-flex; align-items:center; gap:4px; padding:2px 8px; background:rgba(34,197,94,0.1); color:#15803d; border-radius:12px; font-size:0.75rem; font-weight:600;">🟢 ${u.name} ${u.name === currentUser?.name ? '(أنت)' : ''}</span>`
                ).join(' ');
            }
        }
    } catch (e) {
        console.error('Error loading active chat users:', e);
    }
}

let currentChatDate = new Date().toISOString().split('T')[0];
let currentSelectedArchiveDate = null;
let currentArchivedMessages = [];

async function loadInitialChatMessages() {
    try {
        const todayStr = new Date().toISOString().split('T')[0];
        if (currentChatDate !== todayStr) {
            currentChatDate = todayStr;
            lastMessageId = 0;
        }
        
        const res = await fetch('/api/v1/mat/chat/messages');
        if (!res.ok) return;
        const data = await res.json();
        
        const container = document.getElementById('chatMessages');
        if (!container) return;
        
        lastMessageId = 0;
        let html = `
            <div class="chat-bubble system" style="text-align:center; font-size:0.75rem; background:rgba(30,58,138,0.06); color:var(--primary); padding:6px 12px; margin-bottom:10px;">
                🧹 المحادثة الفورية لليوم (${todayStr}). الرسائل السابقة محفوظة في الأرشيف.
            </div>
        `;
        
        // Filter messages to ONLY keep today's messages in active chat
        const todayMessages = (data.messages || []).filter(m => {
            if (!m.created_at) return false;
            const msgDate = m.created_at.split('T')[0].split(' ')[0];
            return msgDate === todayStr;
        });
        
        if (todayMessages.length > 0) {
            todayMessages.forEach(m => {
                const isSelf = currentUser && m.user_name === currentUser.name;
                const timeStr = new Date(m.created_at).toLocaleTimeString('ar-JO', {hour: '2-digit', minute:'2-digit'});
                
                html += `
                    <div class="chat-bubble ${isSelf ? 'self' : ''}" data-id="${m.id}">
                        <div style="font-size: 0.75rem; opacity: 0.7; margin-bottom: 2px;">${m.user_name} - ${timeStr}</div>
                        <div class="text">${m.message}</div>
                    </div>
                `;
                if (m.id > lastMessageId) lastMessageId = m.id;
            });
        } else {
            html += `<div id="chatEmptyPlaceholder" style="text-align:center; color:var(--text-muted); font-size:0.8rem; padding:1rem 0;">لا توجد رسائل مسجلة اليوم بعد. ابدأ المحادثة!</div>`;
        }
        
        container.innerHTML = html;
        container.scrollTop = container.scrollHeight;
    } catch (e) {
        console.error('Error loading initial chat messages:', e);
    }
}

async function pollChatMessages() {
    if (!chatPollActive) return;
    currentPollController = new AbortController();
    try {
        const res = await fetch(`/api/v1/mat/chat/poll?last_id=${lastMessageId}`, {
            signal: currentPollController.signal
        });
        if (res.ok) {
            const data = await res.json();
            if (data.messages && data.messages.length > 0) {
                appendChatMessages(data.messages);
            }
        }
    } catch (e) {
        if (e.name !== 'AbortError') {
            console.error('Chat polling error:', e);
            await new Promise(r => setTimeout(r, 5000));
        }
    }
    if (chatPollActive) {
        pollChatMessages();
    }
}

function appendChatMessages(messages) {
    const container = document.getElementById('chatMessages');
    if (!container) return;
    
    const todayStr = new Date().toISOString().split('T')[0];
    const todayMessages = (messages || []).filter(m => {
        if (!m.created_at) return true;
        const msgDate = m.created_at.split('T')[0].split(' ')[0];
        return msgDate === todayStr;
    });

    if (todayMessages.length === 0) return;
    
    const emptyPlaceholder = document.getElementById('chatEmptyPlaceholder');
    if (emptyPlaceholder) {
        emptyPlaceholder.remove();
    }
    
    const isAtBottom = container.scrollHeight - container.scrollTop <= container.clientHeight + 10;
    
    let html = '';
    todayMessages.forEach(m => {
        const isSelf = currentUser && m.user_name === currentUser.name;
        const timeStr = new Date(m.created_at).toLocaleTimeString('ar-JO', {hour: '2-digit', minute:'2-digit'});
        
        html += `
            <div class="chat-bubble ${isSelf ? 'self' : ''}" data-id="${m.id}">
                <div style="font-size: 0.75rem; opacity: 0.7; margin-bottom: 2px;">${m.user_name} - ${timeStr}</div>
                <div class="text">${m.message}</div>
            </div>
        `;
        if (m.id > lastMessageId) lastMessageId = m.id;
    });
    
    container.insertAdjacentHTML('beforeend', html);
    
    if (isAtBottom) {
        container.scrollTop = container.scrollHeight;
    }
}

async function sendChatMessage() {
    const input = document.getElementById('chatInput');
    const msg = input.value.trim();
    if (!msg) return;
    
    input.value = '';
    
    try {
        const res = await fetch('/api/v1/mat/chat/message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: msg })
        });
        
        if (!res.ok) {
            showToast('فشل إرسال الرسالة', true);
        }
    } catch (e) {
        console.error('Error sending chat message:', e);
        showToast('خطأ في الاتصال', true);
    }
}

function handleChatKey(e) {
    if (e.key === 'Enter') {
        sendChatMessage();
    }
}

// ── CHAT ARCHIVE FUNCTIONS ──────────────────────────────────────

async function toggleChatArchiveModal() {
    openModal('modalChatArchive');
    const today = new Date().toISOString().split('T')[0];
    const picker = document.getElementById('chatArchiveDatePicker');
    if (picker && !picker.value) {
        const yesterday = new Date(Date.now() - 86400000).toISOString().split('T')[0];
        picker.value = yesterday;
    }
    await loadChatArchivesList();
    if (picker && picker.value) {
        loadArchivedChatByPicker();
    }
}

async function loadChatArchivesList() {
    const container = document.getElementById('chatArchivesListContainer');
    if (!container) return;
    
    // Generate past 7 days for quick access
    const dates = [];
    for (let i = 1; i <= 7; i++) {
        const d = new Date(Date.now() - i * 86400000);
        dates.push(d.toISOString().split('T')[0]);
    }
    
    container.innerHTML = dates.map(dStr => `
        <button class="btn btn-outline btn-sm" onclick="loadArchivedChatDate('${dStr}')" style="font-size:0.75rem; padding:3px 8px; border-radius:4px; display:flex; align-items:center; gap:4px; background:#ffffff;">
            <span>📅 ${dStr}</span>
        </button>
    `).join('');
}

async function loadArchivedChatByPicker() {
    const picker = document.getElementById('chatArchiveDatePicker');
    if (picker && picker.value) {
        loadArchivedChatDate(picker.value);
    }
}

async function loadArchivedChatDate(dateStr) {
    currentSelectedArchiveDate = dateStr;
    const titleEl = document.getElementById('archiveDateTitle');
    const messagesEl = document.getElementById('archivedChatMessages');
    const picker = document.getElementById('chatArchiveDatePicker');
    
    if (picker) picker.value = dateStr;
    if (titleEl) titleEl.innerHTML = `📜 سجل محادثات يوم: <span style="color:#2563eb;">${dateStr}</span> (مُؤرشف - للقراءة فقط)`;
    if (messagesEl) messagesEl.innerHTML = '<div style="text-align:center; color:#64748b; font-size:0.85rem; padding:2rem 0;">جاري تحميل المحادثات...</div>';
    
    try {
        const res = await fetch(`/api/v1/mat/chat/messages?date=${dateStr}`);
        if (!res.ok) return;
        const data = await res.json();
        
        currentArchivedMessages = data.messages || [];
        
        if (currentArchivedMessages.length === 0) {
            messagesEl.innerHTML = `<div style="text-align:center; color:#64748b; font-size:0.85rem; padding:2rem 0;">لا توجد رسائل مؤرشفة بتاريخ ${dateStr}.</div>`;
            return;
        }
        
        let html = '';
        currentArchivedMessages.forEach(m => {
            const isSelf = currentUser && m.user_name === currentUser.name;
            const timeStr = new Date(m.created_at).toLocaleTimeString('ar-JO', {hour: '2-digit', minute:'2-digit'});
            
            html += `
                <div class="chat-bubble ${isSelf ? 'self' : ''}" style="margin-bottom:8px;">
                    <div style="font-size: 0.75rem; opacity: 0.7; margin-bottom: 2px;">${m.user_name} (${m.user_role || 'مستخدم'}) - ${timeStr}</div>
                    <div class="text">${m.message}</div>
                </div>
            `;
        });
        
        messagesEl.innerHTML = html;
        messagesEl.scrollTop = 0;
    } catch (e) {
        console.error('Error loading archived chat:', e);
    }
}

function exportArchivedChatText() {
    if (!currentArchivedMessages || currentArchivedMessages.length === 0) {
        showToast('لا توجد رسائل معروضة لتصديرها', true);
        return;
    }
    
    let text = `=== أرشيف المحادثة الفورية - تاريخ: ${currentSelectedArchiveDate || 'غير محدد'} ===\n\n`;
    currentArchivedMessages.forEach(m => {
        const timeStr = new Date(m.created_at).toLocaleTimeString('ar-JO');
        text += `[${timeStr}] ${m.user_name} (${m.user_role || 'مستخدم'}): ${m.message}\n`;
    });
    
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `chat_archive_${currentSelectedArchiveDate || 'export'}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast('تم تصدير ملف الأرشيف بنجاح');
}

// --- Modern Interactive Calendar View Logic (Rule 21) ---
let currentCalendarDate = new Date();
let currentMonthAppointments = [];

function changeCalendarMonth(offset) {
    currentCalendarDate.setMonth(currentCalendarDate.getMonth() + offset);
    loadCalendarView();
}

async function loadCalendarView() {
    const year = currentCalendarDate.getFullYear();
    const month = currentCalendarDate.getMonth();
    
    const monthNames = ['يناير','فبراير','مارس','أبريل','مايو','يونيو','يوليو','أغسطس','سبتمبر','أكتوبر','نوفمبر','ديسمبر'];
    document.getElementById('calendarMonthYear').innerText = `${monthNames[month]} ${year}`;
    
    const firstDay = new Date(year, month, 1);
    const lastDay = new Date(year, month + 1, 0);
    
    const fromStr = `${year}-${String(month+1).padStart(2,'0')}-01`;
    const toStr = `${year}-${String(month+1).padStart(2,'0')}-${String(lastDay.getDate()).padStart(2,'0')}`;
    
    try {
        const res = await fetch(`/api/v1/mat/simple-appointments?from=${encodeURIComponent(fromStr)}&to=${encodeURIComponent(toStr)}`);
        const data = res.ok ? await res.json() : { appointments: [] };
        const appts = data.appointments || [];
        
        renderCalendar(year, month, appts);
    } catch (e) {
        console.error(e);
        renderCalendar(year, month, []);
    }
}

function renderCalendar(year, month, appointments) {
    const grid = document.getElementById('calendarGrid');
    grid.innerHTML = '';
    
    const daysOfWeek = ['الأحد','الإثنين','الثلاثاء','الأربعاء','الخميس','الجمعة','السبت'];
    daysOfWeek.forEach(d => {
        const h = document.createElement('div');
        h.className = 'calendar-day-header';
        h.innerText = d;
        grid.appendChild(h);
    });
    
    const firstDay = new Date(year, month, 1);
    const lastDay = new Date(year, month + 1, 0);
    const startingDay = firstDay.getDay(); 
    const monthLength = lastDay.getDate();
    
    let day = 1;
    const today = new Date();
    
    for (let i = 0; i < 42; i++) {
        const cell = document.createElement('div');
        cell.className = 'calendar-day';
        
        if (i >= startingDay && day <= monthLength) {
            const dateStr = `${year}-${String(month+1).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
            
            if (day === today.getDate() && month === today.getMonth() && year === today.getFullYear()) {
                cell.classList.add('today');
            }
            
            const num = document.createElement('div');
            num.className = 'calendar-date-number';
            num.innerText = day;
            cell.appendChild(num);
            
            const dayAppts = appointments.filter(a => a.appointment_date === dateStr);
            dayAppts.sort((a,b) => (a.appointment_time || '').localeCompare(b.appointment_time || ''));
            
            dayAppts.forEach(a => {
                const ac = document.createElement('div');
                const isParent = !!(a.parent_info || a.parent_appointment_id);
                const maskClass = getApptMaskClass(a.status, a.appointment_date, a.appointment_time, isParent);
                ac.className = `calendar-appt-card ${maskClass}`;
                ac.onclick = (e) => {
                    e.stopPropagation();
                    openAppointmentDetail(a.id);
                };
                ac.style.cursor = 'pointer';
                const statusBadge = `<span class="badge ${getSimpleBadgeClass(a.status)}" style="font-size:0.65rem; padding:1px 4px; float:left;">${a.status}</span>`;
                ac.innerHTML = `<strong>${(a.appointment_time||'').substring(0,5)}</strong> ${a.visitor_name} ${statusBadge}`;
                ac.title = `${a.case_number} - ${a.visitor_name} (${a.status}) — انقر لمعاينة التفاصيل`;
                cell.appendChild(ac);
            });
            
            day++;
        } else {
            cell.classList.add('empty');
        }
        grid.appendChild(cell);
        
        if (day > monthLength && i % 7 === 6) {
            break;
        }
    }
}

// ── FILE RESERVATIONS ────────────────────────────────────────

async function loadReservations() {
    const tbody = document.getElementById('myReservationsTableBody');
    const adminCheck = document.getElementById('showAllReservationsCheck');
    const adminLabel = document.getElementById('adminAllReservationsLabel');
    const title = document.getElementById('myReservationsTitle');
    
    if (!tbody) return;
    
    // Check if admin to show checkbox
    if (currentUser && currentUser.role === 'admin') {
        if(adminLabel) adminLabel.style.display = 'flex';
    }
    
    const showAll = adminCheck && adminCheck.checked ? 1 : 0;
    
    if (title) {
        title.innerText = showAll ? '📂 جميع الملفات المحجوزة بالمركز' : '📂 الملفات المحجوزة (في عهدتي)';
    }

    tbody.innerHTML = '<tr><td colspan="5" class="text-center">جاري التحميل...</td></tr>';
    
    // Load Pending Transfers alongside
    loadPendingTransfers();
    
    try {
        const res = await fetch(`/api/v1/mat/reservations?all=${showAll}`);
        if (!res.ok) throw new Error();
        const data = await res.json();
        
        if (!data.reservations || data.reservations.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center text-light" style="padding: 20px;">لا يوجد ملفات محجوزة حالياً.</td></tr>';
            return;
        }
        
        let html = '';
        data.reservations.forEach(r => {
            // Only allow transfer if it's mine or I am admin
            const isMine = r.officer_id === currentUser.user_id;
            const canTransfer = isMine || currentUser.role === 'admin';
            
            html += `
                <tr>
                    <td class="fw-bold text-primary" style="font-size: 1.1rem;">📄 ${r.file_number}</td>
                    <td><strong>${r.officer_name}</strong> ${isMine ? '<span class="badge badge-completed">أنت</span>' : ''}</td>
                    <td><small>${r.reserved_at}</small></td>
                    <td>${r.notes || '—'}</td>
                    <td>
                        ${canTransfer ? `<button class="btn btn-outline btn-sm" onclick="openTransferCustodyModal(${r.id}, '${r.file_number}')">نقل العهدة</button>` : ''}
                        <button class="btn btn-ghost btn-sm" onclick="viewCustodyHistory(${r.id})">🕒 السجل</button>
                        ${canTransfer ? `<button class="btn btn-ghost btn-sm text-danger" onclick="deleteReservation(${r.id})" title="حذف القيد (تسليم للأرشيف)"><span class="material-icons" style="font-size:16px;vertical-align:middle;">حذف</span></button>` : ''}
                    </td>
                </tr>
            `;
        });
        tbody.innerHTML = html;
    } catch (e) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center text-danger">حدث خطأ أثناء تحميل الملفات المحجوزة.</td></tr>';
    }
}

async function loadPendingTransfers() {
    const container = document.getElementById('pendingTransfersContainer');
    if(!container) return;
    
    try {
        const res = await fetch('/api/v1/mat/reservations/pending');
        const data = await res.json();
        let html = '';
        
        if (data.inbound && data.inbound.length > 0) {
            html += '<h5 style="color: var(--primary-color); margin-bottom: 10px;">📥 طلبات مرسلة إليك:</h5>';
            data.inbound.forEach(t => {
                html += `
                    <div class="alert alert-warning mb-2" style="padding: 10px; border-radius: 6px; background: rgba(243, 156, 18, 0.1); border: 1px solid #f39c12;">
                        <strong>📄 ملف رقم: ${t.file_number}</strong><br>
                        <small>محول من: ${t.from_officer_name}</small><br>
                        ${t.notes ? `<small class="text-muted">ملاحظات: ${t.notes}</small><br>` : ''}
                        <div style="margin-top: 10px; display:flex; gap: 5px;">
                            <button class="btn btn-primary btn-sm" onclick="respondToTransfer(${t.log_id}, 'accept')">✅ استلام</button>
                            <button class="btn btn-outline btn-sm text-danger" style="border-color:var(--danger-color);" onclick="respondToTransfer(${t.log_id}, 'reject')">❌ رفض</button>
                        </div>
                    </div>
                `;
            });
        }
        
        if (data.outbound && data.outbound.length > 0) {
            if(html !== '') html += '<hr style="margin: 15px 0;">';
            html += '<h5 style="color: var(--text-color); margin-bottom: 10px;">📤 طلبات أرسلتها (بانتظار الموافقة):</h5>';
            data.outbound.forEach(t => {
                html += `
                    <div class="alert mb-2" style="padding: 10px; border-radius: 6px; background: var(--bg-secondary); border: 1px solid var(--border-color);">
                        <strong>📄 ملف رقم: ${t.file_number}</strong><br>
                        <small>مرسل إلى: ${t.to_officer_name}</small> <span class="badge badge-scheduled">قيد الانتظار</span>
                    </div>
                `;
            });
        }
        
        if(html === '') {
            container.innerHTML = '<div class="text-center text-light" style="padding: 20px;">لا يوجد طلبات معلقة.</div>';
        } else {
            container.innerHTML = html;
        }
    } catch(e) {
        container.innerHTML = '<div class="text-danger text-center">خطأ في جلب الطلبات</div>';
    }
}

async function respondToTransfer(logId, response) {
    const actionText = response === 'accept' ? 'استلام هذا الملف' : 'رفض الاستلام';
    if(!confirm(`هل أنت متأكد من ${actionText}؟`)) return;
    
    try {
        const res = await fetch('/api/v1/mat/reservations/respond', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({log_id: logId, response: response})
        });
        const data = await res.json();
        if(data.success) {
            showToast(response === 'accept' ? 'تم استلام الملف بنجاح' : 'تم رفض الاستلام');
            loadReservations();
        } else {
            showToast(data.error || 'فشل تنفيذ الطلب', true);
        }
    } catch(e) {
        showToast('خطأ بالاتصال', true);
    }
}

async function viewCustodyHistory(reservationId) {
    const timeline = document.getElementById('custodyHistoryTimeline');
    const fnum = document.getElementById('historyFileNumber');
    const cown = document.getElementById('historyCurrentOwner');
    
    if(!timeline) return;
    timeline.innerHTML = 'جاري التحميل...';
    openModal('modalCustodyHistory');
    
    try {
        const res = await fetch(`/api/v1/mat/reservations/history/${reservationId}`);
        const data = await res.json();
        
        if(!res.ok) {
            timeline.innerHTML = `<span class="text-danger">${data.error || 'خطأ'}</span>`;
            return;
        }
        
        fnum.innerText = data.file.file_number;
        cown.innerText = data.file.current_officer_name;
        
        if(!data.history || data.history.length === 0) {
            timeline.innerHTML = 'لا يوجد سجل حركات لهذا الملف.';
            return;
        }
        
        let html = '';
        data.history.forEach(h => {
            let statusIcon = '🔄';
            let statusColor = 'var(--text-color)';
            let completedClass = '';
            
            if(h.status === 'accepted') { 
                statusIcon = '✅'; 
                statusColor = 'var(--success-color)'; 
                completedClass = 'completed';
            } else if(h.status === 'rejected') { 
                statusIcon = '❌'; 
                statusColor = 'var(--danger-color)'; 
            } else if(h.status === 'pending') { 
                statusIcon = '⏳'; 
                statusColor = '#f39c12'; 
            }
            
            html += `
                <div class="timeline-item ${completedClass}">
                    <div class="timeline-item-header">
                        <span>${h.transferred_at}</span>
                        <span style="color: ${statusColor}; font-weight: bold;">${statusIcon} ${h.status === 'accepted'?'تم الاستلام':(h.status==='rejected'?'مرفوض':'بانتظار الموافقة')}</span>
                    </div>
                    <div class="timeline-item-content">
                        <div class="timeline-item-title">
                            ${h.from_officer_name ? `من ${h.from_officer_name} ` : ''}إلى ${h.to_officer_name}
                        </div>
                        ${h.notes ? `<div style="margin-top: 8px; font-size: 0.9rem; color: var(--text-secondary);"><small>📝 ملاحظات: ${h.notes}</small></div>` : ''}
                    </div>
                </div>
            `;
        });
        timeline.innerHTML = html;
        
    } catch(e) {
        timeline.innerHTML = 'خطأ بالاتصال';
    }
}

async function reserveFile(event) {
    event.preventDefault();
    const file_number = document.getElementById('newReservationFileNumber').value;
    const notes = document.getElementById('newReservationNotes').value;
    
    try {
        const res = await fetch('/api/v1/mat/reservations', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({file_number, notes})
        });
        const data = await res.json();
        if (data.error) {
            showToast(data.error, true);
        } else {
            showToast('تم حجز الملف بنجاح!');
            document.getElementById('newReservationFileNumber').value = '';
            document.getElementById('newReservationNotes').value = '';
            loadReservations();
        }
    } catch (e) {
        showToast('حدث خطأ بالاتصال', true);
    }
}

async function searchReservations() {
    const q = document.getElementById('searchReservationInput').value;
    const resultDiv = document.getElementById('reservationSearchResult');
    if (!q) {
        resultDiv.innerHTML = '<span class="text-danger">الرجاء إدخال رقم الملف للبحث.</span>';
        return;
    }
    
    resultDiv.innerHTML = 'جاري البحث...';
    try {
        const res = await fetch(`/api/v1/mat/reservations/search?q=${encodeURIComponent(q)}`);
        const data = await res.json();
        if (data.reservations && data.reservations.length > 0) {
            const r = data.reservations[0];
            resultDiv.innerHTML = `<span class="text-primary">✅ الملف "${r.file_number}" محجوز حالياً لدى: ${r.officer_name} (تاريخ الحجز: ${r.reserved_at})</span>`;
        } else {
            resultDiv.innerHTML = `<span class="text-success">✅ الملف "${q}" غير محجوز ومتاح.</span>`;
        }
    } catch (e) {
        resultDiv.innerHTML = '<span class="text-danger">حدث خطأ أثناء البحث.</span>';
    }
}

async function deleteReservation(id) {
    if (!confirm('هل أنت متأكد من إلغاء حجز هذا الملف؟')) return;
    try {
        const res = await fetch(`/api/v1/mat/reservations/${id}`, { method: 'DELETE' });
        if (res.ok) {
            showToast('تم تحرير الملف بنجاح!');
            loadReservations();
        }
    } catch (e) {
        showToast('حدث خطأ أثناء التحرير', true);
    }
}

async function openTransferCustodyModal(id, fileNumber) {
    document.getElementById('transferReservationId').value = id;
    document.getElementById('transferFileNumber').value = fileNumber;
    document.getElementById('transferNotes').value = '';
    
    // Fetch officers
    const select = document.getElementById('transferToOfficer');
    select.innerHTML = '<option value="">-- جاري التحميل --</option>';
    openModal('modalTransferCustody');
    
    try {
        const res = await fetch('/api/v1/mat/officers');
        if (res.ok) {
            const data = await res.json();
            let opts = '<option value="">-- اختر الضابط --</option>';
            data.officers.forEach(o => {
                if (o.is_active && o.id !== currentUser.user_id) {
                    opts += `<option value="${o.id}">${o.name} (${o.role})</option>`;
                }
            });
            select.innerHTML = opts;
        }
    } catch (e) {
        select.innerHTML = '<option value="">فشل تحميل الضباط</option>';
    }
}

async function submitTransferCustody(event) {
    event.preventDefault();
    const resId = document.getElementById('transferReservationId').value;
    const toOfficerId = document.getElementById('transferToOfficer').value;
    const notes = document.getElementById('transferNotes').value;
    
    try {
        const res = await fetch('/api/v1/mat/reservations/transfer', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                reservation_id: parseInt(resId),
                to_officer_id: parseInt(toOfficerId),
                notes: notes
            })
        });
        const data = await res.json();
        
        if (res.ok && data.success) {
            showToast('تم إرسال طلب نقل العهدة بنجاح!');
            closeModal('modalTransferCustody');
            loadReservations();
        } else {
            showToast(data.error || 'فشل نقل العهدة', true);
        }
    } catch (e) {
        showToast('حدث خطأ بالاتصال', true);
    }
}

// ── UI HELPERS ──────────────────────────────────────────────
// ── UI HELPERS & RESPONSIVE SIDEBAR DRAWER ──────────────────
function toggleSidebar() {
    const sidebar = document.getElementById('mainSidebar') || document.querySelector('.sidebar');
    if (!sidebar) return;
    
    if (window.innerWidth <= 992) {
        if (sidebar.classList.contains('drawer-open')) {
            closeSidebarDrawer();
        } else {
            openSidebarDrawer();
        }
    } else {
        sidebar.classList.toggle('collapsed');
        localStorage.setItem('sidebarCollapsed', sidebar.classList.contains('collapsed'));
    }
}

function openSidebarDrawer() {
    const sidebar = document.getElementById('mainSidebar') || document.querySelector('.sidebar');
    let backdrop = document.getElementById('sidebarBackdrop');
    if (!backdrop) {
        backdrop = document.createElement('div');
        backdrop.id = 'sidebarBackdrop';
        backdrop.className = 'sidebar-backdrop';
        backdrop.onclick = closeSidebarDrawer;
        document.body.appendChild(backdrop);
    }
    if (sidebar) {
        sidebar.classList.remove('collapsed');
        sidebar.classList.add('drawer-open');
    }
    if (backdrop) backdrop.classList.add('show');
    document.body.style.overflow = 'hidden';
}

function closeSidebarDrawer() {
    const sidebar = document.getElementById('mainSidebar') || document.querySelector('.sidebar');
    const backdrop = document.getElementById('sidebarBackdrop');
    if (sidebar) {
        sidebar.classList.remove('drawer-open');
        if (window.innerWidth <= 992) {
            sidebar.classList.remove('collapsed');
        }
    }
    if (backdrop) backdrop.classList.remove('show');
    document.body.style.overflow = '';
}

// Auto Close Event Listeners (Mobile Nav Click, Backdrop, ESC Key, Window Resize)
document.addEventListener('DOMContentLoaded', () => {
    // Ensure sidebar is expanded (unfolded) by default on desktop
    const sidebar = document.getElementById('mainSidebar') || document.querySelector('.sidebar');
    if (sidebar && window.innerWidth > 992) {
        sidebar.classList.remove('collapsed');
    }

    // Delegation listener for auto drawer close when clicking any navigation button (except accordion header toggles)
    document.addEventListener('click', (e) => {
        if (window.innerWidth <= 992) {
            const navItem = e.target.closest('.sidebar .nav-item');
            if (navItem && !navItem.classList.contains('nav-group-header') && !navItem.classList.contains('sidebar-close-btn')) {
                closeSidebarDrawer();
            }
        }
    });
});

// ESC Key Auto Close Drawer
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeSidebarDrawer();
    }
});

// Window Resize Auto Close Drawer when switching to desktop
window.addEventListener('resize', () => {
    if (window.innerWidth > 992) {
        closeSidebarDrawer();
    }
});

// ─────────────────────────────────────────────────────────────
// ONLINE USERS TOP-BAR POPUP
// ─────────────────────────────────────────────────────────────
function toggleOnlineUsersPopup() {
    const popup = document.getElementById('onlineUsersPopup');
    if (!popup) return;
    const isShown = popup.style.display !== 'none';
    popup.style.display = isShown ? 'none' : 'block';
    if (!isShown) loadOnlineUsers();
}

// Close popup when clicking outside
document.addEventListener('click', (e) => {
    const container = document.getElementById('onlineUsersBadgeContainer');
    if (container && !container.contains(e.target)) {
        const popup = document.getElementById('onlineUsersPopup');
        if (popup) popup.style.display = 'none';
    }
});

// ─────────────────────────────────────────────────────────────
// APPOINTMENT DETAIL MODAL
// ─────────────────────────────────────────────────────────────
async function openAppointmentDetail(apptId) {
    openModal('modalAppointmentDetail');

    const infoRow = document.getElementById('apptDetailInfoRow');
    const historyDiv = document.getElementById('apptDetailHistory');
    const previousDiv = document.getElementById('apptDetailPrevious');
    const titleEl = document.getElementById('apptDetailTitle');

    infoRow.innerHTML = '<div style="grid-column:1/-1;padding:1rem;color:var(--text-muted);">جاري التحميل...</div>';
    historyDiv.innerHTML = '<div style="color:var(--text-muted);text-align:center;padding:2rem;">جاري التحميل...</div>';
    previousDiv.innerHTML = '<div style="color:var(--text-muted);text-align:center;padding:2rem;">جاري التحميل...</div>';

    try {
        const res = await fetch(`/api/v1/mat/simple-appointments/${apptId}`);
        if (!res.ok) {
            infoRow.innerHTML = '<div style="padding:1rem;color:red;">تعذر تحميل تفاصيل الموعد.</div>';
            return;
        }
        const data = await res.json();
        const a = data.appointment;

        // ── Title ──────────────────────────────────────────────
        if (titleEl) titleEl.textContent = `تفاصيل الموعد — ${a.visitor_name} (${a.case_number})`;

        // ── Info Row ───────────────────────────────────────────
        const statusColor = { 'تم الحضور': '#10B981', 'مُؤجل': '#7C3AED', 'لم يحضر': '#EF4444', 'مُجدول': '#1E3A8A', 'لم يجيبوا': '#E74C3C', 'ملغى': '#94A3B8' };
        const sColor = statusColor[a.status] || '#64748B';
        infoRow.innerHTML = [
            { icon: '📄', label: 'رقم القضية',   val: a.case_number        },
            { icon: '🧑', label: 'اسم المراجع', val: a.visitor_name        },
            { icon: '📱', label: 'الهاتف',        val: a.phone || '—'       },
            { icon: '🪪', label: 'رقم الوطني',  val: a.national_id || '—' },
            { icon: '📅', label: 'التاريخ',       val: a.appointment_date   },
            { icon: '⏱️', label: 'الوقت',         val: a.appointment_time   },
            { icon: '📍', label: 'المركز',        val: a.station_name || '—'},
            { icon: '👮', label: 'أنشأه',         val: a.created_by_name || '—' },
        ].map(item => `
            <div style="padding:1rem; border-left:1px solid var(--border-color); border-bottom:1px solid var(--border-color);">
                <div style="font-size:0.72rem;color:var(--text-muted);margin-bottom:2px;">${item.icon} ${item.label}</div>
                <div style="font-weight:700;color:var(--text-primary);font-size:0.95rem;">${item.val}</div>
            </div>`).join('') + `
            <div style="padding:1rem; border-bottom:1px solid var(--border-color); grid-column: span 2; display:flex; align-items:center; gap:0.5rem;">
                <span style="width:10px;height:10px;background:${sColor};border-radius:50%;display:inline-block;"></span>
                <span style="font-weight:700; color:${sColor};">${a.status}</span>
                ${a.notes ? `<span style="color:var(--text-secondary);margin-right:auto;font-size:0.85rem;">📝 ${a.notes}</span>` : ''}
            </div>`;

        // ── Action History ─────────────────────────────────────
        if (!data.history || data.history.length === 0) {
            historyDiv.innerHTML = '<div style="color:var(--text-muted);text-align:center;padding:1.5rem;font-size:0.9rem;">لا يوجد سجل إجراءات لهذا الموعد بعد.</div>';
        } else {
            historyDiv.innerHTML = data.history.map((h, idx) => {
                let parsedDetails = {};
                try { parsedDetails = JSON.parse(h.details || '{}'); } catch (e) {}
                const notesTxt = parsedDetails.notes || '';
                return `
                <div style="display:flex;gap:0.75rem;margin-bottom:1rem;position:relative;">
                    <div style="flex-shrink:0;width:28px;height:28px;border-radius:50%;background:var(--accent-primary);color:#fff;display:flex;align-items:center;justify-content:center;font-size:0.75rem;font-weight:bold;">${idx+1}</div>
                    <div style="background:var(--bg-tertiary);border-radius:var(--radius-md);padding:0.6rem 0.75rem;flex:1;border-right:3px solid var(--accent-primary);">
                        <div style="font-weight:700;font-size:0.85rem;color:var(--text-primary);">${h.action}</div>
                        <div style="font-size:0.78rem;color:var(--text-secondary);margin-top:2px;">👮 ${h.officer_name || 'غير معروف'}</div>
                        ${notesTxt ? `<div style="font-size:0.78rem;color:var(--text-muted);margin-top:4px;">📝 ${notesTxt}</div>` : ''}
                        <div style="font-size:0.72rem;color:var(--text-muted);margin-top:4px;">🕒 ${h.created_at}</div>
                    </div>
                </div>`;
            }).join('');
        }

        // ── Previous Appointments ──────────────────────────────
        const others = (data.all_appointments || []).filter(x => x.id !== a.id);
        if (others.length === 0) {
            previousDiv.innerHTML = '<div style="color:var(--text-muted);text-align:center;padding:1.5rem;font-size:0.9rem;">لا توجد مواعيد سابقة لنفس القضية.</div>';
        } else {
            const statusIcon = { 'تم الحضور': '✅', 'مُؤجل': '🔄', 'لم يحضر': '❌', 'مُجدول': '⏳', 'لم يجيبوا': '📵', 'ملغى': '🚫' };
            previousDiv.innerHTML = others.map(o => {
                const icon = statusIcon[o.status] || '•';
                const maskClass = getApptMaskClass(o.status, o.appointment_date, o.appointment_time);
                return `
                <div class="${maskClass}" style="display:flex;gap:0.5rem;align-items:flex-start;padding:0.6rem;border-radius:var(--radius-md);margin-bottom:0.5rem;cursor:pointer;" onclick="closeModal('modalAppointmentDetail'); setTimeout(()=>openAppointmentDetail(${o.id}),200);">
                    <span style="font-size:1.1rem;">${icon}</span>
                    <div>
                        <div style="font-weight:700;font-size:0.88rem;">${o.appointment_date} — ${o.appointment_time}</div>
                        <div style="font-size:0.78rem;color:var(--text-secondary);">${o.status} | بواسطة: ${o.created_by_name || '—'}</div>
                        ${o.notes ? `<div style="font-size:0.75rem;color:var(--text-muted);">📝 ${o.notes}</div>` : ''}
                    </div>
                </div>`;
            }).join('');
        }

    } catch (err) {
        console.error('Error loading appointment detail:', err);
        infoRow.innerHTML = '<div style="padding:1rem;color:red;">حدث خطأ أثناء تحميل التفاصيل.</div>';
    }
}

// ─────────────────────────────────────────────────────────────
// OVERDUE APPOINTMENT STATUS & NOTES MODAL
// ─────────────────────────────────────────────────────────────
async function openOverdueUpdateModal(apptId) {
    const modal = document.getElementById('modalOverdueUpdate');
    if (!modal) {
        openAppointmentDetail(apptId);
        return;
    }

    document.getElementById('overdueApptId').value = apptId;
    document.getElementById('overdueVisitorName').textContent = 'جاري التحميل...';
    document.getElementById('overdueCaseNumber').textContent = '—';
    document.getElementById('overdueApptDateTime').textContent = '—';
    document.getElementById('overdueActionNotes').value = '';
    document.getElementById('overdueStatusSelect').value = 'تم الحضور';
    toggleOverdueBranchFields();

    const officerSelect = document.getElementById('overdueAssignOfficerSelect');
    if (officerSelect) {
        officerSelect.innerHTML = '<option value="">— جاري تحميل قائمة الموظفين... —</option>';
    }

    openModal('modalOverdueUpdate');

    try {
        const [resAppt, resOfficers] = await Promise.all([
            fetch(`/api/v1/mat/simple-appointments/${apptId}`),
            fetch('/api/v1/mat/officers')
        ]);

        let assignedOfficerId = null;
        if (resAppt.ok) {
            const data = await resAppt.json();
            const a = data.appointment;

            document.getElementById('overdueVisitorName').textContent = a.visitor_name || '—';
            document.getElementById('overdueCaseNumber').textContent = a.case_number || '—';
            document.getElementById('overdueApptDateTime').textContent = `${a.appointment_date} — ${a.appointment_time}`;
            window.currentOverdueAppt = a;
            assignedOfficerId = a.requested_by_id || null;
        }

        if (officerSelect && resOfficers.ok) {
            const offData = await resOfficers.json();
            officerSelect.innerHTML = '<option value="">— بدون إسناد (عام) —</option>';
            (offData.officers || []).filter(o => o.is_active).forEach(o => {
                const opt = document.createElement('option');
                opt.value = o.id;
                opt.textContent = `${o.name} (${o.role === 'admin' ? 'مشرف' : 'ضابط/مستخدم'})`;
                officerSelect.appendChild(opt);
            });
            if (assignedOfficerId) {
                officerSelect.value = assignedOfficerId;
            }
        }
    } catch (e) {
        console.error('Error opening overdue update modal:', e);
    }
}

function toggleOverdueBranchFields() {
    const statusVal = document.getElementById('overdueStatusSelect')?.value;
    const branchDiv = document.getElementById('overdueBranchFields');
    if (branchDiv) {
        if (statusVal === 'مُؤجل') {
            branchDiv.style.display = 'block';
            const tomorrow = new Date();
            tomorrow.setDate(tomorrow.getDate() + 1);
            document.getElementById('overdueNewDate').value = tomorrow.toISOString().split('T')[0];
            document.getElementById('overdueNewTime').value = '10:00';
        } else {
            branchDiv.style.display = 'none';
        }
    }
}

async function submitOverdueUpdate(e) {
    e.preventDefault();

    const apptId = document.getElementById('overdueApptId').value;
    const newStatus = document.getElementById('overdueStatusSelect').value;
    const notes = document.getElementById('overdueActionNotes').value.trim();
    const assignedOfficerVal = document.getElementById('overdueAssignOfficerSelect')?.value;
    const assignedOfficerId = assignedOfficerVal ? parseInt(assignedOfficerVal) : null;

    if (!apptId || !notes) {
        showToast('يرجى إدخال ملاحظات الإجراء والنتيجة', true);
        return;
    }

    try {
        // If status is 'مُؤجل', create the new branched appointment for the new date & time
        if (newStatus === 'مُؤجل') {
            const newDate = document.getElementById('overdueNewDate').value;
            const newTime = document.getElementById('overdueNewTime').value;
            const currentAppt = window.currentOverdueAppt || {};

            const branchPayload = {
                case_number: currentAppt.case_number || '',
                visitor_name: currentAppt.visitor_name || '',
                phone: currentAppt.phone || '',
                national_id: currentAppt.national_id || '',
                appointment_date: newDate,
                appointment_time: newTime,
                status: 'مُجدول',
                notes: `تأجيل وإعادة جدولة — ملاحظات: ${notes}`,
                requested_by_id: assignedOfficerId !== null ? assignedOfficerId : (currentAppt.requested_by_id || null),
                parent_appointment_id: parseInt(apptId)
            };

            await fetch('/api/v1/mat/simple-appointments', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(branchPayload)
            });
        }

        // Update current appointment status, notes, & assigned officer (requested_by_id)
        const res = await fetch(`/api/v1/mat/simple-appointments/${apptId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                status: newStatus,
                notes: notes,
                requested_by_id: assignedOfficerId
            })
        });

        if (res.ok) {
            closeModal('modalOverdueUpdate');
            showToast(`تم إدخال الملاحظات وتحديث حالة الموعد إلى (${newStatus}) بنجاح!`);
            loadSimpleAppointments();
            loadSimpleDashboard();
            loadDailyView();
            if (typeof loadCalendarView === 'function') loadCalendarView();
        } else {
            showToast('فشل تحديث حالة الموعد', true);
        }
    } catch (err) {
        showToast('تعذر الاتصال بالخادم المحلي', true);
    }
}
