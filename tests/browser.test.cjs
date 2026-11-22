// Exercise browser state transitions without a browser or third-party test runtime.
const {readFileSync} = require('fs');
const vm = require('vm');
const assert = require('assert').strict;

class Element {
  constructor() { this.children = []; this.value = ''; this.disabled = false; this.textContent = ''; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  addEventListener() {}
  focus() {}
}
function storage(initial = {}) {
  const map = new Map(Object.entries(initial));
  return {getItem: k => map.get(k) || null, setItem: (k,v) => map.set(k,v), removeItem: k => map.delete(k)};
}
async function harness(pending = null) {
  const elements = new Map();
  let jobs = [{id:'job1', content:'Old message', response:'Old reply', status:'completed'}];
  let identity = {id:'u1',display_name:'Member 1',csrf_token:'token'};
  let authenticated = true;
  let destination = null;
  let heldConversation = null;
  const context = vm.createContext({
    document: {getElementById(id) { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); }, createElement: () => new Element()},
    localStorage: storage({'household-conversation': 'c1'}),
    sessionStorage: storage(pending ? {'household-pending': JSON.stringify(pending)} : {}),
    crypto: require('crypto'),
    location: {assign(path) {destination=path;}},
    setInterval() {},
    fetch: async path => {
      const requestIdentity = identity;
      if (path === '/api/conversations' && heldConversation) {
        const held = heldConversation; heldConversation = null;
        await new Promise(resolve => {held.release = resolve;});
      }
      return {ok: authenticated, status: path === '/auth/logout' ? 204 : authenticated ? 200 : 401, json: async () => {
      if (path === '/auth/logout') throw new SyntaxError('Empty 204 response');
      if (path === '/api/me') return identity;
      if (path === '/api/conversations') return requestIdentity.id === 'u1' ? [{id:'c1', title:'First',visibility:'private'}, {id:'c2', title:'Empty',visibility:'private'}] : [{id:'c3',title:'Other member',visibility:'private'}];
      if (path === '/api/shopping-list') return [];
      return path.includes('/c1/') ? jobs : [];
    }};},
  });
  vm.runInContext(readFileSync('src/household/static/app.js', 'utf8'), context);
  await new Promise(setImmediate);
  return {elements, context, setJobs(value) { jobs = value; }, setIdentity(value) {identity=value;}, expire() {authenticated=false;}, destination() {return destination;}, holdNextConversationList() {heldConversation={}; return heldConversation;}};
}

(async () => {
  const h = await harness();
  await h.elements.get('conversations').children.find(e=>e.textContent==='Empty').onclick();
  assert.equal(h.elements.get('messages').children.length, 0, 'empty chat must clear previous transcript');

  const p = await harness({cid:'c1',user_id:'u1', body:{request_id:'job1', content:'Old message'}});
  assert.equal(p.elements.get('retry-area').children.length, 2);
  p.setJobs([{id:'job1', content:'Old message', status:'processing'}]);
  await vm.runInContext('refresh()', p.context);
  assert.equal(p.elements.get('retry-area').children.length, 2, 'polling must preserve resend controls');
  p.setJobs([{id:'other-job', content:'Other tab request', status:'failed', error:'Please retry'}]);
  await vm.runInContext('refresh()', p.context);
  const controls = p.elements.get('retry-area').children.map(button => button.textContent);
  assert(controls.includes('Retry request'), 'pending message must not hide failed-job retry');
  assert(controls.includes('Keep editing message'), 'a conflicting pending submission needs an escape');
  const switched = await harness();
  switched.setIdentity({id:'u2',display_name:'Member 2',csrf_token:'other-token'});
  await vm.runInContext('refresh()', switched.context);
  assert.equal(switched.elements.get('messages').children.length,0,'switching accounts clears previous transcript');
  assert.equal(switched.elements.get('current-user').textContent,'Member 2');
  const expired = await harness(); expired.expire();
  await vm.runInContext('refresh().catch(()=>{})',expired.context);
  assert.equal(expired.elements.get('messages').children.length,0);
  assert.equal(expired.elements.get('shopping-list').children.length,0);
  assert.equal(expired.destination(),'/signin');
  const recovered = await harness({cid:'c1',user_id:'someone-else',body:{request_id:'other',content:'Private draft'}});
  assert.equal(recovered.elements.get('retry-area').children.length,0,'another account cannot recover a private draft');
  const signedOut = await harness();
  await signedOut.elements.get('logout').onclick();
  assert.equal(signedOut.elements.get('messages').children.length,0,'successful logout must immediately clear private transcript');
  assert.equal(signedOut.destination(),'/signin');
  const late = await harness();
  const held = late.holdNextConversationList();
  const staleList = vm.runInContext('loadConversations().catch(()=>{})',late.context);
  late.setIdentity({id:'u2',display_name:'Member 2',csrf_token:'other-token'});
  await vm.runInContext('refresh()',late.context);
  held.release(); await staleList;
  assert(!late.elements.get('conversations').children.some(e=>e.textContent==='First'), 'a delayed response must not restore another member\'s chat titles');
  assert.equal(late.elements.get('chat-title').textContent,'Other member');
  console.log('8 browser recovery and privacy checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
