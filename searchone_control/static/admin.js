(() => {
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const page = document.body.dataset.page;
  const toastRegion = document.querySelector('[data-toast-region]');
  const backdrop = document.querySelector('[data-drawer-backdrop]');
  let engines = [];

  const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  })[char]);

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.body && typeof options.body !== 'string') {
      headers.set('Content-Type', 'application/json');
      options.body = JSON.stringify(options.body);
    }
    if (!['GET', 'HEAD'].includes((options.method || 'GET').toUpperCase())) {
      headers.set('X-CSRF-Token', csrf);
    }
    const response = await fetch(path, { ...options, headers });
    if (response.status === 204) return null;
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.message || payload.error?.message || payload.error || `请求失败 (${response.status})`);
    }
    return payload;
  }

  function toast(message, kind = '') {
    if (!toastRegion) return;
    const item = document.createElement('div');
    item.className = `toast ${kind}`;
    item.textContent = message;
    toastRegion.append(item);
    setTimeout(() => item.remove(), 3200);
  }

  async function copyText(value) {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return;
    }
    const input = document.createElement('textarea');
    input.value = value;
    input.setAttribute('readonly', '');
    input.style.position = 'fixed';
    input.style.opacity = '0';
    document.body.append(input);
    input.select();
    document.execCommand('copy');
    input.remove();
  }

  function formatDate(value) {
    if (!value) return '从未';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat('zh-CN', {
      month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'
    }).format(date);
  }

  function openDrawer(drawer) {
    drawer.classList.add('open');
    drawer.setAttribute('aria-hidden', 'false');
    backdrop.hidden = false;
    document.body.style.overflow = 'hidden';
  }

  function closeDrawers() {
    document.querySelectorAll('.drawer.open').forEach((drawer) => {
      drawer.classList.remove('open');
      drawer.setAttribute('aria-hidden', 'true');
    });
    backdrop.hidden = true;
    document.body.style.overflow = '';
  }

  document.querySelectorAll('[data-drawer-close]').forEach((button) => button.addEventListener('click', closeDrawers));
  backdrop?.addEventListener('click', closeDrawers);
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeDrawers(); });

  document.querySelector('[data-sidebar-toggle]')?.addEventListener('click', () => {
    document.querySelector('#sidebar')?.classList.toggle('open');
  });

  document.addEventListener('click', async (event) => {
    const copyButton = event.target.closest('[data-copy-value]');
    if (copyButton) {
      await copyText(copyButton.dataset.copyValue);
      toast('已复制');
    }
    const secretToggle = event.target.closest('[data-secret-toggle]');
    if (secretToggle) {
      const input = secretToggle.closest('.secret-control').querySelector('input');
      input.type = input.type === 'password' ? 'text' : 'password';
    }
    const secretCopy = event.target.closest('[data-secret-copy]');
    if (secretCopy) {
      const input = secretCopy.closest('.secret-control').querySelector('input');
      await copyText(input.value);
      toast('凭证已复制');
    }
  });

  async function loadEngines() {
    if (!engines.length) engines = await api('/admin/api/engines');
    return engines;
  }

  function renderEngineOptions(container, selected, filter = '') {
    const normalized = filter.trim().toLowerCase();
    const visible = engines.filter((engine) => !normalized || engine.name.toLowerCase().includes(normalized));
    container.innerHTML = visible.map((engine) => `
      <label class="engine-option" title="${esc(Array.isArray(engine.categories) ? engine.categories.join(', ') : (engine.categories || ''))}">
        <input type="checkbox" value="${esc(engine.name)}" ${selected.has(engine.name) ? 'checked' : ''}>
        <span>${esc(engine.name)}</span>
      </label>
    `).join('') || '<div class="empty-cell">没有匹配渠道</div>';
  }

  function selectedEngines(container) {
    return [...container.querySelectorAll('input:checked')].map((input) => input.value);
  }

  if (page === 'overview') initOverview();
  if (page === 'clients') initClients();
  if (page === 'providers') initProviders();
  if (page === 'proxies') initProxies();

  async function initOverview() {
    try {
      const data = await api('/admin/api/overview');
      Object.entries(data).forEach(([key, value]) => {
        const target = document.querySelector(`[data-stat="${key}"]`);
        if (target) target.textContent = Number(value).toLocaleString('zh-CN');
      });
    } catch (error) { toast(error.message, 'error'); }
  }

  async function initClients() {
    const rows = document.querySelector('[data-client-rows]');
    const drawer = document.querySelector('[data-client-drawer]');
    const form = document.querySelector('[data-client-form]');
    const engineOptions = form.querySelector('[data-engine-options]');
    const engineSearch = form.querySelector('[data-engine-search]');
    const engineCount = form.querySelector('[data-engine-count]');
    let clients = [];
    let selected = new Set();

    const updateEngineCount = () => {
      selected = new Set(selectedEngines(engineOptions));
      engineCount.textContent = selected.size ? `已选择 ${selected.size} 个渠道` : '请选择至少一个渠道';
    };
    engineOptions.addEventListener('change', updateEngineCount);
    engineSearch.addEventListener('input', () => renderEngineOptions(engineOptions, selected, engineSearch.value));

    async function reload() {
      [engines, clients] = await Promise.all([loadEngines(), api('/admin/api/clients')]);
      renderClients(clients);
    }

    function renderClients(items) {
      const term = document.querySelector('[data-client-search]').value.trim().toLowerCase();
      const filtered = items.filter((item) => !term || item.name.toLowerCase().includes(term) || item.key_prefix.toLowerCase().includes(term));
      rows.innerHTML = filtered.map((item) => {
        const status = item.enabled ? ['healthy', '启用'] : ['disabled', '停用'];
        const channelTags = item.allowed_engines.slice(0, 3).map((name) => `<span class="channel-tag">${esc(name)}</span>`).join('');
        const more = item.allowed_engines.length > 3 ? `<span class="channel-tag">+${item.allowed_engines.length - 3}</span>` : '';
        return `<tr>
          <td><span class="status-label"><span class="status-dot ${status[0]}"></span><strong>${esc(item.name)}</strong></span></td>
          <td><code class="key-prefix">${esc(item.key_prefix)}…</code></td>
          <td><div class="channel-list">${channelTags}${more}</div></td>
          <td>${item.rpm_limit}</td><td>${item.daily_limit}</td><td>${item.max_results}</td><td>${item.timeout_seconds}s</td>
          <td>${formatDate(item.last_used_at)}</td>
          <td class="actions"><div class="row-actions"><button class="icon-button" data-client-edit="${item.id}" title="查看和编辑"><svg><use href="#i-edit"/></svg></button></div></td>
        </tr>`;
      }).join('') || '<tr><td colspan="9" class="empty-cell">没有客户端 Key</td></tr>';
    }

    function resetForm() {
      form.reset();
      form.id.value = '';
      form.enabled.checked = true;
      form.rpm_limit.value = 60;
      form.daily_limit.value = 1000;
      form.concurrency_limit.value = 4;
      form.max_results.value = 10;
      form.timeout_seconds.value = 20;
      const preferred = new Set(['baidu', 'bing', 'brave', 'duckduckgo', 'tavily']);
      selected = new Set(engines.filter((engine) => preferred.has(engine.name)).map((engine) => engine.name));
      engineSearch.value = '';
      renderEngineOptions(engineOptions, selected);
      updateEngineCount();
      form.querySelector('[data-key-field]').hidden = true;
      form.querySelector('[data-client-delete]').hidden = true;
      form.querySelector('[data-client-rotate]').hidden = true;
      form.querySelector('[data-client-drawer-title]').textContent = '新建 Key';
    }

    document.querySelector('[data-client-create]').addEventListener('click', async () => {
      await loadEngines();
      resetForm();
      openDrawer(drawer);
      form.name.focus();
    });
    document.querySelector('[data-client-search]').addEventListener('input', () => renderClients(clients));
    rows.addEventListener('click', async (event) => {
      const button = event.target.closest('[data-client-edit]');
      if (!button) return;
      try {
        const item = await api(`/admin/api/clients/${button.dataset.clientEdit}`);
        form.reset();
        form.id.value = item.id;
        form.name.value = item.name;
        form.key.value = item.key;
        form.key.type = 'password';
        form.enabled.checked = item.enabled;
        form.rpm_limit.value = item.rpm_limit;
        form.daily_limit.value = item.daily_limit;
        form.concurrency_limit.value = item.concurrency_limit;
        form.max_results.value = item.max_results;
        form.timeout_seconds.value = item.timeout_seconds;
        form.expires_at.value = item.expires_at ? item.expires_at.slice(0, 16) : '';
        selected = new Set(item.allowed_engines);
        engineSearch.value = '';
        renderEngineOptions(engineOptions, selected);
        updateEngineCount();
        form.querySelector('[data-key-field]').hidden = false;
        form.querySelector('[data-client-delete]').hidden = false;
        form.querySelector('[data-client-rotate]').hidden = false;
        form.querySelector('[data-client-drawer-title]').textContent = '编辑 Key';
        openDrawer(drawer);
      } catch (error) { toast(error.message, 'error'); }
    });

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      updateEngineCount();
      const id = form.id.value;
      const payload = {
        name: form.name.value, enabled: form.enabled.checked, allowed_engines: [...selected],
        rpm_limit: Number(form.rpm_limit.value), daily_limit: Number(form.daily_limit.value),
        concurrency_limit: Number(form.concurrency_limit.value), max_results: Number(form.max_results.value),
        timeout_seconds: Number(form.timeout_seconds.value),
        expires_at: form.expires_at.value ? new Date(form.expires_at.value).toISOString() : null
      };
      try {
        const item = await api(id ? `/admin/api/clients/${id}` : '/admin/api/clients', { method: id ? 'PUT' : 'POST', body: payload });
        form.id.value = item.id;
        form.key.value = item.key;
        form.querySelector('[data-key-field]').hidden = false;
        form.querySelector('[data-client-delete]').hidden = false;
        form.querySelector('[data-client-rotate]').hidden = false;
        form.querySelector('[data-client-drawer-title]').textContent = '编辑 Key';
        await reload();
        toast(id ? 'Key 已更新' : 'Key 已创建');
      } catch (error) { toast(error.message, 'error'); }
    });

    form.querySelector('[data-client-delete]').addEventListener('click', async () => {
      if (!confirm('确认删除这个 API Key？删除后无法恢复。')) return;
      try {
        await api(`/admin/api/clients/${form.id.value}`, { method: 'DELETE' });
        closeDrawers(); await reload(); toast('Key 已删除');
      } catch (error) { toast(error.message, 'error'); }
    });
    form.querySelector('[data-client-rotate]').addEventListener('click', async () => {
      if (!confirm('轮换后旧 Key 会立即失效，继续吗？')) return;
      try {
        const item = await api(`/admin/api/clients/${form.id.value}/rotate`, { method: 'POST' });
        form.key.value = item.key; await reload(); toast('Key 已轮换');
      } catch (error) { toast(error.message, 'error'); }
    });
    try { await reload(); } catch (error) { toast(error.message, 'error'); }
  }

  async function initProviders() {
    const rows = document.querySelector('[data-provider-rows]');
    const drawer = document.querySelector('[data-provider-drawer]');
    const form = document.querySelector('[data-provider-form]');
    let providers = [];

    async function reload() {
      providers = await api('/admin/api/providers');
      rows.innerHTML = providers.map((item) => {
        const health = item.enabled ? item.last_test_status : 'disabled';
        const healthText = item.enabled ? ({ healthy: '正常', failed: '失败', untested: '未测试' }[health] || health) : '已停用';
        return `<tr>
          <td><strong>${esc(item.display_name)}</strong></td><td><code>${esc(item.env_name)}</code></td>
          <td><span class="status-label"><span class="status-dot ${item.configured ? 'healthy' : 'warning'}"></span>${item.configured ? '已配置' : '未配置'}</span></td>
          <td><span class="status-label"><span class="status-dot ${health}"></span>${esc(healthText)}</span></td>
          <td>${formatDate(item.last_tested_at)}</td>
          <td class="actions"><div class="row-actions"><button class="icon-button" data-provider-edit="${item.provider}" title="查看和编辑"><svg><use href="#i-edit"/></svg></button></div></td>
        </tr>`;
      }).join('');
    }

    rows.addEventListener('click', async (event) => {
      const button = event.target.closest('[data-provider-edit]');
      if (!button) return;
      try {
        const item = await api(`/admin/api/providers/${button.dataset.providerEdit}`);
        form.provider.value = item.provider;
        form.enabled.checked = item.enabled;
        form.secret.value = item.secret;
        form.secret.type = 'password';
        form.querySelector('[data-provider-title]').textContent = item.display_name;
        form.querySelector('[data-provider-env]').textContent = item.env_name;
        const result = form.querySelector('[data-provider-result]');
        result.hidden = !item.last_test_message;
        result.className = `connection-result ${item.last_test_status}`;
        result.textContent = item.last_test_message;
        openDrawer(drawer);
      } catch (error) { toast(error.message, 'error'); }
    });

    async function saveProvider(showToast = true) {
      const item = await api(`/admin/api/providers/${form.provider.value}`, {
        method: 'PUT', body: { secret: form.secret.value, enabled: form.enabled.checked }
      });
      if (showToast) toast('供应商凭证已保存');
      await reload();
      return item;
    }
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      try { await saveProvider(); } catch (error) { toast(error.message, 'error'); }
    });
    form.querySelector('[data-provider-test]').addEventListener('click', async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      const resultBox = form.querySelector('[data-provider-result]');
      try {
        await saveProvider(false);
        const result = await api(`/admin/api/providers/${form.provider.value}/test`, { method: 'POST' });
        resultBox.hidden = false; resultBox.className = `connection-result ${result.status}`; resultBox.textContent = result.message;
        toast('连接测试完成'); await reload();
      } catch (error) {
        resultBox.hidden = false; resultBox.className = 'connection-result failed'; resultBox.textContent = error.message;
        toast(error.message, 'error'); await reload();
      } finally { button.disabled = false; }
    });
    try { await reload(); } catch (error) { toast(error.message, 'error'); }
  }

  async function initProxies() {
    const rows = document.querySelector('[data-proxy-rows]');
    const drawer = document.querySelector('[data-proxy-drawer]');
    const form = document.querySelector('[data-proxy-form]');
    const importDrawer = document.querySelector('[data-proxy-import-drawer]');
    const importForm = document.querySelector('[data-proxy-import-form]');
    const engineOptions = form.querySelector('[data-proxy-engine-options]');
    const engineSearch = form.querySelector('[data-proxy-engine-search]');
    const selectAll = document.querySelector('[data-proxy-select-all]');
    const batchTestButton = document.querySelector('[data-proxy-batch-test]');
    const batchTestLabel = document.querySelector('[data-proxy-batch-label]');
    const concurrencyInput = document.querySelector('[data-proxy-concurrency]');
    let proxies = [];
    let selectedChannels = new Set();
    let selectedProxyIds = new Set();
    let testingProxyIds = new Set();
    engineOptions.addEventListener('change', () => { selectedChannels = new Set(selectedEngines(engineOptions)); });
    engineSearch.addEventListener('input', () => renderEngineOptions(engineOptions, selectedChannels, engineSearch.value));

    async function reload() {
      [engines, proxies] = await Promise.all([loadEngines(), api('/admin/api/proxies')]);
      const knownIds = new Set(proxies.map((item) => item.id));
      selectedProxyIds = new Set([...selectedProxyIds].filter((id) => knownIds.has(id)));
      renderProxies();
    }

    function renderProxies() {
      rows.innerHTML = proxies.map((item) => {
        const scope = item.channels.length ? item.channels.slice(0, 2).map((name) => `<span class="channel-tag">${esc(name)}</span>`).join('') : '<span class="channel-tag">全部渠道</span>';
        const testing = testingProxyIds.has(item.id);
        const status = testing ? 'testing' : (item.enabled ? item.status : 'disabled');
        const statusText = testing ? '测试中' : (item.enabled ? ({ healthy: '正常', failed: '失败', untested: '未测试' }[status] || status) : '已停用');
        return `<tr>
          <td class="select-cell"><input type="checkbox" data-proxy-select="${item.id}" aria-label="选择 ${esc(item.name)}" ${selectedProxyIds.has(item.id) ? 'checked' : ''}></td>
          <td><strong>${esc(item.name)}</strong></td><td><code>${esc(item.scheme)}://${esc(item.host)}:${item.port}</code></td>
          <td><div class="channel-list">${scope}</div></td><td>${item.weight}</td>
          <td><span class="status-label"><span class="status-dot ${status}"></span>${esc(statusText)}</span></td>
          <td>${esc(item.exit_ip || '-')}</td><td>${item.latency_ms == null ? '-' : `${item.latency_ms} ms`}</td><td>${formatDate(item.last_checked_at)}</td>
          <td class="actions"><div class="row-actions"><button class="icon-button" data-proxy-edit="${item.id}" title="查看和编辑"><svg><use href="#i-edit"/></svg></button></div></td>
        </tr>`;
      }).join('') || '<tr><td colspan="10" class="empty-cell">尚未添加代理，当前所有渠道使用直连</td></tr>';
      updateSelectionControls();
    }

    function updateSelectionControls() {
      const selectedCount = selectedProxyIds.size;
      selectAll.disabled = !proxies.length;
      selectAll.checked = Boolean(proxies.length && selectedCount === proxies.length);
      selectAll.indeterminate = selectedCount > 0 && selectedCount < proxies.length;
      batchTestButton.disabled = !proxies.length || testingProxyIds.size > 0;
      concurrencyInput.disabled = testingProxyIds.size > 0;
      batchTestLabel.textContent = selectedCount ? `测试选中 (${selectedCount})` : '测试全部';
    }

    function resetForm() {
      form.reset(); form.id.value = ''; form.enabled.checked = true; form.weight.value = 1;
      selectedChannels = new Set(); engineSearch.value = ''; renderEngineOptions(engineOptions, selectedChannels);
      form.querySelector('[data-proxy-title]').textContent = '添加代理';
      form.querySelector('[data-proxy-delete]').hidden = true;
      form.querySelector('[data-proxy-test]').hidden = true;
      form.querySelector('[data-proxy-result]').hidden = true;
    }
    document.querySelector('[data-proxy-create]').addEventListener('click', async () => {
      await loadEngines(); resetForm(); openDrawer(drawer); form.name.focus();
    });
    rows.addEventListener('click', async (event) => {
      const button = event.target.closest('[data-proxy-edit]');
      if (!button) return;
      try {
        const item = await api(`/admin/api/proxies/${button.dataset.proxyEdit}`);
        form.reset();
        ['id', 'name', 'scheme', 'host', 'port', 'username', 'password', 'weight'].forEach((key) => { form[key].value = item[key] ?? ''; });
        form.password.type = 'password'; form.enabled.checked = item.enabled;
        selectedChannels = new Set(item.channels); engineSearch.value = ''; renderEngineOptions(engineOptions, selectedChannels);
        form.querySelector('[data-proxy-title]').textContent = '编辑代理';
        form.querySelector('[data-proxy-delete]').hidden = false;
        form.querySelector('[data-proxy-test]').hidden = false;
        const result = form.querySelector('[data-proxy-result]');
        result.hidden = !item.last_error && !item.exit_ip;
        result.className = `connection-result ${item.status}`;
        result.textContent = item.status === 'healthy' ? `出口 IP ${item.exit_ip}，延迟 ${item.latency_ms} ms` : item.last_error;
        openDrawer(drawer);
      } catch (error) { toast(error.message, 'error'); }
    });
    form.addEventListener('submit', async (event) => {
      event.preventDefault(); selectedChannels = new Set(selectedEngines(engineOptions));
      const id = form.id.value;
      const payload = {
        name: form.name.value, scheme: form.scheme.value, host: form.host.value, port: Number(form.port.value),
        username: form.username.value, password: form.password.value, enabled: form.enabled.checked,
        weight: Number(form.weight.value), channels: [...selectedChannels]
      };
      try {
        const item = await api(id ? `/admin/api/proxies/${id}` : '/admin/api/proxies', { method: id ? 'PUT' : 'POST', body: payload });
        form.id.value = item.id; form.querySelector('[data-proxy-delete]').hidden = false; form.querySelector('[data-proxy-test]').hidden = false;
        form.querySelector('[data-proxy-title]').textContent = '编辑代理'; await reload(); toast(id ? '代理已更新并热应用' : '代理已添加并热应用');
      } catch (error) { toast(error.message, 'error'); }
    });
    form.querySelector('[data-proxy-delete]').addEventListener('click', async () => {
      if (!confirm('确认删除这个代理？')) return;
      try { await api(`/admin/api/proxies/${form.id.value}`, { method: 'DELETE' }); closeDrawers(); await reload(); toast('代理已删除并热应用'); }
      catch (error) { toast(error.message, 'error'); }
    });
    form.querySelector('[data-proxy-test]').addEventListener('click', async (event) => {
      const button = event.currentTarget; button.disabled = true;
      const resultBox = form.querySelector('[data-proxy-result]');
      try {
        const result = await api(`/admin/api/proxies/${form.id.value}/test`, { method: 'POST' });
        resultBox.hidden = false; resultBox.className = `connection-result ${result.status}`;
        resultBox.textContent = `出口 IP ${result.exit_ip}，延迟 ${result.latency_ms} ms`; await reload(); toast('代理测试完成');
      } catch (error) {
        resultBox.hidden = false; resultBox.className = 'connection-result failed'; resultBox.textContent = error.message; await reload(); toast(error.message, 'error');
      } finally { button.disabled = false; }
    });

    selectAll.addEventListener('change', () => {
      selectedProxyIds = selectAll.checked ? new Set(proxies.map((item) => item.id)) : new Set();
      renderProxies();
    });
    rows.addEventListener('change', (event) => {
      const checkbox = event.target.closest('[data-proxy-select]');
      if (!checkbox) return;
      if (checkbox.checked) selectedProxyIds.add(checkbox.dataset.proxySelect);
      else selectedProxyIds.delete(checkbox.dataset.proxySelect);
      updateSelectionControls();
    });

    async function runBatchTest(ids, concurrency, enableHealthy = false) {
      const targetIds = ids.length ? ids : proxies.map((item) => item.id);
      testingProxyIds = new Set(targetIds);
      renderProxies();
      try {
        const result = await api('/admin/api/proxies/test', {
          method: 'POST', body: { ids: targetIds, concurrency, enable_healthy: enableHealthy }
        });
        await reload();
        toast(`测试完成：${result.healthy} 个可用，${result.failed} 个失败`, result.failed ? 'warning' : '');
        return result;
      } finally {
        testingProxyIds = new Set();
        renderProxies();
      }
    }

    batchTestButton.addEventListener('click', async () => {
      const concurrency = Math.max(1, Math.min(Number(concurrencyInput.value) || 20, 50));
      concurrencyInput.value = concurrency;
      try { await runBatchTest([...selectedProxyIds], concurrency); }
      catch (error) { toast(error.message, 'error'); await reload(); }
    });

    const importText = importForm.querySelector('[data-proxy-import-text]');
    const importFile = importForm.querySelector('[data-proxy-import-file]');
    const importFileName = importForm.querySelector('[data-proxy-import-file-name]');
    const importCount = importForm.querySelector('[data-proxy-import-count]');
    const importResult = importForm.querySelector('[data-proxy-import-result]');
    const importSubmit = importForm.querySelector('[data-proxy-import-submit]');
    const updateImportCount = () => {
      const count = importText.value.split(/\r?\n/).filter((line) => line.trim()).length;
      importCount.textContent = `${count.toLocaleString('zh-CN')} 行`;
    };
    document.querySelector('[data-proxy-import]').addEventListener('click', () => {
      importForm.reset();
      importForm.enabled.checked = true;
      importForm.test_after_import.checked = true;
      importForm.concurrency.value = concurrencyInput.value;
      importFileName.textContent = '未选择文件';
      importResult.hidden = true;
      updateImportCount();
      openDrawer(importDrawer);
      importText.focus();
    });
    importText.addEventListener('input', updateImportCount);
    importFile.addEventListener('change', async () => {
      const file = importFile.files[0];
      if (!file) return;
      if (file.size > 1_000_000) {
        importFile.value = '';
        importFileName.textContent = '文件不能超过 1 MB';
        toast('导入文件不能超过 1 MB', 'error');
        return;
      }
      importText.value = await file.text();
      importFileName.textContent = file.name;
      updateImportCount();
    });
    importForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      importSubmit.disabled = true;
      importResult.hidden = true;
      const concurrency = Math.max(1, Math.min(Number(importForm.concurrency.value) || 20, 50));
      const testAfterImport = importForm.test_after_import.checked;
      const enableAfterTest = importForm.enabled.checked;
      importForm.concurrency.value = concurrency;
      concurrencyInput.value = concurrency;
      try {
        const result = await api('/admin/api/proxies/import', {
          method: 'POST', body: { text: importText.value, enabled: enableAfterTest && !testAfterImport }
        });
        selectedProxyIds = new Set(result.created_ids);
        await reload();
        let message = `已导入 ${result.created} 个，跳过重复 ${result.duplicates} 个，错误 ${result.errors.length} 行。`;
        if (testAfterImport && result.created_ids.length) {
          const tested = await runBatchTest(result.created_ids, concurrency, enableAfterTest);
          message += ` 测试可用 ${tested.healthy} 个，失败 ${tested.failed} 个。`;
        }
        if (result.errors.length) {
          message += `\n${result.errors.slice(0, 5).map((item) => `第 ${item.line} 行：${item.message}`).join('\n')}`;
          if (result.errors.length > 5) message += `\n另有 ${result.errors.length - 5} 行错误。`;
          importResult.className = 'connection-result import-result warning';
          importResult.textContent = message;
          importResult.hidden = false;
        } else {
          closeDrawers();
        }
        toast(message.split('\n')[0], result.errors.length ? 'warning' : '');
      } catch (error) {
        importResult.className = 'connection-result import-result failed';
        importResult.textContent = error.message;
        importResult.hidden = false;
        toast(error.message, 'error');
      } finally { importSubmit.disabled = false; }
    });
    try { await reload(); } catch (error) { toast(error.message, 'error'); }
  }
})();
