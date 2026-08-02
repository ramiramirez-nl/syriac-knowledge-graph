const API_BASE = '/api';

// --- Auth helpers ---
// All admin endpoints require an admin Bearer token. We read it once from
// localStorage (set by login.html) and attach it to every API call.
const token = localStorage.getItem('token');

function authHeaders(extra) {
    return Object.assign({ 'Authorization': 'Bearer ' + token }, extra || {});
}

// Any DB- or user-supplied string rendered via innerHTML must go through this.
// OpenAlex titles can contain markup (e.g. <i> tags), so raw interpolation is
// a stored-XSS vector.
function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
}

function requireAdmin() {
    if (!token) {
        window.location.href = '/login.html';
        return false;
    }
    return true;
}

function showTab(tabId, evt) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    evt.target.classList.add('active');
    document.getElementById(tabId).classList.add('active');

    if (tabId === 'works') loadWorks();
    else if (tabId === 'authors') loadAuthors();
    else if (tabId === 'queue') loadQueue();
    else if (tabId === 'import') document.getElementById('importResults').innerHTML = '';
}

async function loadWorks() {
    const q = document.getElementById('searchWork').value;
    const res = await fetch(`${API_BASE}/works?limit=50` + (q ? `&q=${encodeURIComponent(q)}` : ''));
    const works = await res.json();
    const tbody = document.getElementById('worksBody');
    tbody.innerHTML = '';
    works.forEach(w => {
        tbody.innerHTML += `
            <tr>
                <td>${escapeHtml(w.id)}</td>
                <td>${escapeHtml(w.title)}</td>
                <td>${escapeHtml(w.year || '')}</td>
                <td>
                    <button class="btn btn-primary" data-edit-work="${escapeHtml(w.id)}">Edit</button>
                    <button class="btn btn-danger" data-delete-work="${escapeHtml(w.id)}">Delete (Hide)</button>
                    <button class="btn btn-danger" data-exclude-work="${escapeHtml(w.id)}">Exclude (False Positive)</button>
                </td>
            </tr>
        `;
    });
    tbody.querySelectorAll('[data-edit-work]').forEach(btn => {
        btn.addEventListener('click', () => {
            const w = works.find(x => x.id === btn.dataset.editWork);
            if (w) editWork(w);
        });
    });
    tbody.querySelectorAll('[data-delete-work]').forEach(btn => {
        btn.addEventListener('click', () => deleteWork(btn.dataset.deleteWork));
    });
    tbody.querySelectorAll('[data-exclude-work]').forEach(btn => {
        btn.addEventListener('click', () => excludeWork(btn.dataset.excludeWork));
    });
}

async function deleteWork(id) {
    if (!confirm('Are you sure you want to hide this work?')) return;
    const res = await fetch(`${API_BASE}/works/${encodeURIComponent(id)}`, { method: 'DELETE', headers: authHeaders() });
    if (res.ok) {
        alert('Work deleted');
        if (document.getElementById('works').classList.contains('active')) {
            loadWorks();
        } else if (document.getElementById('duplicates').classList.contains('active')) {
            loadDuplicates();
        }
    } else {
        alert('Error deleting work');
    }
}

async function excludeWork(id) {
    if (!confirm('Are you sure you want to mark this work as a false positive? It will be excluded from future imports.')) return;
    const res = await fetch(`${API_BASE}/works/${encodeURIComponent(id)}/exclude`, { method: 'POST', headers: authHeaders() });
    if (res.ok) {
        alert('Work excluded');
        if (document.getElementById('works').classList.contains('active')) {
            loadWorks();
        } else if (document.getElementById('duplicates').classList.contains('active')) {
            loadDuplicates();
        }
    } else {
        alert('Error excluding work');
    }
}

function toggleAddWorkForm() {
    const form = document.getElementById('addWorkForm');
    form.style.display = form.style.display === 'none' ? 'block' : 'none';
    document.getElementById('addWorkResult').innerHTML = '';
}

