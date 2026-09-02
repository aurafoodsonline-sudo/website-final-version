document.addEventListener("submit", (event) => {
  const form = event.target.closest("form[data-confirm]");
  if (!form) return;
  if (!window.confirm(form.dataset.confirm)) {
    event.preventDefault();
    return;
  }
  const button = form.querySelector('button[type="submit"]');
  if (button) {
    button.disabled = true;
    button.textContent = "Working...";
  }
});
