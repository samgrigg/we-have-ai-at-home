const $ = (id) => document.getElementById(id);
let current = localStorage.getItem('household-conversation');
let busy = false;
let polling = false;
let pending = null;
let lastRender = '';
let conversations = [];

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {'Content-Type': 'application/json', ...options.headers},
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try { const body = await response.json(); if (typeof body.detail === 'string') message = body.detail; } catch {}
    throw new Error(message);
  }
  return response.json();
}

function notice(message = '') { $('notice').textContent = message; }
function setBusy(value) {
  busy = value;
  $('send').disabled = value || Boolean(pending);
  $('message').disabled = value || Boolean(pending);
  $('new-chat').disabled = Boolean(pending);
}

function retryButton(label, callback) {
  const button = document.createElement('button');
  button.textContent = label;
  button.onclick = async () => {
    button.disabled = true;
    try { await callback(); } catch (error) { notice(error.message); }
    finally { button.disabled = false; }
  };
  $('retry-area').append(button);
}

function submissionControls() {
  retryButton('Resend message', sendPending);
  retryButton('Keep editing message', async () => {
    const content = pending.body.content;
    pending = null;
    sessionStorage.removeItem('household-pending');
    $('message').value = content;
    notice();
    lastRender = '';
    await loadConversations();
    await refresh();
    $('message').focus();
  });
}

async function loadConversations() {
  conversations = await api('/api/conversations');
  if (!conversations.some((c) => c.id === current)) current = conversations[0]?.id || null;
  $('conversations').replaceChildren();
  for (const c of conversations) {
    const button = document.createElement('button');
    button.textContent = c.title;
    button.className = c.id === current ? 'active' : '';
    button.disabled = Boolean(pending);
    button.onclick = async () => {
      current = c.id; lastRender = '';
      localStorage.setItem('household-conversation', current);
      try { await loadConversations(); await refresh(); } catch (error) { notice(error.message); }
    };
    $('conversations').append(button);
  }
  $('chat-title').textContent = conversations.find((c) => c.id === current)?.title || 'Your household assistant';
}

function bubble(role, text) {
  const div = document.createElement('div');
  div.className = `message ${role}`;
  const label = document.createElement('span');
  label.className = 'speaker'; label.textContent = role === 'user' ? 'You' : 'Household';
  const content = document.createElement('span'); content.textContent = text;
  div.append(label, content); $('messages').append(div);
}

async function refresh() {
  if (polling) return;
  polling = true;
  const cid = current;
  try {
    const [jobs, items] = await Promise.all([
      cid ? api(`/api/conversations/${cid}/messages`) : Promise.resolve([]),
      api('/api/shopping-list'),
    ]);
    if (cid !== current) return;
    const signature = JSON.stringify(jobs);
    if (signature !== lastRender) {
      $('messages').replaceChildren(); $('retry-area').replaceChildren();
      for (const job of jobs) {
        bubble('user', job.content);
        if (job.response) bubble('assistant', job.response);
        if (job.status !== 'completed') {
          const status = document.createElement('p');
          status.className = `job-state ${job.status}`;
          status.textContent = job.status === 'failed' ? job.error : job.status === 'queued' ? 'Waiting for the assistant…' : 'Working on it…';
          $('messages').append(status);
        }
      }
      $('messages').scrollTop = $('messages').scrollHeight;
      lastRender = signature;
    }
    // Keep both kinds of recovery available when another tab submitted first.
    $('retry-area').replaceChildren();
    for (const job of jobs) {
      if (job.status === 'failed') retryButton('Retry request', async () => {
        await api(`/api/jobs/${job.id}/retry`, {method: 'POST'}); lastRender = ''; await refresh();
      });
    }
    if (pending) submissionControls();
    setBusy(jobs.some((j) => j.status !== 'completed'));
    $('shopping-list').replaceChildren();
    for (const item of items) {
      const li = document.createElement('li'); li.textContent = item.name; $('shopping-list').append(li);
    }
    if (!items.length) {
      const li = document.createElement('li'); li.className = 'empty';
      li.textContent = 'Your list is empty. Add something in chat.'; $('shopping-list').append(li);
    }
  } finally { polling = false; }
}

async function createConversation(title = 'New conversation') {
  const c = await api('/api/conversations', {method: 'POST', body: JSON.stringify({title})});
  current = c.id; lastRender = '';
  localStorage.setItem('household-conversation', current);
  $('messages').replaceChildren(); $('retry-area').replaceChildren();
  await loadConversations();
}

$('new-chat').onclick = async () => {
  try { await createConversation(); await refresh(); notice(); $('message').focus(); }
  catch (error) { notice(error.message); }
};

async function sendPending() {
  try {
    await api(`/api/conversations/${pending.cid}/messages`, {
      method: 'POST', body: JSON.stringify(pending.body),
    });
    pending = null; sessionStorage.removeItem('household-pending');
    $('message').value = ''; $('retry-area').replaceChildren(); notice();
    await loadConversations(); await refresh();
  } catch (error) {
    notice(`${error.message}. Your message is saved in this tab; retry uses the same request ID.`);
    $('retry-area').replaceChildren();
    submissionControls();
    setBusy(busy);
  }
}

$('composer').onsubmit = async (event) => {
  event.preventDefault();
  const content = $('message').value.trim();
  if (!content || busy || pending) return;
  setBusy(true);
  try {
    if (!current) await createConversation(content.slice(0, 60));
    pending = {cid: current, body: {request_id: crypto.randomUUID(), content}};
    sessionStorage.setItem('household-pending', JSON.stringify(pending));
    await sendPending();
  } catch (error) { notice(error.message); setBusy(false); }
};

$('message').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); $('composer').requestSubmit(); }
});

async function start() {
  try {
    pending = JSON.parse(sessionStorage.getItem('household-pending') || 'null');
    if (pending) current = pending.cid;
    await loadConversations(); await refresh();
    if (pending) {
      notice('An unsent message was recovered. Resend it to check its status safely.');
      setBusy(busy);
    }
  } catch (error) { notice(error.message); }
  setInterval(() => { refresh().catch((error) => notice(error.message)); }, 1500);
}
start();
