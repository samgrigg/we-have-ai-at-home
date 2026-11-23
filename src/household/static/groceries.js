// Grocery workspace state is independent of the selected chat conversation.
let commandCid = null;
let commandPending = null;
let commandBusy = false;
let commandSending = false;
let grocerySignature = '';
let groceryItems = [];
let groceryEditor = null;
let groceryMutation = false;
let commandJobs = [];
let chatReturnFocus = null;
let chatMedia = null;
let commandControlSignature = '';

function clearGroceryState() {
  commandCid = null; commandPending = null; commandBusy = false; commandSending = false;
  commandControlSignature = '';
  $('list-count').textContent = ''; $('picked-up-count').textContent = '0';
  commandJobs = []; grocerySignature = ''; groceryItems = []; groceryEditor = null;
  groceryMutation = false;
  for (const id of ['picked-up-list', 'command-recipes', 'command-retry']) $(id).replaceChildren();
  for (const id of ['command-response', 'command-notice', 'grocery-notice']) $(id).textContent = '';
  $('command').value = ''; $('command').disabled = false; $('command-send').disabled = false;
  sessionStorage.removeItem('household-command-pending');
  setChatOpen(false);
}

async function loadCommandConversation() {
  const epoch = identityEpoch;
  const context = await api('/api/grocery-commands', {method: 'POST'});
  requireEpoch(epoch);
  commandCid = context.id;
}

function commandControls() {
  $('command-send').disabled = commandBusy || commandSending || Boolean(commandPending);
  $('command').disabled = commandBusy || commandSending || Boolean(commandPending);
  const signature = JSON.stringify([commandPending,commandJobs.filter(j=>j.status==='failed').map(j=>j.id)]);
  if (signature === commandControlSignature) return;
  commandControlSignature = signature;
  $('command-retry').replaceChildren();
  const button = (label, action) => {
    const el = document.createElement('button'); el.textContent = label;
    el.onclick = async () => {
      const epoch = identityEpoch;
      el.disabled = true;
      try { await action(); }
      catch (error) { if (!error.stale && epoch === identityEpoch) $('command-notice').textContent = error.message; }
      finally { if (epoch === identityEpoch) el.disabled = false; }
    };
    $('command-retry').append(el);
  };
  for (const job of commandJobs.filter(j => j.status === 'failed')) {
    button('Retry request', async () => { await api(`/api/jobs/${job.id}/retry`, {method:'POST'}); await refresh(); });
    button('Skip failed request', async () => { await api(`/api/jobs/${job.id}/cancel`, {method:'POST'}); await refresh(); });
  }
  if (commandPending) {
    button('Resend command', sendCommandPending);
    button('Keep editing command', async () => {
      $('command').value = commandPending.body.content;
      commandPending = null; sessionStorage.removeItem('household-command-pending');
      $('command-notice').textContent = ''; commandControls(); $('command').focus();
    });
  }
}

async function sendCommandPending() {
  if (commandSending || !commandPending) return;
  const epoch = identityEpoch;
  const submission = commandPending;
  commandSending = true; commandControls();
  try {
    await api(`/api/conversations/${submission.cid}/messages`, {method:'POST',body:JSON.stringify(submission.body)});
    requireEpoch(epoch);
    commandPending = null; sessionStorage.removeItem('household-command-pending');
    $('command').value = ''; $('command-notice').textContent = '';
    commandBusy = true;
    await refresh();
  } catch (error) {
    if (!error.stale && epoch === identityEpoch && currentUser) {
      $('command-notice').textContent = `${error.message}. Your command is saved in this tab; resend uses the same request ID.`;
    }
  } finally {
    if (epoch === identityEpoch) { commandSending = false; commandControls(); }
  }
}

async function submitCommand(event) {
  event.preventDefault();
  const content = $('command').value.trim();
  if (!content || commandBusy || commandSending || commandPending) return;
  const epoch = identityEpoch;
  commandSending = true; commandControls();
  try {
    if (!commandCid) await loadCommandConversation();
    requireEpoch(epoch);
    commandPending = {cid:commandCid,user_id:currentUser.id,body:{request_id:crypto.randomUUID(),content}};
    sessionStorage.setItem('household-command-pending', JSON.stringify(commandPending));
    commandSending = false;
    await sendCommandPending();
  } catch (error) {
    if (!error.stale && epoch === identityEpoch) {
      commandSending = false; $('command-notice').textContent = error.message; commandControls();
    }
  }
}

