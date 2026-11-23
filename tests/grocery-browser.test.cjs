const {harness} = require('./browser.test.cjs');
const vm = require('vm');
const assert = require('assert').strict;
(async () => {
  const h = await harness();
  h.setItems([{name:'2 c milk',revision:'v1',checked:false},{name:'eggs',revision:'v2',checked:true}]);
  await vm.runInContext('refresh()',h.context);
  assert.equal(h.elements.get('shopping-list').children.length,1);
  assert.equal(h.elements.get('picked-up-list').children.length,1);
  const row = h.elements.get('shopping-list').children[0];
  await row.children[0].onchange();
  const patch = h.requests.find(r=>r.options.method==='PATCH');
  assert.equal(JSON.parse(patch.options.body).revision,'v1');
  assert.equal(JSON.parse(patch.options.body).checked,true);
  const edit = row.children.find(c=>c.textContent==='Edit');
  edit.onclick();
  const form = row.children.find(c=>c.tagName==='form');
  assert(form,'inline editor should open');
  form.children[0].value='3 c milk';
  await vm.runInContext('refresh()',h.context);
  assert.equal(form.children[0].value,'3 c milk','polling must preserve draft');

  h.elements.get('command').value='Add bread';
  await h.elements.get('command-form').onsubmit({preventDefault(){}});
  const sent = h.requests.find(r=>r.path==='/api/conversations/g1/messages'&&r.options.method==='POST');
  assert(sent,'command should use dedicated context');
  await h.elements.get('conversations').children.find(e=>e.textContent==='Empty').onclick();
  h.setCommandJobs([{id:'command1',content:'Add bread',response:'Added bread.',status:'completed'}]);
  await vm.runInContext('refresh()',h.context);
  assert.equal(h.elements.get('command-response').textContent,'Added bread.');
  assert.equal(h.elements.get('chat-panel').hidden,true,'commands must not open chat');

  h.context.api = async () => {throw new Error('Offline');};
  h.elements.get('command').value='eggs';
  await h.elements.get('command-form').onsubmit({preventDefault(){}});
  const first = vm.runInContext('commandPending.body.request_id',h.context);
  await h.elements.get('command-retry').children[0].onclick();
  assert.equal(vm.runInContext('commandPending.body.request_id',h.context),first);
  assert(h.elements.get('command-notice').textContent.includes('Offline'));
  vm.runInContext('clearSensitiveState()',h.context);
  assert.equal(h.elements.get('command-response').textContent,'');
  assert.equal(h.elements.get('command').value,'');
  console.log('Grocery direct control, command isolation, draft preservation and retry checks passed');
})().catch(e=>{console.error(e);process.exitCode=1;});

(async () => {
  const h = await harness();
  h.context.originalApi = vm.runInContext('api',h.context);
  vm.runInContext(`api = async (path, options) => {
    if (path.includes('/c1/')) throw new Error('Chat temporarily unavailable');
    return originalApi(path, options);
  }`,h.context);
  h.setItems([{name:'bread',revision:'v1',checked:false}]);
  await vm.runInContext('refresh()',h.context);
  assert.equal(h.elements.get('shopping-list').children[0].children[1].children[0].textContent,'bread','chat failure must not block groceries');
  assert.equal(h.elements.get('notice').textContent,'Chat temporarily unavailable');
  console.log('Grocery loading stays independent of chat failures');
})().catch(e=>{console.error(e);process.exitCode=1;});

(async () => {
  const h = await harness();
  h.setItems([{name:'milk',revision:'v1',checked:false}]);
  await vm.runInContext('refresh()',h.context);
  const row = h.elements.get('shopping-list').children[0];
  row.children.find(c=>c.textContent==='Edit').onclick();
  const form = row.children.find(c=>c.tagName==='form');
  form.children[0].value = '2 cups milk';
  h.context.api = async (path, options) => {
    if (options?.method==='PATCH') { const e = new Error('Another member changed this item'); e.status=409; throw e; }
    return [{name:'milk',revision:'v2',checked:true}];
  };
  await form.onsubmit({preventDefault(){}});
  assert.equal(form.children[0].value,'2 cups milk');
  assert(form.children[form.children.length-1].textContent.includes('Review your draft'));
  let body;
  h.context.api = async (path,options) => { if(options?.method==='PATCH') body=JSON.parse(options.body); return []; };
  await form.onsubmit({preventDefault(){}});
  assert.equal(body.revision,'v2','a second explicit save must use the refreshed version');
  console.log('Conflicting edits preserve drafts and require explicit resubmission');
})().catch(e=>{console.error(e);process.exitCode=1;});

(async () => {
  const h = await harness();
  h.context.recipeFixture = {id:'command-recipe',title:'Soup',source_url:'https://recipe.example/soup',recipe_yield:'4',multiplier:1,status:'draft',can_confirm:false,existing_items:[],ingredients:[{text:'salt',selected:true}]};
  vm.runInContext('renderRecipes([recipeFixture], "g1", "command-recipes")',h.context);
  assert.equal(h.elements.get('command-recipes').children.length,1);
  assert.equal(h.elements.get('recipe-imports').children.length,0);
  h.setIdentity({id:'u2',display_name:'Member 2',csrf_token:'token2'});
  await vm.runInContext('refresh()',h.context);
  assert.equal(h.elements.get('command-recipes').children.length,0);
  assert.equal(h.elements.get('command-response').textContent,'');
  console.log('Command recipe surfaces stay separate and clear on account changes');
})().catch(e=>{console.error(e);process.exitCode=1;});

(async () => {
  const h = await harness();
  h.setItems([{name:'milk',revision:'v1',checked:false},{name:'eggs',revision:'v2',checked:false}]);
  await vm.runInContext('refresh()',h.context);
  const [milk, eggs] = h.elements.get('shopping-list').children;
  milk.children.find(c=>c.textContent==='Edit').onclick();
  const form = milk.children.find(c=>c.tagName==='form');
  form.children[0].value='3 cups milk';
  await eggs.children[0].onchange();
  assert.equal(vm.runInContext('groceryEditor?.input.value',h.context),'3 cups milk','checking another item must retain the open edit draft');
  h.context.api = async (path,options) => {
    if (options?.method==='PATCH') {const e=new Error('Eggs changed');e.status=409;throw e;}
    return [{name:'milk',revision:'v1',checked:false},{name:'eggs',revision:'v3',checked:false}];
  };
  await eggs.children[0].onchange();
  assert.equal(form.children[form.children.length-1].textContent,'','an unrelated conflict must not change the milk editor');
  console.log('Other item mutations and conflicts preserve the open editor');
})().catch(e=>{console.error(e);process.exitCode=1;});

(async () => {
  const h = await harness();
  h.setItems([{name:'milk',revision:'v1',checked:false}]);
  await vm.runInContext('refresh()',h.context);
  const milk = h.elements.get('shopping-list').children[0];
  milk.children.find(c=>c.textContent==='Edit').onclick();
  const form = milk.children.find(c=>c.tagName==='form');
  form.children[0].value='4 cups milk';
  await milk.children[0].onchange();
  assert.equal(vm.runInContext('groceryEditor?.input.value',h.context),'4 cups milk','checking the edited item must retain its draft');
  console.log('Checking the edited item preserves its draft too');
})().catch(e=>{console.error(e);process.exitCode=1;});
