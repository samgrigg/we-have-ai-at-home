const $ = (id) => document.getElementById(id);
let current = localStorage.getItem('household-conversation');
let busy = false;
let polling = false;
let pending = null;
let lastRender = '';
let conversations = [];
let currentUser = null;
let csrfToken = null;
let identityEpoch = 0;
let productRequest = 0;
let productItem = null;
let lastRecipeRender = "";
const recipeSelections = new Map();

function requireEpoch(epoch) {
  if (epoch !== identityEpoch) {
    const error = new Error('Account changed; discarded an outdated response');
    error.stale = true; throw error;
  }
}
function reportError(error) { if (!error.stale) notice(error.message); }

function clearSensitiveState() {
  identityEpoch++; closeProductSearch(); lastRecipeRender = ""; recipeSelections.clear();
  current = null; pending = null; conversations = []; lastRender = ''; csrfToken = null;
  for (const id of ['messages','shopping-list','conversations','retry-area','recipe-imports']) $(id).replaceChildren();
  $('message').value = ''; $('current-user').textContent = ''; $('chat-title').textContent = '';
  $('scope-label').textContent = '';
  sessionStorage.removeItem('household-pending');
  localStorage.removeItem('household-conversation');
}

async function loadIdentity() {
  const epoch = identityEpoch;
  const identity = await api('/api/me');
  requireEpoch(epoch);
  const changed = currentUser && identity.id !== currentUser.id;
  if (changed) clearSensitiveState();
  currentUser = identity; csrfToken = identity.csrf_token;
  $('current-user').textContent = identity.display_name;
  return changed;
}

async function api(path, options = {}) {
  const epoch = identityEpoch;
  const response = await fetch(path, {
    ...options,
    headers: {'Content-Type': 'application/json', ...(csrfToken ? {'X-CSRF-Token':csrfToken} : {}), ...options.headers},
  });
  requireEpoch(epoch);
  if (!response.ok) {
    if (response.status === 401) {
      clearSensitiveState(); currentUser = null; setBusy(true);
      location.assign('/signin');
    }
    let message = `Request failed (${response.status})`;
    try { const body = await response.json(); if (typeof body.detail === 'string') message = body.detail; } catch {}
    throw new Error(message);
  }
  if (response.status === 204) return null;
  const data = await response.json();
  requireEpoch(epoch);
  return data;
}

function notice(message = '') { $('notice').textContent = message; }
function setBusy(value) {
  busy = value;
  const archived = conversations.find(c => c.id === current)?.visibility === 'legacy_shared';
  $('send').disabled = value || Boolean(pending) || archived;
  $('message').disabled = value || Boolean(pending) || archived;
  $('new-chat').disabled = Boolean(pending);
}

