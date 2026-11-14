(() => {
  const form = document.querySelector('#stay-search');
  if (!form) return;
  const city = form.querySelector('#id_city'), country = form.querySelector('#id_destination');
  const choice = form.querySelector('#id_city_choice'), popup = form.querySelector('#stay-suggestions');
  const label = form.querySelector('[data-selected-country]');
  const manual = form.querySelector('[data-manual-country]');
  const manualToggle=form.querySelector('[data-manual-toggle]');
  const manualMode=open=>{
    manual.hidden=!open;
    manualToggle.setAttribute('aria-expanded',String(open));
    manualToggle.textContent=open?'Hide country field':'Choose country manually';
  };
  manualToggle.hidden=false;
  manualToggle.addEventListener('click',()=>{manualMode(manual.hidden);if(!manual.hidden)country.focus();});
  let timer, controller, options = [], active = -1;
  city.setAttribute('role','combobox');
  city.setAttribute('aria-autocomplete','list');
  city.setAttribute('aria-controls',popup.id);
  city.autocomplete='off';
  function setOpen(open) {
    popup.hidden=!open;
    city.setAttribute('aria-expanded',String(open));
    if (!open) city.removeAttribute('aria-activedescendant');
  }
  function status(text) {
    options=[];active=-1;
    const message=document.createElement('div');
    message.className='stay-suggestion-status';message.setAttribute('role','status');message.textContent=text;
    popup.replaceChildren(message);setOpen(true);
  }
  function selected(place) {
    clearTimeout(timer);controller?.abort();
    city.value=place.city;country.value=place.country;choice.value=place.choice || '';
    label.textContent=place.label;manualMode(false);
    city.setCustomValidity('');setOpen(false);
  }
  function render(places) {
    options=places;active=-1;popup.replaceChildren();
    for (const [i, place] of places.entries()) {
      const row=document.createElement('div'), title=document.createElement('strong'), subtitle=document.createElement('span');
      row.id='stay-place-'+i;row.className='stay-suggestion';row.setAttribute('role','option');row.setAttribute('aria-selected','false');
      title.textContent=place.city;subtitle.textContent=place.label;row.append(title,subtitle);
      row.addEventListener('pointerdown',e=>e.preventDefault());
      row.addEventListener('click',()=>{selected(place);city.focus();});popup.append(row);
    }
    setOpen(true);
  }
  async function search(query) {
    const current=new AbortController();controller=current;
    try {
      const response=await fetch(form.dataset.destinationUrl+'?'+new URLSearchParams({q:query}),{signal:current.signal});
      const data=await response.json();
      if (current.signal.aborted || city.value.trim()!==query) return;
      if (!response.ok) status(data.error || 'Suggestions unavailable. Enter a city and country.');
      else if (!data.places.length) status('No matches. Try another spelling or enter a city and country.');
      else render(data.places);
    } catch (error) {
      if (!current.signal.aborted) status('Suggestions unavailable. Enter a city and country.');
    }
  }
  city.addEventListener('input',()=>{
    clearTimeout(timer);controller?.abort();
    choice.value='';country.value='';label.textContent='';
    const query=city.value.trim();
    if (query.length<2) return setOpen(false);
    status('Finding destinations…');timer=setTimeout(()=>search(query),275);
  });
  city.addEventListener('keydown',e=>{
    if (e.key==='Escape') {setOpen(false);clearTimeout(timer);controller?.abort();return;}
    if (popup.hidden) return;
    if (e.key==='Enter') {
      e.preventDefault();
      if (active>=0) selected(options[active]);
      return;
    }
    if (!options.length || !['ArrowDown','ArrowUp'].includes(e.key)) return;
    e.preventDefault();
    active=active<0?(e.key==='ArrowDown'?0:options.length-1):(active+(e.key==='ArrowDown'?1:-1)+options.length)%options.length;
    [...popup.children].forEach((row,i)=>row.setAttribute('aria-selected',String(i===active)));
    city.setAttribute('aria-activedescendant',popup.children[active].id);
    popup.children[active].scrollIntoView({block:'nearest'});
  });
  city.addEventListener('blur',()=>{clearTimeout(timer);controller?.abort();setOpen(false);});
  country.addEventListener('change',()=>{choice.value='';label.textContent='';});
  setOpen(false);
  manualMode(!!country.getAttribute('aria-invalid'));
  if (city.value && country.value && !country.getAttribute('aria-invalid')) {
    label.textContent=country.selectedOptions[0].textContent;manualMode(false);
  }
  for (const card of document.querySelectorAll('[data-featured-city]')) {
    card.addEventListener('click',event=>{
      event.preventDefault();selected({city:card.dataset.featuredCity,country:card.dataset.country,label:card.dataset.label});
      form.querySelector('#id_start').focus();
    });
  }
  const start=form.querySelector('#id_start'), end=form.querySelector('#id_end');
  function dates() {
    if (!start.value) return;
    const next=new Date(start.value+'T12:00:00Z');
    next.setUTCDate(next.getUTCDate()+1);end.min=next.toISOString().slice(0,10);
    if (end.value && end.value<end.min) end.value='';
  }
  start.addEventListener('change',dates);dates();
  const rooms=form.querySelector('#service-count');
  const guestSummary=()=>{
    const activeRooms=[...form.querySelectorAll('[data-service-party] fieldset:not([disabled])')];
    const adults=activeRooms.reduce((n,r)=>n+Number(r.querySelector('[name^=adults_]').value),0);
    const children=activeRooms.reduce((n,r)=>n+r.querySelector('[name^=ages_]').value.split(',').filter(x=>x.trim()).length,0);
    form.querySelector('[data-guest-summary]').textContent=rooms.value+' room'+(rooms.value==='1'?'':'s')+' · '+(adults+children)+' guests ▾';
  };
  rooms.addEventListener('change',guestSummary);
  form.querySelector('[data-service-party]').addEventListener('input',guestSummary);guestSummary();
  const done=form.querySelector('[data-guest-done]');done.hidden=false;
  done.addEventListener('click',()=>{done.closest('details').open=false;done.closest('details').querySelector('summary').focus();});
  form.addEventListener('invalid',event=>{
    if(event.target===country) manualMode(true);
    const group=event.target.closest('details');
    if(group) group.open=true;
  },true);
  const loading=document.querySelector('.stay-loading');
  form.addEventListener('submit',e=>{
    if (e.submitter?.name==='set_count') return;
    if (!country.value) {e.preventDefault();manualMode(true);country.reportValidity();return;}
    loading.querySelector('[data-loading-place]').textContent=city.value+(label.textContent?', '+label.textContent:'');
    if (!loading.open) loading.showModal();
  });
  window.addEventListener('pageshow',()=>{if(loading.open)loading.close();});
  for (const img of document.querySelectorAll('[data-property-photo]')) {
    const unavailable=()=>img.hidden=true;
    img.addEventListener('error',unavailable);if(img.complete&&!img.naturalWidth)unavailable();
  }
  document.querySelector('#stay-results')?.scrollIntoView({block:'start'});
})();
