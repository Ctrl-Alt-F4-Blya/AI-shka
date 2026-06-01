const byId = (id) => document.getElementById(id);

const elements = {
  canvas: byId('canvas'),
  emptyHint: byId('emptyHint'),
  dropZone: byId('dropZone'),
  fileInput: byId('fileInput'),
  openBtn: byId('openBtn'),
  pasteBtn: byId('pasteBtn'),
  recognizeBtn: byId('recognizeBtn'),
  resultText: byId('resultText'),
  confidenceValue: byId('confidenceValue'),
  confidenceBar: byId('confidenceBar'),
  linksBox: byId('linksBox'),
  linksList: byId('linksList'),
  alternativesList: byId('alternativesList'),
  note: byId('note'),
  statusBox: byId('statusBox'),
  copyTextBtn: byId('copyTextBtn'),
  copyLinksBtn: byId('copyLinksBtn'),
  speakBtn: byId('speakBtn'),
};

const state = {
  image: new Image(),
  hasImage: false,
  links: [],
};

const context = elements.canvas.getContext('2d');

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    "'": '&#39;',
    '"': '&quot;',
  }[char]));
}

async function loadStatus() {
  try {
    const response = await fetch('/api/status');
    const status = await response.json();
    const languages = status.languages && status.languages.length ? status.languages.join(', ') : 'нет списка';
    elements.statusBox.innerHTML = [
      `Pillow: <b>${status.pillow ? 'OK' : 'нет'}</b>`,
      `OCR: <b>${status.tesseract ? 'Tesseract найден' : 'не найден'}</b>`,
      `EasyOCR: <b>${status.easyocr ? 'установлен' : 'не установлен'}</b>`,
      `Языки: ${escapeHtml(languages)}`,
      `OpenAI API: <b>${status.openai ? 'подключён' : 'не подключён'}</b>`,
      `Модель: ${escapeHtml(status.openaiModel || '')}`,
    ].join('<br>');
  } catch (error) {
    elements.statusBox.textContent = 'Сервер не отвечает';
  }
}

function drawPreview() {
  if (!state.hasImage) return;

  const zoom = Number(byId('zoom').value) / 100;
  const contrast = Number(byId('contrast').value) / 100;
  const brightness = Number(byId('brightness').value) / 100;

  elements.canvas.width = Math.max(1, Math.round(state.image.naturalWidth * zoom));
  elements.canvas.height = Math.max(1, Math.round(state.image.naturalHeight * zoom));
  elements.canvas.style.display = 'block';
  elements.emptyHint.style.display = 'none';

  context.save();
  context.filter = [
    byId('gray').checked ? 'grayscale(1)' : '',
    `contrast(${contrast})`,
    `brightness(${brightness})`,
    byId('invert').checked ? 'invert(1)' : '',
  ].filter(Boolean).join(' ');
  context.imageSmoothingEnabled = true;
  context.drawImage(state.image, 0, 0, elements.canvas.width, elements.canvas.height);
  context.restore();
}

function loadFile(file) {
  if (!file) return;

  const reader = new FileReader();
  reader.onload = () => {
    const nextImage = new Image();
    nextImage.onload = () => {
      state.image = nextImage;
      state.hasImage = true;
      drawPreview();
      elements.note.textContent = `Файл загружен: ${file.name || 'изображение'}`;
    };
    nextImage.src = reader.result;
  };
  reader.readAsDataURL(file);
}

function getOriginalImageData() {
  if (!state.hasImage) return null;
  const canvas = document.createElement('canvas');
  canvas.width = state.image.naturalWidth;
  canvas.height = state.image.naturalHeight;
  canvas.getContext('2d').drawImage(state.image, 0, 0);
  return canvas.toDataURL('image/png');
}

function setConfidence(value) {
  const percent = Math.max(0, Math.min(100, Number(value) || 0));
  elements.confidenceValue.textContent = `${percent.toFixed(1)}%`;
  elements.confidenceBar.style.width = `${percent}%`;
}

function renderLinks(links) {
  state.links = links || [];
  if (!state.links.length) {
    elements.linksBox.hidden = true;
    elements.linksList.innerHTML = '';
    return;
  }
  elements.linksBox.hidden = false;
  elements.linksList.innerHTML = state.links.map((item) => `<div class="linkItem">${escapeHtml(item)}</div>`).join('');
}

