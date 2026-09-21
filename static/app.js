async function refreshStatus() {
  const response = await fetch('/api/status');
  document.getElementById('status').textContent = JSON.stringify(await response.json(), null, 2);
}
async function loadConfig() {
  const config = await (await fetch('/api/config')).json();
  document.forms['config-form'].sample_interval.value = config.sample_interval;
  document.forms['config-form'].alarm_threshold.value = config.alarm_threshold;
}
document.getElementById('config-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const message = document.getElementById('message');
  const payload = Object.fromEntries(new FormData(event.target).entries());
  const response = await fetch('/api/config', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  });
  message.textContent = response.ok ? '配置已保存' : `保存失败：${await response.text()}`;
});
Promise.all([refreshStatus(), loadConfig()]);
