const API_BASE = '/api';

function showTab(tabId) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    event.target.classList.add('active');
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
                <td>${w.id}</td>
                <td>${w.title}</td>
                <td>${w.year || ''}</td>
                <td>
                    <button class="btn btn-primary" onclick='editWork(${JSON.stringify(w)})'>Edit</button>
                    <button class="btn btn-danger" onclick="deleteWork('${w.id}')">Delete (Hide)</button>
                    <button class="btn btn-danger" onclick="excludeWork('${w.id}')">Exclude (False Positive)</button>
                </td>
            </tr>
        `;
    });
}

async function deleteWork(id) {
    if (!confirm('Are you sure you want to hide this work?')) return;
    const res = await fetch(`${API_BASE}/works/${id}`, { method: 'DELETE' });
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
    const res = await fetch(`${API_BASE}/works/${id}/exclude`, { method: 'POST' });
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
    document.getElementById('addWorkResult').innerHTML = 'Saving...';
    
    try {
        const res = await fetch(`${API_BASE}/works`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(workData)
        });
        
        if (res.ok) {
            document.getElementById('addWorkResult').style.color = 'green';
            document.getElementById('addWorkResult').innerHTML = 'Work added successfully!';
            // clear form
            document.getElementById('newWorkTitle').value = '';
            document.getElementById('newWorkYear').value = '';
            document.getElementById('newWorkDoi').value = '';
            document.getElementById('newWorkAuthors').value = '';
            
            loadWorks();
        } else {
            const data = await res.json();
            document.getElementById('addWorkResult').style.color = 'red';
            document.getElementById('addWorkResult').innerHTML = 'Error: ' + (data.detail || JSON.stringify(data));
        }
    } catch (err) {
        document.getElementById('addWorkResult').style.color = 'red';
        document.getElementById('addWorkResult').innerHTML = 'Network Error: ' + err.message;
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
    document.getElementById('editWorkResult').innerHTML = 'Saving...';
    
    try {
        const res = await fetch(`${API_BASE}/works/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(workData)
        });
        
        if (res.ok) {
            document.getElementById('editWorkResult').style.color = 'green';
            document.getElementById('editWorkResult').innerHTML = 'Work updated successfully!';
            loadWorks();
        } else {
            const data = await res.json();
            document.getElementById('editWorkResult').style.color = 'red';
            document.getElementById('editWorkResult').innerHTML = 'Error: ' + (data.detail || JSON.stringify(data));
        }
    } catch (err) {
        document.getElementById('editWorkResult').style.color = 'red';
        document.getElementById('editWorkResult').innerHTML = 'Network Error: ' + err.message;
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
                <td>${a.id}</td>
                <td>${a.name}</td>
                <td>
                    <button class="btn btn-primary" onclick="promptMerge('${a.id}', '${a.name.replace(/'/g, "\\'")}')">Merge Into...</button>
                </td>
            </tr>
        `;
    });
}

async function promptMerge(secondaryId, name) {
    const primaryId = prompt(`Enter the PRIMARY Author ID to merge '${name}' (${secondaryId}) into:`);
    if (!primaryId || primaryId === secondaryId) return;

    const res = await fetch(`${API_BASE}/authors/merge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
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
    document.getElementById('duplicatesResults').innerHTML = 'Loading... (this might take a few seconds)';
    const res = await fetch(`${API_BASE}/curation/duplicates?limit=20`);
    const dups = await res.json();
    let html = '<table><thead><tr><th>Similarity</th><th>Work 1</th><th>Work 2</th><th>Actions</th></tr></thead><tbody>';
    dups.forEach(d => {
        html += `
            <tr>
                <td>${d.similarity}%</td>
                <td><strong>${d.work1.id}</strong><br>${d.work1.title}</td>
                <td><strong>${d.work2.id}</strong><br>${d.work2.title}</td>
                <td>
                    <button class="btn btn-primary" onclick="mergeWorks('${d.work1.id}', '${d.work2.id}')" title="Merge 2 into 1">M 2&rarr;1</button>
                    <button class="btn btn-primary" onclick="mergeWorks('${d.work2.id}', '${d.work1.id}')" title="Merge 1 into 2">M 1&rarr;2</button>
                    <button class="btn btn-danger" onclick="deleteWork('${d.work1.id}')">Del 1</button>
                    <button class="btn btn-danger" onclick="deleteWork('${d.work2.id}')">Del 2</button>
                    <button class="btn btn-danger" onclick="excludeWork('${d.work1.id}')">Exc 1</button>
                    <button class="btn btn-danger" onclick="excludeWork('${d.work2.id}')">Exc 2</button>
                </td>
            </tr>
        `;
    });
    html += '</tbody></table>';
    document.getElementById('duplicatesResults').innerHTML = html;
}

