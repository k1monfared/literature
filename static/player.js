/* Shared site player + client-side navigation.
   A single <audio> lives in the sticky header and is never replaced, so the
   currently playing track keeps playing while you move between pages. Internal
   links are intercepted and only <main> is swapped. */
(function () {
  var audio = document.getElementById("player-audio");
  var bar = document.getElementById("playerbar");
  var toggle = document.getElementById("pb-toggle");
  var metaBtn = document.getElementById("pb-meta");
  var titleEl = document.getElementById("pb-title");
  var fill = document.getElementById("pb-fill");
  var progress = document.getElementById("pb-progress");
  var timeEl = document.getElementById("pb-time");
  var speedBtn = document.getElementById("pb-speed");
  var closeBtn = document.getElementById("pb-close");
  var panel = document.getElementById("pb-panel");
  var coverEl = document.getElementById("pb-cover");
  var infoTitle = document.getElementById("pb-info-title");
  var infoPoet = document.getElementById("pb-info-poet");
  var infoSubtitle = document.getElementById("pb-info-subtitle");
  if (!audio || !bar) return;

  var SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 2];
  var speedIndex = 2;
  var scrubbing = false;
  var scrubRatio = 0;
  var pendingStart = null;
  var loadedSrc = "";
  var currentKey = "";

  function parseStart(v) {
    if (!v) return 0;
    var s = String(v);
    if (s.indexOf(":") === -1) return Number(s) || 0;
    var parts = s.split(":").map(Number);
    var total = 0;
    for (var i = 0; i < parts.length; i++) total = total * 60 + (parts[i] || 0);
    return total;
  }

  function fmt(t) {
    if (!isFinite(t) || t < 0) return "0:00";
    var m = Math.floor(t / 60);
    var s = Math.floor(t % 60);
    return m + ":" + (s < 10 ? "0" : "") + s;
  }

  function source() {
    return audio.currentSrc || audio.src || "";
  }

  function refresh() {
    var paused = audio.paused;
    toggle.innerHTML = paused ? "&#9654;" : "&#10074;&#10074;";
    toggle.setAttribute("aria-label", paused ? "Play" : "Pause");
    bar.hidden = !source();
  }

  function setTime() {
    var dur = audio.duration || 0;
    var pos = scrubbing ? scrubRatio * dur : audio.currentTime;
    if (dur) fill.style.width = ((pos / dur) * 100).toFixed(2) + "%";
    timeEl.textContent = fmt(pos) + " / " + fmt(dur);
    progress.setAttribute("aria-valuenow", dur ? Math.round((pos / dur) * 100) : 0);
  }

  audio.addEventListener("play", refresh);
  audio.addEventListener("pause", refresh);
  audio.addEventListener("ended", refresh);
  audio.addEventListener("timeupdate", function () {
    if (!scrubbing) setTime();
  });
  audio.addEventListener("loadedmetadata", function () {
    if (pendingStart !== null) {
      try {
        audio.currentTime = pendingStart;
      } catch (_) {}
      pendingStart = null;
    }
    setTime();
  });

  // --- play / pause ---
  toggle.addEventListener("click", function () {
    if (!source()) return;
    if (audio.paused) audio.play();
    else audio.pause();
  });

  // --- expandable track info ---
  function setPanel(open) {
    panel.hidden = !open;
    metaBtn.setAttribute("aria-expanded", String(open));
  }
  metaBtn.addEventListener("click", function () {
    setPanel(panel.hidden);
  });
  document.addEventListener("click", function (e) {
    if (panel.hidden) return;
    if (e.target.closest("#pb-panel") || e.target.closest("#pb-meta")) return;
    setPanel(false);
  });

  // --- speed ---
  function setSpeed() {
    audio.playbackRate = SPEEDS[speedIndex];
    speedBtn.textContent = SPEEDS[speedIndex] + "\u00d7";
  }
  speedBtn.addEventListener("click", function () {
    speedIndex = (speedIndex + 1) % SPEEDS.length;
    setSpeed();
  });

  // --- scrubbing ---
  function ratioFrom(e) {
    var rect = progress.getBoundingClientRect();
    return Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 1);
  }
  progress.addEventListener("pointerdown", function (e) {
    if (!audio.duration) return;
    scrubbing = true;
    scrubRatio = ratioFrom(e);
    if (progress.setPointerCapture) progress.setPointerCapture(e.pointerId);
    setTime();
  });
  progress.addEventListener("pointermove", function (e) {
    if (!scrubbing) return;
    scrubRatio = ratioFrom(e);
    setTime();
  });
  function endScrub(e) {
    if (!scrubbing) return;
    scrubbing = false;
    if (progress.releasePointerCapture && e.pointerId !== undefined) {
      try { progress.releasePointerCapture(e.pointerId); } catch (_) {}
    }
    if (audio.duration) audio.currentTime = scrubRatio * audio.duration;
    setTime();
  }
  progress.addEventListener("pointerup", endScrub);
  progress.addEventListener("pointercancel", endScrub);
  function skip(delta) {
    if (!source() || !audio.duration) return;
    audio.currentTime = Math.max(0, Math.min(audio.duration, audio.currentTime + delta));
    setTime();
  }

  var rewBtn = document.getElementById("pb-rew");
  var ffBtn = document.getElementById("pb-ff");
  if (rewBtn) rewBtn.addEventListener("click", function () { skip(-15); });
  if (ffBtn) ffBtn.addEventListener("click", function () { skip(15); });

  // Global keyboard shortcuts (only while a track is loaded).
  document.addEventListener("keydown", function (e) {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    var el = e.target;
    var tag = (el && el.tagName ? el.tagName : "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select" || (el && el.isContentEditable)) return;
    if (!source()) return;
    var step = e.shiftKey ? 30 : 5;
    if (e.key === " " || e.code === "Space" || e.key === "Spacebar") {
      e.preventDefault();
      if (audio.paused) audio.play();
      else audio.pause();
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      skip(-step);
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      skip(step);
    }
    // ArrowUp / ArrowDown are left to the browser so the page still scrolls.
  });

  // --- close / clear ---
  closeBtn.addEventListener("click", function (e) {
    e.preventDefault();
    audio.pause();
    audio.removeAttribute("src");
    audio.load();
    titleEl.textContent = "";
    fill.style.width = "0%";
    timeEl.textContent = "0:00 / 0:00";
    setPanel(false);
    bar.hidden = true;
    loadedSrc = "";
    currentKey = "";
    pendingStart = null;
  });

  // --- loading a track from any play button (delegated) ---
  function loadMeta(btn) {
    var abs = function (v) {
      return v ? new URL(v, location.href).href : "";
    };
    var title = btn.getAttribute("data-title") || "";
    titleEl.textContent = title;
    infoTitle.textContent = "";
    if (btn.getAttribute("data-href")) {
      var a = document.createElement("a");
      a.href = abs(btn.getAttribute("data-href"));
      a.textContent = title;
      infoTitle.appendChild(a);
    } else {
      infoTitle.textContent = title;
    }
    infoPoet.textContent = btn.getAttribute("data-poet") || "";
    infoSubtitle.textContent = btn.getAttribute("data-subtitle") || "";
    var cover = abs(btn.getAttribute("data-cover"));
    if (cover) {
      coverEl.src = cover;
      coverEl.hidden = false;
    } else {
      coverEl.hidden = true;
    }
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest ? e.target.closest(".play-track, .track-play") : null;
    if (!btn) return;
    e.preventDefault();
    var src = new URL(btn.getAttribute("data-src"), location.href).href;
    var start = parseStart(btn.getAttribute("data-start"));
    var key = src + "|" + start;
    if (currentKey === key && loadedSrc === src) {
      if (audio.paused) audio.play();
      else audio.pause();
      return;
    }
    loadMeta(btn);
    if (loadedSrc !== src) {
      pendingStart = start;
      audio.src = src;
      loadedSrc = src;
    } else if (start) {
      try {
        audio.currentTime = start;
      } catch (_) {}
    }
    currentKey = key;
    setSpeed();
    bar.hidden = false;
    audio.play();
  });

  // --- client-side navigation so the player keeps playing ---
  var canFetch = location.protocol === "http:" || location.protocol === "https:";
  var loadedKey = location.pathname + location.search;

  function swap(html, url, push) {
    var doc = new DOMParser().parseFromString(html, "text/html");
    var incoming = doc.querySelector("main");
    if (!incoming) throw new Error("no main");
    if (push) history.pushState({}, "", url);
    var current = document.querySelector("main");
    current.replaceWith(document.importNode(incoming, true));
    document.title = doc.title;
    var u = new URL(url, location.href);
    loadedKey = u.pathname + u.search;
    if (u.hash) scrollToId(u.hash);
    else window.scrollTo(0, 0);
  }

  function scrollToId(hash) {
    var id;
    try {
      id = decodeURIComponent(hash.replace(/^#/, ""));
    } catch (_) {
      return;
    }
    var el = document.getElementById(id);
    if (el) el.scrollIntoView();
    else window.scrollTo(0, 0);
  }

  function navigate(url, push) {
    fetch(url, { headers: { "X-Requested-With": "fetch" } })
      .then(function (res) {
        if (!res.ok) throw new Error(res.status);
        return res.text();
      })
      .then(function (html) {
        swap(html, url, push);
      })
      .catch(function () {
        location.href = url;
      });
  }

  if (canFetch) {
    document.addEventListener("click", function (e) {
      if (e.defaultPrevented || e.button !== 0) return;
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      var a = e.target.closest ? e.target.closest("a") : null;
      if (!a) return;
      var href = a.getAttribute("href");
      if (!href || href.charAt(0) === "#" || a.target || a.hasAttribute("download")) return;
      var url;
      try {
        url = new URL(a.href, location.href);
      } catch (_) {
        return;
      }
      if (url.origin !== location.origin) return;
      if (url.href === location.href) {
        e.preventDefault();
        return;
      }
      e.preventDefault();
      navigate(url.href, true);
    });
    window.addEventListener("popstate", function () {
      // Fragment-only changes also fire popstate in some browsers; in that
      // case the document is the same and the browser handles the anchor.
      if (location.pathname + location.search === loadedKey) return;
      navigate(location.href, false);
    });
  }
})();
