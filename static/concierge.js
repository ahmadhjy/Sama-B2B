'use strict';
(() => {
  const root=document.querySelector('#planner[data-guided]');
  if(!root)return;
  const $=selector=>root.querySelector(selector);
  const read=id=>JSON.parse(document.getElementById(id).textContent);
  const names={flight:'Flights',hotel:'Hotel',transfer:'Transfers',esim:'eSIM',insurance:'Travel insurance'};
  const icons={flight:'✈',hotel:'▤',transfer:'↗',esim:'▣',insurance:'♧'};
  const countries=read('provider-countries'),connections=read('provider-available');
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
  function typed(placeholder,callback){input.placeholder=placeholder;textAnswer=callback||null;}
  function recordReply(text){append({role:'assistant',content:$('#guide-question').textContent,guided:true});append({role:'user',content:text,guided:true});}
  function calendar(label,id,value,callback,min=today){
    actions.append(button(label,()=>{controls.replaceChildren();const n=field(label,id,'date',value);n.min=min;actions.prepend(button('Use this date',()=>{if(n.reportValidity())callback(n.value);},'primary'));n.focus();}));
  }
  function validBirthDate(value){const date=new Date(value+'T12:00:00Z');return /^\d{4}-\d{2}-\d{2}$/.test(value)&&value<=today&&value>='1906-01-01'&&!Number.isNaN(date.valueOf())&&date.toISOString().slice(0,10)===value;}
  function scrollCard(){requestAnimationFrame(()=>{messages.scrollTo({top:Math.max(0,card.offsetTop-16),behavior:'auto'});});}
  function setBusy(value,text='Saving your answer…'){
    busy=value;root.setAttribute('aria-busy',String(value));
    root.querySelectorAll('#guide-form button,#guide-form input,#guide-form select,#guide-form textarea,[data-option-id],#assistant-form button,#chat-input,#submit-request').forEach(node=>{
      node.disabled=value||node.dataset.stale==='true';
    });
    $('#assistant-error').textContent=value?text:'';
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
      ['departure',dateLabel(trip.departure)],['return',dateLabel(trip.return_date)|| (guide.one_way?'One way':guide.return_pending?'Return undecided':'')],['travellers',trip.travellers?trip.travellers+' traveller'+(Number(trip.travellers)===1?'':'s'):'']];
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
        if(option.expired){radio.dataset.stale='true';radio.disabled=true;}
        const description=el('span','option-description'),detail=el('span','',option.detail);formatLinks(detail);description.append(el('strong','',option.label+(option.stars?' · '+option.stars+' ★':'')),detail);
        if(kind==='hotel'&&option.attributes?.length){const facts=el('span','hotel-attributes');option.attributes.forEach(a=>facts.append(el('span','hotel-attribute',a.label+': '+a.value)));description.append(facts);}
        const price=el('span','option-price');price.append(el('strong','',option.price_min?`${option.price_min}${option.price_max!==option.price_min?' – '+option.price_max:''} ${option.currency}`:'Sama to quote'),
          el('small','',option.price_min?({per_unit:'One eSIM',per_person:'Per traveller',per_night:'Per night',total:'Party / stay total'}[option.price_basis]||'Estimate'):''));
        choice.append(radio,description,price);row.append(choice);
        if(kind==='hotel'){
          const more=el('details','hotel-room-details');more.append(el('summary','','Room details & amenities'));
          for(const room of option.room_details||[]){const copy=el('div','hotel-room-copy');copy.append(el('strong','',room.name),el('p','','Room size: '+(room.size||'Not provided by supplier')));if(room.description)copy.append(el('p','',room.description));if(room.facilities)copy.append(el('p','',room.facilities));more.append(copy);}
          if(!option.room_details?.length)more.append(el('p','','Further room details were not provided by the supplier.'));row.append(more);
        }
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
    const step=override||guide.step;renderId++;textAnswer=null;input.placeholder='Type a reply, or choose an option above…';controls.replaceChildren();actions.replaceChildren();onAnswer=()=>{};$('#guide-error').textContent='';$('#guide-description').textContent='';
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
      $('#guide-question').textContent=trip.origin&&!override?'Where would you like to go?':'Where are you travelling from?';
      typed('For example: Beirut to Istanbul');
    }else if(step==='departure'){
      $('#guide-question').textContent='When would you like to leave?';typed('For example: 12 November 2026');calendar('Choose on a calendar','guide-departure',trip.departure,value=>sendStep(step,{departure:value}));
    }else if(step==='return'){
      $('#guide-question').textContent='When does your trip end?';typed('A return date, number of nights, or “not decided yet”');calendar('Choose on a calendar','guide-end',trip.return_date,value=>sendStep(step,{return_date:value}),trip.departure);
      if(guide.can_one_way)actions.append(button('One-way trip',()=>sendStep(step,{one_way:true}),'text'));
      actions.append(button('Return date undecided',()=>sendStep(step,{return_pending:true}),'secondary'));
      $('#guide-description').textContent='You can tell me a date or how many nights you’re staying.';
    }else if(step==='travellers'){
      $('#guide-question').textContent='Who is travelling?';$('#guide-description').textContent='Include everyone in this request.';
      const party=guide.passengers,fields={};
      [['adults','Adults','12 years and over'],['children','Children','2–11 years'],['infants','Infants','Under 2 years']].forEach(([key,label,help])=>{
        const row=el('div','traveller-counter'),copy=el('div');copy.append(el('strong','',label),el('small','',help));const counter=el('div','counter-control'),n=el('input');n.type='number';n.readOnly=true;n.id='guide-'+key;n.setAttribute('aria-label',label);n.min=key==='adults'?1:0;n.max=100;n.value=party[key]??(key==='adults'?(Number(trip.travellers)||1):0);n.required=true;
        counter.append(button('−',()=>{n.value=Math.max(Number(n.min),Number(n.value)-1);}),n,button('+',()=>{n.value=Math.min(100,Number(n.value)+1);}));row.append(copy,counter);controls.append(row);fields[key]=n;
      });next(()=>sendStep(step,Object.fromEntries(Object.entries(fields).map(([k,n])=>[k,Number(n.value)]))));
      typed('For example: 2 adults and 1 child');
    }else if(step==='flight'){
      $('#guide-step-label').textContent='FLIGHTS';$('#guide-question').textContent='How would you like to fly?';const detail=guide.details.flight||{},grid=el('div','cabin-choices');controls.append(grid);
      ['Economy','Premium economy','Business','First'].forEach((cabin,i)=>{const label=el('label','pill-choice'),radio=el('input');radio.type='radio';radio.name='cabin';radio.value=cabin;radio.checked=detail.cabin?detail.cabin===cabin:i===0;label.append(radio,el('span','',cabin));grid.append(label);});
      $('#guide-description').textContent='Choose a cabin. Tell me an airline in chat, or choose any airline.';
      const flightReply=airline=>sendStep(step,{cabin:controls.querySelector('[name=cabin]:checked').value,airline});
      actions.append(button('Any airline · Find flights',()=>flightReply(''),'primary'));typed('Preferred airline, or ask a question…',text=>{if(!/[?]/.test(text)&&text.split(/\s+/).length<=5&&!/\b(how|what|when|why|show|find|hotel|near|breakfast)\b/i.test(text))return flightReply(/^(any|no preference|any airline)( is fine)?$/i.test(text)?'':text);return chat(text);});skip('flight');
    }else if(step==='transfer'){
      $('#guide-step-label').textContent='TRANSFERS';$('#guide-question').textContent='Where should we pick you up and drop you off?';typed('For example: arrival airport to our hotel');actions.append(button('Airport to my hotel',()=>sendStep(step,{note:'Arrival airport to the hotel. Sama to confirm pickup details.'}),'primary'));skip('transfer');
    }else if(['hotel','esim','insurance'].includes(step)){
      renderProvider(step);
    }else if(step.endsWith('_options')){
      renderOffers(step.replace('_options',''));
    }else if(step==='notes'){
      $('#guide-step-label').textContent='ALMOST DONE';$('#guide-question').textContent='Anything else for Sama?';typed('Tell me here, or choose “Nothing else”…');actions.append(button('Nothing else · Review request',()=>sendStep(step,{note:''}),'primary'));
    }else if(step==='ready'){
      $('#guide-step-label').textContent='READY WHEN YOU ARE';$('#guide-question').textContent='Your request is ready.';$('#guide-description').textContent='Review the trip, then send it to your Sama team.';actions.append(button('Review & send request →',openReview,'primary'));
      if(!reviewShown){reviewShown=true;setTimeout(openReview,150);}
    }
    if(override)actions.append(button('Back to current step',()=>{override='';wizard='';render();},'text'));
    memory();
    $('#guide-step-label').textContent='HelloSama assistant'+(phase===1?' · '+(names[step.replace('_options','')]||'Your services'):'');
    if(!input.placeholder)input.placeholder='Type a reply, or choose an option above…';
  }
  const countryName=code=>countries.find(c=>c.code===code)?.name||code;
  function askCountry(value,callback){
    const choices=el('div','guide-choice-tabs');controls.append(choices);
    const draw=items=>{choices.replaceChildren();items.forEach(c=>choices.append(button(c.name,()=>callback(c.code),'reply-chip')));};
    draw([...new Set([value,guide.context?.country,guide.context?.nationality,'LB','FR','TR','AE','GB','US'].filter(Boolean))].slice(0,6).map(code=>countries.find(c=>c.code===code)).filter(Boolean));
    typed('Type the country name here…',async text=>{
      const aliases={lebanese:'LB',french:'FR',british:'GB',english:'GB',american:'US',turkish:'TR',emirati:'AE',usa:'US',uk:'GB',uae:'AE'};
      const name=text.trim().toLowerCase().replace(/’/g,"'").replace(/^(?:i am|i'm|we are|we're|we live in|i live in|my nationality is|nationality is|from)\s+/,'').replace(/(?:\s+please)?[.! ]*$/,''),code=aliases[name]||name;
      const match=countries.find(c=>c.code.toLowerCase()===code.toLowerCase()||c.name.toLowerCase()===name);
      if(match){await callback(match.code);return;}
      const matches=countries.filter(c=>c.name.toLowerCase().includes(name)).slice(0,8);
      if(matches.length){draw(matches);$('#guide-description').textContent='Which of these did you mean?';}else await chat(text);
    });
  }
  async function saveContext(data,nextStep,automatic=false){
    if(busy)return;setBusy(true);
    try{const result=await postJSON(root.dataset.guideUrl,{step:'context',values:data,version:guide.version,automatic});apply(result);appendAnswers(result);Object.assign(quote,guide.context);wizard=nextStep;setBusy(false);render();scrollCard();}
    catch(error){setBusy(false);$('#guide-error').textContent=error.message;}
  }
  function afterDestination(kind){return kind==='hotel'?(quote.nationality?'rooms':'nationality'):kind==='insurance'?(quote.residence?'birthdates':'residence'):'search';}
  function pendingDates(kind){
    if(!['hotel','insurance'].includes(kind)||trip.return_date)return false;
    $('#guide-question').textContent=kind==='hotel'?'I’ll leave your hotel dates open.':'I’ll leave your insurance dates open.';
    $('#guide-description').textContent='Sama needs the '+(kind==='hotel'?'check-out':'cover end')+' date before checking prices. You can still include this service in your request.';
    actions.append(button('Let Sama confirm the dates',()=>sendStep('skip_service',{service:kind}),'primary'),button('Add an end date',()=>edit('return'),'text'));
    return true;
  }
  function renderProvider(kind){
    if(wizardKind!==kind){
      wizardKind=kind;quote={...(guide.context||{}),...(!guide.details[kind]?.manual?guide.details[kind]:{}),criteria:{...(guide.hotel_criteria||{})}};
      wizard=quote.country?(kind==='hotel'&&!quote.city_id?'city':afterDestination(kind)):(connections.hotel&&trip.destination?'city':'country');
    }
    $('#guide-step-label').textContent=names[kind].toUpperCase();
    if(pendingDates(kind))return;
    if(!connections[kind]){
      $('#guide-question').textContent='Sama can arrange your '+names[kind].toLowerCase()+'.';$('#guide-description').textContent='Online offers aren’t connected for this service yet. Include it in your request and Sama will help.';actions.append(button('Include '+names[kind].toLowerCase()+' in my request',()=>sendStep('skip_service',{service:kind}),'primary'));return;
    }
    if(quote.country)$('#guide-description').textContent='Using '+(kind==='hotel'&&quote.city_name?quote.city_name+', ':'')+countryName(quote.country)+' · '+dateLabel(trip.departure)+(trip.return_date?'–'+dateLabel(trip.return_date):'')+' · '+trip.travellers+' travellers. You can change these above.';
    if(wizard==='country'){
      $('#guide-question').textContent='Which country is '+trip.destination+' in?';
      askCountry(quote.country,code=>{if(quote.country!==code){delete quote.city_id;delete quote.city_name;}quote.country=code;return saveContext({field:'country',country:code},kind==='hotel'?'city':afterDestination(kind));});
    }else if(wizard==='city'){
      $('#guide-question').textContent=kind==='hotel'?'I’ll look for hotels in your destination.':'Let’s match your destination.';
      $('#guide-description').textContent='I’ll reuse the city and country across your services. Choose a suggestion if there is more than one match.';
      const suggestions=el('div','city-suggestions'),status=el('p','city-status');status.setAttribute('role','status');controls.append(status,suggestions);
      let sequence=0,query=quote.city_name||trip.destination;const generation=renderId;
      const choose=(city,automatic=false)=>{quote.city_id=String(city.id);quote.city_name=city.name;quote.country=city.country;return saveContext({field:'city',city_id:quote.city_id,city_name:city.name,country:city.country},afterDestination(kind),automatic);};
      const lookup=async automatic=>{
        const seq=++sequence,name=query.trim();suggestions.replaceChildren();if(name.length<2){status.textContent='Tell me the city name in chat.';return;}status.textContent='Matching your destination…';
        try{const response=await fetch(root.dataset.citiesUrl+'?'+new URLSearchParams({country:quote.country||'',q:name}));const result=await response.json();if(generation!==renderId||seq!==sequence)return;if(!response.ok)throw new Error(result.error);
          const matches=result.cities,exact=matches.filter(c=>c.exact);status.textContent=matches.length?'Choose your city:':'No matching city. Try another spelling or choose the country below.';
          if(automatic&&exact.length===1){await choose(exact[0],true);return;}
          matches.forEach(city=>suggestions.append(button(city.name+', '+city.country_name,()=>choose(city),'reply-chip')));
        }catch(error){if(generation===renderId&&seq===sequence)status.textContent=error.message;}
      };
      typed('Type the destination city here…',text=>{query=text;return lookup(true);});
      setTimeout(()=>{if(generation===renderId)lookup(!quote.city_id&&!quote.change_city);},0);
      actions.append(button('Choose country instead',()=>{wizard='country';render();},'text'));
    }else if(wizard==='nationality'){
      $('#guide-question').textContent='What is the lead traveller’s nationality?';$('#guide-description').textContent+=' The hotel needs this for eligible prices.';askCountry(quote.nationality,code=>{quote.nationality=code;return saveContext({field:'nationality',nationality:code},'rooms');});
    }else if(wizard==='rooms'){
      $('#guide-question').textContent='How many rooms would you like?';$('#guide-description').textContent=partyLabel(guide.passengers)+'. I’ll confirm who stays in each room.';
      const party=guide.passengers;
      const choose=count=>{recordReply(count+' room'+(count===1?'':'s'));quote.rooms=Array.from({length:count},()=>({adults:0,childrenAges:[]}));quote.assignAdult=0;quote.assignChild=0;wizard='room_guests';render();};
      const minRooms=Math.max(1,Math.ceil(party.adults/9),Math.ceil((party.children+party.infants)/8)),maxRooms=Math.min(10,party.adults);
      if(minRooms>maxRooms)$('#guide-description').textContent='This group needs a room allocation arranged by Sama. You can include the hotel service below.';
      for(let count=minRooms;count<=maxRooms;count++)controls.append(button(count+' room'+(count===1?'':'s'),()=>choose(count),'reply-chip'));
      typed('Tell me the number of rooms…',text=>{const words=['one','two','three','four','five','six','seven','eight','nine','ten'],match=text.match(/^(\d+)\s*(?:rooms?)?$/i),count=match?Number(match[1]):words.indexOf(text.trim().toLowerCase().replace(/ rooms?$/,''))+1;if(count>=minRooms&&count<=maxRooms)choose(count);else chat(text);});
    }else if(wizard==='room_guests'){
      const party=guide.passengers,rooms=quote.rooms;
      if(rooms.length===1){rooms[0].adults=party.adults;quote.assignAdult=1;}
      const remaining=party.adults-rooms.reduce((n,r)=>n+r.adults,0),index=quote.assignAdult||0;
      if(index<rooms.length){
        $('#guide-question').textContent='How many adults in room '+(index+1)+'?';
        const max=Math.min(9,remaining-(rooms.length-index-1)),min=Math.max(1,remaining-9*(rooms.length-index-1));
        const choose=count=>{recordReply(count+' adult'+(count===1?'':'s')+' in room '+(index+1));rooms[index].adults=count;quote.assignAdult=index+1;render();};
        for(let count=min;count<=max;count++)controls.append(button(String(count),()=>choose(count),'reply-chip'));
        typed('Number of adults in this room…',text=>{const count=Number(text.trim());if(Number.isInteger(count)&&count>=min&&count<=max)choose(count);else chat(text);});
      }else if((quote.assignChild||0)<party.children+party.infants){
        const child=quote.assignChild||0;
        if(!quote.childRoom&&quote.childRoom!==0&&rooms.length===1)quote.childRoom=0;
        if(quote.childRoom===undefined){$('#guide-question').textContent='Which room for child / infant '+(child+1)+'?';rooms.forEach((room,i)=>{if(room.childrenAges.length<8)controls.append(button('Room '+(i+1),()=>{recordReply('Room '+(i+1));quote.childRoom=i;render();},'reply-chip'));});}
        else{
          $('#guide-question').textContent='How old will child / infant '+(child+1)+' be at check-in?';
          const choose=age=>{recordReply(age===0?'Under 1 year':age+' year'+(age===1?'':'s')+' old');rooms[quote.childRoom].childrenAges.push(age);delete quote.childRoom;quote.assignChild=child+1;render();};
          const minAge=child<party.children?2:0,maxAge=child<party.children?11:1;
          for(let age=minAge;age<=maxAge;age++)controls.append(button(age===0?'Under 1':String(age),()=>choose(age),'reply-chip'));
          typed('Age at check-in…',text=>{const clean=text.trim().replace(/’/g,"'").replace(/^(?:he is|he's|she is|she's|age|aged|my son is|my daughter is)\s+/i,'').replace(/[.!]+$/,''),match=clean.match(/^(\d+)(?:\s*(?:years?(?: old)?))?$/i),age=match?Number(match[1]):-1;if(Number.isInteger(age)&&age>=minAge&&age<=maxAge)choose(age);else $('#guide-error').textContent='Choose an age from '+minAge+' to '+maxAge+', or change the traveller counts above.';});
        }
      }else{wizard='hotel_stars';setTimeout(render,0);}
    }else if(wizard.startsWith('hotel_')){
      hotelPreferences(kind);
    }else if(wizard==='residence'){
      $('#guide-question').textContent='Which country do the travellers live in?';askCountry(quote.residence,code=>{quote.residence=code;quote.birth_dates=[];return saveContext({field:'residence',residence:code},'birthdates');});
    }else if(wizard==='birthdates'){
      const index=quote.birth_dates?.length||0;$('#guide-question').textContent='What is traveller '+(index+1)+'’s date of birth?';$('#guide-description').textContent='Private reply: used only for this insurance quote. It is not saved in the conversation or sent to the AI.';
      const choose=value=>{if(!validBirthDate(value)){$('#guide-error').textContent='Use DD/MM/YYYY or choose a date on the calendar.';return;}quote.birth_dates=quote.birth_dates||[];quote.birth_dates.push(value);append({role:'user',content:'Birth date provided privately for traveller '+(index+1)+'.',guided:true});if(quote.birth_dates.length<Number(trip.travellers))render();else saveQuoteDetails(kind);};
      calendar('Choose on a calendar','guide-birthdate','',choose,'1906-01-01');
      typed('Private birth date · DD/MM/YYYY',text=>{const m=text.trim().match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);choose(m?m[3]+'-'+m[2].padStart(2,'0')+'-'+m[1].padStart(2,'0'):text.trim());});
    }else if(wizard==='search'){
      $('#guide-question').textContent='I’ll check '+countryName(quote.country)+' eSIM options for you.';
      const generation=renderId;setTimeout(()=>{if(generation===renderId)saveQuoteDetails(kind,true);},0);
    }
    if(['nationality','rooms'].includes(wizard))actions.append(button('Change hotel city',()=>{quote.change_city=true;wizard='city';render();},'text'));
    if(['residence','birthdates','search'].includes(wizard))actions.append(button('Change destination country',()=>{wizard='country';render();},'text'));
    skip(kind);
  }
  function hotelPreferences(kind){
    const c=quote.criteria||(quote.criteria={});
    if(!quote.forcePreferences){
      if(wizard==='hotel_stars'&&c.stars?.length)wizard='hotel_meals';
      if(wizard==='hotel_meals'&&c.board_basis&&c.board_basis!=='any')wizard='hotel_cancel';
      if(wizard==='hotel_cancel'&&c.refundability&&c.refundability!=='any')wizard='hotel_area';
      if(wizard==='hotel_area'&&c.landmark){const generation=renderId;setTimeout(()=>{if(!busy&&generation===renderId)saveQuoteDetails(kind);},0);return;}
    }
    const choices=(question,items,key,nextStep)=>{$('#guide-question').textContent=question;items.forEach(([label,value])=>controls.append(button(label,()=>{recordReply(label);c[key]=value;wizard=nextStep;render();},'reply-chip')));};
    if(wizard==='hotel_stars')choices('What hotel rating would you prefer?',[['Any rating',[]],['3 stars',[3]],['4 stars',[4]],['5 stars',[5]],['4 stars and above',[4,5]]],'stars','hotel_meals');
    else if(wizard==='hotel_meals')choices('Which meal plan would you like?',[['No preference','any'],['Room only','RO'],['Breakfast included','BB'],['Half board','HB'],['Full board','FB'],['All inclusive','AI']],'board_basis','hotel_cancel');
    else if(wizard==='hotel_cancel')choices('Do you need a refundable option?',[['Either is fine','any'],['Refundable only','refundable'],['Non-refundable only','non_refundable']],'refundability','hotel_area');
    else{
      $('#guide-question').textContent='Any preferred area, landmark or hotel?';$('#guide-description').textContent='Tell me a district, airport, station or landmark. “Near” means within 1 km unless you choose another distance.';
      actions.append(button('Show hotels with these preferences',()=>saveQuoteDetails(kind),'primary'));
      if(c.landmark)actions.append(button('Remove area preference',()=>{c.landmark='';quote.preferences='';saveQuoteDetails(kind);},'text'));
    }
    typed('For example: near the old town, breakfast included…',interpretHotel);
  }
  async function interpretHotel(text){
    if(/^(why|how|what (?:does|is|are the differences))\b/i.test(text))return chat(text);
    if(busy)return;setBusy(true,'Checking your hotel preferences…');
    try{
      const result=await postJSON(root.dataset.offersUrl,{kind:'hotel',interpret:text,filters:quote.criteria||{}});appendAnswers(result);apply(result);quote.criteria={...(quote.criteria||{}),...guide.hotel_criteria};
      const field={hotel_stars:'stars',hotel_meals:'board_basis',hotel_cancel:'refundability'}[wizard];
      if(field&&result.parsed_preferences?.includes(field))wizard={hotel_stars:'hotel_meals',hotel_meals:'hotel_cancel',hotel_cancel:'hotel_area'}[wizard];
      else if(wizard==='hotel_area'){setBusy(false);await saveQuoteDetails('hotel');return;}
      setBusy(false);render();scrollCard();
    }catch(error){if(error.data)apply(error.data);setBusy(false);$('#guide-error').textContent=error.message;}
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
    if(pendingDates(kind))return;
    $('#guide-step-label').textContent=names[kind].toUpperCase();$('#guide-question').textContent='Choose your '+({flight:'flight',hotel:'hotel',esim:'eSIM',insurance:'travel cover'}[kind])+', or leave it to Sama.';
    $('#guide-description').textContent='Selecting an option adds it to your request.';
    if(kind==='insurance')$('#guide-description').textContent='Choose a plan preference. Sama confirms final cover and price. Nothing is booked.';
    if(kind==='hotel')$('#guide-description').textContent=guide.hotel_feedback||'Choose a hotel, or tell me what to change in chat.';
    if(kind==='hotel'&&guide.hotel_places?.length){
      $('#guide-question').textContent='Which location did you mean?';guide.hotel_places.forEach(p=>controls.append(button(p.name,()=>searchProvider(kind,[],{location_id:p.id}),'reply-chip')));typed('Choose a place above, or give me another landmark…');skip(kind);return;
    }
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
    }else{
      if(kind==='hotel'){
        actions.append(button('More matching hotels',()=>searchProvider(kind,[],{more:true})),button('Change hotel preferences',()=>{override='hotel';wizardKind='hotel';quote={...(guide.context||{}),...guide.details.hotel,criteria:{...(guide.hotel_criteria||{})},forcePreferences:true};wizard='hotel_stars';render();}));
      }else actions.append(button('Search again / change preferences',()=>edit(kind)));
    }
    skip(kind);
  }
  async function searchProvider(kind,birthdates=[],extra={}){
    if(busy)return;setBusy(true,'Checking '+names[kind].toLowerCase()+' offers…');
    try{const result=await postJSON(root.dataset.offersUrl,{kind,...guide.details[kind],...extra,...(kind==='insurance'?{birth_dates:birthdates}:{})});append(result.message);apply(result);updateSelections(result.message);searched.add(kind+':'+guide.version);setBusy(false);render();scrollCard();}
    catch(error){if(error.data)apply(error.data);searched.add(kind+':'+guide.version);setBusy(false);render();$('#guide-error').textContent=error.message;actions.prepend(button('Continue with Sama’s help',()=>sendStep('skip_service',{service:kind}),'primary'));}
    finally{birthdates.fill('');}
  }
  async function searchFlights(){
    if(busy)return;
    if(root.dataset.available!=='true'){$('#guide-error').textContent='Online flight research is unavailable. Sama can find options for you.';return;}
    const detail=guide.details.flight||{};
    const returning=guide.one_way?', one way':trip.return_date?', returning '+trip.return_date:', return date undecided; research outbound flights only';
    await chat(`Show sourced flight timings for ${trip.origin} to ${trip.destination}, departing ${trip.departure}${returning}, for ${trip.travellers} travellers. ${detail.cabin||''}. ${detail.airline?'Preferred airline: '+detail.airline+'.':''} Keep the reply brief.`,false);
  }
  async function chat(content,showUser=true){
    if(busy)return;setBusy(true,'Your assistant is checking…');if(showUser)append({role:'user',content});
    try{const result=await postJSON(root.dataset.aiUrl,{message:content,scope:override||guide.step,question:$('#guide-question').textContent});append(result.message);apply(result);if(wizardKind==='hotel')quote.criteria={...(quote.criteria||{}),...(result.hotel_update||{})};override='';if(result.searched_kind==='hotel')searched.add('hotel:'+guide.version);setBusy(false);render();scrollCard();}
    catch(error){if(error.data)apply(error.data);searched.add('hotel:'+guide.version);setBusy(false);render();$('#assistant-error').textContent=error.message;}
  }
  chatForm.addEventListener('submit',event=>{event.preventDefault();if(!input.value.trim()||busy)return;const content=input.value.trim();input.value='';if(textAnswer)textAnswer(content);else chat(content);});
  input.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();chatForm.requestSubmit();}});
  messages.addEventListener('change',async event=>{
    const radio=event.target.closest('[data-option-id]');if(!radio||busy)return;const kind=radio.name.replace('travel-choice-','');
    if(!guide.services.includes(kind)){$('#guide-error').textContent='Add this service to your trip first.';radio.checked=false;return;}
    setBusy(true,'Saving your choice…');try{const result=await postJSON(root.dataset.selectUrl,{option_id:radio.value});updateSelections(result);setBusy(false);
      if(guide.details[kind]&&!guide.details[kind].manual)await sendStep('complete_service',{service:kind});
      else{append({role:'assistant',content:'Your '+names[kind].toLowerCase()+' preference is saved. Let’s finish the remaining trip details.'});render();scrollCard();}
    }catch(error){setBusy(false);updateSelections({selections});$('#guide-error').textContent=error.message;}
  });
  function openReview(){
    if(busy||submittedUrl)return;
    if(guide.step!=='ready'){override='';render();scrollCard();return;}
    const facts=$('#review-facts');facts.replaceChildren();
    [['Route',trip.origin+' → '+trip.destination,'route'],['Travel dates',dateLabel(trip.departure)+(trip.return_date?' → '+dateLabel(trip.return_date):guide.one_way?' · One way':' · Return/end date undecided'),'departure'],
      ['Travellers',partyLabel(guide.passengers),'travellers'],['Services',guide.services.map(k=>names[k]).join(', '),'services']].forEach(([label,value,step])=>{
      const row=el('div','review-fact'),copy=el('div');copy.append(el('small','',label),el('strong','',value));row.append(copy,button('Edit',()=>edit(step),'text'));facts.append(row);
      if(step==='departure')row.append(button('Edit end',()=>edit('return'),'text'));
    });
    const offers=$('#review-options');offers.replaceChildren();guide.services.forEach(kind=>{const option=selections[kind],detail=guide.details[kind]||{},row=el('div','review-option');row.append(icon(kind),el('div'));const body=row.lastElementChild;body.append(el('strong','',names[kind]),el('span','',option?option.label:kind==='transfer'&&detail.note?detail.note:'Sama will find the best option'));
      if(kind==='insurance'&&option)body.append(el('small','','Sama confirms final cover and price.'));
      if(kind==='flight'&&detail.cabin)body.append(el('small','',detail.cabin+(detail.airline?' · '+detail.airline:'')));
      if(kind==='hotel'&&detail.rooms)body.append(el('small','',detail.rooms.length+' room'+(detail.rooms.length===1?'':'s')+' · '+(detail.preferences||detail.city_name)));
      if(kind==='hotel'&&option?.stars)body.append(el('small','',option.stars+' ★'+(option.room_details?.filter(r=>r.size).map(r=>' · '+r.size).join('')||'')));
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
  messages.querySelectorAll('.chat-message.ai .message-body,.option-description>span:not(.hotel-attributes)').forEach(formatLinks);
  render();updateSelections({selections});setBusy(false);
  if($('#batch-review'))$('#batch-review').scrollIntoView();else scrollCard();
})();
