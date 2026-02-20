// Multiroom Audio Web Interface - Minimal JS

// Toast notification
function showToast(message, isError = false) {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.classList.remove('hidden', 'error');
    if (isError) {
        toast.classList.add('error');
    }

    // Hide after 3 seconds
    setTimeout(() => {
        toast.classList.add('hidden');
    }, 3000);
}

// HTMX event handlers
document.body.addEventListener('htmx:responseError', function(event) {
    showToast('Fehler: ' + (event.detail.xhr.statusText || 'Verbindung fehlgeschlagen'), true);
});

// Make showToast globally available
window.showToast = showToast;
