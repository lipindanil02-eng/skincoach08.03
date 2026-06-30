// SkinCoach Web — фронтенд
const API_URL = '';

// ─── Auth state ───────────────────────────────────────────────────────────
let currentUser = JSON.parse(localStorage.getItem('skincoach_user') || 'null');

if (currentUser) {
    document.getElementById('login-screen').classList.add('hidden');
    document.getElementById('app-screen').classList.remove('hidden');
    document.getElementById('user-badge').textContent = currentUser.name || 'Пользователь';
}

// Login form
document.getElementById('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = document.getElementById('login-name').value.trim();
    if (!name) return;
    try {
        const res = await fetch(`${API_URL}/api/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name }),
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Ошибка входа');
        }
        const data = await res.json();
        currentUser = data.user;
        localStorage.setItem('skincoach_user', JSON.stringify(currentUser));
        document.getElementById('login-screen').classList.add('hidden');
        document.getElementById('app-screen').classList.remove('hidden');
        document.getElementById('user-badge').textContent = currentUser.name;
    } catch (err) {
        alert('Ошибка: ' + err.message);
    }
});

// Logout
document.getElementById('logout-btn').addEventListener('click', () => {
    localStorage.removeItem('skincoach_user');
    location.reload();
});

// ─── Navigation ───────────────────────────────────────────────────────────
const sections = ['upload', 'results', 'program', 'profile'];
const navButtons = document.querySelectorAll('.nav-btn');

function showSection(name) {
    sections.forEach(s => {
        const el = document.getElementById(`${s}-section`);
        if (el) el.classList.add('hidden');
    });
    const target = document.getElementById(`${name}-section`);
    if (target) target.classList.remove('hidden');

    navButtons.forEach(btn => {
        btn.classList.remove('active', 'bg-teal-500', 'text-white');
        btn.classList.add('text-slate-600');
        if (btn.dataset.section === name) {
            btn.classList.add('active', 'bg-teal-500', 'text-white');
            btn.classList.remove('text-slate-600');
        }
    });
}

navButtons.forEach(btn => {
    btn.addEventListener('click', () => {
        const section = btn.dataset.section;
        showSection(section);
        if (section === 'program') loadProgram();
        if (section === 'profile') loadProfile();
    });
});

// ─── Photo upload ────────────────────────────────────────────────────────
const dropZone = document.getElementById('drop-zone');
const photoInput = document.getElementById('photo-input');
const previewContainer = document.getElementById('preview-container');
const photoPreview = document.getElementById('photo-preview');
const analyzeBtn = document.getElementById('analyze-btn');
const analysisStatus = document.getElementById('analysis-status');
const statusText = document.getElementById('status-text');

let selectedFile = null;

dropZone.addEventListener('click', () => photoInput.click());

dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('dragover');
});

dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('dragover');
});

dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    const files = e.dataTransfer.files;
    if (files.length) handleFile(files[0]);
});

photoInput.addEventListener('change', (e) => {
    if (e.target.files.length) handleFile(e.target.files[0]);
});

function handleFile(file) {
    if (!file.type.startsWith('image/')) {
        alert('Пожалуйста, выбери изображение');
        return;
    }
    selectedFile = file;
    const reader = new FileReader();
    reader.onload = (e) => {
        photoPreview.src = e.target.result;
        previewContainer.classList.remove('hidden');
    };
    reader.readAsDataURL(file);
}

// ─── Analyze ─────────────────────────────────────────────────────────────
analyzeBtn.addEventListener('click', async () => {
    if (!selectedFile) return;
    if (!currentUser) {
        alert('Сначала войди');
        return;
    }

    analyzeBtn.disabled = true;
    previewContainer.classList.add('hidden');
    analysisStatus.classList.remove('hidden');
    statusText.textContent = 'Загружаем и анализируем...';

    const formData = new FormData();
    formData.append('user_id', currentUser.id);
    formData.append('photo', selectedFile);

    // Симуляция прогресса (реальный запрос может идти 30-90 сек)
    const progressMessages = [
        'Проверяем качество фото...',
        'ML-модель анализирует кожу...',
        'Дерматологический ИИ ставит диагноз...',
        'Составляем рекомендации...',
    ];
    let i = 0;
    const progressInterval = setInterval(() => {
        i = (i + 1) % progressMessages.length;
        statusText.textContent = progressMessages[i];
    }, 6000);

    try {
        const res = await fetch(`${API_URL}/api/analyze/`, {
            method: 'POST',
            body: formData,
        });
        clearInterval(progressInterval);
        const data = await res.json();

        if (!res.ok) {
            if (res.status === 404 && (data.detail || '').includes('User not found')) {
                // user_id устарел — сбрасываем и просим войти заново
                localStorage.removeItem('skincoach_user');
                currentUser = null;
                clearInterval(progressInterval);
                location.reload();
                return;
            }
            throw new Error(data.detail || 'Ошибка анализа');
        }

        showResults(data);
    } catch (err) {
        clearInterval(progressInterval);
        alert('Ошибка: ' + err.message);
        previewContainer.classList.remove('hidden');
    } finally {
        analyzeBtn.disabled = false;
        analysisStatus.classList.add('hidden');
    }
});

function showResults(data) {
    const content = document.getElementById('results-content');
    const name = currentUser ? (currentUser.name || 'друг') : 'друг';
    let html = '';

    // 1. Приветствие и краткое описание того, что ИИ увидел
    const vision = data.vision || {};
    const visionDesc = vision.raw_description || vision.description || vision.summary || '';
    if (visionDesc) {
        html += `<div class="bg-white border border-slate-200 rounded-xl p-4">
            <p class="text-slate-700">${escapeHtml(name)}, я вижу, что ${escapeHtml(visionDesc)}</p>
        </div>`;
    } else {
        html += `<div class="bg-white border border-slate-200 rounded-xl p-4">
            <p class="text-slate-700">${escapeHtml(name)}, анализ фото выполнен.</p>
        </div>`;
    }

    // 2. ML предсказание с top-3 процентами
    if (data.ml && data.ml.predictions && data.ml.predictions.length) {
        const preds = data.ml.predictions;
        let mlHtml = '<div class="bg-blue-50 border border-blue-200 rounded-xl p-4">';
        mlHtml += '<p class="font-semibold text-blue-900 mb-2">🔬 Предварительный анализ (ML):</p>';
        preds.forEach(p => {
            const pct = (p.probability * 100).toFixed(1);
            const cls = escapeHtml(p.class_name);
            mlHtml += `<div class="flex justify-between items-center py-1">
                <span class="text-blue-900">${cls}</span>
                <span class="font-mono font-bold text-blue-700">${pct}%</span>
            </div>`;
        });
        mlHtml += '</div>';
        html += mlHtml;
    }

    // 3. Гипотезы от LLM (reasoner A) с процентами, если есть
    const reasoning = data.reasoning || {};
    const hyps = reasoning.hypotheses || [];
    if (hyps.length) {
        let rHtml = '<div class="bg-purple-50 border border-purple-200 rounded-xl p-4">';
        rHtml += '<p class="font-semibold text-purple-900 mb-2">🧠 Рассуждение ИИ-дерматолога:</p>';
        hyps.slice(0, 3).forEach(h => {
            rHtml += `<div class="flex justify-between items-center py-1">
                <span class="text-purple-900">${escapeHtml(h.diagnosis || h.condition || '?')}</span>
                <span class="font-mono font-bold text-purple-700">${h.probability || 0}%</span>
            </div>`;
        });
        rHtml += '</div>';
        html += rHtml;
    }

    // 4. Финальный диагноз
    const diagnosis = data.diagnosis || 'требует уточнения';
    html += `<div class="bg-amber-50 border border-amber-200 rounded-xl p-4">
        <p class="text-sm text-amber-600 font-medium">Диагноз:</p>
        <p class="font-bold text-amber-900 text-lg">${escapeHtml(diagnosis)}</p>
    </div>`;

    // 5. Рекомендации
    html += `<div class="bg-slate-50 rounded-xl p-4">
        <h3 class="font-semibold mb-2">📋 Рекомендации</h3>
        <p class="text-slate-700 whitespace-pre-line">${escapeHtml(data.recommendations || 'Анализ выполнен')}</p>
    </div>`;

    content.innerHTML = html;
    showSection('results');
}

document.getElementById('new-photo-btn').addEventListener('click', () => {
    selectedFile = null;
    photoInput.value = '';
    previewContainer.classList.add('hidden');
    showSection('upload');
});

document.getElementById('to-program-btn').addEventListener('click', () => {
    loadProgram();
    showSection('program');
});

// ─── Program ─────────────────────────────────────────────────────────────
document.getElementById('next-day-btn').addEventListener('click', async () => {
    if (!currentUser) return;
    try {
        const res = await fetch(`${API_URL}/api/program/next?user_id=${currentUser.id}`, {
            method: 'POST',
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail);
        renderProgram(data);
    } catch (err) {
        alert('Ошибка: ' + err.message);
    }
});

async function loadProgram() {
    if (!currentUser) return;
    try {
        const res = await fetch(`${API_URL}/api/program/?user_id=${currentUser.id}`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail);
        renderProgram(data);
    } catch (err) {
        document.getElementById('program-content').textContent = 'Ошибка загрузки программы';
    }
}

function renderProgram(data) {
    document.getElementById('program-day').textContent = `День ${data.day} · Неделя ${data.week}`;
    document.getElementById('program-content').textContent = data.last_plan || 'Программа скоро появится...';
}

// ─── Profile ─────────────────────────────────────────────────────────────
async function loadProfile() {
    if (!currentUser) return;
    try {
        const res = await fetch(`${API_URL}/api/profile/?user_id=${currentUser.id}`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail);

        const analysesHtml = data.analyses.length
            ? '<ul class="divide-y divide-slate-100">' + data.analyses.map(a =>
                `<li class="py-2"><span class="text-slate-500 text-sm">${new Date(a.created_at).toLocaleDateString('ru-RU')}</span> — ${escapeHtml(a.diagnosis || 'анализ')}</li>`
            ).join('') + '</ul>'
            : '<p class="text-slate-500">История анализов пуста</p>';

        document.getElementById('profile-content').innerHTML = `
            <div class="flex justify-between"><span class="text-slate-500">Имя</span><span>${escapeHtml(data.user.name || '—')}</span></div>
            <div class="flex justify-between"><span class="text-slate-500">Username</span><span>${escapeHtml(data.user.username || '—')}</span></div>
            <div class="mt-4"><h3 class="font-semibold mb-2">История анализов</h3>${analysesHtml}</div>
        `;
    } catch (err) {
        document.getElementById('profile-content').textContent = 'Ошибка загрузки профиля';
    }
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
