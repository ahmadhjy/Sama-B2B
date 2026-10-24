'use strict';
(() => {
  const root=document.querySelector('#planner[data-guided]');
  if(!root)return;
  const $=selector=>root.querySelector(selector);
  const read=id=>JSON.parse(document.getElementById(id).textContent);
  const names={flight:'Flights',hotel:'Hotel',transfer:'Transfers',esim:'eSIM',insurance:'Travel insurance'};
  const icons={flight:'✈',hotel:'▤',transfer:'↗',esim:'▣',insurance:'♧'};
  const countries=read('provider-countries'),connections=read('provider-available'),insuranceTest=read('insurance-test');
  let trip=read('draft-trip'),values=read('guide-values'),guide=read('guide-state'),selections=read('chat-selections');
  let busy=false,override='',onAnswer=()=>{},quote={},wizard='',wizardKind='',submittedUrl='',reviewShown=false,offerHome=null,renderId=0,textAnswer=null;
  const searched=new Set();
  const card=$('#guide-card'),controls=$('#guide-controls'),actions=$('#guide-actions');
  const messages=$('#assistant-messages'),guideForm=$('#guide-form'),chatForm=$('#assistant-form');
  const input=$('#chat-input'),dialog=$('#request-review'),requestForm=$('#request-form');
  const now=new Date(),today=now.getFullYear()+'-'+String(now.getMonth()+1).padStart(2,'0')+'-'+String(now.getDate()).padStart(2,'0');
  const el=(tag,className,text)=>{const node=document.createElement(tag);if(className)node.className=className;if(text!==undefined)node.textContent=text;return node;};
  function icon(kind){
    const box=el('span','service-icon'),svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');svg.setAttribute('stroke-width','1.6');svg.setAttribute('stroke-linecap','round');svg.setAttribute('stroke-linejoin','round');svg.setAttribute('aria-hidden','true');
    const paths={flight:['M22 2 9 15','M22 2l-7 20-4-9-9-4Z'],hotel:['M4 21V4h16v17','M2 21h20','M9 21v-5h6v5','M8 8h1m6 0h1M8 12h1m6 0h1'],transfer:['M5 17H3v-6l3-6h12l3 6v6h-2','M5 17h14','M5 12h14','M7 17v3M17 17v3','M7 15h1m8 0h1'],esim:['M8 3h8l4 4v14H4V7Z','M9 10h6v7H9Z','M9 13h6m-3-3v7'],insurance:['M12 22s8-4 8-12V5l-8-3-8 3v5c0 8 8 12 8 12Z','m9 12 2 2 4-4']};
    (paths[kind]||paths.flight).forEach(d=>{const path=document.createElementNS(svg.namespaceURI,'path');path.setAttribute('d',d);svg.append(path);});box.append(svg);return box;
  }
  const dateLabel=value=>value?new Date(value+'T12:00:00').toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'}):'';
  const partyLabel=party=>[['adults','adult','adults'],['children','child','children'],['infants','infant','infants']].map(([key,one,many])=>(party[key]||0)+' '+(party[key]===1?one:many)).join(' · ');
  function button(text,callback,style='secondary'){
    const b=el('button','button '+style,text);b.type='button';b.addEventListener('click',()=>{if(!busy)callback();});return b;
  }
  function field(label,id,type='text',value='',required=true){
    const box=el('div','guide-field'),caption=el('label','',label),control=el(type==='textarea'?'textarea':'input');
    caption.htmlFor=id;control.id=id;control.name=id;control.required=required;
    if(type!=='textarea')control.type=type;else control.rows=3;
    control.value=value||'';control.maxLength=type==='textarea'?2000:120;box.append(caption,control);controls.append(box);return control;
  }
  function country(label,id,value=''){
    const box=el('div','guide-field'),caption=el('label','',label),select=el('select');caption.htmlFor=id;select.id=id;select.required=true;
    select.add(new Option('Choose a country',''));countries.forEach(c=>select.add(new Option(c.name,c.code)));select.value=value;box.append(caption,select);controls.append(box);return select;
  }
  function next(callback,label='Continue →'){
    const b=el('button','button primary',label);b.type='submit';actions.append(b);onAnswer=callback;
  }
  function skip(kind){actions.append(button('Let Sama find options for me',()=>sendStep('skip_service',{service:kind}),'text'));}
  function scrollCard(){requestAnimationFrame(()=>{messages.scrollTo({top:Math.max(0,card.offsetTop-16),behavior:'auto'});});}
  function setBusy(value,text='Saving your answer…'){
    busy=value;root.setAttribute('aria-busy',String(value));
    root.querySelectorAll('#guide-form button,#guide-form input,#guide-form select,#guide-form textarea,[data-option-id],#assistant-form button,#submit-request').forEach(node=>{
      node.disabled=value||node.dataset.stale==='true'||(node.closest('#assistant-form')&&root.dataset.available!=='true');
    });
    $('#assistant-error').textContent=value?text:(root.dataset.available==='true'?'':'Use the question cards to finish your request.');
  }
  function updateSelections(data){
    if(data.selections)selections=data.selections;
    messages.querySelectorAll('[data-option-id]').forEach(radio=>{
      if(data.stale_message_indexes?.includes(Number(radio.value.split(':')[0]))||data.expired_option_ids?.includes(radio.value)){radio.dataset.stale='true';radio.disabled=true;}
      radio.checked=Object.values(selections).some(o=>o.id===radio.value);radio.closest('.option-row').classList.toggle('selected',radio.checked);
    });
  }
  function apply(data){
    if(data.trip)trip=data.trip;if(data.values)values=data.values;if(data.guide)guide=data.guide;
    updateSelections(data);memory();
  }
  function appendAnswers(result){(result.messages||[result.message]).forEach(append);}
  async function sendStep(step,data){
    if(busy)return;
    setBusy(true);$('#guide-error').textContent='';
    try{
      const result=await postJSON(root.dataset.guideUrl,{step,values:data,version:guide.version});
      apply(result);appendAnswers(result);override='';wizard='';wizardKind='';quote={};setBusy(false);render();scrollCard();
      return true;
    }catch(error){setBusy(false);$('#guide-error').textContent=error.message;return false;}
  }
  function edit(step){if(busy)return;dialog.close();override=step;wizard='';wizardKind='';quote={};render();scrollCard();}
  function memory(){
    const box=$('#trip-memory');box.replaceChildren();
    const pieces=[['services',guide.services.map(k=>names[k]).join(' + ')],['route',trip.origin&&trip.destination?trip.origin+' → '+trip.destination:''],
      ['departure',dateLabel(trip.departure)],['return',dateLabel(trip.return_date)|| (guide.one_way?'One way':'')],['travellers',trip.travellers?trip.travellers+' traveller'+(Number(trip.travellers)===1?'':'s'):'']];
    pieces.forEach(([step,text])=>{if(text)box.append(button(text+' · Edit',()=>edit(step),'memory'));});box.hidden=!box.children.length;
    $('#open-request-review').hidden=guide.step!=='ready';
  }
  function append(message){
    if(!message)return;
    const node=el('div','chat-message '+(message.role==='user'?'outgoing':'ai')+(message.guided?' guided-answer':''));
    const body=el('div','message-body',message.content);
    if(message.role!=='user')formatLinks(body);
    node.append(el('div','message-label',message.role==='user'?'You':'HelloSama assistant'),body);
    for(const kind of ['flight','hotel','esim','insurance','travel']){
      const choices=(message.options||[]).map((o,index)=>({...o,index})).filter(o=>(o.kind||'travel')===kind);if(!choices.length)continue;
      const group=el('section','option-group '+kind);group.setAttribute('aria-label',names[kind]||'Travel options');
      const heading=el('div','option-group-heading');heading.append(el('strong','',(icons[kind]||'✦')+' '+(names[kind]||'Travel')+' options'),el('small','','Choose one, or ask Sama to find another option'));group.append(heading);
      choices.forEach(option=>{
        const row=el('article','option-row'),choice=el('label','option-choice'),radio=el('input');radio.type='radio';radio.name='travel-choice-'+kind;radio.value=`${message.message_index}:${option.index}`;radio.dataset.optionId=radio.value;
        if(option.sandbox||option.expired){radio.dataset.stale='true';radio.disabled=true;}
        const description=el('span','option-description');description.append(el('strong','',option.label+(option.sandbox?' · Test quote':'')),el('span','',option.detail));
        const price=el('span','option-price');price.append(el('strong','',option.price_min?`${option.price_min}${option.price_max!==option.price_min?' – '+option.price_max:''} ${option.currency}`:'Sama to quote'),
          el('small','',option.price_min?({per_unit:'One eSIM',per_person:'Per traveller',per_night:'Per night',total:'Party / stay total'}[option.price_basis]||'Estimate'):''));
        choice.append(radio,description,price);row.append(choice);
        try{const url=new URL(option.source_url);if(['https:','http:'].includes(url.protocol)){const link=el('a','option-source','Details ↗');link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';row.append(link);}}catch(_){}
        group.append(row);
      });node.append(group);
    }
    if(message.sources?.length){const details=el('details','concierge-sources');details.append(el('summary','','Sources'));message.sources.forEach(source=>{try{const url=new URL(source.url);if(!['https:','http:'].includes(url.protocol))return;const a=el('a','',source.title);a.href=url.href;a.target='_blank';a.rel='noopener noreferrer';details.append(a);}catch(_){}});node.append(details);}
    messages.insertBefore(node,card);return node;
  }
  function formatLinks(body){
    // Render citation links without interpreting arbitrary supplier/model HTML.
    const text=body.textContent,pattern=/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g;let start=0,match;
    body.replaceChildren();
    while((match=pattern.exec(text))){body.append(document.createTextNode(text.slice(start,match.index)));const link=el('a','',match[1]);link.href=match[2];link.target='_blank';link.rel='noopener noreferrer';body.append(link);start=pattern.lastIndex;}
    body.append(document.createTextNode(text.slice(start)));
  }
  guideForm.addEventListener('submit',event=>{event.preventDefault();if(!busy&&guideForm.reportValidity())onAnswer();});
  function render(){
    if(offerHome){offerHome.parent.append(offerHome.group);offerHome=null;}
    const step=override||guide.step;renderId++;textAnswer=null;controls.replaceChildren();actions.replaceChildren();onAnswer=()=>{};$('#guide-error').textContent='';$('#guide-description').textContent='';
    if(step!=='ready')reviewShown=false;
    $('#guide-question').textContent=guide.question;$('#guide-step-label').textContent=override?'CHANGE YOUR DETAILS':'YOUR TRIP';
    const phase=['services','route','departure','return','travellers'].includes(step)?0:['notes','ready'].includes(step)?2:1;
    root.querySelectorAll('[data-progress]').forEach((li,index)=>{li.classList.toggle('current',index===phase);li.classList.toggle('done',index<phase);if(index===phase)li.setAttribute('aria-current','step');else li.removeAttribute('aria-current');});
    if(step==='services'){
      $('#guide-question').textContent='What would you like us to arrange?';$('#guide-description').textContent='Choose all the services you need.';
      const grid=el('div','service-grid');controls.append(grid);
      Object.entries(names).forEach(([kind,name])=>{
        const label=el('label','service-choice'),check=el('input');check.type='checkbox';check.value=kind;check.name='service';check.checked=guide.services.includes(kind);
        label.append(check,icon(kind),el('strong','',name),el('small','',{flight:'Timings & flight choices',hotel:'Rooms & stays',transfer:'Airport & local journeys',esim:'Mobile data abroad',insurance:'Cover for your trip'}[kind]));grid.append(label);
      });next(()=>sendStep(step,{services:[...controls.querySelectorAll(':checked')].map(n=>n.value)}));
    }else if(step==='route'){
      $('#guide-question').textContent='Where are you travelling from and to?';
      const from=field('From','guide-origin','text',trip.origin),to=field('To','guide-destination','text',trip.destination);from.placeholder='City or airport';to.placeholder='City or destination';
      next(()=>sendStep(step,{origin:from.value,destination:to.value}));
    }else if(step==='departure'){
      $('#guide-question').textContent='When would you like to leave?';const start=field('Departure date','guide-departure','date',trip.departure);start.min=today;next(()=>sendStep(step,{departure:start.value}));
    }else if(step==='return'){
      $('#guide-question').textContent='When does your trip end?';
      const tabs=el('div','guide-choice-tabs');controls.append(tabs);let mode='date',dateField,nights;
      const area=el('div');controls.append(area);
      const draw=selected=>{mode=selected;area.replaceChildren();tabs.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.mode===selected)));
        const label=el('label','',selected==='date'?'Return / end date':'Number of nights'),n=el('input');n.type=selected==='date'?'date':'number';n.required=true;n.id='guide-end';label.htmlFor=n.id;
        if(selected==='date'){n.value=trip.return_date||'';n.min=trip.departure;dateField=n;}else{n.min=1;n.max=365;n.value='5';nights=n;}area.className='guide-field';area.append(label,n);};
      [['date','Choose a date'],['nights','Number of nights']].forEach(([mode,label])=>{const b=button(label,()=>draw(mode));b.dataset.mode=mode;tabs.append(b);});draw('date');
      next(()=>sendStep(step,mode==='date'?{return_date:dateField.value}:{nights:Number(nights.value)}));
      if(guide.can_one_way)actions.append(button('One-way trip',()=>sendStep(step,{one_way:true}),'text'));
    }else if(step==='travellers'){
      $('#guide-question').textContent='Who is travelling?';$('#guide-description').textContent='Include everyone in this request.';
      const party=guide.passengers,fields={};
      [['adults','Adults','12 years and over'],['children','Children','2–11 years'],['infants','Infants','Under 2 years']].forEach(([key,label,help])=>{
        const row=el('div','traveller-counter'),copy=el('div');copy.append(el('strong','',label),el('small','',help));const counter=el('div','counter-control'),n=el('input');n.type='number';n.id='guide-'+key;n.setAttribute('aria-label',label);n.min=key==='adults'?1:0;n.max=100;n.value=party[key]??(key==='adults'?(Number(trip.travellers)||1):0);n.required=true;
        counter.append(button('−',()=>{n.value=Math.max(Number(n.min),Number(n.value)-1);}),n,button('+',()=>{n.value=Math.min(100,Number(n.value)+1);}));row.append(copy,counter);controls.append(row);fields[key]=n;
      });next(()=>sendStep(step,Object.fromEntries(Object.entries(fields).map(([k,n])=>[k,Number(n.value)]))));
    }else if(step==='flight'){
      $('#guide-step-label').textContent='FLIGHTS';$('#guide-question').textContent='How would you like to fly?';const detail=guide.details.flight||{},grid=el('div','cabin-choices');controls.append(grid);
      ['Economy','Premium economy','Business','First'].forEach((cabin,i)=>{const label=el('label','pill-choice'),radio=el('input');radio.type='radio';radio.name='cabin';radio.value=cabin;radio.checked=detail.cabin?detail.cabin===cabin:i===0;label.append(radio,el('span','',cabin));grid.append(label);});
      const airline=field('Preferred airline (optional)','guide-airline','text',detail.airline,false);airline.placeholder='Any airline is fine';next(()=>sendStep(step,{cabin:controls.querySelector('[name=cabin]:checked').value,airline:airline.value}),'Find flight options →');skip('flight');
    }else if(step==='transfer'){
      $('#guide-step-label').textContent='TRANSFERS';$('#guide-question').textContent='Where do you need a transfer?';const n=field('Pickup, drop-off and any preferences','guide-transfer','textarea',guide.details.transfer?.note,false);n.placeholder='For example: arrival airport to our hotel, for 2 people.';
      next(()=>sendStep(step,{note:n.value||'Sama to confirm pickup and drop-off.'}));
    }else if(['hotel','esim','insurance'].includes(step)){
      renderProvider(step);
    }else if(step.endsWith('_options')){
      renderOffers(step.replace('_options',''));
    }else if(step==='notes'){
      $('#guide-step-label').textContent='ALMOST DONE';$('#guide-question').textContent='Anything else for Sama?';$('#guide-description').textContent='Special requests, a preferred hotel area, or anything we should know.';const n=field('Your note (optional)','guide-note','textarea',guide.note,false);next(()=>sendStep(step,{note:n.value}),'Review my request →');actions.append(button('Nothing else',()=>sendStep(step,{note:''}),'text'));
    }else if(step==='ready'){
      $('#guide-step-label').textContent='READY WHEN YOU ARE';$('#guide-question').textContent='Your request is ready.';$('#guide-description').textContent='Review the trip, then send it to your Sama team.';actions.append(button('Review & send request →',openReview,'primary'));
      if(!reviewShown){reviewShown=true;setTimeout(openReview,150);}
    }
    if(override)actions.append(button('Back to current step',()=>{override='';wizard='';render();},'text'));
    memory();
    $('#guide-step-label').textContent='HelloSama assistant'+(phase===1?' · '+(names[step.replace('_options','')]||'Your services'):'');
    input.placeholder=wizard==='birthdates'?'Enter the birth date above (kept private)':'Type a reply, or choose an option above…';
  }
  const countryName=code=>countries.find(c=>c.code===code)?.name||code;
  function countryReply(select,callback){
    textAnswer=async text=>{const match=countries.find(c=>c.code.toLowerCase()===text.toLowerCase()||c.name.toLowerCase()===text.toLowerCase());if(!match){$('#guide-error').textContent='Choose a country from the list, or type its name.';return;}select.value=match.code;await callback();};
  }
  async function saveContext(data,nextStep,automatic=false){
    if(busy)return;setBusy(true);
    try{const result=await postJSON(root.dataset.guideUrl,{step:'context',values:data,version:guide.version,automatic});apply(result);appendAnswers(result);Object.assign(quote,guide.context);wizard=nextStep;setBusy(false);render();scrollCard();}
    catch(error){setBusy(false);$('#guide-error').textContent=error.message;}
  }
  function afterDestination(kind){return kind==='hotel'?(quote.nationality?'rooms':'nationality'):kind==='insurance'?(quote.residence?'birthdates':'residence'):'search';}
  function insuranceNotice(){
    $('#guide-question').textContent='Sama can arrange your travel insurance.';
    $('#guide-description').textContent='Online insurance is currently in test mode, so those plans cannot be selected. I can include cover in your request for Sama to quote.';
    actions.append(button('Let Sama arrange cover',()=>sendStep('skip_service',{service:'insurance'}),'primary'));
  }
  function renderProvider(kind){
    if(wizardKind!==kind){
      wizardKind=kind;quote={...(guide.context||{}),...(!guide.details[kind]?.manual?guide.details[kind]:{})};
      wizard=quote.country?(kind==='hotel'&&!quote.city_id?'city':afterDestination(kind)):(connections.hotel&&trip.destination?'city':'country');
    }
    $('#guide-step-label').textContent=names[kind].toUpperCase();
    if(kind==='insurance'&&insuranceTest){insuranceNotice();return;}
    if(!connections[kind]){
      $('#guide-question').textContent='Sama can arrange your '+names[kind].toLowerCase()+'.';$('#guide-description').textContent='Online offers aren’t connected for this service yet. Include it in your request and Sama will help.';actions.append(button('Include '+names[kind].toLowerCase()+' in my request',()=>sendStep('skip_service',{service:kind}),'primary'));return;
    }
    if(quote.country)$('#guide-description').textContent='Using '+(kind==='hotel'&&quote.city_name?quote.city_name+', ':'')+countryName(quote.country)+' · '+dateLabel(trip.departure)+(trip.return_date?'–'+dateLabel(trip.return_date):'')+' · '+trip.travellers+' travellers. You can change these above.';
    if(wizard==='country'){
      $('#guide-question').textContent='Which country is '+trip.destination+' in?';
      const n=country('Destination country','guide-country',quote.country);
      const reply=()=>{if(quote.country!==n.value){delete quote.city_id;delete quote.city_name;}quote.country=n.value;return saveContext({field:'country',country:n.value},kind==='hotel'?'city':afterDestination(kind));};next(reply);countryReply(n,reply);
    }else if(wizard==='city'){
      $('#guide-question').textContent=kind==='hotel'?'I’ll look for hotels in your destination.':'Let’s match your destination.';
      $('#guide-description').textContent='I’ll reuse the city and country across your services. Choose a suggestion if there is more than one match.';
      const q=field(kind==='hotel'?'City for your hotel':'Destination city','guide-city-query','search',quote.city_name||trip.destination),suggestions=el('div','city-suggestions'),status=el('p','city-status');status.setAttribute('role','status');controls.append(status,suggestions);
      let timer,sequence=0;const generation=renderId;
      const choose=(city,automatic=false)=>{quote.city_id=String(city.id);quote.city_name=city.name;quote.country=city.country;return saveContext({field:'city',city_id:quote.city_id,city_name:city.name,country:city.country},afterDestination(kind),automatic);};
      const lookup=async automatic=>{
        const seq=++sequence,name=q.value.trim();suggestions.replaceChildren();if(name.length<2){status.textContent='Type at least two letters to see matching cities.';return;}status.textContent='Matching your destination…';
        try{const response=await fetch(root.dataset.citiesUrl+'?'+new URLSearchParams({country:quote.country||'',q:name}));const result=await response.json();if(generation!==renderId||seq!==sequence)return;if(!response.ok)throw new Error(result.error);
          const matches=result.cities,exact=matches.filter(c=>c.exact);status.textContent=matches.length?'Choose your city:':'No matching city. Try another spelling or choose the country below.';
          if(automatic&&exact.length===1){await choose(exact[0],true);return;}
          matches.forEach(city=>suggestions.append(button(city.name+', '+city.country_name,()=>choose(city),'reply-chip')));
        }catch(error){if(generation===renderId&&seq===sequence)status.textContent=error.message;}
      };
      q.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>lookup(false),350);});textAnswer=text=>{q.value=text;return lookup(true);};onAnswer=()=>lookup(false);
      setTimeout(()=>{if(generation===renderId)lookup(!quote.city_id&&!quote.change_city);},0);
      actions.append(button('Choose country instead',()=>{wizard='country';render();},'text'));
    }else if(wizard==='nationality'){
      $('#guide-question').textContent='What is the lead traveller’s nationality?';$('#guide-description').textContent+=' The hotel needs this for eligible prices.';const n=country('Nationality','guide-nationality',quote.nationality);const reply=()=>{quote.nationality=n.value;return saveContext({field:'nationality',nationality:n.value},'rooms');};next(reply);countryReply(n,reply);
    }else if(wizard==='rooms'){
      $('#guide-question').textContent='Any hotel preferences?';
      const party=guide.passengers;
      if(!quote.rooms?.length)quote.rooms=[{adults:Math.min(party.adults||1,9),childrenAges:[...Array(party.children||0).fill(''),...Array(party.infants||0).fill(0)]}];
      const allocation=el('details','room-allocation'),summary=el('summary');allocation.open=quote.rooms.length>1||!!party.children||party.adults>9;allocation.append(summary);controls.append(allocation);
      const rooms=el('div','guide-rooms');allocation.append(rooms);
      const draw=()=>{rooms.replaceChildren();quote.rooms.forEach((room,index)=>{
        const box=el('fieldset','guide-room');box.append(el('legend','','Room '+(index+1)));
        const adult=el('input');adult.type='number';adult.min=1;adult.max=9;adult.required=true;adult.value=room.adults;adult.setAttribute('aria-label','Adults in room '+(index+1));adult.addEventListener('input',()=>room.adults=Number(adult.value));const label=el('label','','Adults');label.append(adult);box.append(label);
        room.childrenAges.forEach((age,child)=>{const row=el('div','child-age'),caption=el('label','','Child / infant '+(child+1)+' age'),n=el('input');n.type='number';n.min=0;n.max=18;n.required=true;n.value=age;caption.append(n);n.addEventListener('input',()=>room.childrenAges[child]=n.value===''?'':Number(n.value));row.append(caption,button('Remove',()=>{room.childrenAges.splice(child,1);draw();},'text'));box.append(row);});
        if(room.childrenAges.length<8)box.append(button('＋ Add child or infant',()=>{room.childrenAges.push('');draw();},'text'));
        if(quote.rooms.length>1)box.append(button('Remove room',()=>{quote.rooms.splice(index,1);draw();},'text'));rooms.append(box);
      });summary.textContent=quote.rooms.length+' room'+(quote.rooms.length===1?'':'s')+' · '+partyLabel(party)+' · Change rooms';};draw();
      allocation.append(button('＋ Add another room',()=>{if(quote.rooms.length<10){quote.rooms.push({adults:1,childrenAges:[]});draw();}},'secondary'));
      if(party.children)$('#guide-description').textContent+=' Add the children’s ages below; your traveller counts are already filled in.';
      const pref=field('Hotel preferences (optional)','guide-hotel-preferences','text',quote.preferences,false);pref.placeholder='Area, breakfast, room type…';next(()=>{quote.preferences=pref.value;saveQuoteDetails(kind);},'Show hotel options →');
    }else if(wizard==='residence'){
      $('#guide-question').textContent='Which country do the travellers live in?';const n=country('Country of residence','guide-residence',quote.residence);const reply=()=>{quote.residence=n.value;quote.birth_dates=[];return saveContext({field:'residence',residence:n.value},'birthdates');};next(reply);countryReply(n,reply);
    }else if(wizard==='birthdates'){
      const index=quote.birth_dates?.length||0;$('#guide-question').textContent='What is traveller '+(index+1)+'’s date of birth?';$('#guide-description').textContent='Used only for this insurance quote. It is not saved in the chat or sent to the AI.';const n=field('Birth date · traveller '+(index+1)+' of '+trip.travellers,'guide-birthdate','date');n.max=today;
      next(()=>{quote.birth_dates=quote.birth_dates||[];quote.birth_dates.push(n.value);if(quote.birth_dates.length<Number(trip.travellers))render();else saveQuoteDetails(kind);},index+1===Number(trip.travellers)?'Show insurance options →':'Next traveller →');
      textAnswer=()=>{$('#guide-error').textContent='Use the private birth-date field above. Birth dates are not sent to the AI.';};
    }else if(wizard==='search'){
      $('#guide-question').textContent='I’ll check '+countryName(quote.country)+' eSIM options for you.';
      const generation=renderId;setTimeout(()=>{if(generation===renderId)saveQuoteDetails(kind,true);},0);
    }
    if(['nationality','rooms'].includes(wizard))actions.append(button('Change hotel city',()=>{quote.change_city=true;wizard='city';render();},'text'));
    if(['residence','birthdates','search'].includes(wizard))actions.append(button('Change destination country',()=>{wizard='country';render();},'text'));
    skip(kind);
  }
  async function saveQuoteDetails(kind,automatic=false){
    const dates=quote.birth_dates||[];const data={...quote};delete data.birth_dates;
    if(busy)return;setBusy(true);
    try{
      const result=await postJSON(root.dataset.guideUrl,{step:kind,values:data,version:guide.version,automatic});apply(result);appendAnswers(result);override='';wizard='';wizardKind='';quote={};setBusy(false);
      searched.add(kind+':'+guide.version);render();await searchProvider(kind,dates);
    }catch(error){setBusy(false);$('#guide-error').textContent=error.message;}
  }
  function renderOffers(kind){
    if(kind==='insurance'&&insuranceTest){insuranceNotice();return;}
    $('#guide-step-label').textContent=names[kind].toUpperCase();$('#guide-question').textContent='Choose your '+({flight:'flight',hotel:'hotel',esim:'eSIM',insurance:'travel cover'}[kind])+', or leave it to Sama.';
    $('#guide-description').textContent='Selecting an option adds it to your request.';
    if(selections[kind])actions.append(button('Continue with my selected option',()=>sendStep('complete_service',{service:kind}),'primary'));
    const choices=[...messages.querySelectorAll(`[name="travel-choice-${kind}"]`)].filter(n=>n.dataset.stale!=='true');
    if(choices.length){const group=choices.at(-1).closest('.option-group');offerHome={group,parent:group.parentElement};controls.append(group);}
    if(!choices.length){
      const key=kind+':'+guide.version;
      if(!searched.has(key)){
        searched.add(key);
        if(kind==='flight')setTimeout(searchFlights,0);
        else if(kind==='insurance'){wizardKind='insurance';quote={...guide.details.insurance,birth_dates:[]};wizard='birthdates';override='insurance';setTimeout(render,0);}
        else setTimeout(()=>searchProvider(kind),0);
      }else actions.append(button('Try the search again',()=>kind==='flight'?searchFlights():kind==='insurance'?edit('insurance'):searchProvider(kind),'primary'));
    }else actions.append(button('Search again / change preferences',()=>edit(kind)));
    skip(kind);
  }
  async function searchProvider(kind,birthdates=[]){
    if(busy)return;setBusy(true,'Checking '+names[kind].toLowerCase()+' offers…');
    try{const result=await postJSON(root.dataset.offersUrl,{kind,...guide.details[kind],...(kind==='insurance'?{birth_dates:birthdates}:{})});append(result.message);updateSelections(result.message);setBusy(false);render();scrollCard();}
    catch(error){setBusy(false);$('#guide-error').textContent=error.message;actions.prepend(button('Continue with Sama’s help',()=>sendStep('skip_service',{service:kind}),'primary'));}
    finally{birthdates.fill('');}
  }
  async function searchFlights(){
    if(busy)return;
    if(root.dataset.available!=='true'){$('#guide-error').textContent='Online flight research is unavailable. Sama can find options for you.';return;}
    const detail=guide.details.flight||{};
    await chat(`Show sourced flight timings for ${trip.origin} to ${trip.destination}, departing ${trip.departure}${trip.return_date?', returning '+trip.return_date:', one way'}, for ${trip.travellers} travellers. ${detail.cabin||''}. ${detail.airline?'Preferred airline: '+detail.airline+'.':''} Keep the reply brief.`,false);
  }
  async function chat(content,showUser=true){
    if(busy)return;setBusy(true,'Your assistant is checking…');if(showUser)append({role:'user',content});
    try{const result=await postJSON(root.dataset.aiUrl,{message:content});append(result.message);apply(result);override='';setBusy(false);render();scrollCard();}
    catch(error){setBusy(false);$('#assistant-error').textContent=error.message;}
  }
  chatForm.addEventListener('submit',event=>{event.preventDefault();if(!input.value.trim()||busy)return;const content=input.value.trim();input.value='';if(textAnswer)textAnswer(content);else chat(content);});
  input.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();chatForm.requestSubmit();}});
  messages.addEventListener('change',async event=>{
    const radio=event.target.closest('[data-option-id]');if(!radio||busy)return;const kind=radio.name.replace('travel-choice-','');
    if(!guide.services.includes(kind)){$('#guide-error').textContent='Add this service to your trip first.';radio.checked=false;return;}
    setBusy(true,'Saving your choice…');try{const result=await postJSON(root.dataset.selectUrl,{option_id:radio.value});updateSelections(result);setBusy(false);await sendStep('complete_service',{service:kind});}catch(error){setBusy(false);updateSelections({selections});$('#guide-error').textContent=error.message;}
  });
  function openReview(){
    if(busy||submittedUrl)return;
    if(guide.step!=='ready'){override='';render();scrollCard();return;}
    const facts=$('#review-facts');facts.replaceChildren();
    [['Route',trip.origin+' → '+trip.destination,'route'],['Travel dates',dateLabel(trip.departure)+(trip.return_date?' → '+dateLabel(trip.return_date):' · One way'),'departure'],
      ['Travellers',partyLabel(guide.passengers),'travellers'],['Services',guide.services.map(k=>names[k]).join(', '),'services']].forEach(([label,value,step])=>{
      const row=el('div','review-fact'),copy=el('div');copy.append(el('small','',label),el('strong','',value));row.append(copy,button('Edit',()=>edit(step),'text'));facts.append(row);
      if(step==='departure')row.append(button('Edit end',()=>edit('return'),'text'));
    });
    const offers=$('#review-options');offers.replaceChildren();guide.services.forEach(kind=>{const option=selections[kind],detail=guide.details[kind]||{},row=el('div','review-option');row.append(icon(kind),el('div'));const body=row.lastElementChild;body.append(el('strong','',names[kind]),el('span','',option?option.label:kind==='transfer'&&detail.note?detail.note:'Sama will find the best option'));
      if(kind==='flight'&&detail.cabin)body.append(el('small','',detail.cabin+(detail.airline?' · '+detail.airline:'')));
      if(kind==='hotel'&&detail.rooms)body.append(el('small','',detail.rooms.length+' room'+(detail.rooms.length===1?'':'s')+' · '+(detail.preferences||detail.city_name)));
      if(option?.price_min)body.append(el('small','',option.price_min+' '+option.currency+' · '+({per_unit:'one eSIM',per_person:'per traveller',per_night:'per night',total:'party / stay total'}[option.price_basis]||'estimate')));row.append(button('Edit',()=>edit(kind),'text'));offers.append(row);});
    const notes=$('#review-notes');notes.replaceChildren();if(guide.note)notes.append(el('small','','Your note'),el('p','',guide.note));
    Object.entries(values).forEach(([key,value])=>{const field=requestForm.elements.namedItem(key);if(field)field.value=value??'';});
    requestForm.elements.namedItem('journey_version').value=guide.version;
    if(!dialog.open)dialog.showModal();$('#review-title').focus();
  }
  $('#open-request-review').addEventListener('click',openReview);
  root.querySelectorAll('.review-close').forEach(b=>b.addEventListener('click',()=>dialog.close()));
  dialog.addEventListener('close',()=>{if(submittedUrl)location.href=submittedUrl;});
  requestForm.addEventListener('submit',async event=>{
    event.preventDefault();if(busy||submittedUrl)return;setBusy(true,'Sending your request to Sama…');$('#submit-error').textContent='';
    try{
      const response=await fetch(location.href,{method:'POST',credentials:'same-origin',body:new FormData(requestForm),headers:{'X-CSRFToken':csrf(),'X-Requested-With':'XMLHttpRequest'}});const result=await response.json();
      if(!response.ok||!result.submitted)throw new Error(result.error||'Your request could not be sent. Please check your trip.');
      submittedUrl=result.url;requestForm.hidden=true;$('#request-success').hidden=false;$('#review-eyebrow').textContent='SENT TO SAMA';$('#review-title').textContent='Your request has been sent.';$('#review-intro').textContent='Everything below is saved with your request.';$('#success-reference').textContent='Request '+result.reference;$('#view-submitted-request').href=result.url;$('#review-intro').after($('#request-success'));$('#trip-status').textContent='Sent to Sama';setBusy(false);$('#review-title').focus();
      root.querySelectorAll('.review-fact button,.review-option button').forEach(b=>b.hidden=true);
    }catch(error){setBusy(false);$('#submit-error').textContent=error.message;}
  });
  messages.querySelectorAll('.chat-message.ai .message-body').forEach(formatLinks);
  render();updateSelections({selections});setBusy(false);
  if($('#batch-review'))$('#batch-review').scrollIntoView();else scrollCard();
})();