function retryButton(label, callback) {
  const button = document.createElement('button');
  button.textContent = label;
  button.onclick = async () => {
    button.disabled = true;
    try { await callback(); } catch (error) { reportError(error); }
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
  const epoch = identityEpoch;
  const loaded = await api('/api/conversations');
  requireEpoch(epoch);
  conversations = loaded;
  if (!conversations.some((c) => c.id === current)) current = conversations.find(c => c.visibility === 'private')?.id || conversations.find(c => c.visibility === 'family')?.id || conversations[0]?.id || null;
  $('conversations').replaceChildren();
  for (const [visibility, label] of [['private','My chats'],['family','Family chat'],['legacy_shared','POC archive']]) {
    const group = conversations.filter(c => c.visibility === visibility);
    if (!group.length) continue;
    const heading = document.createElement('p'); heading.className='nav-group'; heading.textContent=label;
    $('conversations').append(heading);
    for (const c of group) {
    const button = document.createElement('button');
    button.textContent = c.title;
    button.className = c.id === current ? 'active' : '';
    button.disabled = Boolean(pending);
    button.onclick = async () => {
      current = c.id; lastRender = ''; lastRecipeRender = ''; recipeSelections.clear(); $('recipe-imports').replaceChildren();
      localStorage.setItem('household-conversation', current);
      try { await loadConversations(); await refresh(); } catch (error) { reportError(error); }
    };
    $('conversations').append(button);
    }
  }
  $('chat-title').textContent = conversations.find((c) => c.id === current)?.title || 'Your household assistant';
  const scope = conversations.find(c => c.id === current)?.visibility;
  $('scope-label').textContent = scope === 'family' ? 'Shared with all five family members' : scope === 'legacy_shared' ? 'Shared POC archive · read-only' : 'Personal chat · visible only to you';
}

function bubble(role, text, author = 'You') {
  const div = document.createElement('div');
  div.className = `message ${role}`;
  const label = document.createElement('span');
  label.className = 'speaker'; label.textContent = role === 'user' ? author : 'Household';
  const content = document.createElement('span'); content.textContent = text;
  div.append(label, content); $('messages').append(div);
}


function renderRecipes(recipes, cid) {
  const signature = JSON.stringify([cid,recipes]);
  if (signature === lastRecipeRender) return;
  lastRecipeRender = signature;
  $('recipe-imports').replaceChildren();
  for (const recipe of recipes) {
    if (recipe.status === 'dismissed') continue;
    const card = document.createElement('article'); card.className='recipe-preview';
    const title = document.createElement('h3'); title.textContent=recipe.title;
    const source = document.createElement('a'); source.href=recipe.source_url;
    source.target='_blank'; source.rel='noopener noreferrer'; source.textContent='View source recipe';
    const description = document.createElement('p');
    description.textContent=`Original yield: ${recipe.recipe_yield} · Quantities ×${recipe.multiplier}. Review package sizes and optional ingredients.`;
    card.append(title,source,description);
    const selections=[];
    recipe.ingredients.forEach((item,index)=>{
      const label=document.createElement('label'); label.className='recipe-ingredient';
      const box=document.createElement('input'); box.type='checkbox';
      const version=JSON.stringify([recipe.ingredients,recipe.multiplier]);
      if(recipeSelections.get(recipe.id)?.version!==version) recipeSelections.set(recipe.id,{version,selected:recipe.ingredients.map(i=>i.selected)});
      box.checked=recipe.status==='confirmed'?recipe.confirmed_indices.includes(index):recipeSelections.get(recipe.id).selected[index];
      box.onchange=()=>{recipeSelections.get(recipe.id).selected[index]=box.checked;};
      box.disabled=recipe.status!=='draft' || !recipe.can_confirm;
      const text=document.createElement('span');
      const normalized=item.text.toLowerCase();
      const overlap=recipe.existing_items.some(existing=>normalized.includes(existing.toLowerCase()) || existing.toLowerCase().includes(normalized));
      text.textContent=item.text+(overlap?' · Possible overlap on your list':'')+(item.check_quantity?' · Check quantity':'');
      label.append(box,text); card.append(label); selections.push([index,box]);
    });
    const status=document.createElement('p'); status.className='muted';
    status.textContent=recipe.status==='confirmed'?'Ingredients added to the shared list.':recipe.can_confirm?'Uncheck anything you already have. Only selected ingredients will be added.':'Waiting for the completed preview; only the requesting member can confirm.';
    card.append(status);
    if(recipe.status==='draft' && recipe.can_confirm){
      const confirm=document.createElement('button'); confirm.className='primary'; confirm.textContent='Confirm ingredients';
      const dismiss=document.createElement('button'); dismiss.textContent='Dismiss recipe';
      const epoch=identityEpoch;
      const act=async(action)=>{
        requireEpoch(epoch);
        confirm.disabled=true; dismiss.disabled=true;
        try {
          const selected_indices=selections.filter(([,box])=>box.checked).map(([index])=>index);
          if(action==='confirm' && !selected_indices.length) throw new Error('Select at least one ingredient.');
          await api(`/api/recipe-imports/${recipe.id}/${action}`,{method:'POST',...(action==='confirm'?{body:JSON.stringify({selected_indices})}:{})});
          requireEpoch(epoch);
          if(cid!==current)return;
          lastRecipeRender=''; await refresh();
        }catch(error){reportError(error);}
        finally{confirm.disabled=false; dismiss.disabled=false;}
      };
      confirm.onclick=()=>act('confirm'); dismiss.onclick=()=>act('dismiss');
      card.append(confirm,dismiss);
    }
    $('recipe-imports').append(card);
  }
}


function closeProductSearch(){
  productRequest++; productItem=null;
  $('product-search').replaceChildren();
}
function productCurrent(epoch,request){
  requireEpoch(epoch);
  if(request!==productRequest){const error=new Error('Product search changed');error.stale=true;throw error;}
}
const money=value=>value===null?'Price unavailable':'$'+Number(value).toFixed(2);
async function openProductSearch(item){
  closeProductSearch(); productItem=item.name;
  const epoch=identityEpoch;
  const title=document.createElement('h3'); title.textContent='Products at your Smith’s';
  const original=document.createElement('p');original.textContent='Needed: '+item.name;
  const query=document.createElement('input');query.type='text';query.maxLength=100;query.placeholder='Ingredient search';query.value=item.requirement?.term||'';query.setAttribute?.('aria-label','Ingredient search');
  const search=document.createElement('button');search.textContent='Search';
  const close=document.createElement('button');close.textContent='Close';close.onclick=closeProductSearch;
  const results=document.createElement('div');results.id='product-results';
  $('product-search').append(title,original,query,search,close,results);
  const run=async()=>{
    const request=++productRequest;search.disabled=true;
    results.replaceChildren();const loading=document.createElement('p');loading.textContent='Finding package options…';results.append(loading);
    try{
      const body={item_name:item.name};if(query.value.trim())body.search_term=query.value.trim();
      const found=await api('/api/products/search',{method:'POST',body:JSON.stringify(body)});
      productCurrent(epoch,request);query.value=found.search_term;
      renderProductResults(found,epoch,request);
    }catch(error){
      if(!error.stale && epoch===identityEpoch && request===productRequest){results.replaceChildren();const note=document.createElement('p');note.textContent=error.message;results.append(note);}
    }finally{search.disabled=false;}
  };
  search.onclick=run;
  query.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();run();}});
  await run();
}
function renderProductResults(result,epoch,request){
  productCurrent(epoch,request);
  const results=$('product-results');results.replaceChildren();
  const observed=document.createElement('p');observed.className='muted';observed.textContent='Catalog checked '+new Date(result.checked_at).toLocaleString()+'. Review ingredients, package sizes and current shelf stock.';
  results.append(observed);
  if(!result.candidates.length){const note=document.createElement('p');note.textContent='No suitable matches found. Try a more specific ingredient name, or shop using the original list item.';results.append(note);}
  result.candidates.forEach((candidate,index)=>{
    const card=document.createElement('article');card.className='product-candidate';
    const title=document.createElement('h4');title.textContent=candidate.description+(candidate.preferred?' · Your usual choice':index===0 && candidate.selectable?' · Suggested option':'');
    const details=document.createElement('p');details.textContent=`${candidate.size} · ${money(candidate.price)} per package · Reported stock: ${candidate.stock}`;
    const quantity=document.createElement('input');quantity.type='number';quantity.min=String(candidate.packages||1);quantity.max='99';quantity.step='1';quantity.value=String(candidate.packages||1);quantity.setAttribute?.('aria-label','Number of packages');
    const label=document.createElement('label');label.textContent='Packages: ';label.append(quantity);
    const estimate=document.createElement('p');
    const update=()=>{
      const count=Number(quantity.value);
      const cost=candidate.price===null?null:candidate.price*count;
      const remaining=candidate.package_amount===null || candidate.package_amount===undefined?null:candidate.remaining+(count-candidate.packages)*candidate.package_amount;
      estimate.textContent=(candidate.quantity_review?'Quantity needs review; one package is a starting value, not a calculated recommendation. ':`Covers requirement; approximately ${Number(remaining.toFixed(2))} ${candidate.unit} left. `)+(cost===null?'Price unavailable.':`Estimated total: ${money(cost)}.`);
    };
    quantity.oninput=update;update();
    const remember=document.createElement('input');remember.type='checkbox';remember.checked=candidate.preferred;
    const preference=document.createElement('label');preference.textContent='Remember as our usual product ';preference.append(remember);
    const choose=document.createElement('button');choose.textContent='Select product';choose.disabled=!candidate.selectable;
    const status=document.createElement('p');status.className='muted';
    choose.onclick=async()=>{
      try{
        productCurrent(epoch,request);choose.disabled=true;
        const count=Number(quantity.value);
        if(!Number.isInteger(count)||count<Number(quantity.min)||count>99)throw new Error('Choose a valid package count that covers the requirement.');
        await api('/api/products/select',{method:'POST',body:JSON.stringify({search_id:result.id,candidate_id:candidate.candidate_id,packages:count,remember:remember.checked})});
        productCurrent(epoch,request);status.textContent='Product choice saved to the shared list.';
        await refresh();
      }catch(error){if(!error.stale)status.textContent=error.message;}
      finally{choose.disabled=!candidate.selectable;}
    };
    card.append(title,details,label,estimate,preference,choose,status);results.append(card);
  });
}

