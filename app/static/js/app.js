/* ClipForge Studio — tiny progressive enhancements. htmx does the heavy lifting. */
(function () {
  'use strict';
  // Dismiss toasts after 5s (pause on hover)
  document.addEventListener('click', function (e) {
    var t = e.target.closest('.c-toast');
    if (t) t.remove();
  });
  setTimeout(function () {
    document.querySelectorAll('.c-toast').forEach(function (t) { t.remove(); });
  }, 5000);
})();