async function submitNewWork() {
    const title = document.getElementById('newWorkTitle').value.trim();
    if (!title) {
        alert("Title is required");
        return;
    }
    const yearStr = document.getElementById('newWorkYear').value.trim();
    const doi = document.getElementById('newWorkDoi').value.trim();
    const authorsStr = document.getElementById('newWorkAuthors').value.trim();

    const year = yearStr ? parseInt(yearStr) : null;
    const authors = authorsStr ? authorsStr.split(',').map(a => a.trim()).filter(a => a) : [];

    const work_type = document.getElementById('newWorkType').value;

    const workData = {
        title: title,
        year: year,
        doi: doi,
        authors: authors,
        work_type: work_type
    };

    if (work_type === 'manuscript') {
        workData.manuscript_details = {
            language: document.getElementById('newMsLang').value.trim() || null,
            date_composed: document.getElementById('newMsDate').value.trim() || null,
            archive_location: document.getElementById('newMsArchive').value.trim() || null,
            shelfmark: document.getElementById('newMsShelf').value.trim() || null,
            incipit: document.getElementById('newMsIncipit').value.trim() || null
        };
    }

    document.getElementById('addWorkResult').style.color = 'black';
    document.getElementById('addWorkResult').textContent = 'Saving...';

    try {
        const res = await fetch(`${API_BASE}/works`, {
            method: 'POST',
            headers: authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify(workData)
        });

        if (res.ok) {
            document.getElementById('addWorkResult').style.color = 'green';
            document.getElementById('addWorkResult').textContent = 'Work added successfully!';
            // clear form
            document.getElementById('newWorkTitle').value = '';
            document.getElementById('newWorkYear').value = '';
            document.getElementById('newWorkDoi').value = '';
            document.getElementById('newWorkAuthors').value = '';

            loadWorks();
        } else {
            const data = await res.json();
            document.getElementById('addWorkResult').style.color = 'red';
            document.getElementById('addWorkResult').textContent = 'Error: ' + (data.detail || JSON.stringify(data));
        }
    } catch (err) {
        document.getElementById('addWorkResult').style.color = 'red';
        document.getElementById('addWorkResult').textContent = 'Network Error: ' + err.message;
    }
}

function toggleEditWorkForm() {
    const form = document.getElementById('editWorkForm');
    form.style.display = form.style.display === 'none' ? 'block' : 'none';
    document.getElementById('editWorkResult').innerHTML = '';
}

function toggleManuscriptFields(prefix) {
    const type = document.getElementById(prefix + 'WorkType').value;
    const fields = document.getElementById(prefix + 'ManuscriptFields');
    if (type === 'manuscript') {
        fields.style.display = 'block';
    } else {
        fields.style.display = 'none';
    }
}

function editWork(work) {
    document.getElementById('editWorkId').value = work.id;
    document.getElementById('editWorkTitle').value = work.title || '';
    document.getElementById('editWorkYear').value = work.year || '';
    document.getElementById('editWorkDoi').value = work.doi || '';
    document.getElementById('editWorkType').value = work.work_type || 'article';

    if (work.work_type === 'manuscript' && work.manuscript_details) {
        document.getElementById('editMsLang').value = work.manuscript_details.language || '';
        document.getElementById('editMsDate').value = work.manuscript_details.date_composed || '';
        document.getElementById('editMsArchive').value = work.manuscript_details.archive_location || '';
        document.getElementById('editMsShelf').value = work.manuscript_details.shelfmark || '';
        document.getElementById('editMsIncipit').value = work.manuscript_details.incipit || '';
    } else {
        document.getElementById('editMsLang').value = '';
        document.getElementById('editMsDate').value = '';
        document.getElementById('editMsArchive').value = '';
        document.getElementById('editMsShelf').value = '';
        document.getElementById('editMsIncipit').value = '';
    }
    toggleManuscriptFields('edit');

    document.getElementById('editWorkForm').style.display = 'block';
    document.getElementById('addWorkForm').style.display = 'none';
    document.getElementById('editWorkResult').innerHTML = '';

    // Scroll to form
    document.getElementById('editWorkForm').scrollIntoView();
}