async function refresh() {
  if (polling) return;
  polling = true;
  try {
    if (await loadIdentity()) await loadConversations();
    const epoch = identityEpoch;
    const cid = current;
    const [jobs, items, recipes] = await Promise.all([
      cid ? api(`/api/conversations/${cid}/messages`) : Promise.resolve([]),
      api('/api/shopping-list'),
      cid ? api(`/api/conversations/${cid}/recipe-imports`) : Promise.resolve([]),
    ]);
    requireEpoch(epoch);
    if (cid !== current) return;
    renderRecipes(recipes, cid);
    const signature = JSON.stringify(jobs);
    if (signature !== lastRender) {
      $('messages').replaceChildren(); $('retry-area').replaceChildren();
      for (const job of jobs) {
        bubble('user', job.content, job.submitted_by === currentUser.id ? 'You' : job.author_name || 'POC member');
        if (job.response) bubble('assistant', job.response);
        if (job.status !== 'completed') {
          const status = document.createElement('p');
          status.className = `job-state ${job.status}`;
          status.textContent = job.status === 'cancelled' ? 'Request skipped. Any completed list changes remain saved.' : job.status === 'failed' ? job.error : job.status === 'queued' ? 'Waiting for the assistant…' : 'Working on it…';
          $('messages').append(status);
        }
      }
      $('messages').scrollTop = $('messages').scrollHeight;
      lastRender = signature;
    }
    // Keep both kinds of recovery available when another tab submitted first.
    $('retry-area').replaceChildren();
    for (const job of jobs) {
      if (job.status === 'failed') {
        retryButton('Retry request', async () => {
          await api(`/api/jobs/${job.id}/retry`, {method: 'POST'}); lastRender = ''; await refresh();
        });
        retryButton('Skip failed request', async () => {
          await api(`/api/jobs/${job.id}/cancel`, {method:'POST'}); lastRender=''; await refresh();
        });
      }
    }
    if (pending) submissionControls();
    setBusy(jobs.some((j) => !['completed','cancelled'].includes(j.status)));
    if(productItem && !items.some(item=>item.name===productItem)) closeProductSearch();
    $('shopping-list').replaceChildren();
    for (const item of items) {
      const li = document.createElement('li'); li.textContent = item.name;
      if (item.added_by_name) {
        const by = document.createElement('span'); by.className='item-author'; by.textContent='Added by '+item.added_by_name; li.append(by);
      }
      if(item.product_selection){
        const selected=item.product_selection;
        const details=document.createElement('p'); details.className='selected-product';
        details.textContent=`Selected: ${selected.packages} × ${selected.product.description} (${selected.product.size}). Price observed ${new Date(selected.checked_at).toLocaleString()}. Chosen by ${selected.selected_by_name}.`;
        li.append(details);
      }
      const find=document.createElement('button'); find.textContent=item.product_selection?'Change product':'Find products at Smith’s';
      find.onclick=()=>openProductSearch(item);
      li.append(find);
      $('shopping-list').append(li);
    }
    if (!items.length) {
      const li = document.createElement('li'); li.className = 'empty';
      li.textContent = 'Your list is empty. Add something in chat.'; $('shopping-list').append(li);
    }
  } finally { polling = false; }
}

