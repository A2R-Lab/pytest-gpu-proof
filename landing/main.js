// Preserve old MkDocs homepage bookmarks without changing new section anchors.
function redirectOldBookmark() {
  if (['pytest-gpu-proof', 'start-here'].includes(location.hash.slice(1))) {
    location.replace('docs/' + location.search + location.hash);
  }
}
redirectOldBookmark();
window.addEventListener('hashchange', redirectOldBookmark);
document.querySelector('#copy-citation').addEventListener('click', async () => {
  const status = document.querySelector('#copy-status');
  try {
    await navigator.clipboard.writeText(document.querySelector('#bibtex').textContent);
    status.textContent = 'Citation copied.';
  } catch {
    status.textContent = 'Select the citation text above to copy it.';
  }
});
