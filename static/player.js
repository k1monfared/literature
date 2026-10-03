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
  var tracksBySrc = {};
  var shownKey = "";
  var trackButtons = [];
  var bookButtons = [];
  var SVG_PLAY =
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>';
  var SVG_PAUSE =
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg>';

  function setIcon(el, pause) {
    var ico = el.querySelector ? el.querySelector(".ico") : null;
    (ico || el).innerHTML = pause ? SVG_PAUSE : SVG_PLAY;
  }

  function updateTrackIcons() {
    var playing = !audio.paused && !audio.ended;
    for (var i = 0; i < trackButtons.length; i++) {
      setIcon(trackButtons[i].el, playing && trackButtons[i].key === shownKey);
    }
    for (var j = 0; j < bookButtons.length; j++) {
      setIcon(bookButtons[j].el, playing && bookButtons[j].src === loadedSrc);
    }
  }

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
    toggle.innerHTML = paused ? SVG_PLAY : SVG_PAUSE;
    toggle.setAttribute("aria-label", paused ? "Play" : "Pause");
    bar.hidden = !source();
    updateTrackIcons();
  }

  function setTime() {
    var dur = audio.duration || 0;
    var pos = scrubbing ? scrubRatio * dur : audio.currentTime;
    if (dur) fill.style.width = ((pos / dur) * 100).toFixed(2) + "%";
    timeEl.textContent = fmt(pos) + " / " + fmt(dur);
    progress.setAttribute("aria-valuenow", dur ? Math.round((pos / dur) * 100) : 0);
    updateActiveTitle(pos);
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
    shownKey = "";
  });

  // --- track metadata ---
  function metaFrom(btn) {
    var abs = function (v) {
      return v ? new URL(v, location.href).href : "";
    };
    return {
      src: abs(btn.getAttribute("data-src")),
      start: parseStart(btn.getAttribute("data-start")),
      title: btn.getAttribute("data-title") || "",
      poet: btn.getAttribute("data-poet") || "",
      subtitle: btn.getAttribute("data-subtitle") || "",
      cover: abs(btn.getAttribute("data-cover")),
      href: abs(btn.getAttribute("data-href")),
    };
  }

  function applyMeta(m) {
    titleEl.textContent = m.title;
    infoTitle.textContent = "";
    if (m.href) {
      var a = document.createElement("a");
      a.href = m.href;
      a.textContent = m.title;
      infoTitle.appendChild(a);
    } else {
      infoTitle.textContent = m.title;
    }
    infoPoet.textContent = m.poet;
    infoSubtitle.textContent = m.subtitle;
    if (m.cover) {
      coverEl.src = m.cover;
      coverEl.hidden = false;
    } else {
      coverEl.hidden = true;
    }
  }

  // Collect the per-poem timestamps in the page so the title can follow the
  // playback position as it crosses from one poem into the next.
  function refreshTracks() {
    tracksBySrc = {};
    trackButtons = [];
    bookButtons = [];
    var seen = {};
    var buttons = document.querySelectorAll(".track-play");
    for (var i = 0; i < buttons.length; i++) {
      var m = metaFrom(buttons[i]);
      if (!m.src) continue;
      var k = m.src + "|" + m.start;
      trackButtons.push({ el: buttons[i], key: k });
      if (seen[k]) continue;
      seen[k] = 1;
      (tracksBySrc[m.src] = tracksBySrc[m.src] || []).push(m);
    }
    var bbuttons = document.querySelectorAll(".play-track");
    for (var j = 0; j < bbuttons.length; j++) {
      bookButtons.push({ el: bbuttons[j], src: metaFrom(bbuttons[j]).src });
    }
    for (var s in tracksBySrc) {
      tracksBySrc[s].sort(function (a, b) {
        return a.start - b.start;
      });
    }
    updateTrackIcons();
  }

  function activeTrackFor(pos) {
    var list = tracksBySrc[loadedSrc] || [];
    var active = null;
    for (var i = 0; i < list.length; i++) {
      if (list[i].start <= pos + 0.25) active = list[i];
      else break;
    }
    return active;
  }

  function updateActiveTitle(pos) {
    if (!loadedSrc) return;
    var t = activeTrackFor(pos);
    if (!t) return;
    var k = t.src + "|" + t.start;
    if (k !== shownKey) {
      shownKey = k;
      applyMeta(t);
      updateTrackIcons();
    }
  }

  // --- loading a track from any play button (delegated) ---
  document.addEventListener("click", function (e) {
    var btn = e.target.closest ? e.target.closest(".play-track, .track-play") : null;
    if (!btn) return;
    e.preventDefault();
    var m = metaFrom(btn);
    var isTrack = btn.classList.contains("track-play");
    var key = m.src + "|" + m.start;

    // The book button toggles whenever its audio is loaded; a per-poem button
    // toggles only when it is the track currently playing/paused.
    var isActive = loadedSrc === m.src && (isTrack ? key === shownKey : true);
    if (isActive) {
      if (audio.paused) audio.play();
      else audio.pause();
      updateTrackIcons();
      return;
    }

    applyMeta(m);
    shownKey = key;
    if (loadedSrc !== m.src) {
      pendingStart = m.start;
      audio.src = m.src;
      loadedSrc = m.src;
    } else {
      try {
        audio.currentTime = m.start;
      } catch (_) {}
    }
    currentKey = key;
    setSpeed();
    bar.hidden = false;
    updateTrackIcons();
    audio.play();
  });

  refreshTracks();

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
    refreshTracks();
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
