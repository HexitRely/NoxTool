document.addEventListener('DOMContentLoaded', () => {
    window.app = window.app || {};
    // State
    let products = [];
    let clients = [];
    let invoices = [];
    let config = {};
    let modulesState = [];
    let currentUser = null;
    let selectedItems = [];
    let editingInvoiceId = null;
    let currentType = 'FAKTURA';
    let currentCategory = 'All';
    let currentPayment = 'PRZELEW';

    // Elements (use function for nav-btn as they may change)
    const views = document.querySelectorAll('.view');
    const viewTitle = document.getElementById('view-title');
    function getNavButtons() { return document.querySelectorAll('#sidebar-nav .nav-btn'); }

    // --- VIEW ROUTING ---
    function showView(viewId, skipReset = false) {
        if (currentUser && currentUser.must_change_password && viewId !== 'settings') {
            return;
        }
        // Permission guard â€” block access to views user doesn't have permission for (non-admin only)
        if (currentUser && currentUser.role !== 'ADMIN') {
            const permMap = {
                dashboard: 'can_access_dashboard',
                pos: 'can_access_pos',
                invoices: 'can_access_history',
                products: 'can_manage_catalog',
                clients: 'can_access_crm',
                finance: 'can_access_finance',
                settings: 'can_access_settings',
                projects: 'can_access_projects'
            };
            const requiredPerm = permMap[viewId];
            if (requiredPerm && !currentUser[requiredPerm]) {
                showToast('🚫 Brak dostępu do tego modułu.', 'error');
                return;
            }
        }
        
        views.forEach(v => v.style.display = 'none');
        const targetView = document.getElementById(`view-${viewId}`);
        if (targetView) targetView.style.display = 'block';
        
        getNavButtons().forEach(b => b.classList.toggle('active', b.dataset.view === viewId));
        const titles = { dashboard: 'Dashboard', pos: 'Punkt Sprzedaży', invoices: 'Historia', products: 'Katalog', clients: 'Klienci', finance: 'Finanse', settings: 'Ustawienia', calendar: 'Mój Kalendarz', projects: 'Projekty i Zadania' };
        viewTitle.textContent = titles[viewId] || viewId;
        
        if (viewId === 'dashboard') loadDashboard();
        if (viewId === 'invoices') loadInvoices();
        if (viewId === 'products') loadProducts();
        if (viewId === 'clients') loadClients();
        if (viewId === 'finance') loadFinance();
        if (viewId === 'settings') {
            initSettingsTabs();
            loadSettings();
            loadProfile();
        }
        if (viewId === 'pos') initPOS(skipReset);
        if (viewId === 'calendar') loadCalendar();
        if (viewId === 'projects') loadProjects();
    }

    document.getElementById('sidebar-nav').addEventListener('click', e => {
        const btn = e.target.closest('.nav-btn');
        if (btn) showView(btn.dataset.view);
    });

    // --- MODULE SYSTEM ---
    async function loadModules() {
        modulesState = await apiFetch('modules');
        applyModuleVisibility();
    }

    function applyModuleVisibility() {
        const moduleMap = {};
        modulesState.forEach(m => moduleMap[m.key] = m.is_enabled);

        const r = currentUser ? currentUser.role : '';

        // Show/hide nav buttons based on module state AND user role
        document.querySelectorAll('#sidebar-nav .nav-btn[data-module]').forEach(btn => {
            const modKey = btn.dataset.module;
            const viewKey = btn.dataset.view;
            let isEnabled = modKey === 'core' || moduleMap[modKey] !== false;
            
            if (r !== 'ADMIN') {
                if (viewKey === 'dashboard' && !currentUser.can_access_dashboard) isEnabled = false;
                if (viewKey === 'pos' && !currentUser.can_access_pos && !currentUser.can_create_documents) isEnabled = false;
                if (viewKey === 'invoices' && !currentUser.can_access_history && !currentUser.can_create_documents) isEnabled = false;
                if (viewKey === 'products' && !currentUser.can_manage_catalog) isEnabled = false;
                if (viewKey === 'clients' && !currentUser.can_access_crm) isEnabled = false;
                if (viewKey === 'finance' && !currentUser.can_access_finance) isEnabled = false;
                if (viewKey === 'settings' && !currentUser.can_access_settings) isEnabled = false;
                if (viewKey === 'projects' && !currentUser.can_access_projects) isEnabled = false;
            }

            btn.style.display = isEnabled ? '' : 'none';
        });

        // Hide sidebar limit info if user cannot access finance
        const limitInfo = document.querySelector('.sidebar-limit-info');
        if (limitInfo) {
            limitInfo.style.display = (r === 'ADMIN' || currentUser.can_access_finance) ? '' : 'none';
        }

        // Hide "Nowy Projekt" button if user cannot manage projects
        const btnNewProject = document.getElementById('btn-new-project');
        if (btnNewProject) {
            btnNewProject.style.display = (r === 'ADMIN' || currentUser.can_manage_projects) ? '' : 'none';
        }
    }

    function renderModulesSettings() {
        const container = document.getElementById('modules-list');
        if (!container || !modulesState.length) return;

        container.innerHTML = modulesState.map(mod => `
            <div style="display: flex; justify-content: space-between; align-items: center;
                        background: rgba(255,255,255,0.04); padding: 14px 18px;
                        border-radius: 10px; border: 1px solid ${ mod.is_enabled ? 'var(--accent-color)' : 'var(--border-color)' };">
                <div>
                    <span style="font-size: 1.3rem; margin-right: 10px;">${mod.icon}</span>
                    <strong>${mod.display_name}</strong>
                    ${mod.is_core ? '<span style="font-size: 0.7rem; background: rgba(99,102,241,0.3); color: #a5b4fc; padding: 2px 8px; border-radius: 20px; margin-left: 8px;">CORE</span>' : ''}
                </div>
                <label class="module-toggle">
                    <input type="checkbox" ${ mod.is_enabled ? 'checked' : '' } ${ mod.is_core ? 'disabled' : '' }
                           onchange="window.app.toggleModule('${mod.key}', this)">
                    <span class="module-toggle-slider"></span>
                </label>
            </div>
        `).join('');
    }


    // --- AUTH & STUDIOS ---
    async function loadAuthAndSetup() {
        try {
            currentUser = await apiFetch('auth/me');
            if (!currentUser || currentUser.error) throw new Error("Unauthorized");
            
            // Setup Header UI
            document.getElementById('current-user-header').textContent = currentUser.username;
            const badge = document.getElementById('auth-role-badge');
            badge.textContent = currentUser.role.substring(0, 2).toUpperCase();
            badge.className = `auth-badge role-${currentUser.role}`;

            if (currentUser.role === 'ADMIN') {
                const sSelect = document.getElementById('studio-selector');
                sSelect.style.display = 'block';
                const studios = await apiFetch('studios');
                
                if (Array.isArray(studios)) {
                    sSelect.innerHTML = '<option value="">Wszystkie (ZarzÄ…dzanie PeĹ‚ne)</option>' + 
                        studios.map(s => `<option value="${s.id}">${s.name}</option>`).join('');
                }
                
                // Get URL paramount
                const urlParams = new URLSearchParams(window.location.search);
                if (urlParams.has('studio_id')) sSelect.value = urlParams.get('studio_id');
                
                sSelect.onchange = (e) => {
                    const sid = e.target.value;
                    if (sid) {
                        window.location.href = `/?studio_id=${sid}`;
                    } else {
                        window.location.href = `/`;
                    }
                };
            }
        } catch (e) {
            console.error(e);
            window.location.href = '/login';
        }
    }

    document.getElementById('btn-logout').addEventListener('click', async () => {
        await fetch('/api/auth/logout', { method: 'POST' });
        window.location.href = '/login';
    });

    // --- THEME MANAGEMENT ---
    window.app.toggleTheme = () => {
        const currentTheme = document.documentElement.getAttribute('data-theme') || 'dark';
        const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', newTheme);
        localStorage.setItem('theme', newTheme);
        showToast(`PrzeĹ‚Ä…czono na motyw ${newTheme === 'dark' ? 'ciemny' : 'jasny'}`, 'info');
    };

    const btnThemeToggle = document.getElementById('btn-theme-toggle');
    if (btnThemeToggle) {
        btnThemeToggle.onclick = window.app.toggleTheme;
    }

    // Apply saved theme immediately
    const savedTheme = localStorage.getItem('theme') || 'dark';
    document.documentElement.setAttribute('data-theme', savedTheme);

    // --- API CALLS ---
    async function apiFetch(endpoint, method = 'GET', body = null) {
        const options = { method, headers: { 'Content-Type': 'application/json' } };
        if (body) options.body = JSON.stringify(body);
        const res = await fetch(`/api/${endpoint}`, options);
        const data = await res.json();
        if (res.status === 403 && data.module_disabled) {
            showToast(`🧩 Moduł wyłączony: ${data.error}`, 'error');
        }
        return data;
    }

    function showToast(message, type = 'info') {
        let container = document.getElementById('toast-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'toast-container';
            document.body.appendChild(container);
        }
        
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        
        const icon = type === 'success' ? '✅' : (type === 'error' ? '❌' : 'ℹ️');
        toast.innerHTML = `<span>${icon}</span> <span>${message}</span>`;
        
        container.appendChild(toast);
        
        setTimeout(() => {
            toast.classList.add('fade-out');
            setTimeout(() => toast.remove(), 400);
        }, 5000);
    }

    // --- DASHBOARD ---
    async function loadDashboard() {
        if (currentUser && currentUser.role === 'FREELANCER') {
            document.getElementById('monthly-total').parentElement.innerHTML = '<p>Brak dostępu do modułu Dashboard.</p>';
            return;
        }

        const sid = new URLSearchParams(window.location.search).get('studio_id');
        const url = sid ? `dashboard?studio_id=${sid}` : 'dashboard';
        const data = await apiFetch(url);
        
        if (data.error) return; // handled by interceptor

        document.getElementById('monthly-total').textContent = `${data.monthly_sum.toFixed(2)} PLN`;
        
        const limitLabel = document.getElementById('limit-type-title');
        const periodInfo = document.getElementById('dashboard-period-info');
        
        if (data.limit_type === 'DISABLED') {
            limitLabel.textContent = 'Monitor Limitów (Wyłączony)';
            periodInfo.textContent = 'Sumowanie nieaktywne';
            document.getElementById('remaining-limit').textContent = 'Limit nie obowiązuje';
            document.getElementById('income-progress').style.width = '0%';
        } else {
            limitLabel.textContent = data.limit_type === 'QUARTERLY' ? 'Limit Kwartalny' : 'Limit Miesięczny';
            periodInfo.textContent = data.limit_type === 'QUARTERLY' ? 'W kwartale' : 'W miesiącu';
            document.getElementById('sidebar-limit').textContent = `${data.limit.toFixed(2)} PLN`;
            document.getElementById('remaining-limit').textContent = `Pozostało: ${(data.limit - data.monthly_sum).toFixed(2)} PLN`;
            
            const progress = (data.monthly_sum / data.limit) * 100;
            document.getElementById('income-progress').style.width = `${Math.min(progress, 100)}%`;
        }
        
        document.getElementById('invoice-count').textContent = data.invoice_count;
        
        const warning = document.getElementById('ndg-warning');
        if (data.limit_type !== 'DISABLED') {
            if (data.critical) {
                warning.style.display = 'block';
                warning.querySelector('p').textContent = '⚠️ LIMIT PRZEKROCZONY! Czas na rejestrację firmy!';
                warning.style.background = 'rgba(239, 68, 68, 0.3)';
            } else if (data.warning) {
                warning.style.display = 'block';
                warning.querySelector('p').textContent = '⚠️ UWAGA: Zbliżasz się do limitu działalności!';
                warning.style.background = 'rgba(245, 158, 11, 0.2)';
            } else {
                warning.style.display = 'none';
            }
        } else {
            warning.style.display = 'none';
        }

        const invs = await apiFetch('invoices');
        const tbody = document.querySelector('#recent-invoices-table tbody');
        if (tbody) {
            tbody.innerHTML = invs.slice(0, 5).map(inv => `
                <tr>
                    <td>${inv.number} <span class="type-badge type-${inv.type.toLowerCase()}">${inv.type}</span></td>
                    <td>${inv.client}</td>
                    <td>${inv.date}</td>
                    <td>${inv.total.toFixed(2)} PLN</td>
                    <td><button class="status-badge ${inv.status.toLowerCase()}" onclick="window.app.toggleInvoiceStatus(${inv.id})">${inv.status}</button></td>
                    <td>
                        <div style="display: flex; gap: 5px;">
                            <a href="/pdfs/${inv.pdf}" target="_blank" class="btn btn-secondary btn-sm">📄</a>
                            <button class="btn btn-primary btn-sm" onclick="window.app.editInvoice(${inv.id})">✏️</button>
                            <button class="btn btn-success btn-sm" onclick="window.app.copyInvoiceToWorker(${inv.id})">📤</button>
                        </div>
                    </td>
                </tr>
            `).join('');
        }
        
        const configData = await apiFetch('config');
        // UsuniÄ™to nadpisywanie current-user-header nazwÄ… MY_NAME, aby nie mazaÄ‡ nazwy Auth.
    }

    // --- POS MODULE ---
    async function initPOS(skipReset = false) {
        clients = await apiFetch('clients');
        products = await apiFetch('products');
        
        if (!skipReset) {
            // Reset basket and editing state
            selectedItems = [];
            editingInvoiceId = null;
            document.getElementById('btn-pos-generate').textContent = 'WYSTAW I WYĹšLIJ DOKUMENT';
            document.getElementById('pos-client-name').value = '';
            document.getElementById('pos-client-nip').value = '';
            document.getElementById('pos-client-address').value = '';
            document.getElementById('pos-contract-num').value = '';
            document.getElementById('pos-description').value = '';
            
            renderPOSItems();
        }
        
        // Populate Client Datalist (Combined Search)
        const dl = document.getElementById('pos-client-datalist');
        dl.innerHTML = clients.map(c => `
            <option value="${c.name}">
            <option value="${c.nip}">
        `).join('');

        // Handle Client Auto-fill
        const nameInput = document.getElementById('pos-client-name');
        nameInput.oninput = (e) => {
            const val = e.target.value;
            const found = clients.find(c => c.name === val || c.nip === val);
            if (found) {
                document.getElementById('pos-client-name').value = found.name;
                document.getElementById('pos-client-nip').value = found.nip || '';
                document.getElementById('pos-client-address').value = found.address || '';
            }
        };

        // Categories from Products
        const categories = [...new Set(products.map(p => p.category))];
        const tabContainer = document.getElementById('pos-product-tabs');
        tabContainer.innerHTML = '<button type="button" class="tab-btn active" data-cat="All">Wszystkie</button>' +
            categories.map(cat => `<button type="button" class="tab-btn" data-cat="${cat}">${cat}</button>`).join('');
            
        tabContainer.querySelectorAll('.tab-btn').forEach(btn => {
            btn.onclick = () => {
                tabContainer.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                currentCategory = btn.dataset.cat;
                renderPOSTiles();
            };
        });

        // Doc Type
        document.querySelectorAll('.type-btn').forEach(btn => {
            btn.onclick = () => {
                document.querySelectorAll('.type-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                currentType = btn.dataset.type;
                document.getElementById('pos-payment-section').style.display = 
                    (currentType === 'WZ' || currentType === 'WYCENA') ? 'none' : 'block';
            };
        });

        // Payment Method
        document.querySelectorAll('.payment-btn').forEach(btn => {
            btn.onclick = () => {
                document.querySelectorAll('.payment-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                currentPayment = btn.dataset.method;
            };
        });

        renderPOSTiles();

        // Default "Worker Invoice" for non-admins (Employer Invoice)
        if (currentUser.role !== 'ADMIN') {
            const workerInv = document.getElementById('pos-worker-invoice');
            if (workerInv) workerInv.checked = true;
        }
    }

    function renderPOSTiles() {
        const grid = document.getElementById('pos-tiles-grid');
        let filtered = currentCategory === 'All' ? products : products.filter(p => p.category === currentCategory);
        grid.innerHTML = filtered.map(p => `
            <div class="product-tile" onclick="window.app.openTileAdd(${p.id})">
                <div class="tile-icon">📦</div>
                <div class="tile-name">${p.name}</div>
                <div class="tile-price">${p.price.toFixed(2)} PLN</div>
            </div>
        `).join('');
    }

    function renderPOSItems() {
        const list = document.getElementById('pos-items-list');
        list.innerHTML = selectedItems.map((item, idx) => `
            <div class="item-row" style="grid-template-columns: 1fr 60px 40px; margin-bottom: 5px; background: rgba(255,255,255,0.05); padding: 5px; border-radius: 5px; display: grid;">
                <div style="font-size: 0.8rem;">${item.name} <small>(${item.price.toFixed(2)})</small></div>
                <div style="font-weight: 700; font-size: 0.8rem; text-align: center;">x ${item.quantity}</div>
                <button type="button" class="btn btn-danger btn-sm" onclick="window.app.removePOSItem(${idx})">×</button>
            </div>
        `).join('');
        const total = selectedItems.reduce((acc, it) => acc + (it.price * it.quantity), 0);
        document.getElementById('pos-total').textContent = total.toFixed(2);
    }

    // NIP Lookup / GUS
    const btnLookup = document.getElementById('btn-lookup-nip');
    if (btnLookup) {
        btnLookup.onclick = async () => {
            const rawNip = document.getElementById('pos-client-nip').value;
            const cleanNip = rawNip.replace(/\D/g, '');
            
            if (cleanNip.length !== 10) {
                return showToast('Nieprawidłowy format NIP – wymagane dokładnie 10 cyfr.', 'error');
            }
            
            btnLookup.textContent = '⏳ Czekaj...';
            btnLookup.disabled = true;
            
            try {
                const data = await apiFetch(`lookup-nip/${cleanNip}`);
                btnLookup.textContent = '🔍 Pobierz z GUS';
                btnLookup.disabled = false;
                
                if (data.success) {
                    document.getElementById('pos-client-name').value = data.name;
                    document.getElementById('pos-client-address').value = data.address;
                    
                    if (data.source === 'MF') {
                        showToast(`Pobrano dane z Białej Listy MF. (Status: ${data.status_vat})`, 'success');
                    } else if (data.source === 'CEIDG') {
                        showToast('Pobrano dane z rejestru CEIDG.', 'success');
                    }
                } else {
                    showToast(data.error || 'Błąd API lub nie znaleziono podmiotu.', 'error');
                }
            } catch (err) {
                btnLookup.textContent = '🔍 Pobierz z GUS';
                btnLookup.disabled = false;
                showToast('Błąd połączenia z serwerem. Upewnij się, że masz internet.', 'error');
            }
        };
    }

    // POS Generate
    const btnGenerate = document.getElementById('btn-pos-generate');
    if (btnGenerate) {
        btnGenerate.onclick = async () => {
            if (selectedItems.length === 0) return alert('Koszyk jest pusty! Dodaj przynajmniej jeden produkt.');
            
            const payload = {
                document_type: currentType,
                payment_method: currentPayment,
                client_id: editingInvoiceId ? null : null, // Backend can handle either existing client_id or new_client_data
                contract_number: document.getElementById('pos-contract-num').value,
                description: document.getElementById('pos-description').value,
                include_rights_clause: document.getElementById('pos-rights-clause').checked,
                include_qr_code: document.getElementById('pos-qr-code').checked,
                items: selectedItems,
                new_client_data: {
                    name: document.getElementById('pos-client-name').value,
                    nip: document.getElementById('pos-client-nip').value,
                    id_type: window.app.currentPosIdType || 'NIP',
                    address: document.getElementById('pos-client-address').value
                },
                is_worker_invoice: document.getElementById('pos-worker-invoice')?.checked || false
            }

            if (!payload.new_client_data.name && currentType !== 'PARAGON') {
                return alert(`Dane odbiorcy (Nazwa) sÄ… wymagane dla dokumentu typu: ${currentType}. ProszÄ™ uzupeĹ‚niÄ‡ formularz.`);
            }

            const method = editingInvoiceId ? 'PUT' : 'POST';
            const endpoint = editingInvoiceId ? `invoices/${editingInvoiceId}` : 'invoices';
            
            const res = await apiFetch(endpoint, method, payload);
            if (res.success) {
                alert(editingInvoiceId ? 'Dokument został zaktualizowany!' : 'Dokument został wystawiony i przesłany!');
                if (res.pdf_url) window.open(res.pdf_url, '_blank');
                showView('dashboard');
            } else {
                alert('Błąd zapisu: ' + (res.error || 'Nieznany błąd serwera.'));
            }
        };
    }

    // --- PRODUCTS ---
    async function loadProducts() {
        products = await apiFetch('products');
        const tbody = document.querySelector('#products-table tbody');
        if (tbody) {
            tbody.innerHTML = products.map(p => `
                <tr>
                    <td><small>${p.sort_order}</small></td>
                    <td><span class="type-badge" style="background: rgba(255,255,255,0.1);">${p.category}</span></td>
                    <td><strong>${p.name}</strong></td>
                    <td>${p.price.toFixed(2)}</td>
                    <td>
                        <button class="btn btn-primary btn-sm" onclick="window.app.editProduct(${p.id})">✏️</button>
                        <button class="btn btn-danger btn-sm" onclick="window.app.deleteProduct(${p.id})">🗑️</button>
                    </td>
                </tr>
            `).join('');
        }
        const cats = [...new Set(products.map(p => p.category))];
        const dl = document.getElementById('category-list');
        if (dl) dl.innerHTML = cats.map(c => `<option value="${c}">`).join('');
    }

    const btnAddProdModal = document.getElementById('btn-add-product-modal');
    if (btnAddProdModal) {
        btnAddProdModal.onclick = () => {
            document.getElementById('product-modal-title').textContent = 'Dodaj Produkt';
            document.getElementById('m-product-id').value = '';
            document.getElementById('form-product-core').reset();
            document.getElementById('modal-product').style.display = 'block';
        };
    }

    const formProdCore = document.getElementById('form-product-core');
    if (formProdCore) {
        formProdCore.onsubmit = async (e) => {
            e.preventDefault();
            const id = document.getElementById('m-product-id').value;
            const data = {
                name: document.getElementById('m-product-name').value,
                price: document.getElementById('m-product-price').value,
                category: document.getElementById('m-product-category').value,
                sort_order: document.getElementById('m-product-sort').value
            };
            await apiFetch(id ? `products/${id}` : 'products', id ? 'PUT' : 'POST', data);
            document.getElementById('modal-product').style.display = 'none';
            loadProducts();
        };
    }

    // --- CLIENTS ---
    async function loadClients() {
        clients = await apiFetch('clients');
        const list = document.querySelector('#clients-table tbody');
        if (list) {
            list.innerHTML = clients.map(c => `
                <tr>
                    <td><a href="#" onclick="window.app.viewClientDetails(${c.id}); return false;" style="color: var(--accent-color); font-weight: 600;">${c.name}</a></td>
                    <td>${c.nip || '-'}</td>
                    <td>
                        <button class="btn btn-primary btn-sm" onclick="window.app.editClient(${c.id})">✏️</button>
                        <button class="btn btn-danger btn-sm" onclick="window.app.deleteClient(${c.id})">🗑️</button>
                    </td>
                </tr>
            `).join('');
        }
    }

    // --- ALL INVOICES ---
    async function loadInvoices() {
        invoices = await apiFetch('invoices');
        window.app.renderInvoicesTable();
    }

    // --- SETTINGS ---
    async function loadSettings() {
        config = await apiFetch('config');
        for (const [key, val] of Object.entries(config)) {
            const input = document.querySelector(`[name="${key}"]`);
            if (input) {
                if (input.type === 'radio') {
                    if (input.value === val) input.checked = true;
                } else {
                    input.value = val;
                }
            }
        }
        toggleLimitValueInput();

        // Finance settings
        if (document.getElementById('set-cost-limit')) {
            document.getElementById('set-cost-limit').value = config.COST_THRESHOLD_LIMIT || '1000.00';
            document.getElementById('set-cost-categories').value = config.EXPENSE_CATEGORIES || '';
        }

        // Modules panel
        await loadModules();
        renderModulesSettings();

        // Admin Panel
        if (currentUser && currentUser.role === 'ADMIN') {
            document.getElementById('settings-admin-panel').style.display = 'block';
            await loadAdminUi();
        } else {
            document.getElementById('settings-admin-panel').style.display = 'none';
        }
    }

    function toggleLimitValueInput() {
        const type = document.querySelector('input[name="LIMIT_TYPE"]:checked')?.value;
        const group = document.getElementById('limit-val-group');
        if (group) group.style.display = type === 'DISABLED' ? 'none' : 'block';
    }

    document.querySelectorAll('input[name="LIMIT_TYPE"]').forEach(r => {
        r.onchange = toggleLimitValueInput;
    });

    const formSettings = document.getElementById('form-settings');
    if (formSettings) {
        formSettings.onsubmit = async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const data = Object.fromEntries(formData);
            await apiFetch('config', 'POST', data);
            alert('Konfiguracja zapisana pomyślnie!');
            loadDashboard();
        };
    }

    const formFinanceSettings = document.getElementById('form-finance-settings');
    if (formFinanceSettings) {
        formFinanceSettings.onsubmit = async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const data = Object.fromEntries(formData);
            await apiFetch('config', 'POST', data);
            showToast('Konfiguracja finansowa zapisana!', 'success');
            loadFinance();
        };
    }

    const formWebhooks = document.getElementById('form-webhooks');
    if (formWebhooks) {
        formWebhooks.onsubmit = async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const data = Object.fromEntries(formData);
            await apiFetch('config', 'POST', data);
            showToast('Webhooki zaktualizowane!', 'success');
        };
    }

    // --- ADMIN PANEL ---
    async function loadAdminUi() {
        const studios = await apiFetch('studios');
        const users = await apiFetch('users');

        // Render Studios
        const tbodyS = document.getElementById('admin-studios-list');
        if (tbodyS) tbodyS.innerHTML = studios.map(s => `
            <tr>
                <td>${s.name}</td>
                <td><button type="button" class="btn btn-danger btn-sm" onclick="window.app.deleteStudio(${s.id})">Usuń</button></td>
            </tr>
        `).join('');

        // Populate select in User Form & Edit Form
        const userStudioSel = document.getElementById('add-user-studio');
        const editUserStudioSel = document.getElementById('edit-user-studio');
        const studioOpts = '<option value="">(Wszystkie STUDIA - Global)</option>' + 
            studios.map(s => `<option value="${s.id}">${s.name}</option>`).join('');
            
        if (userStudioSel) userStudioSel.innerHTML = studioOpts;
        if (editUserStudioSel) editUserStudioSel.innerHTML = studioOpts;

        window.app.activeAdminUsers = users; // save it for edit modal lookup

        // Render Users
        const tbodyU = document.getElementById('admin-users-list');
        if (tbodyU) tbodyU.innerHTML = users.map(u => `
            <tr>
                <td><strong>${u.username}</strong>${u.full_name ? '<br><small>'+u.full_name+'</small>' : ''}</td>
                <td>
                    <span class="auth-badge role-${u.role}" style="display:inline-flex;">${u.role.substring(0,2)}</span>
                    <br><small style="color:var(--text-secondary); font-size: 0.6rem;">
                        [<span style="color:${u.can_access_dashboard?'#4ade80':'#f87171'}">D</span>]
                        [<span style="color:${u.can_access_pos?'#4ade80':'#f87171'}">P</span>]
                        [<span style="color:${u.can_access_history?'#4ade80':'#f87171'}">H</span>]
                        [<span style="color:${u.can_manage_catalog?'#4ade80':'#f87171'}">K</span>]
                        [<span style="color:${u.can_access_crm?'#4ade80':'#f87171'}">C</span>]
                        [<span style="color:${u.can_access_finance?'#4ade80':'#f87171'}">F</span>]
                        [<span style="color:${u.can_access_projects?'#4ade80':'#f87171'}">Zp</span>]
                        [<span style="color:${u.can_manage_projects?'#4ade80':'#f87171'}">Zm</span>]
                        [<span style="color:${u.can_access_settings?'#4ade80':'#f87171'}">S</span>]
                    </small>
                </td>
                <td>${u.studio_name || 'Global'}</td>
                <td>
                    <button type="button" class="btn btn-primary btn-sm" onclick="window.app.editUser(${u.id})">Edytuj</button>
                    <button type="button" class="btn btn-danger btn-sm" onclick="window.app.deleteUser(${u.id})">Usuń</button>
                </td>
            </tr>
        `).join('');
    }

    const formAddStudio = document.getElementById('form-add-studio');
    if (formAddStudio) {
        formAddStudio.onsubmit = async (e) => {
            e.preventDefault();
            const name = document.getElementById('add-studio-name').value;
            const res = await apiFetch('studios', 'POST', { name });
            if (res.success) {
                showToast('Studio dodane', 'success');
                e.target.reset();
                await loadAdminUi();
            }
        };
    }

    const formAddUser = document.getElementById('form-add-user');
    if (formAddUser) {
        formAddUser.onsubmit = async (e) => {
            e.preventDefault();
            const username = document.getElementById('add-user-name').value;
            const full_name = document.getElementById('add-user-full-name').value;
            const password = document.getElementById('add-user-pass').value;
            const role = document.getElementById('add-user-role').value;
            const studio_id = document.getElementById('add-user-studio').value;
            const can_manage_catalog = document.getElementById('add-user-catalogue').checked;
            const can_access_history = document.getElementById('add-user-history').checked;
            const can_access_dashboard = document.getElementById('add-user-dashboard').checked;
            const can_access_pos = document.getElementById('add-user-pos').checked;
            const can_access_crm = document.getElementById('add-user-crm').checked;
            const can_access_finance = document.getElementById('add-user-finance').checked;
            const can_access_projects = document.getElementById('add-user-projects').checked;
            const can_manage_projects = document.getElementById('add-user-manage-projects').checked;
            const can_manage_tasks = document.getElementById('add-user-manage-tasks').checked;
            const can_access_settings = document.getElementById('add-user-settings').checked;
            
            const payload = { 
                username, full_name, password, role, 
                studio_id: studio_id ? parseInt(studio_id) : null,
                can_manage_catalog, can_access_history, can_access_dashboard,
                can_access_pos, can_access_crm, can_access_finance,
                can_access_settings, can_access_projects, can_manage_projects,
                can_manage_tasks,
                can_create_documents: document.getElementById('add-user-create-docs').checked,
                must_change_password: true
            };
            
            const res = await apiFetch('users/create', 'POST', payload);
            if (res.success) {
                showToast('User dodany', 'success');
                e.target.reset();
                await loadAdminUi();
            } else {
                showToast(res.error, 'error');
            }
        };
    }

    const formEditUser = document.getElementById('form-edit-user');
    if (formEditUser) {
        formEditUser.onsubmit = async (e) => {
            e.preventDefault();
            const id = document.getElementById('edit-user-id').value;
            const full_name = document.getElementById('edit-user-full-name').value;
            const role = document.getElementById('edit-user-role').value;
            const studio_id = document.getElementById('edit-user-studio').value;
            const password = document.getElementById('edit-user-pass').value;
            const can_manage_catalog = document.getElementById('edit-user-catalogue').checked;
            const can_access_history = document.getElementById('edit-user-history').checked;
            const can_access_dashboard = document.getElementById('edit-user-dashboard').checked;
            const can_access_pos = document.getElementById('edit-user-pos').checked;
            const can_access_crm = document.getElementById('edit-user-crm').checked;
            const can_access_finance = document.getElementById('edit-user-finance').checked;
            const can_access_projects = document.getElementById('edit-user-projects').checked;
            const can_manage_projects = document.getElementById('edit-user-manage-projects').checked;
            const can_manage_tasks = document.getElementById('edit-user-manage-tasks').checked;
            const can_access_settings = document.getElementById('edit-user-settings').checked;

            const payload = { 
                role, full_name,
                studio_id: studio_id ? parseInt(studio_id) : null,
                can_manage_catalog, can_access_history, can_access_dashboard,
                can_access_pos, can_access_crm, can_access_finance,
                can_access_settings, can_access_projects, can_manage_projects,
                can_manage_tasks,
                can_create_documents: document.getElementById('edit-user-create-docs')?.checked || false
            };
            if (password) payload.password = password;

            const res = await apiFetch(`users/${id}`, 'PUT', payload);
            if (res.success) {
                showToast('Użytkownik zaktualizowany', 'success');
                document.getElementById('modal-user-edit').style.display = 'none';
                await loadAdminUi();
            } else {
                showToast(res.error, 'error');
            }
        };
    }

    window.app.editUser = (id) => {
        const u = window.app.activeAdminUsers.find(x => x.id === id);
        if (!u) return;
        document.getElementById('edit-user-id').value = u.id;
        document.getElementById('edit-user-full-name').value = u.full_name || '';
        document.getElementById('edit-user-role').value = u.role;
        document.getElementById('edit-user-studio').value = u.assigned_studio_id || '';
        document.getElementById('edit-user-pass').value = '';
        document.getElementById('edit-user-catalogue').checked = u.can_manage_catalog;
        document.getElementById('edit-user-history').checked = u.can_access_history;
        document.getElementById('edit-user-dashboard').checked = u.can_access_dashboard;
        document.getElementById('edit-user-pos').checked = u.can_access_pos;
        document.getElementById('edit-user-crm').checked = u.can_access_crm;
        document.getElementById('edit-user-finance').checked = u.can_access_finance;
        document.getElementById('edit-user-settings').checked = u.can_access_settings;
        document.getElementById('edit-user-projects').checked = u.can_access_projects;
        document.getElementById('edit-user-manage-projects').checked = !!u.can_manage_projects;
        document.getElementById('edit-user-manage-tasks').checked = !!u.can_manage_tasks;
        if (document.getElementById('edit-user-create-docs')) {
            document.getElementById('edit-user-create-docs').checked = !!u.can_create_documents;
        }
        document.getElementById('modal-user-edit').style.display = 'block';
    };

    window.app.deleteStudio = async (id) => {
        if (!confirm('Na pewno usunąć studio? Rekordy zostaną osierocone (NULL).')) return;
        const res = await apiFetch(`studios/${id}`, 'DELETE');
        if (res.success) loadAdminUi();
    };

    window.app.deleteUser = async (id) => {
        if (!confirm('Na pewno usunąć usera?')) return;
        const res = await apiFetch(`users/${id}`, 'DELETE');
        if (res.success) {
            loadAdminUi();
        } else {
            showToast(res.error || "Błąd", 'error');
        }
    };


    const formAddClient = document.getElementById('form-add-client');
    if (formAddClient) {
        formAddClient.onsubmit = async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const data = Object.fromEntries(formData);
            const res = await apiFetch('clients', 'POST', data);
            if (res.success) {
                showToast('Klient dodany pomyĹ›lnie!', 'success');
                e.target.reset();
                loadClients();
            } else {
                showToast('BĹ‚Ä…d dodawania klienta: ' + (res.error || 'Nieznany bĹ‚Ä…d'), 'error');
            }
        };
    }

    const formEditClient = document.getElementById('form-edit-client');
    if (formEditClient) {
        formEditClient.onsubmit = async (e) => {
            e.preventDefault();
            const id = document.getElementById('e-client-id').value;
            const data = {
                name: document.getElementById('e-client-name').value,
                nip: document.getElementById('e-client-nip').value,
                address: document.getElementById('e-client-address').value,
                email: document.getElementById('e-client-email').value,
                phone: document.getElementById('e-client-phone').value
            };
            await apiFetch(`clients/${id}`, 'PUT', data);
            document.getElementById('modal-client-edit').style.display = 'none';
            loadClients();
        };
    }

    // --- GLOBALS ---
    Object.assign(window.app, {
        showView,
        openTileAdd: (id) => {
            const p = products.find(prod => prod.id === id);
            document.getElementById('tile-add-name').textContent = p.name;
            document.getElementById('tile-add-price').value = p.price;
            document.getElementById('tile-add-qty').value = 1;
            document.getElementById('modal-tile-add').style.display = 'block';
            
            document.getElementById('btn-tile-confirm').onclick = () => {
                selectedItems.push({
                    name: p.name,
                    price: parseFloat(document.getElementById('tile-add-price').value),
                    quantity: parseInt(document.getElementById('tile-add-qty').value)
                });
                renderPOSItems();
                document.getElementById('modal-tile-add').style.display = 'none';
            };
        },
        removePOSItem: (idx) => {
            selectedItems.splice(idx, 1);
            renderPOSItems();
        },
        toggleInvoiceStatus: async (id) => {
            await apiFetch(`invoices/${id}/status`, 'PATCH');
            loadDashboard();
            loadInvoices();
        },
        editClient: async (id) => {
            const c = await apiFetch(`clients/${id}`);
            document.getElementById('e-client-id').value = c.id;
            document.getElementById('e-client-name').value = c.name;
            document.getElementById('e-client-nip').value = c.nip || '';
            document.getElementById('e-client-address').value = c.address || '';
            document.getElementById('e-client-email').value = c.email || '';
            document.getElementById('e-client-phone').value = c.phone || '';
            document.getElementById('modal-client-edit').style.display = 'block';
        },
        deleteClient: async (id) => {
            if (confirm('UsunÄ…Ä‡ klienta? Wszystkie powiÄ…zane faktury rĂłwnieĹĽ zostanÄ… usuniÄ™te!')) {
                await apiFetch(`clients/${id}`, 'DELETE');
                loadClients();
                loadDashboard();
            }
        },
        renderInvoicesTable: () => {
            const sortBy = document.getElementById('sort-invoice').value;
            const filterClient = document.getElementById('filter-invoice-client').value;
            
            let filtered = [...invoices];
            if (filterClient) filtered = filtered.filter(inv => inv.client_id == filterClient);

            filtered.sort((a, b) => {
                if (sortBy === 'date_desc') return new Date(b.date) - new Date(a.date);
                if (sortBy === 'date_asc') return new Date(a.date) - new Date(b.date);
                if (sortBy === 'amount_desc') return b.total - a.total;
                return 0;
            });

            const tbody = document.querySelector('#all-invoices-table tbody');
            if (tbody) {
                tbody.innerHTML = filtered.map(inv => `
                    <tr>
                        <td><strong>${inv.number}</strong> <span class="type-badge type-${inv.type.toLowerCase()}">${inv.type}</span></td>
                        <td>${inv.client}</td>
                        <td>${inv.date}</td>
                        <td>${inv.total.toFixed(2)}</td>
                        <td><button class="status-badge ${inv.status.toLowerCase()}" onclick="window.app.toggleInvoiceStatus(${inv.id})">${inv.status}</button></td>
                        <td>
                            <div style="display: flex; gap: 5px; align-items: center;">
                                <a href="/api/pdf/invoice/${inv.id}" target="_blank" class="btn btn-secondary btn-sm" title="Pobierz PDF">📄</a>
                                ${inv.has_confirmation ? `
                                    <a href="/api/pdf/confirmation/${inv.id}" target="_blank" class="btn btn-info btn-sm" title="Pobierz Potwierdzenie">📜</a>
                                    <button class="btn btn-danger btn-sm" onclick="window.app.deleteConfirmation(${inv.id})" title="Usuń Potwierdzenie" style="padding: 2px 5px; font-size: 0.7rem;">🗑️📜</button>
                                ` : `
                                    <button class="btn btn-secondary btn-sm" onclick="window.app.openConfirmationForm(${inv.id})" title="Generuj Potwierdzenie" style="padding: 2px 5px; font-size: 0.7rem;">➕📜</button>
                                `}
                                <button class="btn btn-primary btn-sm" onclick="window.app.editInvoice(${inv.id})" title="Edytuj">✏️</button>
                                ${inv.type === 'WYCENA' ? `<button class="btn btn-success btn-sm" onclick="window.app.convertQuote(${inv.id})" title="Kopiuj na fakturę">📄</button>` : ''}
                                <button class="btn btn-danger btn-sm" onclick="window.app.deleteInvoice(${inv.id})" title="Usuń Dokument">🗑️</button>
                            </div>
                        </td>
                    </tr>
                `).join('');
            }
        },
        editProduct: async (id) => {
            const p = await apiFetch(`products/${id}`);
            document.getElementById('product-modal-title').textContent = 'Edytuj Produkt';
            document.getElementById('m-product-id').value = p.id;
            document.getElementById('m-product-name').value = p.name;
            document.getElementById('m-product-price').value = p.price;
            document.getElementById('m-product-sort').value = p.sort_order;
            document.getElementById('m-product-category').value = p.category;
            document.getElementById('modal-product').style.display = 'block';
        },
        deleteProduct: async (id) => {
            if (confirm('UsunÄ…Ä‡ produkt?')) {
                await apiFetch(`products/${id}`, 'DELETE');
                loadProducts();
            }
        },
        deleteInvoice: async (id) => {
            if (confirm('Usunąć dokument?')) {
                await apiFetch(`invoices/${id}`, 'DELETE');
                loadInvoices();
                loadDashboard();
            }
        },
        deleteConfirmation: async (invoiceId) => {
            if (confirm('Usunąć Potwierdzenie Projektu (PDF) dla tego dokumentu?')) {
                // Find confirmation id for this invoice
                const inv = invoices.find(i => i.id === invoiceId);
                if (inv) {
                    await apiFetch(`confirmations/${invoiceId}`, 'DELETE'); // Route handles lookup by invoice logic or id
                    // Wait, my backend route took CONFIRMATION id, but I can make it take invoice id for easier frontend use.
                    // Actually, let's fix backend to handle by invoice_id if preferred, or just fetch it.
                    // Let's assume the backend route /api/confirmations/<id> is for confirmation ID.
                    // BUT, to keep it simple, I'll update backend to handle lookup by invoice_id.
                    loadInvoices();
                }
            }
        },
        convertQuote: async (id) => {
            const res = await apiFetch(`invoices/${id}/convert`, 'POST');
            if (res.success) {
                alert('Wycena zostaĹ‚a pomyĹ›lnie zamieniona na fakturÄ™!');
                loadInvoices();
                loadDashboard();
            }
        },
        viewClientDetails: async (id) => {
            const data = await apiFetch(`clients/${id}`);
            document.getElementById('client-detail-name').textContent = data.name;
            document.getElementById('client-total-spent').textContent = `${data.total_spent.toFixed(2)} PLN`;
            document.getElementById('client-doc-count').textContent = data.invoices.length;
            const tbody = document.querySelector('#client-invoices-table tbody');
            tbody.innerHTML = data.invoices.map(inv => `
                <tr>
                    <td>${inv.number}</td>
                    <td>${inv.date}</td>
                    <td>${inv.total.toFixed(2)}</td>
                    <td><span class="status-badge ${inv.status.toLowerCase()}">${inv.status}</span></td>
                    <td><a href="/api/pdf/${inv.type === 'WYCENA' ? 'confirmation' : 'invoice'}/${inv.id}" target="_blank" class="btn btn-secondary btn-sm">PDF</a></td>
                </tr>
            `).join('');
            document.getElementById('modal-client-details').style.display = 'block';
        },
        editInvoice: async (id) => {
            const inv = await apiFetch(`invoices/${id}`);
            if (!inv) return;

            // Switch to POS with skipReset flag
            showView('pos', true);
            
            // Set state
            editingInvoiceId = id;
            selectedItems = inv.items;
            currentType = inv.type || 'FAKTURA';
            
            // Update Doc Type UI
            document.querySelectorAll('.type-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.type === currentType);
            });
            const paySec = document.getElementById('pos-payment-section');
            if (paySec) paySec.style.display = (currentType === 'WZ' || currentType === 'WYCENA') ? 'none' : 'block';

            // Fill core UI
            document.getElementById('btn-pos-generate').textContent = 'ZAKTUALIZUJ DOKUMENT';
            document.getElementById('pos-contract-num').value = inv.contract_number || '';
            document.getElementById('pos-description').value = inv.description || '';
            document.getElementById('pos-rights-clause').checked = inv.include_rights_clause;
            document.getElementById('pos-qr-code').checked = inv.include_qr_code;
            
            // Set Client (try to find in current list)
            const client = clients.find(c => c.id === inv.client_id);
            if (client) {
                document.getElementById('pos-client-name').value = client.name;
                document.getElementById('pos-client-nip').value = client.nip || '';
                document.getElementById('pos-client-address').value = client.address || '';
            }
            
            renderPOSItems();
        },

        // --- FINANCE & COSTS ---
        loadFinance: async () => {
            const expenses = await apiFetch('expenses');
            const conf = await apiFetch('config');
            const cats = (conf.EXPENSE_CATEGORIES || '').split(',').map(c => c.trim()).filter(c => c);
            
            // Populate category filter/select
            const filterCat = document.getElementById('filter-cost-category');
            if (filterCat && filterCat.options.length <= 1) {
                filterCat.innerHTML = '<option value="">Wszystkie Kategorie</option>' + 
                    cats.map(c => `<option value="${c}">${c}</option>`).join('');
            }
            
            const expCatSelect = document.getElementById('exp-category');
            if (expCatSelect) {
                expCatSelect.innerHTML = cats.map(c => `<option value="${c}">${c}</option>`).join('');
            }

            // Stats
            const total = expenses.reduce((sum, e) => sum + e.amount, 0);
            const now = new Date();
            const monthlyTotal = expenses.filter(e => {
                const d = new Date(e.date);
                return d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear();
            }).reduce((sum, e) => sum + e.amount, 0);

            document.getElementById('total-costs-sum').textContent = `${total.toFixed(2)} PLN`;
            document.getElementById('monthly-costs-sum').textContent = `${monthlyTotal.toFixed(2)} PLN`;
            
            // Logic for Top Category
            if (expenses.length > 0) {
                const catCounts = {};
                expenses.forEach(e => catCounts[e.category] = (catCounts[e.category] || 0) + e.amount);
                const top = Object.entries(catCounts).sort((a,b) => b[1] - a[1])[0][0];
                document.getElementById('top-cost-category').textContent = top;
            } else {
                document.getElementById('top-cost-category').textContent = '-';
            }

            // Render Table
            const tbody = document.querySelector('#expenses-table tbody');
            tbody.innerHTML = expenses.map(e => `
                <tr>
                    <td>${e.date}</td>
                    <td title="${e.title}"><strong>${e.title}</strong></td>
                    <td><span class="type-badge" style="background: rgba(255,255,255,0.1);">${e.category}</span></td>
                    <td><small>${e.project_name || '-'}</small></td>
                    <td style="font-weight: bold; color: var(--danger-color);">${e.amount.toFixed(2)} PLN</td>
                    <td>
                        ${e.file_path ? `<button class="btn btn-secondary btn-sm" onclick="window.app.viewCostDoc('${e.file_path}')">đź‘ď¸Ź</button>` : ''}
                        <button class="btn btn-danger btn-sm" onclick="window.app.deleteExpense(${e.id})">đź—‘ď¸Ź</button>
                    </td>
                </tr>
            `).join('');
        },
        viewCostDoc: (path) => {
            const container = document.getElementById('preview-container');
            const ext = path.split('.').pop().toLowerCase();
            if (ext === 'pdf') {
                container.innerHTML = `<iframe src="/static/${path}" width="100%" height="100%" style="border:none;"></iframe>`;
            } else {
                container.innerHTML = `<div style="display:flex; justify-content:center; align-items:center; height:100%; overflow:auto;"><img src="/static/${path}" style="max-width:100%; height:auto;"></div>`;
            }
            document.getElementById('modal-document-preview').style.display = 'block';
        },
        deleteExpense: async (id) => {
            if (confirm('UsunÄ…Ä‡ ten koszt wraz z dokumentem?')) {
                await apiFetch(`expenses/${id}`, 'DELETE');
                showToast('Koszt usuniÄ™ty.', 'info');
                loadFinance();
            }
        }
    });

    // --- FINANCE EVENT HANDLERS ---
    function loadFinance() { window.app.loadFinance(); }

    // Live filters for the expense table
    ['filter-cost-title', 'filter-cost-category', 'filter-cost-date'].forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        el.addEventListener('input', () => {
            const titleVal = document.getElementById('filter-cost-title').value.toLowerCase();
            const catVal   = document.getElementById('filter-cost-category').value;
            const dateVal  = document.getElementById('filter-cost-date').value;
            document.querySelectorAll('#expenses-table tbody tr').forEach(row => {
                const title = row.cells[1]?.textContent.toLowerCase() || '';
                const cat   = row.cells[2]?.textContent.trim() || '';
                const date  = row.cells[0]?.textContent.trim() || '';
                const show  =
                    (!titleVal || title.includes(titleVal)) &&
                    (!catVal   || cat === catVal) &&
                    (!dateVal  || date === dateVal);
                row.style.display = show ? '' : 'none';
            });
        });
    });

    const btnAddExp = document.getElementById('btn-add-expense-modal');
    if (btnAddExp) {
        btnAddExp.onclick = async () => {
            // Load projects for select
            const projs = await apiFetch('projects');
            const pSel = document.getElementById('exp-project');
            pSel.innerHTML = '<option value="">Wybierz projekt...</option>' + 
                projs.map(p => `<option value="${p.id}">${p.name}</option>`).join('');
            
            document.getElementById('form-add-expense').reset();
            document.getElementById('exp-date').value = new Date().toISOString().split('T')[0];
            document.getElementById('modal-expense').style.display = 'block';
        };
    }

    const formAddExp = document.getElementById('form-add-expense');
    if (formAddExp) {
        formAddExp.onsubmit = async (e) => {
            e.preventDefault();
            const btn = e.target.querySelector('button[type="submit"]');
            btn.disabled = true;
            btn.textContent = 'Trwa zapisywanie...';

            let filePath = null;
            const fileInput = document.getElementById('exp-file');
            
            // 1. Upload file if exists
            if (fileInput.files.length > 0) {
                const formData = new FormData();
                formData.append('file', fileInput.files[0]);
                try {
                    const uploadRes = await fetch('/api/costs/upload', { method: 'POST', body: formData });
                    const uploadData = await uploadRes.json();
                    if (uploadData.success) {
                        filePath = uploadData.file_path;
                    } else {
                        showToast('BĹ‚Ä…d uploadu: ' + uploadData.error, 'error');
                        btn.disabled = false;
                        btn.textContent = 'ZAPISZ WYDATEK';
                        return;
                    }
                } catch (err) {
                    showToast('BĹ‚Ä…d poĹ‚Ä…czenia podczas uploadu.', 'error');
                    btn.disabled = false;
                    btn.textContent = 'ZAPISZ WYDATEK';
                    return;
                }
            }

            // 2. Save Expense Data
            const data = {
                title: document.getElementById('exp-title').value,
                amount: document.getElementById('exp-amount').value,
                date: document.getElementById('exp-date').value,
                category: document.getElementById('exp-category').value,
                project_id: document.getElementById('exp-project').value || null,
                file_path: filePath
            };

            const res = await apiFetch('expenses', 'POST', data);
            btn.disabled = false;
            btn.textContent = 'ZAPISZ WYDATEK';

            if (res.success) {
                showToast('Koszt zapisany pomyĹ›lnie!', 'success');
                document.getElementById('modal-expense').style.display = 'none';
                loadFinance();
            } else {
                showToast('BĹ‚Ä…d zapisu: ' + (res.error || 'Nieznany bĹ‚Ä…d'), 'error');
            }
        };
    }

    // --- GLOBALS (continued) ---
    window.app.toggleModule = async (key, checkbox) => {
        const res = await apiFetch('modules/toggle', 'POST', { key });
        if (res.success) {
            // Update local state
            const mod = modulesState.find(m => m.key === key);
            if (mod) mod.is_enabled = res.is_enabled;
            applyModuleVisibility();
            renderModulesSettings();
            showToast(
                res.is_enabled ? `âś… ModuĹ‚ ${key} wĹ‚Ä…czony` : `âŹ¸ď¸Ź ModuĹ‚ ${key} wyĹ‚Ä…czony`,
                res.is_enabled ? 'success' : 'info'
            );
        } else {
            checkbox.checked = !checkbox.checked; // revert
            showToast(res.error, 'error');
        }
    };

    // --- CALENDAR & PROJECTS ---
    async function loadProjects() {
        const projects = await apiFetch('projects');
        const container = document.getElementById('projects-list-container');
        if (!container) return;
        
        if (!projects || projects.length === 0) {
            container.innerHTML = '<p style="color:var(--text-secondary); text-align:center; padding: 20px;">Brak projektów.</p>';
            return;
        }
        
        let html = '';
        for (let p of projects) {
            const tasksRes = await apiFetch(`projects/${p.id}/tasks`);
            let tasksHtml = '';
            if (tasksRes && tasksRes.length > 0) {
                tasksHtml = tasksRes.map(t => {
                    const statusColor = t.status === 'DONE' ? '#10b981' : (t.status === 'IN_PROGRESS' ? '#f59e0b' : '#3b82f6');
                    
                    // Render links as dynamic buttons
                    let linksHtml = '';
                    if (t.links && typeof t.links === 'string') {
                        const urls = t.links.split(/[\s,]+/).filter(url => url.trim() !== '');
                        linksHtml = urls.map(url => {
                            let label = 'Link';
                            if (url.includes('drive.google')) label = 'Google Drive';
                            if (url.includes('dropbox')) label = 'Dropbox';
                            if (url.includes('youtube') || url.includes('youtu.be')) label = 'YouTube';
                            if (url.includes('github')) label = 'GitHub';
                            return `<a href="${url}" target="_blank" class="btn btn-sm" style="background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.2); padding: 2px 8px; font-size: 0.7rem; color: #fff; margin-right: 5px;">🔗 ${label}</a>`;
                        }).join('');
                    }

                    return `
                    <div style="background: rgba(0,0,0,0.2); padding: 10px; border-radius: 6px; margin-bottom: 5px; display: flex; justify-content: space-between; align-items:center;">
                        <div style="flex: 1;">
                            <strong>${t.title}</strong>
                            <span style="font-size: 0.7rem; color: ${statusColor}; border: 1px solid ${statusColor}; padding: 1px 6px; border-radius: 12px; margin-left:10px;">${t.status}</span><br>
                            <div class="formatted-markdown" style="font-size: 0.85rem; color: #d1d5db; margin: 4px 0;">${marked.parse(t.description || '*Brak opisu*')}</div>
                            <span style="font-size: 0.8rem; color: var(--text-secondary);">Deadline: ${t.deadline || 'Brak'} | Przypisany: ${t.assigned_user_name || 'Brak'}</span>
                            <div style="margin-top: 6px;">${linksHtml}</div>
                        </div>
                        ${(currentUser.role === 'ADMIN' || currentUser.can_manage_projects) ? `
                            <div style="display: flex; gap: 5px; margin-left: 10px;">
                                <button class="btn btn-secondary btn-sm" onclick="window.app.editTask(${t.id}, ${p.id})" title="Edytuj">✏️</button>
                                <button class="btn btn-danger btn-sm" onclick="window.app.deleteTask(${t.id})" title="Usuń">🗑️</button>
                            </div>
                        ` : ''}
                    </div>`;
                }).join('');
            } else {
                tasksHtml = '<p style="font-size:0.8rem; color:var(--text-secondary);">Brak zadań w tym projekcie.</p>';
            }
            
            html += `
                <div style="border: 1px solid var(--border-color); border-radius: 8px; overflow: hidden;">
                    <div style="background: rgba(255,255,255,0.05); padding: 15px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border-color);">
                        <div>
                            <h4 style="margin: 0; color: #fff;">${p.name}</h4>
                            <span style="font-size: 0.8rem; color: var(--text-secondary);">Klient: ${p.client} | Przypisany: ${p.assigned_user_name || 'Brak'}</span>
                        </div>
                        <div style="display: flex; gap: 5px;">
                            ${(currentUser.role === 'ADMIN' || currentUser.can_manage_projects) ? `
                                <button class="btn btn-primary btn-sm" onclick="window.app.openTaskForm(${p.id})">➕ Zadanie</button>
                                <button class="btn btn-danger btn-sm" onclick="window.app.deleteProject(${p.id})" title="Usuń Projekt">🗑️</button>
                            ` : ''}
                        </div>
                    </div>
                    <div style="padding: 15px;">
                        ${tasksHtml}
                    </div>
                </div>
            `;
        }
        container.innerHTML = html;
    }
    
    window.app.openProjectForm = async () => {
        document.getElementById('form-project').reset();
        document.getElementById('p-id').value = '';
        
        const clients = await apiFetch('clients');
        
        // Safely fetch users (Producer/Admin can fetch users usually)
        let users = [];
        try {
            users = await apiFetch('users/list');
            if (users.error) users = [];
        } catch (e) { users = []; }
        
        const cSel = document.getElementById('p-client');
        cSel.innerHTML = clients.map(c => `<option value="${c.id}">${c.name}</option>`).join('');
        
        const uSel = document.getElementById('p-assigned');
        uSel.innerHTML = '<option value="">Brak</option>' + users.map(u => `<option value="${u.id}">${u.username}</option>`).join('');
        
        document.getElementById('modal-project-form').style.display = 'block';
    };

    const formProject = document.getElementById('form-project');
    if (formProject) {
        formProject.onsubmit = async (e) => {
            e.preventDefault();
            const id = document.getElementById('p-id').value;
            const payload = {
                client_id: document.getElementById('p-client').value,
                name: document.getElementById('p-name').value,
                description: document.getElementById('p-desc').value,
                assigned_user_id: document.getElementById('p-assigned').value || null
            };
            const res = await apiFetch(id ? `projects/${id}` : 'projects', id ? 'PUT' : 'POST', payload);
            if (res.success) {
                document.getElementById('modal-project-form').style.display = 'none';
                loadProjects();
            } else {
                showToast(res.error, 'error');
            }
        };
    }
    
    let debounceTimer;
    const tDesc = document.getElementById('t-desc');
    if (tDesc) {
        tDesc.addEventListener('input', e => {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                document.getElementById('t-desc-preview').innerHTML = marked.parse(e.target.value || '*Brak podglÄ…du*');
            }, 300);
        });
    }

    window.app.openTaskForm = async (projectId) => {
        document.getElementById('form-task').reset();
        document.getElementById('t-id').value = '';
        document.getElementById('t-project-id').value = projectId;
        document.getElementById('t-desc-preview').innerHTML = '*Brak podglÄ…du*';
        
        let users = [];
        try {
            users = await apiFetch('users/list');
            if (users.error) users = [];
        } catch (e) { users = []; }
        
        const uSel = document.getElementById('t-assigned');
        uSel.innerHTML = '<option value="">Brak</option>' + users.map(u => `<option value="${u.id}">${u.username}</option>`).join('');
        
        document.getElementById('modal-task-form').style.display = 'block';
    };
    
    window.app.editTask = async (taskId, projectId) => {
        const tasks = await apiFetch(`projects/${projectId}/tasks`);
        const t = tasks.find(x => x.id === taskId);
        if (!t) return;
        
        await window.app.openTaskForm(projectId);
        document.getElementById('t-id').value = t.id;
        document.getElementById('t-title').value = t.title;
        document.getElementById('t-desc').value = t.description || '';
        document.getElementById('t-desc-preview').innerHTML = marked.parse(t.description || '*Brak podglÄ…du*');
        if (t.deadline) document.getElementById('t-deadline').value = t.deadline;
        document.getElementById('t-links').value = t.links;
        document.getElementById('t-assigned').value = t.assigned_user_id || '';
        document.getElementById('t-status').value = t.status || 'TODO';
    };

    window.app.openConfirmationForm = (invoiceId) => {
        document.getElementById('conf-invoice-id').value = invoiceId;
        document.getElementById('form-confirmation').reset();
        document.getElementById('modal-confirmation').style.display = 'block';
    };

    const formConf = document.getElementById('form-confirmation');
    if (formConf) {
        formConf.onsubmit = async (e) => {
            e.preventDefault();
            const data = {
                invoice_id: document.getElementById('conf-invoice-id').value,
                title: document.getElementById('conf-title').value,
                deadline: document.getElementById('conf-deadline').value,
                scope: document.getElementById('conf-scope').value
            };
            const res = await apiFetch('confirmations', 'POST', data);
            if (res.success) {
                showToast('Potwierdzenie zostało wygenerowane i wysłane!', 'success');
                document.getElementById('modal-confirmation').style.display = 'none';
                loadInvoices();
            } else {
                showToast(res.error, 'error');
            }
        };
    }

    const formTask = document.getElementById('form-task');
    if (formTask) {
        formTask.onsubmit = async (e) => {
            e.preventDefault();
            const id = document.getElementById('t-id').value;
            const projectId = document.getElementById('t-project-id').value;
            
            const payload = {
                title: document.getElementById('t-title').value,
                description: document.getElementById('t-desc').value,
                deadline: document.getElementById('t-deadline').value,
                links: document.getElementById('t-links').value,
                assigned_user_id: document.getElementById('t-assigned').value || null,
                status: document.getElementById('t-status').value
            };
            
            const endpoint = id ? `tasks/${id}` : `projects/${projectId}/tasks`;
            const method = id ? 'PUT' : 'POST';
            
            const res = await apiFetch(endpoint, method, payload);
            if (res.success) {
                document.getElementById('modal-task-form').style.display = 'none';
                loadProjects();
            } else {
                showToast(res.error, 'error');
            }
        };
    }

    window.app.deleteProject = async (id) => {
        if (!confirm('Czy na pewno chcesz usunąć ten projekt wraz ze wszystkimi zadaniami?')) return;
        const res = await apiFetch(`projects/${id}`, 'DELETE');
        if (res.success) {
            showToast('Projekt został usunięty');
            loadProjects();
        } else {
            showToast(res.error, 'error');
        }
    };

    window.app.deleteTask = async (id) => {
        if (!confirm('Usunąć to zadanie?')) return;
        const res = await apiFetch(`tasks/${id}`, 'DELETE');
        if (res.success) {
            showToast('Zadanie usunięte');
            loadProjects();
        } else {
            showToast(res.error, 'error');
        }
    };
    
    let currentCalMonth = new Date();
    
    async function loadCalendar() {
        const data = await apiFetch('calendar');
        if (!data || data.error) return;
        
        const elMonth = document.getElementById('cal-month');
        if (!elMonth) return;
        elMonth.innerText = currentCalMonth.toLocaleDateString('pl-PL', { month: 'long', year: 'numeric' });
        
        const grid = document.getElementById('calendar-grid');
        grid.innerHTML = '';
        
        const y = currentCalMonth.getFullYear(), m = currentCalMonth.getMonth();
        const firstDay = new Date(y, m, 1).getDay();
        const daysInMonth = new Date(y, m + 1, 0).getDate();
        const adjustedFirstDay = firstDay === 0 ? 6 : firstDay - 1;
        
        const days = ['Pn', 'Wt', 'Śr', 'Cz', 'Pt', 'Sb', 'Nd'];
        days.forEach(d => grid.innerHTML += `<div style="text-align:center; font-weight:bold; padding: 5px; color: var(--accent-light);">${d}</div>`);
        
        for (let i = 0; i < adjustedFirstDay; i++) {
            grid.innerHTML += `<div class="cal-day empty" style="padding: 10px; background: rgba(0,0,0,0.1); border-radius: 6px;"></div>`;
        }
        
        for (let d = 1; d <= daysInMonth; d++) {
            const dateStr = `${y}-${String(m+1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
            const events = data.filter(x => x.date === dateStr);
            
            let evHtml = '';
            events.forEach(ev => {
                let color = '#3b82f6'; // Default (WORK)
                let icon = '💼';
                
                if (ev.type === 'project') {
                    color = '#8b5cf6'; icon = '🎵'; 
                } else if (ev.type === 'task') {
                    color = ev.status === 'DONE' ? '#10b981' : (ev.status === 'IN_PROGRESS' ? '#f59e0b' : '#3b82f6');
                    icon = '✅';
                } else {
                    if (ev.event_type === 'VACATION') { color = '#10b981'; icon = '🌴'; }
                    else if (ev.event_type === 'BUSY') { color = '#ef4444'; icon = '🔴'; }
                    else if (ev.event_type === 'OTHER') { color = '#f59e0b'; icon = '⚪'; }
                }

                const label = (ev.username && ev.username !== currentUser.username) ? `[${ev.username}] ` : '';
                const clickAction = ev.type === 'manual' && ev.is_mine ? `onclick="event.stopPropagation(); window.app.openAddEventModal('${dateStr}', ${JSON.stringify(ev).replace(/"/g, '&quot;')})"` : '';
                const visibilityIcon = ev.is_public ? ' 🌍' : '';

                evHtml += `<div style="background: ${color}; color: white; font-size: 0.65rem; padding: 3px 5px; border-radius: 4px; margin-top:3px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; cursor: pointer;" title="${label}${ev.title}${visibilityIcon}" ${clickAction}>${icon} ${label}${ev.title}</div>`;
            });
            
            const isToday = new Date().toISOString().split('T')[0] === dateStr;
            const border = isToday ? 'border: 2px solid var(--accent-color);' : 'border: 1px solid rgba(255,255,255,0.1);';
            grid.innerHTML += `
                <div class="cal-day" style="padding: 8px; background: rgba(255,255,255,0.05); border-radius: 6px; min-height: 100px; cursor: pointer; ${border}" onclick="window.app.openAddEventModal('${dateStr}')">
                    <div style="font-weight:bold; margin-bottom: 5px; ${isToday ? 'color: var(--accent-color);' : 'color: #aaa;'}">${d}</div>
                    ${evHtml}
                </div>
            `;
        }
    }

    window.app.openAddEventModal = (date, event = null) => {
        const modal = document.getElementById('modal-calendar-event');
        const form = document.getElementById('form-calendar-event');
        document.getElementById('cal-ev-id').value = event ? event.id : '';
        document.getElementById('cal-ev-title').value = event ? event.title : '';
        document.getElementById('cal-ev-date').value = date || (event ? event.date : '');
        document.getElementById('cal-ev-type').value = event ? (event.event_type || 'WORK') : 'WORK';
        document.getElementById('cal-ev-public').checked = event ? event.is_public : false;
        
        document.getElementById('btn-delete-cal-ev').style.display = event ? 'block' : 'none';
        modal.style.display = 'block';
    };

    const calEvForm = document.getElementById('form-calendar-event');
    if (calEvForm) {
        calEvForm.onsubmit = async (e) => {
            e.preventDefault();
            const id = document.getElementById('cal-ev-id').value;
            const data = {
                title: document.getElementById('cal-ev-title').value,
                date: document.getElementById('cal-ev-date').value,
                event_type: document.getElementById('cal-ev-type').value,
                is_public: document.getElementById('cal-ev-public').checked
            };
            
            const method = 'POST'; // We only have POST (create) for now, but I can add UPDATE if needed.
            // For now, if ID exists, we delete and re-create or just say "not implemented"
            // Let's implement UPDATE route in app.py or just use the current POST as "SAVE"
            
            const res = await apiFetch('calendar', { method, body: JSON.stringify(data) });
            if (res.success) {
                if (id) await apiFetch(`calendar/${id}`, { method: 'DELETE' }); // Simple update-via-replace
                document.getElementById('modal-calendar-event').style.display = 'none';
                loadCalendar();
                showToast('Wydarzenie zapisane');
            }
        };
    }

    document.getElementById('btn-delete-cal-ev').onclick = async () => {
        const id = document.getElementById('cal-ev-id').value;
        if (!id) return;
        if (confirm('Czy na pewno usunąć to wydarzenie?')) {
            const res = await apiFetch(`calendar/${id}`, { method: 'DELETE' });
            if (res.success) {
                document.getElementById('modal-calendar-event').style.display = 'none';
                loadCalendar();
                showToast('Wydarzenie usunięte');
            }
        }
    };
    
    const btnPrev = document.getElementById('cal-prev');
    const btnNext = document.getElementById('cal-next');
    if (btnPrev) btnPrev.onclick = () => { currentCalMonth.setMonth(currentCalMonth.getMonth() - 1); loadCalendar(); };
    if (btnNext) btnNext.onclick = () => { currentCalMonth.setMonth(currentCalMonth.getMonth() + 1); loadCalendar(); };

    // Listen for profile form submit
    const profileForm = document.getElementById('form-user-profile');
    if (profileForm) {
        profileForm.onsubmit = async (e) => {
            e.preventDefault();
            const data = {
                username: document.getElementById('profile-username').value,
                full_name: document.getElementById('profile-full-name').value,
                email: document.getElementById('profile-email').value,
                nip: document.getElementById('profile-nip').value,
                pesel: document.getElementById('profile-pesel').value,
                address: document.getElementById('profile-address').value,
                bank_account: document.getElementById('profile-bank-account').value,
                id_type: window.app.currentProfileIdType || 'NIP',
                password: document.getElementById('profile-password').value
            };
            const res = await apiFetch('user/profile', 'POST', data);
            if (res && res.success) {
                showToast('Profil został zaktualizowany.', 'success');
                document.getElementById('profile-password').value = '';
                currentUser = res.user;
                
                // Immediately refresh the profile UI and notice state
                loadProfile(res.user); 
                
                if (res.user.must_change_password) {
                    showToast('Uwaga: Nadal musisz uzupełnić NIP i Adres oraz zmienić hasło, aby odblokować system.', 'warning');
                } else {
                    showToast('🎉 System odblokowany! Możesz teraz korzystać z aplikacji.', 'success');
                }
            } else {
                showToast(res.error || 'Błąd podczas zapisywania profilu.', 'error');
            }
        };
    }

    // Entry â€” load auth, then modules, then start
    loadAuthAndSetup()
        .then(loadModules)
        .then(() => {
            const u = currentUser;
            if (u.must_change_password) {
                showView('settings');
                return;
            }
            
            // Navigate to the first view the user has permission to see
            if (u.role === 'ADMIN' || u.can_access_dashboard) {
                showView('dashboard');
            } else if (u.can_access_pos) {
                showView('pos');
            } else if (u.can_access_history) {
                showView('invoices');
            } else if (u.can_manage_catalog) {
                showView('products');
            } else if (u.can_access_crm) {
                showView('clients');
            } else if (u.can_access_finance) {
                showView('finance');
            } else if (u.can_access_projects) {
                showView('projects');
            } else {
                showView('calendar');
            }
        });
    // --- PROFILE & NEW SETTINGS LOGIC ---
    function initSettingsTabs() {
        const tabs = document.querySelectorAll('#settings-tabs .tab-btn');
        if (!tabs.length) return;
        
        tabs.forEach(btn => {
            btn.onclick = () => {
                tabs.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                
                document.querySelectorAll('.settings-tab-content').forEach(c => c.style.display = 'none');
                const target = document.getElementById(`tab-settings-${btn.dataset.tab}`);
                if (target) target.style.display = 'block';
            };
        });

        // Trigger the active tab (usually 'Firma') to be shown
        const activeTab = document.querySelector('#settings-tabs .tab-btn.active') || tabs[0];
        if (activeTab) activeTab.click();

        // Hide admin-only tabs if not admin
        if (currentUser && currentUser.role !== 'ADMIN') {
            document.querySelectorAll('.admin-only').forEach(el => el.style.display = 'none');
            // If the currently active tab is admin-only, switch to the first visible one
            const activeTab = document.querySelector('#settings-tabs .tab-btn.active');
            if (activeTab && activeTab.classList.contains('admin-only')) {
                const firstVisible = document.querySelector('#settings-tabs .tab-btn:not(.admin-only)');
                if (firstVisible) firstVisible.click();
            }
        } else {
            document.querySelectorAll('.admin-only').forEach(el => el.style.display = '');
        }
    }

    async function loadProfile(userSource = null) {
        // Use provided user object or fetch from API
        const u = userSource || await apiFetch('user/profile');
        if (u) {
            // Profile Tab
            if (document.getElementById('profile-username')) document.getElementById('profile-username').value = u.username || '';
            if (document.getElementById('profile-full-name')) document.getElementById('profile-full-name').value = u.full_name || '';
            if (document.getElementById('profile-email')) document.getElementById('profile-email').value = u.email || '';
            if (document.getElementById('profile-nip')) document.getElementById('profile-nip').value = u.nip || '';
            if (document.getElementById('profile-pesel')) document.getElementById('profile-pesel').value = u.pesel || '';
            if (document.getElementById('profile-address')) document.getElementById('profile-address').value = u.address || '';
            if (document.getElementById('profile-bank-account')) document.getElementById('profile-bank-account').value = u.bank_account || '';
            window.app.toggleProfileIdType(u.id_type || 'NIP');

            // Handle mandatory profile update state
            const notice = document.getElementById('first-login-notice');
            const navButtons = document.querySelectorAll('#sidebar-nav .nav-btn');
            
            if (u.must_change_password) {
                if (notice) notice.style.display = 'block';
                // Lock the Sidebar/Navigation (except Settings)
                navButtons.forEach(btn => {
                    if (btn.dataset.view !== 'settings') {
                        btn.style.opacity = '0.3';
                        btn.style.pointerEvents = 'none';
                    }
                });
                // Switch specifically to Profile tab
                setTimeout(() => {
                    const profileTabBtn = document.querySelector('#settings-tabs .tab-btn[data-tab="user-profile"]');
                    if (profileTabBtn) profileTabBtn.click();
                }, 100);
            } else {
                if (notice) notice.style.display = 'none';
                navButtons.forEach(btn => {
                    btn.style.opacity = '';
                    btn.style.pointerEvents = '';
                });
            }

            // Security & Webhooks Tab
            const encToggle = document.getElementById('profile-pdf-encryption');
            if (encToggle) {
                encToggle.checked = u.pdf_encryption_enabled || false;
                document.getElementById('pdf-password-group').style.display = encToggle.checked ? 'block' : 'none';
                encToggle.onchange = (e) => {
                    document.getElementById('pdf-password-group').style.display = e.target.checked ? 'block' : 'none';
                };
            }
            if (document.getElementById('profile-pdf-password')) document.getElementById('profile-pdf-password').value = u.pdf_password || '';
            if (document.getElementById('profile-webhook-admin')) document.getElementById('profile-webhook-admin').value = u.discord_admin_webhook || '';
            if (document.getElementById('profile-webhook-ekipa')) document.getElementById('profile-webhook-ekipa').value = u.discord_contractor_webhook || '';
        }
    }

    window.app.generatePdfPassword = () => {
        const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*";
        let pass = "";
        for (let i = 0; i < 10; i++) {
            pass += chars.charAt(Math.floor(Math.random() * chars.length));
        }
        const input = document.getElementById('profile-pdf-password');
        if (input) {
            input.value = pass;
            showNotification('Wygenerowano nowe hasło PDF. Pamiętaj, aby zapisać zmiany!', 'info');
        }
    };

    window.app.savePersonalConfigs = async () => {
        const data = {
            pdf_encryption_enabled: document.getElementById('profile-pdf-encryption').checked,
            pdf_password: document.getElementById('profile-pdf-password').value,
            discord_admin_webhook: document.getElementById('profile-webhook-admin').value,
            discord_contractor_webhook: document.getElementById('profile-webhook-ekipa').value
        };

        const res = await apiFetch('user/profile', 'POST', data);
        if (res && res.success) {
            currentUser = res.user;
            showNotification('Ustawienia bezpieczeństwa i integracji zostały zapisane.', 'success');
        }
    };

    window.app.toggleIdType = (type) => {
        window.app.currentPosIdType = type;
        const btnNip = document.getElementById('pos-id-type-nip');
        const btnPesel = document.getElementById('pos-id-type-pesel');
        if (btnNip) btnNip.classList.toggle('active', type === 'NIP');
        if (btnPesel) btnPesel.classList.toggle('active', type === 'PESEL');
        const ni = document.getElementById('pos-client-nip');
        if (ni) ni.placeholder = type === 'NIP' ? 'Wpisz NIP...' : 'Wpisz PESEL...';
    };

    window.app.toggleProfileIdType = (type) => {
        window.app.currentProfileIdType = type;
        const btnNip = document.getElementById('profile-id-type-nip');
        const btnPesel = document.getElementById('profile-id-type-pesel');
        if (btnNip) btnNip.classList.toggle('active', type === 'NIP');
        if (btnPesel) btnPesel.classList.toggle('active', type === 'PESEL');
        
        const gNip = document.getElementById('group-profile-nip');
        const gPesel = document.getElementById('group-profile-pesel');
        if (gNip) gNip.style.display = type === 'NIP' ? 'block' : 'none';
        if (gPesel) gPesel.style.display = type === 'PESEL' ? 'block' : 'none';
    };

});
