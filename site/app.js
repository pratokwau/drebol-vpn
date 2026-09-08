/* Drebol VPN — логика витрины. Настройки приходят из config.js (пишет бот). */

(function () {
  "use strict";

  var cfg = window.SITE_CONFIG || {};

  // ── Ссылка на бота ────────────────────────────────────────────────
  var botUrl = cfg.botUrl || "";
  document.querySelectorAll("[data-bot-link]").forEach(function (a) {
    if (botUrl) {
      a.href = botUrl;
      a.target = "_blank";
    } else {
      // бот не задан — не ведём в никуда
      a.href = "#top";
      a.removeAttribute("target");
    }
  });

  // ── Текстовые значения из конфига ─────────────────────────────────
  document.querySelectorAll("[data-cfg]").forEach(function (el) {
    var val = cfg[el.getAttribute("data-cfg")];
    if (val) el.textContent = val;
  });

  // ── Ссылки из конфига (документы) ─────────────────────────────────
  document.querySelectorAll("[data-cfg-href]").forEach(function (a) {
    var val = cfg[a.getAttribute("data-cfg-href")];
    if (val) {
      a.href = val;
      a.target = "_blank";
      a.rel = "noopener";
    } else if (a.hasAttribute("data-hide-empty")) {
      a.remove();
    }
  });

  // ── Год в подвале ─────────────────────────────────────────────────
  var y = document.getElementById("year");
  if (y) y.textContent = new Date().getFullYear();

  // ── Появление блоков при скролле ──────────────────────────────────
  var revealables = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          e.target.classList.add("in");
          io.unobserve(e.target);
        }
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -40px 0px" });
    revealables.forEach(function (el) { io.observe(el); });
  } else {
    revealables.forEach(function (el) { el.classList.add("in"); });
  }

  // ── Счётчики в hero ───────────────────────────────────────────────
  function runCounter(el) {
    var fixedText = el.getAttribute("data-text");
    if (fixedText) { el.textContent = fixedText; return; }

    var target = parseFloat(el.getAttribute("data-count"));
    if (isNaN(target)) return;

    var prefix = el.getAttribute("data-prefix") || "";
    var suffix = el.getAttribute("data-suffix") || "";
    var decimals = (String(target).split(".")[1] || "").length;
    var dur = 1400;
    var start = null;

    function frame(ts) {
      if (start === null) start = ts;
      var p = Math.min((ts - start) / dur, 1);
      var eased = 1 - Math.pow(1 - p, 3);
      el.textContent = prefix + (target * eased).toFixed(decimals) + suffix;
      if (p < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  var counters = document.querySelectorAll("[data-count]");
  if ("IntersectionObserver" in window) {
    var cio = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          runCounter(e.target);
          cio.unobserve(e.target);
        }
      });
    }, { threshold: 0.5 });
    counters.forEach(function (el) { cio.observe(el); });
  } else {
    counters.forEach(runCounter);
  }

  // ── Тень навигации при прокрутке ──────────────────────────────────
  var nav = document.querySelector(".nav");
  function onScroll() {
    if (nav) nav.classList.toggle("stuck", window.scrollY > 8);
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  // ── Подсветка карточки под курсором ───────────────────────────────
  var fine = window.matchMedia("(hover:hover) and (pointer:fine)").matches;
  if (fine) {
    document.querySelectorAll(".card").forEach(function (card) {
      card.addEventListener("mousemove", function (e) {
        var r = card.getBoundingClientRect();
        card.style.setProperty("--mx", (e.clientX - r.left) + "px");
        card.style.setProperty("--my", (e.clientY - r.top) + "px");
      });
    });
  }
})();
