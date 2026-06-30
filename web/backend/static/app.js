// SkinCoach Web — фронтенд
const API_URL = '';

// Telegram WebApp initData (в dev-режиме пустая строка — бэкенд пропускает)
let initData = '';
if (window.Telegram && window.Telegram.WebApp) {
    initData = window.Telegram.WebApp.initData || '';
    window.Telegram.WebApp.ready();
    window.Telegram.WebApp.expand();
}

// Навигация
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

// Загрузка фото
const dropZone = document.getElementById('drop-zone');
const photoInput = document.getElementById('photo-input');
const previewContainer = document.getElementById('preview-container');
const photoPreview = document.getElementById('photo-preview');
const analyzeBtn = document.getElementById('analyze-btn');
const analysisStatus = document.getElementById('analysis-status');

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

// Анализ
analyzeBtn.addEventListener('click', async () => {
    if (!selectedFile) return;

    analyzeBtn.disabled = true;
    previewContainer.classList.add('hidden');
    analysisStatus.classList.remove('hidden');

    const formData = new FormData();
    formData.append('init_data', initData);
    formData.append('photo', selectedFile);

    try {
        const res = await fetch(`${API_URL}/api/analyze/`, {
            method: 'POST',
            body: formData,
        });
        const data = await res.json();

        if (!res.ok) throw new Error(data.detail || 'Ошибка анализа');

        showResults(data);
    } catch (err) {
        alert('Ошибка: ' + err.message);
        previewContainer.classList.remove('hidden');
    } finally {
        analyzeBtn.disabled = false;
        analysisStatus.classList.add('hidden');
    }
});

function showResults(data) {
    const content = document.getElementById('results-content');
    content.innerHTML = `
        <div class="bg-amber-50 border border-amber-200 rounded-xl p-4">
            <p class="font-medium text-amber-800">⚠️ ${escapeHtml(data.diagnosis)}</p>
        </div>
        <div class="bg-slate-50 rounded-xl p-4">
            <h3 class="font-semibold mb-2">Рекомендации</h3>
            <p class="text-slate-700 whitespace-pre-line">${escapeHtml(data.recommendations)}</p>
        </div>
    `;
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

// Программа
document.getElementById('next-day-btn').addEventListener('click', async () => {
    try {
        const res = await fetch(`${API_URL}/api/program/next?init_data=${encodeURIComponent(initData)}`, {
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
    try {
        const res = await fetch(`${API_URL}/api/program/?init_data=${encodeURIComponent(initData)}`);
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

// Профиль
async function loadProfile() {
    try {
        const res = await fetch(`${API_URL}/api/profile/?init_data=${encodeURIComponent(initData)}`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail);

        document.getElementById('user-badge').textContent = data.user.name || data.user.username || 'Пользователь';
        document.getElementById('user-badge').classList.remove('hidden');

        const analysesHtml = data.analyses.length
            ? '<ul class="divide-y divide-slate-100">' + data.analyses.map(a =>
                `<li class="py-2"><span class="text-slate-500 text-sm">${new Date(a.created_at).toLocaleDateString('ru-RU')}</span> — ${escapeHtml(a.diagnosis || 'анализ')}</li>`
            ).join('') + '</ul>'
            : '<p class="text-slate-500">История анализов пуста</p>';

        document.getElementById('profile-content').innerHTML = `
            <div class="flex justify-between"><span class="text-slate-500">Имя</span><span>${escapeHtml(data.user.name || '—')}</span></div>
            <div class="flex justify-between"><span class="text-slate-500">Username</span><span>${escapeHtml(data.user.username || '—')}</span></div>
            <div class="flex justify-between"><span class="text-slate-500">Подписка</span><span class="capitalize">${escapeHtml(data.user.subscription)}</span></div>
            <div class="mt-4"><h3 class="font-semibold mb-2">История</h3>${analysesHtml}</div>
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

// При загрузке
showSection('upload');
if (initData) loadProfile();