async function createConversation(title = 'New conversation') {
  const epoch = identityEpoch;
  const c = await api('/api/conversations', {method: 'POST', body: JSON.stringify({title})});
  requireEpoch(epoch);
  current = c.id; lastRender = ''; lastRecipeRender = ''; recipeSelections.clear(); $('recipe-imports').replaceChildren();
  localStorage.setItem('household-conversation', current);
  $('messages').replaceChildren(); $('retry-area').replaceChildren();
  await loadConversations();
}

$('new-chat').onclick = async () => {
  try { await createConversation(); await refresh(); notice(); $('message').focus(); }
  catch (error) { reportError(error); }
};

async function sendPending() {
  const epoch = identityEpoch;
  const submission = pending;
  try {
    await api(`/api/conversations/${submission.cid}/messages`, {
      method: 'POST', body: JSON.stringify(submission.body),
    });
    requireEpoch(epoch);
    pending = null; sessionStorage.removeItem('household-pending');
    $('message').value = ''; $('retry-area').replaceChildren(); notice();
    await loadConversations(); await refresh();
  } catch (error) {
    if (error.stale || !currentUser) return;
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
  const epoch = identityEpoch;
  try {
    if (!current) await createConversation(content.slice(0, 60));
    requireEpoch(epoch);
    pending = {cid: current, user_id: currentUser.id, body: {request_id: crypto.randomUUID(), content}};
    sessionStorage.setItem('household-pending', JSON.stringify(pending));
    await sendPending();
  } catch (error) { if (!error.stale) { notice(error.message); setBusy(false); } }
};

$('message').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); $('composer').requestSubmit(); }
});

async function start() {
  try {
    await loadIdentity();
    pending = JSON.parse(sessionStorage.getItem('household-pending') || 'null');
    if (pending && pending.user_id !== currentUser.id) {
      pending = null; sessionStorage.removeItem('household-pending');
    }
    if (pending) current = pending.cid;
    await loadConversations(); await refresh();
    if (pending) {
      notice('An unsent message was recovered. Resend it to check its status safely.');
      setBusy(busy);
    }
  } catch (error) { reportError(error); }
  setInterval(() => { refresh().catch(reportError); }, 1500);
}
$('logout').onclick = async () => {
  try {
    await api('/auth/logout', {method:'POST'});
    clearSensitiveState(); currentUser=null; setBusy(true); location.assign('/signin');
  } catch (error) { reportError(error); }
};
start();
