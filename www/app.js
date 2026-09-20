async function refreshStatus() {
  const res = await fetch('/api/status');
  const data = await res.json();
  document.querySelectorAll('#status dd').forEach(dd => {
    dd.textContent = data[dd.dataset.k];
  });
}

async function refreshConfig() {
  const res = await fetch('/api/config');
  const data = await res.json();
  document.getElementById('config-view').textContent = JSON.stringify(data, null, 2);
  const form = document.getElementById('config-form');
  for (const [key, value] of Object.entries(data)) {
    if (form.elements[key]) form.elements[key].value = value;
  }
}

document.getElementById('config-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const msg = document.getElementById('message');
  const res = await fetch('/api/config', {
    method: 'POST',
    body: new URLSearchParams(new FormData(event.target)),
  });
  const text = await res.text();
  msg.classList.toggle('error', !res.ok);
  msg.textContent = res.ok ? '配置已保存' : ('保存失败: ' + res.status);
  if (res.ok) refreshConfig();
});

document.getElementById('refresh').addEventListener('click', refreshStatus);
refreshStatus();
refreshConfig();
setInterval(refreshStatus, 5000);
