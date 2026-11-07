// A page loaded before a deploy calls callbacks the new server may no longer have: a
// button then does nothing (the server answers 500). Every response carries the server's
// code version (X-App-Version); when it is not the page's own (meta app-version), a bar
// at the top offers to reload the page.
(function () {
    'use strict';
    var meta = document.querySelector('meta[name="app-version"]');
    var mine = meta && meta.content;
    if (!mine || !window.fetch) { return; }
    var TEXT = {
        cs: ['Aplikace byla aktualizována. Načtěte stránku znovu a nahrajte soubor znovu.',
             'Načíst znovu'],
        en: ['The app has been updated. Reload the page and upload the file again.',
             'Reload'],
        de: ['Die App wurde aktualisiert. Laden Sie die Seite neu und laden Sie die Datei ' +
             'erneut hoch.', 'Neu laden']
    };
    function show() {
        if (document.getElementById('stale-banner')) { return; }
        var checked = document.querySelector('#lang input:checked');
        var text = TEXT[checked && checked.value] || TEXT.cs;
        var bar = document.createElement('div');
        bar.id = 'stale-banner';
        bar.className = 'stale-banner';
        bar.setAttribute('role', 'alert');
        var msg = document.createElement('span');
        msg.textContent = text[0];
        var btn = document.createElement('button');
        btn.className = 'btn-primary';
        btn.textContent = text[1];
        btn.addEventListener('click', function () { window.location.reload(); });
        bar.appendChild(msg);
        bar.appendChild(btn);
        document.body.appendChild(bar);
    }
    var fetch0 = window.fetch;
    window.fetch = function () {
        return fetch0.apply(this, arguments).then(function (response) {
            var theirs = response.headers && response.headers.get('X-App-Version');
            if (theirs && theirs !== mine) { show(); }
            return response;
        });
    };
})();