async function submitEditWork() {
    const id = document.getElementById('editWorkId').value;
    const title = document.getElementById('editWorkTitle').value.trim();
    if (!title) {
        alert("Title is required");
        return;
    }
    const yearStr = document.getElementById('editWorkYear').value.trim();
    const doi = document.getElementById('editWorkDoi').value.trim();

    const year = yearStr ? parseInt(yearStr) : null;

    const work_type = document.getElementById('editWorkType').value;

    const workData = {
        title: title,
        year: year,
        doi: doi,
        work_type: work_type
    };

    if (work_type === 'manuscript') {
        workData.manuscript_details = {
            language: document.getElementById('editMsLang').value.trim() || null,
            date_composed: document.getElementById('editMsDate').value.trim() || null,
            archive_location: document.getElementById('editMsArchive').value.trim() || null,
            shelfmark: document.getElementById('editMsShelf').value.trim() || null,
            incipit: document.getElementById('editMsIncipit').value.trim() || null
        };
    }


    document.getElementById('editWorkResult').style.color = 'black';
    document.getElementById('editWorkResult').textContent = 'Saving...';

    try {
        const res = await fetch(`${API_BASE}/works/${encodeURIComponent(id)}`, {
            method: 'PUT',
            headers: authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify(workData)
        });

        if (res.ok) {
            document.getElementById('editWorkResult').style.color = 'green';
            document.getElementById('editWorkResult').textContent = 'Work updated successfully!';
            loadWorks();
        } else {
            const data = await res.json();
            document.getElementById('editWorkResult').style.color = 'red';
            document.getElementById('editWorkResult').textContent = 'Error: ' + (data.detail || JSON.stringify(data));
        }
    } catch (err) {
        document.getElementById('editWorkResult').style.color = 'red';
        document.getElementById('editWorkResult').textContent = 'Network Error: ' + err.message;
    }
}

async function loadAuthors() {
    const q = document.getElementById('searchAuthor').value;
    const res = await fetch(`${API_BASE}/authors?limit=50` + (q ? `&q=${encodeURIComponent(q)}` : ''));
    const authors = await res.json();
    const tbody = document.getElementById('authorsBody');
    tbody.innerHTML = '';
    authors.forEach(a => {
        tbody.innerHTML += `
            <tr>
                <td>${escapeHtml(a.id)}</td>
                <td>${escapeHtml(a.name)}</td>
                <td>
                    <button class="btn btn-primary" data-merge-author="${escapeHtml(a.id)}">Merge Into...</button>
                </td>
            </tr>
        `;
    });
    tbody.querySelectorAll('[data-merge-author]').forEach(btn => {
        btn.addEventListener('click', () => {
            const a = authors.find(x => x.id === btn.dataset.mergeAuthor);
            if (a) promptMerge(a.id, a.name);
        });
    });
}

async function promptMerge(secondaryId, name) {
    const primaryId = prompt(`Enter the PRIMARY Author ID to merge '${name}' (${secondaryId}) into:`);
    if (!primaryId || primaryId === secondaryId) return;

    const res = await fetch(`${API_BASE}/authors/merge`, {
        method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ primary_id: primaryId, secondary_ids: [secondaryId] })
    });

    if (res.ok) {
        alert('Author merged successfully');
        loadAuthors();
    } else {
        alert('Error merging author');
    }
}

