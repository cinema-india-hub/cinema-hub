(() => {
  const cards = document.querySelectorAll('.story-card');
  cards.forEach(card => {
    card.addEventListener('pointermove', e => {
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
      const r = card.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width - .5;
      const y = (e.clientY - r.top) / r.height - .5;
      card.style.transform = `translateY(-8px) rotateX(${(-y * 2).toFixed(2)}deg) rotateY(${(x * 2).toFixed(2)}deg)`;
    });
    card.addEventListener('pointerleave', () => card.style.transform = '');
  });
})();
