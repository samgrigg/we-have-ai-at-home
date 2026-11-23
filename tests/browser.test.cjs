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
  let items = [];
  let commandJobs = [];
  const requests = [];
  let jobs = [{id:'job1', content:'Old message', response:'Old reply', status:'completed'}];
  let identity = {id:'u1',display_name:'Member 1',csrf_token:'token'};
  let authenticated = true;
  let destination = null;
  let heldConversation = null;
  const context = vm.createContext({
    document: {getElementById(id) { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); }, createElement: tag => {const el=new Element(); el.tagName=tag; Object.defineProperty(el,'id',{set(value){elements.set(value,el);}}); return el;}},
    localStorage: storage({'household-conversation': 'c1'}),
    sessionStorage: storage(pending ? {'household-pending': JSON.stringify(pending)} : {}),
    crypto: require('crypto'),
    location: {assign(path) {destination=path;}},
    setInterval() {},
    fetch: async (path, options = {}) => {
      requests.push({path,options});
      const requestIdentity = identity;
      if (path === '/api/conversations' && heldConversation) {
        const held = heldConversation; heldConversation = null;
        await new Promise(resolve => {held.release = resolve;});
      }
      return {ok: authenticated, status: path === '/auth/logout' ? 204 : authenticated ? 200 : 401, json: async () => {
      if (path === '/auth/logout') throw new SyntaxError('Empty 204 response');
      if (path === '/api/me') return identity;
      if (path === '/api/conversations') return requestIdentity.id === 'u1' ? [{id:'c1', title:'First',visibility:'private'}, {id:'c2', title:'Empty',visibility:'private'}] : [{id:'c3',title:'Other member',visibility:'private'}];
      if (path === '/api/grocery-commands') return {id:'g1'};
      if (path === '/api/shopping-list') return items;
      if (path.endsWith('/recipe-imports')) return [];
      if (path.includes('/g1/')) return commandJobs;
      return path.includes('/c1/') ? jobs : [];
    }};},
  });
  vm.runInContext(readFileSync('src/household/static/groceries.js', 'utf8'), context);
  vm.runInContext(readFileSync('src/household/static/app.js', 'utf8'), context);
  await new Promise(setImmediate);
  return {elements, context, requests, setItems(value) {items=value;}, setCommandJobs(value) {commandJobs=value;}, setJobs(value) { jobs = value; }, setIdentity(value) {identity=value;}, expire() {authenticated=false;}, destination() {return destination;}, holdNextConversationList() {heldConversation={}; return heldConversation;}};
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

// Recipe previews use safe text nodes, explicit selections and authenticated APIs.
(async () => {
  const h = await harness();
  vm.runInContext(`renderRecipes([{id:'r1',created_by:'u1',title:'<script>unsafe</script>',source_url:'https://recipe.example/soup',recipe_yield:'4',multiplier:2,status:'draft',can_confirm:true,existing_items:['chicken'],ingredients:[{text:'2 lb chicken',selected:true,check_quantity:false},{text:'salt',selected:false,check_quantity:true}]}], 'c1')`, h.context);
  const card=h.elements.get('recipe-imports').children[0];
  assert(card, 'recipe preview should render');
  assert.equal(card.children[0].textContent,'<script>unsafe</script>');
  const labels=card.children.filter(e=>e.className==='recipe-ingredient');
  assert.equal(labels[0].children[0].checked,true);
  assert.equal(labels[1].children[0].checked,false);
  assert(labels[0].children[1].textContent.includes('Possible overlap'));
  vm.runInContext('clearSensitiveState()',h.context);
  assert.equal(h.elements.get('recipe-imports').children.length,0,'account changes must clear recipe data');
  console.log('Recipe preview rendering and privacy checks passed');
})().catch(error=>{console.error(error);process.exitCode=1;});

(async () => {
  const h=await harness();
  const draft={id:'r2',created_by:'u1',title:'Soup',source_url:'https://recipe.example/soup',recipe_yield:'4',multiplier:1,status:'draft',can_confirm:true,existing_items:[],ingredients:[{text:'milk',selected:true}]};
  h.context.previewFixture=draft;
  vm.runInContext('renderRecipes([previewFixture], "c1")',h.context);
  let box=h.elements.get('recipe-imports').children[0].children.find(e=>e.className==='recipe-ingredient').children[0];
  box.checked=false; box.onchange();
  draft.existing_items=['bread'];
  vm.runInContext('renderRecipes([previewFixture], "c1")',h.context);
  box=h.elements.get('recipe-imports').children[0].children.find(e=>e.className==='recipe-ingredient').children[0];
  assert.equal(box.checked,false,'list updates must preserve user checkbox selections');
  console.log('Recipe checkbox persistence check passed');
})().catch(error=>{console.error(error);process.exitCode=1;});

(async () => {
  const h=await harness();
  const draft={id:'r3',title:'Soup',source_url:'https://recipe.example/soup',recipe_yield:'4',multiplier:1,status:'draft',can_confirm:false,existing_items:[],ingredients:[{text:'salt',selected:true}]};
  h.context.previewFixture=draft;
  vm.runInContext('renderRecipes([previewFixture], "c1")',h.context);
  draft.can_confirm=true; draft.ingredients[0].selected=false;
  vm.runInContext('renderRecipes([previewFixture], "c1")',h.context);
  const box=h.elements.get('recipe-imports').children[0].children.find(e=>e.className==='recipe-ingredient').children[0];
  assert.equal(box.checked,false,'a revised preview must use the final server omission selection');
  console.log('Recipe revision selection check passed');
})().catch(error=>{console.error(error);process.exitCode=1;});

(async()=>{
 const h=await harness();
 vm.runInContext(`renderProductResults({id:'s1',item_name:'1/2 cup heavy cream',search_term:'heavy cream',checked_at:'2026-11-22T12:00:00Z',candidates:[{candidate_id:'cream:0',description:'Heavy Cream',size:'1 pt',price:3.39,stock:'HIGH',selectable:true,packages:1,remaining:12,unit:'fl oz',quantity_review:false,package_amount:16,preferred:false}]},identityEpoch,productRequest)`,h.context);
 assert(h.elements.get('product-results').children.length>0,'product candidates should render');
 vm.runInContext('clearSensitiveState()',h.context);
 assert.equal(h.elements.get('product-search').children.length,0,'product results must clear on account change');
 console.log('Product result rendering and privacy checks passed');
})().catch(e=>{console.error(e);process.exitCode=1;});


(async()=>{
 const h=await harness();
 let release;
 h.context.api=async()=>await new Promise(resolve=>{release=resolve;});
 const loading=vm.runInContext('openProductSearch({name:"milk"})',h.context);
 vm.runInContext('closeProductSearch()',h.context);
 release({id:'late',search_term:'milk',candidates:[],checked_at:'2026-11-22T12:00:00Z'});
 await loading;
 assert.equal(h.elements.get('product-search').children.length,0,'closed searches must reject delayed product results');
 console.log('Delayed product response fencing check passed');
})().catch(e=>{console.error(e);process.exitCode=1;});

module.exports = {harness, Element};