async function loadDuplicates() {
    document.getElementById('duplicatesResults').textContent = 'Loading... (this might take a few seconds)';
    const res = await fetch(`${API_BASE}/curation/duplicates?limit=20`, { headers: authHeaders() });
    const dups = await res.json();
    let html = '<table><thead><tr><th>Similarity</th><th>Work 1</th><th>Work 2</th><th>Actions</th></tr></thead><tbody>';
    dups.forEach(d => {
        const w1 = escapeHtml(d.work1.id), w2 = escapeHtml(d.work2.id);
        html += `
            <tr>
                <td>${escapeHtml(d.similarity)}%</td>
                <td><strong>${w1}</strong><br>${escapeHtml(d.work1.title)}</td>
                <td><strong>${w2}</strong><br>${escapeHtml(d.work2.title)}</td>
                <td>
                    <button class="btn btn-primary" data-merge-works="${w1}|${w2}" title="Merge 2 into 1">M 2&rarr;1</button>
                    <button class="btn btn-primary" data-merge-works="${w2}|${w1}" title="Merge 1 into 2">M 1&rarr;2</button>
                    <button class="btn btn-danger" data-del-work="${w1}">Del 1</button>
                    <button class="btn btn-danger" data-del-work="${w2}">Del 2</button>
                    <button class="btn btn-danger" data-exc-work="${w1}">Exc 1</button>
                    <button class="btn btn-danger" data-exc-work="${w2}">Exc 2</button>
                </td>
            </tr>
        `;
    });
    html += '</tbody></table>';
    document.getElementById('duplicatesResults').innerHTML = html;
    document.querySelectorAll('[data-merge-works]').forEach(btn => {
        btn.addEventListener('click', () => {
            const [p, s] = btn.dataset.mergeWorks.split('|');
            mergeWorks(p, s);
        });
    });
    document.querySelectorAll('[data-del-work]').forEach(btn => {
        btn.addEventListener('click', () => deleteWork(btn.dataset.delWork));
    });
    document.querySelectorAll('[data-exc-work]').forEach(btn => {
        btn.addEventListener('click', () => excludeWork(btn.dataset.excWork));
    });
}

async function mergeWorks(primaryId, secondaryId) {
    if (!confirm('Are you sure you want to merge ' + secondaryId + ' into ' + primaryId + '? This cannot be undone easily.')) return;

    const res = await fetch(`${API_BASE}/works/merge`, {
        method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ primary_id: primaryId, secondary_id: secondaryId })
    });

    if (res.ok) {
        alert('Works merged successfully');
        loadDuplicates();
    } else {
        const err = await res.json();
        alert('Error merging works: ' + (err.detail || 'Unknown error'));
    }
}

async function uploadBibtex() {
    const fileInput = document.getElementById('bibtexFile');
    if (!fileInput.files.length) {
        alert('Please select a file first.');
        return;
    }

    const file = fileInput.files[0];
    const formData = new FormData();
    formData.append('file', file);

    document.getElementById('importResults').textContent = 'Uploading and processing...';

    try {
        const res = await fetch(`${API_BASE}/import/bibtex`, {
            method: 'POST',
            headers: authHeaders(),
            body: formData
        });

        const data = await res.json();
        if (res.ok) {
            document.getElementById('importResults').innerHTML = `
                <div style="color: green; font-weight: bold; margin-bottom: 10px;">Import Successful!</div>
                <ul style="line-height: 1.6;">
                    <li><strong>Total records found:</strong> ${escapeHtml(data.total_processed)}</li>
                    <li><strong>Successfully added:</strong> ${escapeHtml(data.added)}</li>
                    <li><strong>Skipped:</strong> ${escapeHtml(data.skipped)} (Duplicates or missing titles)</li>
                </ul>
            `;
            fileInput.value = '';
        } else {
            document.getElementById('importResults').innerHTML = `<div style="color: red;">Error: ${escapeHtml(data.detail || JSON.stringify(data))}</div>`;
        }
    } catch (err) {
        document.getElementById('importResults').innerHTML = `<div style="color: red;">Network error: ${escapeHtml(err.message)}</div>`;
    }
}

async function loadQueue() {
    document.getElementById('queueResults').textContent = 'Loading...';

    try {
        const res = await fetch(`${API_BASE}/contributions?status=pending`, {
            headers: authHeaders()
        });

        if (res.ok) {
            const queue = await res.json();
            if (queue.length === 0) {
                document.getElementById('queueResults').textContent = 'Queue is empty.';
                return;
            }

            let html = '<table><thead><tr><th>ID</th><th>User ID</th><th>Type</th><th>Payload</th><th>Actions</th></tr></thead><tbody>';
            queue.forEach(c => {
                html += `
                    <tr>
                        <td>${escapeHtml(c.id)}</td>
                        <td>${escapeHtml(c.user_id)}</td>
                        <td>${escapeHtml(c.type)}</td>
                        <td><pre style="max-width:300px; overflow:auto; font-size:12px;">${escapeHtml(c.payload)}</pre></td>
                        <td>
                            <button class="btn btn-primary" data-contrib="${escapeHtml(c.id)}|approve">Approve</button>
                            <button class="btn btn-danger" data-contrib="${escapeHtml(c.id)}|reject">Reject</button>
                        </td>
                    </tr>
                `;
            });
            html += '</tbody></table>';
            document.getElementById('queueResults').innerHTML = html;
            document.querySelectorAll('[data-contrib]').forEach(btn => {
                btn.addEventListener('click', () => {
                    const [id, action] = btn.dataset.contrib.split('|');
                    processContribution(id, action);
                });
            });
        } else {
            document.getElementById('queueResults').innerHTML = '<div style="color:red;">Error loading queue. Admin privileges required.</div>';
        }
    } catch (err) {
        document.getElementById('queueResults').innerHTML = `<div style="color:red;">Network error: ${escapeHtml(err.message)}</div>`;
    }
}

