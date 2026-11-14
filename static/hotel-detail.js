(() => {
  const dialog = document.querySelector('.property-lightbox');
  if (!dialog?.showModal) return;
  const image = dialog.querySelector('img');
  const counter = dialog.querySelector('[data-gallery-count]');
  const error = dialog.querySelector('[data-gallery-error]');
  const previous = dialog.querySelector('[data-gallery-prev]');
  const next = dialog.querySelector('[data-gallery-next]');
  let links = [];
  let index = 0;
  let opener;

  function showPhoto(position) {
    index = (position + links.length) % links.length;
    image.hidden = false;
    error.hidden = true;
    image.alt = links[index].getAttribute('aria-label').replace(/^View /, '');
    image.src = links[index].href;
    counter.textContent = (index + 1) + ' / ' + links.length;
  }

  function open(group, position, trigger) {
    links = [...group.querySelectorAll('[data-gallery-photo]')];
    opener = trigger;
    previous.disabled = next.disabled = links.length < 2;
    showPhoto(position);
    dialog.showModal();
    dialog.querySelector('[data-gallery-close]').focus();
  }

  for (const group of document.querySelectorAll('[data-photo-group]')) {
    group.querySelectorAll('[data-gallery-photo]').forEach((link, position) => {
      link.addEventListener('click', event => {
        event.preventDefault();
        open(group, position, link);
      });
      const thumbnail = link.querySelector('img');
      if (!thumbnail) return;
      const unavailable = () => {
        thumbnail.hidden = true;
        link.classList.add('property-photo-unavailable');
      };
      thumbnail.addEventListener('error', unavailable);
      if (thumbnail.complete && !thumbnail.naturalWidth) unavailable();
    });
    const button = group.querySelector('[data-open-gallery]');
    button.hidden = false;
    button.addEventListener('click', () => open(group, 0, button));
  }

  image.addEventListener('error', () => {
    image.hidden = true;
    error.hidden = false;
  });
  previous.addEventListener('click', () => showPhoto(index - 1));
  next.addEventListener('click', () => showPhoto(index + 1));
  dialog.querySelector('[data-gallery-close]').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => opener?.focus());
  dialog.addEventListener('keydown', event => {
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault();
      showPhoto(index + (event.key === 'ArrowLeft' ? -1 : 1));
    }
  });
})();