function renderAlternatives(items) {
  elements.alternativesList.innerHTML = (items || []).map((item) => {
    const confidence = Number(item.confidence || 0).toFixed(1);
    const meta = `${confidence}% · psm ${escapeHtml(item.psm || '')} · ${escapeHtml(item.variant || '')}${item.whitelist ? ' · whitelist' : ''}`;
    return `<div class="altItem"><b>${meta}</b>\n${escapeHtml(item.text || '')}</div>`;
  }).join('');
}

async function recognizeImage() {
  const image = getOriginalImageData();
  if (!image) {
    elements.note.textContent = 'Сначала загрузи картинку.';
    return;
  }

  elements.recognizeBtn.disabled = true;
  elements.recognizeBtn.textContent = 'Распознаю...';
  elements.note.textContent = 'Идёт распознавание. На сложной картинке это может занять 10–40 секунд.';

  try {
    const response = await fetch('/api/ocr', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image,
        language: byId('language').value,
        mode: byId('mode').value,
        engine: byId('engine').value,
      }),
    });
    const result = await response.json();

    elements.resultText.value = result.text || (!result.ok ? (result.message || '') : '');
    setConfidence(result.confidence || 0);
    renderLinks(result.links || []);
    renderAlternatives(result.alternatives || []);

    if (result.ok) {
      elements.note.textContent = `Готово. Движок: ${result.engine || 'unknown'}${result.endpoint ? ' · ' + result.endpoint : ''}. Язык: ${result.language || byId('language').value}.`;
    } else {
      elements.note.textContent = result.message || 'Не получилось распознать текст.';
    }
  } catch (error) {
    elements.note.textContent = `Ошибка запроса: ${error.message}`;
  } finally {
    elements.recognizeBtn.disabled = false;
    elements.recognizeBtn.textContent = 'Распознать';
  }
}

async function copyToClipboard(text) {
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    elements.note.textContent = 'Скопировано.';
  } catch (error) {
    elements.note.textContent = 'Не получилось скопировать автоматически. Выдели текст вручную.';
  }
}

async function pasteImage() {
  try {
    const items = await navigator.clipboard.read();
    for (const item of items) {
      const type = item.types.find((entry) => entry.startsWith('image/'));
      if (!type) continue;
      const blob = await item.getType(type);
      loadFile(new File([blob], 'clipboard.png', { type }));
      return;
    }
    elements.note.textContent = 'В буфере нет картинки. Можно нажать Ctrl+V прямо на странице.';
  } catch (error) {
    elements.note.textContent = 'Браузер не дал доступ к буферу. Нажми Ctrl+V на странице.';
  }
}

function speakResult() {
  const text = elements.resultText.value.trim();
  if (!text) return;
  speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = byId('language').value.includes('rus') ? 'ru-RU' : 'en-US';
  speechSynthesis.speak(utterance);
}

elements.openBtn.addEventListener('click', () => elements.fileInput.click());
elements.fileInput.addEventListener('change', (event) => loadFile(event.target.files[0]));
elements.pasteBtn.addEventListener('click', pasteImage);
elements.recognizeBtn.addEventListener('click', recognizeImage);
elements.copyTextBtn.addEventListener('click', () => copyToClipboard(elements.resultText.value));
elements.copyLinksBtn.addEventListener('click', () => copyToClipboard(state.links.join('\n')));
elements.speakBtn.addEventListener('click', speakResult);

['zoom', 'contrast', 'brightness', 'invert', 'gray'].forEach((id) => {
  byId(id).addEventListener('input', drawPreview);
});

elements.dropZone.addEventListener('dragover', (event) => {
  event.preventDefault();
  elements.dropZone.classList.add('drag');
});
elements.dropZone.addEventListener('dragleave', () => elements.dropZone.classList.remove('drag'));
elements.dropZone.addEventListener('drop', (event) => {
  event.preventDefault();
  elements.dropZone.classList.remove('drag');
  loadFile(event.dataTransfer.files[0]);
});

document.addEventListener('paste', (event) => {
  const items = event.clipboardData && event.clipboardData.items;
  if (!items) return;
  for (const item of items) {
    if (!item.type.startsWith('image/')) continue;
    loadFile(item.getAsFile());
    event.preventDefault();
    break;
  }
});

loadStatus();
