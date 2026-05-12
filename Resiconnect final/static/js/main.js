// ResiConnect — main.js

// Modal helpers
function openModal(id) {
  const el = document.getElementById(id);
  if (el) { el.style.display = 'flex'; el.classList.add('open'); }
}
function closeModal(id) {
  const el = document.getElementById(id);
  if (el) { el.style.display = 'none'; el.classList.remove('open'); }
}

// Close modals on overlay click
document.addEventListener('click', (e) => {
  if (e.target.classList.contains('modal-overlay')) {
    e.target.style.display = 'none';
    e.target.classList.remove('open');
  }
});

// Auto-dismiss flash messages
document.addEventListener('DOMContentLoaded', () => {
  const flashes = document.querySelectorAll('.flash');
  flashes.forEach(f => {
    setTimeout(() => {
      f.style.transition = 'opacity 0.5s';
      f.style.opacity = '0';
      setTimeout(() => f.remove(), 500);
    }, 4000);
  });
});

let lastSeenNoticeId = localStorage.getItem("lastNoticeId");

function checkNewNotice() {
  // 🚫 Skip only for admin
  if (USER_ROLE === 'admin') return;

  fetch('/api/latest-notice')
    .then(res => res.json())
    .then(data => {
      if (!data.id) return;

      if (lastSeenNoticeId != data.id) {
        showPopup(data);
        localStorage.setItem("lastNoticeId", data.id);
        lastSeenNoticeId = data.id;
      }
    })
    .catch(err => console.error("Notice fetch error:", err));
}

function showPopup(data) {
  document.getElementById("popupTitle").innerText = data.title;
  document.getElementById("popupBody").innerText = data.body;

  const popup = document.getElementById("noticePopup");
  popup.style.display = "flex";
  popup.classList.add("open");
}

function closePopup() {
  const popup = document.getElementById("noticePopup");
  popup.style.display = "none";
  popup.classList.remove("open");
}

// run for everyone (admin will just skip inside)
setInterval(checkNewNotice, 10000);
document.addEventListener("DOMContentLoaded", checkNewNotice);