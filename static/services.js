(() => {
  const form = document.querySelector('[data-service-form]');
  if (!form) return;
  const coverage = form.querySelectorAll('[name="bundle_category"]');
  const showCoverage = () => {
    const selected = form.querySelector('[name="bundle_category"]:checked');
    for (const group of form.querySelectorAll('[data-coverage]')) {
      group.hidden = !!selected && selected.value !== group.dataset.coverage;
      group.querySelector('select').disabled = group.hidden;
    }
  };
  coverage.forEach(input => input.addEventListener('change', showCoverage));
  showCoverage();

  for (const select of form.querySelectorAll('select')) {
    if (select.options.length < 25 || select.hasAttribute('data-native-select')) continue;
    const all = [...select.options];
    const search = document.createElement('input');
    search.type = 'search';
    search.className = 'service-select-search';
    search.placeholder = 'Type to find a country or region';
    search.setAttribute('aria-label', 'Filter ' + (select.labels[0]?.textContent || 'options').replace(/:$/, ''));
    select.before(search);
    search.addEventListener('input', () => {
      const selected = select.value;
      const term = search.value.trim().toLocaleLowerCase();
      select.replaceChildren(...all.filter(option => !option.value || option.value === selected ||
        option.textContent.toLocaleLowerCase().includes(term)));
      select.value = selected;
    });
    search.addEventListener('keydown', event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        const matches = [...select.options].filter(option => option.value &&
          option.textContent.toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase()));
        if (matches.length === 1) select.value = matches[0].value;
        select.focus();
      }
    });
  }

  const results = document.querySelector('#service-results');
  if (results && matchMedia('(max-width: 760px)').matches && !location.hash) {
    results.focus({preventScroll:true});
    results.scrollIntoView();
  }

  const party = form.querySelector('[data-service-party]');
  if (!party?.firstElementChild) return;
  const count = form.querySelector('#service-count');
  const groups = Array.from(party.children);
  const example = groups[0].cloneNode(true);
  form.querySelector('[data-count-fallback]').hidden = true;
  const updateParty = () => {
    const total = Number(count.value);
    for (let index = 0; index < total; index++) {
      if (groups[index]) continue;
      const group = example.cloneNode(true);
      group.querySelector('legend').textContent = (form.dataset.serviceForm === 'hotel' ? 'Room ' : 'Traveller ') + (index + 1);
      group.querySelectorAll('.errorlist').forEach(error => error.remove());
      for (const input of group.querySelectorAll('input')) {
        const oldId = input.id;
        input.name = input.name.replace(/_0$/, '_' + index);
        input.id = 'id_' + input.name;
        input.value = input.name.startsWith('adults_') ? '1' : '';
        input.removeAttribute('aria-invalid');
        input.removeAttribute('aria-describedby');
        const label = [...group.querySelectorAll('label')].find(label => label.htmlFor === oldId);
        if (label) label.htmlFor = input.id;
        if (input.name.startsWith('birth_') && label) label.textContent = 'Date of birth:';
      }
      groups[index] = group;
      party.append(group);
    }
    groups.forEach((group, index) => {
      group.hidden = index >= total;
      group.disabled = group.hidden;
    });
  };
  count.addEventListener('change', updateParty);
  updateParty();
})();