async function processContribution(id, action) {
    if (!confirm(`Are you sure you want to ${action} this contribution?`)) return;

    try {
        const res = await fetch(`${API_BASE}/contributions/${encodeURIComponent(id)}/${encodeURIComponent(action)}`, {
            method: 'POST',
            headers: authHeaders()
        });

        if (res.ok) {
            alert(`Contribution ${action}d successfully`);
            loadQueue();
        } else {
            const data = await res.json();
            alert(`Error: ${data.detail || 'Unknown error'}`);
        }
    } catch (err) {
        alert(`Network error: ${err.message}`);
    }
}

// Initial load — gate behind login first.
document.addEventListener('DOMContentLoaded', () => {
    if (requireAdmin()) loadWorks();
});

// ---------------------------------------------------------------------------
// Review queue: the recorded duplicate_candidates backlog.
//
// Kept separate from loadDuplicates() because that one recomputes pairs on
// every call and cannot be worked down to zero. Here each decision persists,
// so the count actually falls.
// ---------------------------------------------------------------------------

const QUEUE_PAGE_SIZE = 25;
let queueOffset = 0;

async function loadReviewQueue(offset) {
    queueOffset = Math.max(0, offset || 0);
    const box = document.getElementById('reviewQueueResults');
    box.textContent = 'Loading...';

    const res = await fetch(
        `${API_BASE}/curation/queue?limit=${QUEUE_PAGE_SIZE}&offset=${queueOffset}`,
        { headers: authHeaders() }
    );
    if (!res.ok) {
        box.textContent = 'Error loading queue.';
        return;
    }

    const data = await res.json();
    document.getElementById('queueCount').textContent =
        data.total ? `${data.total} pair(s) awaiting review` : 'empty';

    if (!data.pairs.length) {
        box.innerHTML = '<p>Nothing left to review. The queue is clear.</p>';
        document.getElementById('reviewQueuePager').innerHTML = '';
        return;
    }

    box.innerHTML = data.pairs.map(renderPair).join('');
    wireQueueButtons();
    renderQueuePager(data);
}

// Highlight where the two titles diverge, so the curator can see at a glance
// whether the difference is meaningful or just punctuation/case.
function markTitleDiff(titleA, titleB) {
    const a = titleA || '', b = titleB || '';
    const norm = s => s.toLowerCase().replace(/[^a-z0-9]+/g, '');
    if (norm(a) === norm(b)) {
        return [escapeHtml(a), escapeHtml(b)];
    }
    const wordsB = new Set(norm(b).match(/[a-z0-9]+/g) || []);
    const wordsA = new Set(norm(a).match(/[a-z0-9]+/g) || []);
    const mark = (text, otherWords) => text.split(/(\s+)/).map(tok => {
        const key = tok.toLowerCase().replace(/[^a-z0-9]+/g, '');
        if (!key) return escapeHtml(tok);
        return otherWords.has(key)
            ? escapeHtml(tok)
            : `<span class="diff">${escapeHtml(tok)}</span>`;
    }).join('');
    return [mark(a, wordsB), mark(b, wordsA)];
}

