/* Never expose an HTML error/login document as JSON or as user-facing text. */
window.m360ReadJson = async function (response) {
  const french = document.querySelector('.codex-chat')?.dataset.responseLanguage === 'fr';
  const message = (fr, en) => french ? fr : en;
  const contentType = response.headers.get('Content-Type') || '';
  if (response.redirected || response.status === 401) {
    throw new Error(message('Votre session a expiré. Reconnectez-vous.', 'Your session has expired. Sign in again.'));
  }
  if (!contentType.toLowerCase().includes('application/json')) {
    throw new Error(response.status === 403
      ? message('Accès ou session à vérifier. Actualisez la page.', 'Access or session verification failed. Refresh the page.')
      : message(`Service temporairement indisponible (HTTP ${response.status}).`, `Service temporarily unavailable (HTTP ${response.status}).`));
  }
  try {
    const payload = await response.json();
    if (payload.code === 'DATABASE_BUSY') payload.error = message('La base locale est occupée. Réessayez dans un instant.', 'The local database is busy. Please try again shortly.');
    return payload;
  } catch {
    throw new Error(message('Réponse du serveur invalide. Réessayez.', 'Invalid server response. Please retry.'));
  }
};
