'use strict';
document.querySelectorAll('[data-portal-choice]').forEach(button => button.addEventListener('click', () => {
  const corporate=button.dataset.portalChoice==='corporate';
  document.querySelector('#corporate-signin').hidden=!corporate;
  document.querySelector('#portal-unavailable-note').hidden=corporate;
  document.querySelectorAll('[data-portal-choice]').forEach(choice => {
    const selected=choice===button;
    choice.classList.toggle('selected',selected);
    choice.setAttribute('aria-pressed',String(selected));
  });
}));
const csrf = () => document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
async function postJSON(url, data) {
  const response = await fetch(url, {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json','X-CSRFToken':csrf()}, body:JSON.stringify(data)});
  let result;
  try { result = await response.json(); } catch (_) { throw new Error('Please refresh the page and sign in again if needed.'); }
  if (!response.ok) throw new Error(result.error || 'This action could not be completed.');
  return result;
}
document.querySelector('#menu-toggle')?.addEventListener('click', event => {
  const open = document.querySelector('#sidebar').classList.toggle('is-open');
  event.currentTarget.setAttribute('aria-expanded', String(open));
});
document.querySelectorAll('[data-confirm]').forEach(button => button.addEventListener('click', event => {
  if (!window.confirm(button.dataset.confirm)) event.preventDefault();
}));
document.querySelectorAll('.attachment-picker input').forEach(input => input.addEventListener('change', () => {
  input.parentElement.querySelector('.attachment-count').textContent = input.files.length ? `(${input.files.length} selected)` : '';
}));
document.querySelector('#refresh-conversation')?.addEventListener('click', () => window.location.reload());
const thread = document.querySelector('#conversation-messages');
if (thread) {
  const showMessage = () => {
    const target = /^#message-\d+$/.test(location.hash) ? document.getElementById(location.hash.slice(1)) : null;
    if (target && thread.contains(target)) {
      thread.scrollTop += target.getBoundingClientRect().top - thread.getBoundingClientRect().top - 20;
    } else if (!location.hash) thread.scrollTop = thread.scrollHeight;
  };
  showMessage();
  window.addEventListener('hashchange', showMessage);
}
if (thread?.dataset.updatesUrl) {
  const indicator=document.querySelector('#conversation-refresh');
  indicator.querySelector('button').addEventListener('click',()=>window.location.reload());
  setInterval(async()=>{
    if (document.hidden) return;
    try {
      const response=await fetch(thread.dataset.updatesUrl);
      if (!response.ok) return;
      const data=await response.json();
      if (data.last_message_id!==Number(thread.dataset.lastId) || data.status!==thread.dataset.status) {
        const editing=[...document.querySelectorAll('textarea')].some(field=>field.value.trim()) || [...document.querySelectorAll('input[type=file]')].some(field=>field.files.length);
        if (!editing && !document.querySelector('form:focus-within')) window.location.reload();
        else indicator.hidden=false;
      }
    } catch (_) {}
  },20000);
}
const planner = document.querySelector('#planner');
if (planner) {
  const conversation = document.querySelector('#assistant-messages');
  const form = document.querySelector('#assistant-form');
  const input = document.querySelector('#chat-input');
  const summary = document.querySelector('#generate-summary');
  const error = document.querySelector('#assistant-error');
  const review = document.querySelector('#request-review');
  const requestForm = document.querySelector('#request-form');
  const submit = document.querySelector('#submit-request');
  const manual = document.querySelector('#manual-request');
  const available = planner.dataset.available === 'true';
  const hint = document.querySelector('#planner-next-hint');
  let selections=JSON.parse(document.querySelector('#chat-selections')?.textContent||'{}');
  let tripDetails=JSON.parse(document.querySelector('#draft-trip')?.textContent||'{}');
  function fillTrip(details){
    ['title','service_type','origin','destination','departure','return_date','travellers','budget','requirements'].forEach(key=>{
      const field=requestForm.elements.namedItem(key);
      if(field)field.value=details[key]||(key==='service_type'?'travel':'');
    });
  }
  function showSelections(result){
    selections=result.selections;
    const box=document.querySelector('#selected-itinerary');box.hidden=!Object.keys(selections).length;
    const list=document.querySelector('#selected-options');list.replaceChildren();
    Object.entries(selections).forEach(([kind,option])=>{
      const row=document.createElement('div');const title=document.createElement('strong');title.textContent=kind[0].toUpperCase()+kind.slice(1)+' · '+option.label;
      const detail=document.createElement('small');detail.textContent=option.detail;row.append(title,detail);list.append(row);
    });
    document.querySelector('#package-estimate').textContent=result.estimate?`Estimated total: ${result.estimate.low} – ${result.estimate.high} ${result.estimate.currency}`:'Sama will confirm the price in your quotation.';
    conversation.querySelectorAll('[data-option-id]').forEach(radio=>{
      if(result.stale_message_indexes?.includes(Number(radio.value.split(':')[0])) || result.expired_option_ids?.includes(radio.value)){
        radio.dataset.stale='true';radio.disabled=true;
      }
      radio.checked=Object.values(selections).some(option=>option.id===radio.value);
      radio.closest('.option-row').classList.toggle('selected',radio.checked);
    });
  }
  conversation.addEventListener('change',async event=>{
    const radio=event.target.closest('[data-option-id]');if(!radio||busy)return;
    setBusy(true);
    try{const result=await postJSON(planner.dataset.selectUrl,{option_id:radio.value});showSelections(result);setBusy(false);hint.textContent='Option saved. Add another service or send your request below.';advanceTrip();document.querySelector('#provider-inputs').open=false;showReview('Your option is saved. Check your trip, then submit it to Sama.');}
    catch(err){showSelections({selections});setBusy(false);error.textContent=err.message;}
  });
  let edited = false;
  let editVersion = 0;
  let hasConversation = !!conversation.querySelector('.outgoing');
  let busy = false;
  review.hidden = available && planner.dataset.reviewOpen !== 'true';
  function showReview(text, focus = true) {
    review.hidden = false;
    if (text) document.querySelector('#review-status').textContent = text;
    document.querySelector('#plan-step-chat').removeAttribute('aria-current');
    document.querySelector('#plan-step-review').setAttribute('aria-current', 'step');
    if (focus) {
      document.querySelector('#review-title').focus({preventScroll:true});
      review.scrollIntoView({behavior:'smooth',block:'start'});
    }
  }
  if (!review.hidden) showReview('', false);
  if(document.querySelector('#batch-review'))document.querySelector('#batch-review').scrollIntoView({block:'start'});
  const validationError = document.querySelector('#request-errors');
  if (validationError) {
    validationError.focus({preventScroll:true});
    review.scrollIntoView({block:'start'});
  }
  requestForm.addEventListener('input', () => { edited = true; editVersion += 1; });
  window.addEventListener('beforeunload', event => {
    if ((edited || input.value.trim() || requestForm.elements.namedItem('attachments')?.files.length) && !submit.disabled) {
      event.preventDefault(); event.returnValue='';
    }
  });
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault(); if (!busy && available) form.requestSubmit();
    }
  });
  document.querySelectorAll('[data-chat-prompt]').forEach(button => button.addEventListener('click', () => {
    input.value=button.dataset.chatPrompt; input.focus();
  }));
  document.querySelector('#save-draft')?.addEventListener('click', async event => {
    if (busy || !requestForm.reportValidity()) return;
    const button=event.currentTarget; button.disabled=true;
    const savingVersion=editVersion;
    try {
      const body=new URLSearchParams();
      new FormData(requestForm).forEach((value,key)=>{if(typeof value==='string' && key!=='traveller_details')body.append(key,value);});
      const response=await fetch(planner.dataset.saveUrl,{method:'POST',credentials:'same-origin',body,headers:{'X-CSRFToken':csrf()}});
      const result=await response.json();
      if(!response.ok) throw new Error(result.error || 'Could not save this draft.');
      showSelections(result);
      tripDetails=result.trip;
      if (editVersion===savingVersion) edited=!!requestForm.elements.namedItem('traveller_details').value;
      advanceTrip();
      error.textContent=editVersion===savingVersion
        ? 'Reviewed trip details saved. Private details and selected files stay in this form until you submit.'
        : 'The earlier details were saved. Save again to keep the changes you just made.';
    } catch(err) {error.textContent=err.message;} finally {button.disabled=false;}
  });
  manual.addEventListener('click', () => showReview('Fill in the trip details, then select Submit request to Sama.'));
  requestForm.addEventListener('submit', event => {
    if (busy) {event.preventDefault();return;}
    submit.disabled = true;
    submit.textContent = 'Submitting your request…';
  });
  window.addEventListener('pageshow', () => {submit.disabled = false;submit.textContent = 'Submit request to Sama →';});
  requestForm.addEventListener('invalid', event => {
    if (event.target.closest('details')) event.target.closest('details').open = true;
  }, true);
  function append(message) {
    const element = document.createElement('div');
    element.className = 'chat-message ' + (message.role === 'user' ? 'outgoing' : 'ai');
    const label = document.createElement('div'); label.className = 'message-label';
    label.textContent = message.role === 'user' ? 'You' : 'HelloSama assistant';
    const body = document.createElement('div'); body.className = 'message-body'; body.textContent = message.content;
    element.append(label,body);
    if(message.options?.length){
      ['flight','hotel','esim','insurance','travel'].forEach(kind=>{
        const choices=message.options.map((option,index)=>({...option,index})).filter(option=>(option.kind||'travel')===kind);
        if(!choices.length)return;
        const group=document.createElement('section');group.className='option-group '+kind;
        const heading=document.createElement('div');heading.className='option-group-heading';
        const title=document.createElement('strong');title.textContent=kind==='flight'?'✈ Flight options':kind==='hotel'?'▤ Hotel options':kind==='esim'?'▣ eSIM plans':kind==='insurance'?'✓ Travel insurance':'✦ Travel options';
        const caption=document.createElement('small');caption.textContent=message.options.some(o=>o.provider)?'Provider prices · Nothing booked':'Published options · Sama confirms availability';heading.append(title,caption);group.append(heading);
        choices.forEach(option=>{
          const card=document.createElement('article');card.className='option-row';
          const choice=document.createElement('label');choice.className='option-choice';
          const radio=document.createElement('input');radio.type='radio';radio.name='travel-choice-'+kind;radio.value=`${message.message_index}:${option.index}`;radio.dataset.optionId=radio.value;if(option.sandbox){radio.dataset.stale='true';radio.disabled=true;}
          const description=document.createElement('span');description.className='option-description';
          const label=document.createElement('strong');label.textContent=option.label+(option.stars?' '+option.stars+' ★':'')+(option.sandbox?' · TEST QUOTE':'');
          const detail=document.createElement('span');detail.textContent=option.detail;description.append(label,detail);
          const price=document.createElement('span');price.className='option-price';
          const amount=document.createElement('strong');amount.textContent=option.price_min?`${option.price_min}${option.price_max!==option.price_min?' – '+option.price_max:''} ${option.currency}`:'Price to be confirmed';
          const basis=document.createElement('small');basis.textContent=option.price_min?(option.price_basis==='per_night'?'per night':option.price_basis==='per_person'?'per passenger':option.price_basis==='per_unit'?'one eSIM':option.price_basis==='unknown'?'from price':'party / stay total')+(option.provider?' · Provider quote':' · Estimate'):'';price.append(amount,basis);
          choice.append(radio,description,price);card.append(choice);
          try{const url=new URL(option.source_url);if(['https:','http:'].includes(url.protocol)){
            const source=document.createElement('a');source.className='option-source';source.href=url.href;source.target='_blank';source.rel='noopener noreferrer';source.textContent='View source ↗';card.append(source);
          }}catch(_){}
          group.append(card);
        });element.append(group);
      });
    }
    if (message.sources?.length) {
      const sources = document.createElement('div'); sources.className = 'source-links';
      message.sources.forEach(source => {
        try {
          const url = new URL(source.url);
          if (!['http:','https:'].includes(url.protocol)) return;
          const link=document.createElement('a'); link.href=url.href; link.textContent=source.title; link.target='_blank'; link.rel='noopener noreferrer';sources.append(link);
        } catch (_) {}
      });
      element.append(sources);
    }
    conversation.insertBefore(element, document.querySelector('#provider-search')); conversation.scrollTop=conversation.scrollHeight;
  }
  const providerForm=document.querySelector('#provider-form');
  const providerPanel=document.querySelector('#provider-search');
  const providerStatus=document.querySelector('#provider-search-status');
  const connections=JSON.parse(document.querySelector('#provider-available').textContent);
  let providerKind='hotel';
  function advanceTrip(){
    const known=!!tripDetails.destination;
    providerPanel.hidden=!known;
    if(!known)return;
    if(!edited)fillTrip(tripDetails);
    showReview('Choose any offers above, check your trip and send it to Sama.',false);
    const count=Number(tripDetails.travellers)||0;
    document.querySelector('#trip-review-overview').textContent=[tripDetails.origin&&tripDetails.destination?tripDetails.origin+' → '+tripDetails.destination:tripDetails.destination,tripDetails.departure,tripDetails.return_date,count?count+' traveller(s)':''].filter(Boolean).join(' · ');
    document.querySelector('#trip-edit-fields').open=!requestForm.checkValidity();
    summary.hidden=true;manual.textContent='Review & send request →';manual.classList.add('primary');
    hint.textContent='Choose any extras above, then select Submit request to Sama. Nothing is booked yet.';
    const births=document.querySelector('#offer-birthdates');
    if(births.children.length!==count){
      births.replaceChildren();
      for(let i=0;i<Math.min(count,100);i++){
        const row=document.createElement('div');row.className='field';
        const label=document.createElement('label');label.htmlFor='offer-birth-'+i;label.textContent='Traveller '+(i+1)+' · birth date';
        const field=document.createElement('input');field.type='date';field.id=label.htmlFor;field.dataset.birthDate='true';row.append(label,field);births.append(row);
      }
    }
  }
  function chooseProvider(kind){
    providerKind=kind;
    providerForm.querySelectorAll('[data-provider]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.provider===kind)));
    providerForm.querySelectorAll('[data-provider-fields]').forEach(section=>{
      section.hidden=section.dataset.providerFields!==kind;
      section.querySelectorAll('input,select,button').forEach(field=>field.disabled=section.hidden);
    });
    document.querySelector('#find-provider-offers').textContent='Show '+({hotel:'hotel offers',esim:'eSIM plans',insurance:'insurance plans'}[kind])+' →';
    document.querySelector('#provider-connection').textContent=connections[kind]?'':'This provider is not connected yet. You can still send this service request to Sama.';
    providerStatus.textContent='';
  }
  providerForm.querySelectorAll('[data-provider]').forEach(button=>button.addEventListener('click',()=>chooseProvider(button.dataset.provider)));
  function addRoom(){
    const holder=document.querySelector('#offer-rooms');if(holder.children.length>=10)return;
    const row=document.createElement('div');row.className='offer-room';
    const adultsLabel=document.createElement('label');adultsLabel.textContent='Adults';
    const adults=document.createElement('input');adults.type='number';adults.min='1';adults.max='9';adults.value='1';adults.dataset.roomAdults='true';adultsLabel.append(adults);
    const childrenLabel=document.createElement('label');childrenLabel.textContent='Children’s ages (comma-separated)';
    const children=document.createElement('input');children.placeholder='e.g. 4, 7';children.dataset.roomChildren='true';childrenLabel.append(children);
    const remove=document.createElement('button');remove.type='button';remove.className='text-button';remove.textContent='Remove room';remove.addEventListener('click',()=>{if(holder.children.length>1)row.remove();});
    row.append(adultsLabel,childrenLabel,remove);holder.append(row);
  }
  addRoom();chooseProvider('hotel');
  document.querySelector('#add-offer-room').addEventListener('click',addRoom);
  document.querySelector('#offer-country').addEventListener('change',()=>document.querySelector('#offer-city').replaceChildren(new Option('Find and choose a city','')));
  document.querySelector('#find-hotel-city').addEventListener('click',async()=>{
    const country=document.querySelector('#offer-country').value;
    const query=document.querySelector('#offer-city-query').value.trim();
    if(!country||query.length<2){providerStatus.textContent='Choose the country and enter at least two letters of the city.';return;}
    const button=document.querySelector('#find-hotel-city');button.disabled=true;providerStatus.textContent='Finding cities…';
    try{
      const response=await fetch(providerForm.dataset.citiesUrl+'?'+new URLSearchParams({country,q:query}));const result=await response.json();
      if(!response.ok)throw new Error(result.error||'Could not find cities.');
      const select=document.querySelector('#offer-city');select.replaceChildren(new Option('Choose a city',''));
      result.cities.forEach(city=>select.add(new Option(city.name,city.id)));
      if(result.cities.length===1)select.value=result.cities[0].id;
      providerStatus.textContent=result.cities.length?'Choose the matching city.':'No matching city. Try a different spelling.';
    }catch(err){providerStatus.textContent=err.message;}finally{button.disabled=false;}
  });
  providerForm.addEventListener('submit',async event=>{
    event.preventDefault();if(busy)return;
    if(!requestForm.checkValidity()){
      showReview('Complete the missing trip details below so the provider can quote accurately.');requestForm.reportValidity();return;
    }
    const data={kind:providerKind,country:document.querySelector('#offer-country').value};
    if(providerKind==='hotel'){
      data.city_id=document.querySelector('#offer-city').value;data.nationality=document.querySelector('#offer-nationality').value;
      data.rooms=[...document.querySelectorAll('.offer-room')].map(row=>({adults:Number(row.querySelector('[data-room-adults]').value),childrenAges:row.querySelector('[data-room-children]').value.trim()?row.querySelector('[data-room-children]').value.split(',').map(v=>Number(v.trim())):[]}));
    }
    if(providerKind==='insurance'){
      data.residence=document.querySelector('#offer-residence').value;
      data.birth_dates=[...document.querySelectorAll('[data-birth-date]')].map(field=>field.value);
    }
    setBusy(true);document.querySelector('#find-provider-offers').disabled=true;providerStatus.textContent='Checking the provider’s offers…';
    try{
      // Save edited trip details before searching. Provider prices are bound to this exact itinerary.
      const body=new URLSearchParams();new FormData(requestForm).forEach((value,key)=>{if(typeof value==='string'&&key!=='traveller_details')body.append(key,value);});
      const response=await fetch(planner.dataset.saveUrl,{method:'POST',credentials:'same-origin',body,headers:{'X-CSRFToken':csrf()}});const saved=await response.json();
      if(!response.ok)throw new Error(saved.error||'Check your trip details.');
      tripDetails=saved.trip;showSelections(saved);
      const result=await postJSON(providerForm.dataset.offersUrl,data);append(result.message);showSelections(result.message);
      providerStatus.textContent=result.message.options.length?'Select an offer above to add it to this trip.':'No matching offers. Adjust the details or send the request to Sama.';
      document.querySelectorAll('[data-birth-date]').forEach(field=>field.value='');
      setBusy(false);advanceTrip();
      conversation.querySelectorAll('.chat-message').item(conversation.querySelectorAll('.chat-message').length-1)?.scrollIntoView({behavior:'smooth',block:'start'});
    }catch(err){setBusy(false);providerStatus.textContent=err.message;}
    finally{document.querySelector('#find-provider-offers').disabled=false;}
  });
  function setBusy(value) {
    busy=value; form.querySelector('button').disabled=value || !available;
    summary.disabled=value || !available || !hasConversation;
    submit.disabled=value;
    manual.disabled=value;
    conversation.querySelectorAll('[data-option-id]').forEach(radio=>radio.disabled=value||radio.dataset.stale==='true');
    document.querySelector('#save-draft').disabled=value;
    requestForm.setAttribute('aria-busy', String(value));
    error.textContent=value?'Your assistant is working on it…':'';
  }
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (busy || !input.value.trim()) return;
    const message=input.value.trim(); append({role:'user',content:message}); hasConversation=true;input.value='';setBusy(true);
    if (!review.hidden) document.querySelector('#review-status').textContent='Updating your trip details…';
    try { const result=await postJSON(planner.dataset.aiUrl,{message}); append(result.message); if(result.message.selections)showSelections(result.message); if(result.message.trip && Object.keys(result.message.trip).length){tripDetails=result.message.trip;if(!edited)fillTrip(tripDetails);} setBusy(false);advanceTrip(); }
    catch (err) {setBusy(false);error.textContent=err.message;}
  });
  summary.addEventListener('click',async () => {
    if (busy) return;
    if (input.value.trim()) {error.textContent='Send your last message first so it can be included in the request.';input.focus();return;}
    if (edited && !window.confirm('Generate a new form from the chat? This will replace your edits to the trip details. Private traveller details will be kept.')) return;
    setBusy(true);
    const editableFields=[...requestForm.querySelectorAll('input:not([type=hidden]),textarea')];
    const selects=[...requestForm.querySelectorAll('select')];
    editableFields.forEach(field=>{field.readOnly=true;});
    selects.forEach(field=>{field.disabled=true;});
    try {
      const result=['title','origin','destination'].some(key=>tripDetails[key])?{summary:tripDetails}:await postJSON(planner.dataset.aiUrl,{action:'summary'});
      fillTrip(result.summary);
      if(result.summary.selections)showSelections(result.summary);
      edited=!!requestForm.elements.namedItem('traveller_details').value;
      if (requestForm.elements.namedItem('budget').value) document.querySelector('#extra-details').open=true;
      setBusy(false);error.textContent='Your form is ready below. It has not been sent yet.';
      showReview('Your form is ready. Check the details, fill any gaps, then select Submit request to Sama.');
    } catch (err) {setBusy(false);error.textContent=err.message;}
    finally {editableFields.forEach(field=>{field.readOnly=false;});selects.forEach(field=>{field.disabled=false;});}
  });
  advanceTrip();
  conversation.scrollTop=conversation.scrollHeight;
  summary.disabled = !available || !hasConversation;
}
function pushStatus(text) {document.querySelectorAll('.push-status').forEach(el=>el.textContent=text);}
document.querySelectorAll('.push-enable').forEach(button=>button.addEventListener('click',async()=>{
  try {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) throw new Error('This browser does not support device notifications. On iPhone or iPad, add HelloSama to your Home Screen first.');
    const permission=await Notification.requestPermission();
    if (permission!=='granted') throw new Error('Notifications were not enabled. You can change this in your browser settings.');
    const config=await (await fetch('/api/push/config/')).json();
    if (!config.public_key) throw new Error('Device notifications are not configured yet.');
    await navigator.serviceWorker.register('/service-worker.js');
    const registration=await navigator.serviceWorker.ready;
    const raw=atob(config.public_key.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-config.public_key.length%4)%4));
    const key=Uint8Array.from(raw,c=>c.charCodeAt(0));
    const subscription=await registration.pushManager.getSubscription() || await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:key});
    await postJSON('/api/push/subscribe/',subscription.toJSON());pushStatus('Notifications are enabled on this device.');
  } catch (error) {pushStatus(error.message);}
}));
document.querySelectorAll('.push-disable').forEach(button=>button.addEventListener('click',async()=>{
  try {
    const registration=await navigator.serviceWorker.getRegistration();
    const subscription=await registration?.pushManager.getSubscription();
    if (subscription) {await postJSON('/api/push/unsubscribe/',{endpoint:subscription.endpoint});await subscription.unsubscribe();}
    pushStatus('Notifications are disabled on this device.');
  } catch (error) {pushStatus(error.message);}
}));
if (document.querySelector('[data-unread]')) setInterval(async()=>{
  if (document.hidden) return;
  try {const response=await fetch('/api/notifications/'); if (response.ok) {const data=await response.json();document.querySelectorAll('[data-unread]').forEach(el=>el.textContent=data.unread);}}catch (_){}
},60000);
// Prompts fill the composer; the user chooses when to send.
document.querySelectorAll('[data-message-prompt]').forEach(button=>button.addEventListener('click',()=>{
  const input=document.querySelector('#message-body');
  if(input){input.value=button.dataset.messagePrompt;input.focus();}
}));
document.querySelector('[data-request-history]')?.addEventListener('change',event=>{location.href=event.target.value;});
const companyCodes=document.querySelector('#company-choices');
if(companyCodes){
  const companies=JSON.parse(companyCodes.textContent);
  const code=document.querySelector('#id_account_number');
  const update=()=>{const company=companies.find(c=>c.account_number.toLowerCase()===code.value.trim().toLowerCase());
    document.querySelector('#owner-company-name').textContent=company?.name || (code.value.trim() ? 'To be confirmed from Sama Accounting' : 'Enter the accounting client code below');};
  code.addEventListener('input',update);update();
}

document.querySelectorAll('a[href="#edit-trip-details"]').forEach(link=>link.addEventListener('click',()=>{const editor=document.querySelector('#edit-trip-details');if(editor)editor.open=true;}));
