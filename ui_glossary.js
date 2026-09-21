(() => {
  const glossary = __GLOSSARY_DATA__;
  const tip = document.createElement('div');
  tip.id = 'term-tooltip';
  tip.role = 'tooltip';
  tip.hidden = true;
  document.body.appendChild(tip);
  let active = null, pinned = false, timer, frame;
  function close() {
    if (active) {
      active.setAttribute('aria-expanded', 'false');
      active.removeAttribute('aria-describedby');
    }
    active = null; pinned = false; tip.hidden = true;
  }
  function position() {
    if (!active?.isConnected || !active.getClientRects().length) return close();
    const box = active.getBoundingClientRect();
    tip.style.maxHeight = `${Math.max(80, innerHeight - 24)}px`;
    const height = tip.getBoundingClientRect().height;
    tip.style.left = `${Math.max(12, Math.min(box.left, innerWidth - tip.offsetWidth - 12))}px`;
    tip.style.top = `${Math.max(12, Math.min(box.bottom + 8 + height <= innerHeight - 12 ? box.bottom + 8 : box.top - height - 8, innerHeight - height - 12))}px`;
  }
  function open(button) {
    clearTimeout(timer);
    if (active !== button) close();
    active = button;
    tip.replaceChildren();
    for (const term of button.dataset.terms.split('|')) {
      if (!glossary[term]) continue;
      const item = document.createElement('div');
      const title = document.createElement('strong');
      const body = document.createElement('p');
      title.textContent = term; body.textContent = glossary[term];
      item.append(title, body); tip.append(item);
    }
    tip.hidden = false;
    button.setAttribute('aria-expanded', 'true');
    button.setAttribute('aria-describedby', tip.id);
    position();
  }
  function laterClose() { if (!pinned) timer = setTimeout(close, 180); }
  document.addEventListener('pointerover', event => {
    const button = event.target.closest('.term-help');
    if (button && event.pointerType !== 'touch') open(button);
    if (tip.contains(event.target)) clearTimeout(timer);
  });
  document.addEventListener('pointerout', event => {
    if (event.target.closest('.term-help') || tip.contains(event.target)) laterClose();
  });
  document.addEventListener('focusin', event => {
    if (event.target.matches('.term-help')) open(event.target);
  });
  document.addEventListener('focusout', event => {
    if (event.target.matches('.term-help')) laterClose();
  });
  document.addEventListener('click', event => {
    const button = event.target.closest('.term-help');
    if (button) {
      event.preventDefault(); event.stopPropagation();
      if (active === button && pinned) close();
      else { open(button); pinned = true; }
    } else if (!tip.contains(event.target)) close();
  }, true);
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') close();
  });
  window.addEventListener('resize', () => { if (active) position(); });
  document.addEventListener('scroll', () => { if (active) position(); }, true);
  const terms = Object.keys(glossary).sort((a, b) => b.length - a.length);
  const match = (text, term) => /^[A-Za-z-]+$/.test(term)
    ? new RegExp(`(^|[^A-Za-z])${term}([^A-Za-z]|$)`, 'i').test(text)
    : text.includes(term);
  function annotate() {
    frame = null;
    if (active && !active.isConnected) close();
    document.querySelectorAll('.gradio-container label, .gradio-container [data-testid="block-info"], .gradio-container .prose p, .gradio-container .prose li, .gradio-container .prose h2, .gradio-container .prose h3').forEach(element => {
      if (element.closest('.term-section, .term-help, [role="option"]') || element.querySelector('input, textarea, select, p, li')) return;
      const existing = element.querySelector(':scope > .term-help');
      const text = element.textContent;
      const found = terms.filter(term => match(text, term)).filter((term, index, list) =>
        !list.slice(0, index).some(longer => longer.includes(term))).slice(0, 6);
      const key = found.join('|');
      if (!key) { existing?.remove(); return; }
      if (existing?.dataset.terms === key) return;
      const button = existing || document.createElement('button');
      button.type = 'button'; button.className = 'term-help'; button.dataset.terms = key;
      button.setAttribute('aria-label', `解释：${found.join('、')}`);
      button.setAttribute('aria-expanded', 'false');
      if (!existing) element.appendChild(button);
      if (active === button) open(button);
    });
  }
  new MutationObserver(() => { if (!frame) frame = requestAnimationFrame(annotate); })
    .observe(document.querySelector('.gradio-container') || document.body,
      {childList: true, subtree: true, characterData: true});
  annotate();
})();