async function refreshCommands() {
  if (!commandCid) return;
  const epoch = identityEpoch;
  const cid = commandCid;
  const [jobs, recipes] = await Promise.all([
    api(`/api/conversations/${cid}/messages`), api(`/api/conversations/${cid}/recipe-imports`),
  ]);
  requireEpoch(epoch);
  if (cid !== commandCid) return;
  commandJobs = jobs;
  commandBusy = jobs.some(j => !['completed','cancelled'].includes(j.status));
  const latest = jobs[jobs.length - 1];
  $('command-response').textContent = latest ? (
    latest.status === 'failed' ? (latest.error || 'This request needs another try.') :
    latest.status === 'cancelled' ? 'Request skipped. Any completed grocery changes remain saved.' :
    latest.status === 'queued' ? 'On the list to do…' :
    latest.status === 'processing' ? 'Bridget is working on it…' : latest.response || ''
  ) : '';
  renderRecipes(recipes, cid, 'command-recipes');
  commandControls();
}

function groceryError(error) {
  if (!error.stale) $('grocery-notice').textContent = error.message;
}

async function mutateGrocery(item, changes, method = 'PATCH') {
  const epoch = identityEpoch;
  groceryMutation = true;
  try {
    const saved = await api('/api/shopping-list', {method,body:JSON.stringify({name:item.name,revision:item.revision,...changes})});
    requireEpoch(epoch);
    if (groceryEditor?.item === item && (method === 'DELETE' || changes.new_name !== undefined)) groceryEditor = null;
    if (saved?.revision) Object.assign(item, saved);
    grocerySignature = ''; $('grocery-notice').textContent = '';
    groceryMutation = false;
    await refresh();
    return true;
  } catch (error) {
    if (epoch !== identityEpoch || error.stale) return false;
    groceryError(error);
    groceryMutation = false;
    if (error.status === 409) {
      // Rebase only after showing the conflict. The next explicit Save uses this revision.
      let items;
      try { items = await api('/api/shopping-list'); requireEpoch(epoch); }
      catch (reloadError) { if (!reloadError.stale && epoch === identityEpoch) groceryError(reloadError); return false; }
      groceryItems = items;
      const latest = items.find(i => i.name === item.name);
      if (latest) Object.assign(item, latest);
      if (groceryEditor?.item === item) {
        groceryEditor.status.textContent = latest ? `${error.message} Latest item: ${latest.name}. Review your draft, then Save again.` : 'This item was removed or renamed. Your draft is kept below; cancel to see the latest list.';
        groceryEditor.save.disabled = !latest;
        groceryEditor.blocked = !latest;
      } else { grocerySignature = ''; renderGroceryItems(items); }
    }
    return false;
  } finally { if (epoch === identityEpoch) groceryMutation = false; }
}