async function mergeWorks(primaryId, secondaryId) {
    if (!confirm('Are you sure you want to merge ' + secondaryId + ' into ' + primaryId + '? This cannot be undone easily.')) return;

    const res = await fetch(`${API_BASE}/works/merge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
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
    
    document.getElementById('importResults').innerHTML = 'Uploading and processing...';
    
    try {
        const res = await fetch(`${API_BASE}/import/bibtex`, {
            method: 'POST',
            body: formData
        });
        
        const data = await res.json();
        if (res.ok) {
            document.getElementById('importResults').innerHTML = `
                <div style="color: green; font-weight: bold; margin-bottom: 10px;">Import Successful!</div>
                <ul style="line-height: 1.6;">
                    <li><strong>Total records found:</strong> ${data.total_processed}</li>
                    <li><strong>Successfully added:</strong> ${data.added}</li>
                    <li><strong>Skipped:</strong> ${data.skipped} (Duplicates or missing titles)</li>
                </ul>
            `;
            fileInput.value = '';
        } else {
            document.getElementById('importResults').innerHTML = `<div style="color: red;">Error: ${data.detail || JSON.stringify(data)}</div>`;
        }
    } catch (err) {
        document.getElementById('importResults').innerHTML = `<div style="color: red;">Network error: ${err.message}</div>`;
    }
}

async function loadQueue() {
    document.getElementById('queueResults').innerHTML = 'Loading...';
    const token = localStorage.getItem('token');
    if (!token) {
        document.getElementById('queueResults').innerHTML = '<div style="color:red;">Error: Not logged in as admin. Please login.</div>';
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/contributions?status=pending`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        
        if (res.ok) {
            const queue = await res.json();
            if (queue.length === 0) {
                document.getElementById('queueResults').innerHTML = 'Queue is empty.';
                return;
            }
            
            let html = '<table><thead><tr><th>ID</th><th>User ID</th><th>Type</th><th>Payload</th><th>Actions</th></tr></thead><tbody>';
            queue.forEach(c => {
                html += `
                    <tr>
                        <td>${c.id}</td>
                        <td>${c.user_id}</td>
                        <td>${c.type}</td>
                        <td><pre style="max-width:300px; overflow:auto; font-size:12px;">${c.payload}</pre></td>
                        <td>
                            <button class="btn btn-primary" onclick="processContribution(${c.id}, 'approve')">Approve</button>
                            <button class="btn btn-danger" onclick="processContribution(${c.id}, 'reject')">Reject</button>
                        </td>
                    </tr>
                `;
            });
            html += '</tbody></table>';
            document.getElementById('queueResults').innerHTML = html;
        } else {
            document.getElementById('queueResults').innerHTML = '<div style="color:red;">Error loading queue. Admin privileges required.</div>';
        }
    } catch (err) {
        document.getElementById('queueResults').innerHTML = `<div style="color:red;">Network error: ${err.message}</div>`;
    }
}

async function processContribution(id, action) {
    if (!confirm(`Are you sure you want to ${action} this contribution?`)) return;
    
    const token = localStorage.getItem('token');
    try {
        const res = await fetch(`${API_BASE}/contributions/${id}/${action}`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` }
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

// Initial load
document.addEventListener('DOMContentLoaded', loadWorks);
