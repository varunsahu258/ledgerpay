const $ = (id) => document.getElementById(id);
const state = { accounts: [], accountCursor: null, historyCursor: null };
const idempotencyInput = $("idempotency-key");

function newKey() {
  idempotencyInput.value = crypto.randomUUID();
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}

function showNotice(message, isError = false) {
  const box = $("notice");
  box.textContent = message;
  box.classList.toggle("error", isError);
  box.hidden = false;
  clearTimeout(showNotice.timer);
  showNotice.timer = setTimeout(() => { box.hidden = true; }, 6000);
}

async function request(url, options = {}) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.message || body.detail || `Request failed (${response.status})`);
  return body;
}

function accountOption(account) {
  return `<option value="${account.id}">#${account.id} · ${escapeHtml(account.owner_name)} · ${escapeHtml(account.currency)} ${account.balance_minor.toLocaleString()} minor</option>`;
}

async function loadAccounts({ append = false } = {}) {
  const url = new URL("/accounts", location.origin);
  url.searchParams.set("limit", "100");
  if (append && state.accountCursor) url.searchParams.set("cursor", state.accountCursor);
  const page = await request(url);
  state.accounts = append ? [...state.accounts, ...page.items] : page.items;
  state.accountCursor = page.next_cursor;
  $("account-rows").innerHTML = state.accounts.length ? state.accounts.map((a) => `
    <tr><td><span class="account-id">#${a.id}</span></td><td>${escapeHtml(a.owner_name)}</td><td><span class="currency-pill">${escapeHtml(a.currency)}</span></td><td class="right amount">${a.balance_minor.toLocaleString()}</td><td class="date">${new Date(a.created_at).toLocaleDateString()}</td></tr>`).join("") : '<tr><td colspan="5" class="empty">No accounts yet. Create one with the API or run <code>make demo</code>.</td></tr>';
  $("account-count").textContent = state.accounts.length.toLocaleString();
  $("currency-count").textContent = new Set(state.accounts.map((a) => a.currency)).size.toLocaleString();
  $("account-page-label").textContent = state.accountCursor ? `Showing ${state.accounts.length} accounts` : `Showing ${state.accounts.length} account${state.accounts.length === 1 ? "" : "s"}`;
  $("load-more").hidden = !state.accountCursor;
  const selects = [$("from-account"), $("to-account"), $("history-account")];
  const prev = selects.map((select) => select.value);
  selects[0].innerHTML = '<option value="">Select source</option>' + state.accounts.map(accountOption).join("");
  selects[1].innerHTML = '<option value="">Select destination</option>' + state.accounts.map(accountOption).join("");
  selects[2].innerHTML = '<option value="">Select account</option>' + state.accounts.map(accountOption).join("");
  selects.forEach((select, i) => { if (prev[i]) select.value = prev[i]; });
}

async function checkHealth() {
  const dot = $("health-dot");
  try {
    await request("/health");
    dot.className = "ok";
    $("health-label").textContent = "API connected";
  } catch {
    dot.className = "bad";
    $("health-label").textContent = "API unavailable";
  }
}

async function loadHistory({ append = false } = {}) {
  const accountId = $("history-account").value;
  if (!accountId) return showNotice("Choose an account first.", true);
  const url = new URL(`/accounts/${accountId}/transactions`, location.origin);
  url.searchParams.set("limit", "25");
  if (append && state.historyCursor) url.searchParams.set("cursor", state.historyCursor);
  if ($("start-date").value) url.searchParams.set("start_date", $("start-date").value);
  if ($("end-date").value) url.searchParams.set("end_date", $("end-date").value);
  try {
    const page = await request(url);
    state.historyCursor = page.next_cursor;
    const entries = page.items || [];
    const html = entries.map((entry) => `
      <article class="history-item"><strong>Transfer ${escapeHtml(entry.transfer_id.slice(0, 8))}…</strong><span class="amount ${entry.amount_minor < 0 ? "negative" : "positive"}">${entry.amount_minor > 0 ? "+" : ""}${entry.amount_minor.toLocaleString()}</span>
      <small>${new Date(entry.created_at).toLocaleString()} · ${entry.from_account} → ${entry.to_account}</small>
      <button class="text-button reverse" data-transfer="${escapeHtml(entry.transfer_id)}" type="button">Reverse transfer ↶</button></article>`).join("");
    $("history-list").innerHTML = append ? $("history-list").innerHTML + html : (html || '<p class="empty">No ledger entries in this date range.</p>');
    $("history-more").hidden = !state.historyCursor;
    $("history-list").querySelectorAll(".reverse").forEach((button) => button.addEventListener("click", () => reverseTransfer(button.dataset.transfer)));
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function reverseTransfer(transferId) {
  if (!confirm(`Create a new transfer reversing ${transferId}? This cannot be undone.`)) return;
  try {
    const result = await request(`/transfers/${transferId}/reverse`, {
      method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() },
    });
    showNotice(`Reversal recorded · transfer ${result.id}`);
    await loadAccounts();
    state.historyCursor = null;
    await loadHistory();
  } catch (error) { showNotice(error.message, true); }
}

$("refresh-accounts").addEventListener("click", () => loadAccounts().catch((e) => showNotice(e.message, true)));
$("load-more").addEventListener("click", () => loadAccounts({ append: true }).catch((e) => showNotice(e.message, true)));
$("show-account-form").addEventListener("click", () => { $("account-form").hidden = !$("account-form").hidden; });
$("account-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await request("/accounts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ owner_name: $("owner-name").value, currency: $("currency").value }) });
    showNotice("Account created with a zero balance.");
    $("account-form").reset();
    $("account-form").hidden = true;
    await loadAccounts();
  } catch (error) { showNotice(error.message, true); }
});
$("new-key").addEventListener("click", newKey);
$("swap-accounts").addEventListener("click", () => {
  const from = $("from-account"); const to = $("to-account"); const current = from.value;
  from.value = to.value; to.value = current;
});
$("load-history").addEventListener("click", () => { state.historyCursor = null; loadHistory(); });
$("history-more").addEventListener("click", () => loadHistory({ append: true }));
$("history-account").addEventListener("change", () => { state.historyCursor = null; $("history-list").innerHTML = '<p class="empty">Select “Load transactions” to fetch this account’s ledger entries.</p>'; });
$("transfer-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const amount = Number($("amount").value);
  if (!Number.isSafeInteger(amount) || amount < 1) {
    showNotice("Enter a positive whole minor-unit amount within JavaScript's safe integer range.", true);
    return;
  }
  const submit = $("submit-transfer");
  submit.disabled = true; submit.textContent = "Sending…";
  try {
    const result = await request("/transfers", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyInput.value.trim() },
      body: JSON.stringify({ from_account: Number($("from-account").value), to_account: Number($("to-account").value), amount_minor: amount }),
    });
    showNotice(`Transfer ${result.status} · ${result.amount_minor.toLocaleString()} minor units · ${result.id}`);
    newKey();
    await loadAccounts();
  } catch (error) { showNotice(error.message, true); }
  finally { submit.disabled = false; submit.innerHTML = 'Send transfer <span>→</span>'; }
});

newKey();
checkHealth();
loadAccounts().catch((error) => showNotice(error.message, true));