function renderSide(pair, side, titleHtml) {
    const id = pair[`work_id_${side}`];
    const authors = pair[`authors_${side}`] || [];
    const doi = pair[`doi_${side}`];
    return `
        <div class="pair-side">
            <h4>${titleHtml}</h4>
            <dl>
                <dt>ID</dt><dd>${escapeHtml(id)}</dd>
                <dt>Year</dt><dd>${escapeHtml(String(pair[`year_${side}`] ?? '—'))}</dd>
                <dt>Type</dt><dd>${escapeHtml(pair[`type_${side}`] || '—')}</dd>
                <dt>Venue</dt><dd>${escapeHtml(pair[`venue_${side}`] || '—')}</dd>
                <dt>Authors</dt><dd>${authors.length ? escapeHtml(authors.join(', ')) : '<em>none recorded</em>'}</dd>
                <dt>Cited</dt><dd>${escapeHtml(String(pair[`cited_${side}`] ?? 0))}</dd>
                <dt>DOI</dt><dd>${doi ? `<a href="${escapeHtml(doi)}" target="_blank" rel="noopener noreferrer">${escapeHtml(doi)}</a>` : '—'}</dd>
            </dl>
        </div>`;
}

function renderPair(pair) {
    const [titleA, titleB] = markTitleDiff(pair.title_a, pair.title_b);
    const a = pair.work_id_a, b = pair.work_id_b;
    const key = `${a}|${b}`;
    return `
        <div class="pair" data-pair="${escapeHtml(key)}">
            <div class="pair-head">
                <span class="score">similarity ${(pair.score * 100).toFixed(1)}%${pair.same_doi ? ' · same DOI' : ''}</span>
                <span>${escapeHtml(pair.reasons || '')}</span>
            </div>
            <div class="pair-body">
                ${renderSide(pair, 'a', titleA)}
                ${renderSide(pair, 'b', titleB)}
            </div>
            <div class="pair-actions">
                <button class="btn btn-primary" data-queue-merge="${escapeHtml(a)}|${escapeHtml(b)}">Same work — keep left</button>
                <button class="btn btn-primary" data-queue-merge="${escapeHtml(b)}|${escapeHtml(a)}">Same work — keep right</button>
                <button class="btn" data-queue-reject="${escapeHtml(key)}">Different — not a duplicate</button>
            </div>
        </div>`;
}

function wireQueueButtons() {
    document.querySelectorAll('[data-queue-merge]').forEach(btn => {
        btn.addEventListener('click', () => {
            const [keep, drop] = btn.dataset.queueMerge.split('|');
            queueMerge(keep, drop);
        });
    });
    document.querySelectorAll('[data-queue-reject]').forEach(btn => {
        btn.addEventListener('click', () => {
            const [a, b] = btn.dataset.queueReject.split('|');
            queueReject(a, b);
        });
    });
}

async function queueMerge(keepId, dropId) {
    if (!confirm(`Merge ${dropId} into ${keepId}?\n\n${dropId} will be hidden (soft-deleted) and its citations, authorship and links moved to ${keepId}.`)) return;
    const res = await fetch(`${API_BASE}/works/merge`, {
        method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ primary_id: keepId, secondary_id: dropId })
    });
    if (res.ok) {
        loadReviewQueue(queueOffset);
    } else {
        alert('Error merging works');
    }
}

async function queueReject(a, b) {
    const res = await fetch(`${API_BASE}/curation/reject`, {
        method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ work_id_a: a, work_id_b: b })
    });
    if (res.ok) {
        loadReviewQueue(queueOffset);
    } else {
        alert('Error rejecting pair');
    }
}

function renderQueuePager(data) {
    const shownTo = Math.min(data.offset + data.pairs.length, data.total);
    const parts = [`<span>Showing ${data.offset + 1}–${shownTo} of ${data.total}</span> `];
    if (data.offset > 0) {
        parts.push(`<button class="btn" onclick="loadReviewQueue(${Math.max(0, data.offset - QUEUE_PAGE_SIZE)})">&larr; Previous</button>`);
    }
    if (shownTo < data.total) {
        parts.push(`<button class="btn" onclick="loadReviewQueue(${data.offset + QUEUE_PAGE_SIZE})">Next &rarr;</button>`);
    }
    document.getElementById('reviewQueuePager').innerHTML = parts.join(' ');
}
