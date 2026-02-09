const drawBtn = document.getElementById('draw-btn');
const copyBtn = document.getElementById('copy-btn');
const resultPanel = document.getElementById('result');
const copyPanel = document.getElementById('copy-panel');
const errorPanel = document.getElementById('error-panel');
const drinkList = document.getElementById('drink-list');
const foodList = document.getElementById('food-list');
const copyText = document.getElementById('copy-text');
const copyHint = document.getElementById('copy-hint');

function clearState() {
  errorPanel.classList.add('hidden');
  errorPanel.textContent = '';
  copyHint.textContent = '';
}

function renderList(target, items) {
  target.innerHTML = '';
  items.forEach((item) => {
    const li = document.createElement('li');
    li.className = 'item';
    li.innerHTML = `
      <strong>${item.item_name}</strong>
      <span>${item.store_name}</span>
      <a href="${item.store_url}" target="_blank" rel="noopener noreferrer">店家頁</a>
      <a href="${item.group_order_url}" target="_blank" rel="noopener noreferrer">團購表單</a>
    `;
    target.appendChild(li);
  });
}

async function drawRandomSelection() {
  clearState();
  drawBtn.disabled = true;
  drawBtn.textContent = '抽選中...';

  try {
    const response = await fetch('/api/random-selection');
    const data = await response.json();

    if (!data.ok) {
      throw new Error(data.message || '抽選失敗');
    }

    renderList(drinkList, data.result.drinks);
    renderList(foodList, data.result.foods);

    resultPanel.classList.remove('hidden');
    copyPanel.classList.remove('hidden');

    copyText.value = data.copy_text;
  } catch (error) {
    resultPanel.classList.add('hidden');
    copyPanel.classList.add('hidden');
    errorPanel.textContent = error.message;
    errorPanel.classList.remove('hidden');
  } finally {
    drawBtn.disabled = false;
    drawBtn.textContent = '隨機抽選';
  }
}

async function copyResultText() {
  if (!copyText.value.trim()) {
    copyHint.textContent = '目前沒有可複製內容。';
    return;
  }

  try {
    await navigator.clipboard.writeText(copyText.value);
    copyHint.textContent = '已複製：商店名+ubereat團購表單';
  } catch (err) {
    copyText.select();
    document.execCommand('copy');
    copyHint.textContent = '已複製（使用備援模式）。';
  }
}

drawBtn.addEventListener('click', drawRandomSelection);
copyBtn.addEventListener('click', copyResultText);