function renderGroceryItems(items) {
  groceryItems = items;
  const signature = JSON.stringify(items);
  if (signature === grocerySignature || groceryEditor || groceryMutation) return;
  grocerySignature = signature;
  $('shopping-list').replaceChildren(); $('picked-up-list').replaceChildren();
  const active = items.filter(i => !i.checked);
  $('list-count').textContent = `${active.length} ${active.length === 1 ? 'item' : 'items'} to pick up`;
  $('picked-up-count').textContent = String(items.length - active.length);
  for (const item of items) {
    const li = document.createElement('li'); li.className = 'grocery-item' + (item.checked ? ' is-checked' : '');
    const check = document.createElement('input'); check.type = 'checkbox'; check.checked = item.checked;
    check.setAttribute?.('aria-label', `${item.checked ? 'Uncheck' : 'Mark picked up'} ${item.name}`);
    check.onchange = async () => {
      check.disabled = true;
      const desired = !item.checked;
      const ok = await mutateGrocery(item, {checked:desired});
      if (ok) { item.checked = desired; check.checked = desired; }
      else check.checked = item.checked;
      check.disabled = false;
      li.className = 'grocery-item' + (item.checked ? ' is-checked' : '');
      check.setAttribute?.('aria-label', `${item.checked ? 'Uncheck' : 'Mark picked up'} ${item.name}`);
    };
    const text = document.createElement('div'); text.className = 'item-copy';
    const name = document.createElement('span'); name.className = 'item-name'; name.textContent = item.name;
    const by = document.createElement('small'); by.className = 'item-author'; by.textContent = item.added_by_name ? `Added by ${item.added_by_name}` : 'Shared with family';
    text.append(name, by);
    if (item.product_selection) {
      const selected = item.product_selection;
      const details = document.createElement('p'); details.className = 'selected-product';
      details.textContent = `${selected.packages} × ${selected.product.description} (${selected.product.size}) · Chosen by ${selected.selected_by_name} · Price observed ${new Date(selected.checked_at).toLocaleString()}`;
      text.append(details);
    }
    const find = document.createElement('button'); find.className = 'product-link'; find.textContent = item.product_selection ? 'Change product' : 'Find at Smith’s';
    find.onclick = () => openProductSearch(item).then(() => $('product-search').scrollIntoView?.({behavior:'smooth',block:'nearest'})).catch(groceryError);
    const edit = document.createElement('button'); edit.className = 'quiet'; edit.textContent = 'Edit';
    edit.onclick = () => {
      if (groceryEditor) { groceryEditor.input.focus(); return; }
      const form = document.createElement('form'); form.className = 'item-editor';
      const input = document.createElement('input'); input.type = 'text'; input.value = item.name; input.maxLength = 120; input.required = true; input.setAttribute?.('aria-label','Item and quantity');
      const help = document.createElement('p'); help.textContent = 'Include the quantity, e.g. “2 cups milk”. Changing this clears its product choice.';
      const save = document.createElement('button'); save.type = 'submit'; save.textContent = 'Save'; save.className = 'primary';
      const cancel = document.createElement('button'); cancel.type = 'button'; cancel.textContent = 'Cancel';
      const status = document.createElement('p'); status.setAttribute?.('role','status');
      groceryEditor = {item,input,status,save,blocked:false};
      form.onsubmit = async event => {
        event.preventDefault();
        if (!input.value.trim() || groceryMutation) return;
        save.disabled = true;
        await mutateGrocery(item, {new_name:input.value.trim()});
        if (groceryEditor) save.disabled = groceryEditor.blocked;
      };
      cancel.onclick = () => { groceryEditor = null; grocerySignature = ''; renderGroceryItems(groceryItems); };
      form.append(input,help,save,cancel,status); li.append(form); input.focus();
    };
    const remove = document.createElement('button'); remove.className = 'remove-item'; remove.textContent = 'Remove'; remove.setAttribute?.('aria-label',`Remove ${item.name}`);
    remove.onclick = async () => { remove.disabled = true; const ok = await mutateGrocery(item, {}, 'DELETE'); if (ok) li.hidden = true; remove.disabled = false; };
    li.append(check,text,find,edit,remove);
    $(item.checked ? 'picked-up-list' : 'shopping-list').append(li);
  }
  if (!active.length) {
    const empty = document.createElement('li'); empty.className = 'empty';
    empty.textContent = items.length ? 'All picked up. Nicely done!' : 'A fresh start. Tell Bridget what to pick up above.';
    $('shopping-list').append(empty);
  }
}

function setChatOpen(open) {
  const panel = $('chat-panel');
  if (open && panel.hidden) chatReturnFocus = document.activeElement;
  panel.hidden = !open;
  $('open-chat').setAttribute?.('aria-expanded', String(open));
  const mobile = chatMedia?.matches || false;
  $('chat-backdrop').hidden = !open || !mobile;
  panel.setAttribute?.('role', mobile ? 'dialog' : 'complementary');
  if (mobile && open) panel.setAttribute?.('aria-modal','true'); else panel.removeAttribute?.('aria-modal');
  if (document.body) document.body.style.overflow = open && mobile ? 'hidden' : '';
  for (const surface of document.querySelectorAll?.('.app-header, .app-shell') || []) surface.inert = open && mobile;
  if (open) $('close-chat').focus(); else if (chatReturnFocus) chatReturnFocus.focus();
}

function initGroceries() {
  $('chat-panel').hidden = true;
  $('open-chat').onclick = () => setChatOpen($('chat-panel').hidden);
  $('close-chat').onclick = () => setChatOpen(false);
  $('chat-backdrop').onclick = () => setChatOpen(false);
  chatMedia = typeof matchMedia === 'function' ? matchMedia('(max-width: 700px)') : null;
  chatMedia?.addEventListener('change', () => { if (!$('chat-panel').hidden) setChatOpen(true); });
  document.addEventListener?.('keydown', event => {
    if ($('chat-panel').hidden) return;
    if (event.key === 'Escape') { event.preventDefault(); setChatOpen(false); }
    if (event.key === 'Tab' && chatMedia?.matches) {
      const nodes = [...$('chat-panel').querySelectorAll('button:not(:disabled),a[href],textarea:not(:disabled),input:not(:disabled)')].filter(el=>el.getClientRects().length);
      const first = nodes[0], last = nodes[nodes.length-1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
  });
  $('command-form').onsubmit = submitCommand;
  $('command').addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); $('command-form').requestSubmit(); }
  });
}
