(() => {
  const body = document.body;
  const token = body.dataset.token;
  const form = document.getElementById('upload-form');
  if (!form) return;

  const worksheetSelect = document.getElementById('worksheet-select');
  const filesInput = document.getElementById('files');
  const sameStudent = document.getElementById('same-student');
  const fileCount = document.getElementById('file-count');
  const message = document.getElementById('upload-message');
  const button = document.getElementById('upload-button');
  const statusList = document.getElementById('status-list');
  const refreshButton = document.getElementById('refresh');

  const labels = {
    queued: '排队中',
    processing: '识别中',
    graded: '已批改',
    needs_review: '待老师复核',
    confirmed: '已确认',
    failed: '失败',
    interrupted: '中断，可重试',
  };

  let trackedIds = [];

  function setMessage(text) {
    message.textContent = text || '';
  }

  function renderStatus(items) {
    if (!items.length) {
      statusList.innerHTML = '<p class="muted">上传后这里会显示每份作业的进度。</p>';
      return;
    }
    statusList.innerHTML = items.map((item) => {
      const label = labels[item.status] || item.status;
      const score = item.score === null || item.score === undefined ? '' : `${item.score} / ${item.max_score}`;
      const student = item.student ? ` · ${item.student}` : '';
      const error = item.error ? `<div class="bad">${escapeHtml(item.error)}</div>` : '';
      return `<div class="mobile-status-row">
        <div class="top"><span>#${item.id}${escapeHtml(student)}</span><span>${label}</span></div>
        ${score ? `<div class="score">${score}</div>` : ''}
        ${error}
      </div>`;
    }).join('');
  }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[ch]));
  }

  async function refreshStatus() {
    if (!trackedIds.length) return;
    try {
      const response = await fetch(`/m/${token}/status?ids=${trackedIds.join(',')}`);
      const data = await response.json();
      renderStatus(data.items || []);
      const active = (data.items || []).some((item) =>
        ['queued', 'processing', 'interrupted'].includes(item.status));
      if (active) {
        setTimeout(refreshStatus, 3000);
      }
    } catch (error) {
      setMessage('状态刷新失败：' + error);
    }
  }

  filesInput.addEventListener('change', () => {
    const count = filesInput.files.length;
    fileCount.textContent = count ? `已选择 ${count} 张` : '还没有选择照片';
  });

  refreshButton.addEventListener('click', refreshStatus);

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!filesInput.files.length) {
      setMessage('先选择至少一张照片。');
      return;
    }
    button.disabled = true;
    setMessage('上传中…');
    const payload = new FormData();
    payload.append('worksheet_id', worksheetSelect.value);
    if (sameStudent.checked) payload.append('same_student', 'true');
    for (const file of filesInput.files) payload.append('files', file);

    try {
      const response = await fetch(`/m/${token}/upload`, { method: 'POST', body: payload });
      const data = await response.json();
      if (!data.ok) {
        setMessage(data.error || '上传失败');
        return;
      }
      trackedIds = data.submission_ids || [];
      setMessage(`已收到 ${trackedIds.length} 份，开始批改…`);
      filesInput.value = '';
      fileCount.textContent = '还没有选择照片';
      await refreshStatus();
    } catch (error) {
      setMessage('上传失败：' + error);
    } finally {
      button.disabled = false;
    }
  });
})();
