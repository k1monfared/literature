/* Shared site player + client-side navigation.
   A single <audio> lives in the sticky header and is never replaced, so the
   currently playing track keeps playing while you move between pages. Internal
   links are intercepted and only <main> is swapped. */
(function () {
  var audio = document.getElementById("player-audio");
  var bar = document.getElementById("playerbar");
  var toggle = document.getElementById("pb-toggle");
  var titleEl = document.getElementById("pb-title");
  var fill = document.getElementById("pb-fill");
  var progress = document.getElementById("pb-progress");
  var timeEl = document.getElementById("pb-time");
  var closeBtn = document.getElementById("pb-close");
  if (!audio || !bar) return;

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
    if (audio.duration) {
      fill.style.width = (audio.currentTime / audio.duration) * 100 + "%";
    }
    timeEl.textContent = fmt(audio.currentTime) + " / " + fmt(audio.duration);
  }

  audio.addEventListener("play", refresh);
  audio.addEventListener("pause", refresh);
  audio.addEventListener("ended", refresh);
  audio.addEventListener("timeupdate", setTime);
  audio.addEventListener("loadedmetadata", setTime);

  toggle.addEventListener("click", function () {
    if (audio.paused) audio.play();
    else audio.pause();
  });

  progress.addEventListener("click", function (e) {
    if (!audio.duration) return;
    var rect = progress.getBoundingClientRect();
    var ratio = Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 1);
    audio.currentTime = ratio * audio.duration;
    setTime();
  });

  closeBtn.addEventListener("click", function (e) {
    e.preventDefault();
    audio.pause();
    audio.removeAttribute("src");
    audio.load();
    fill.style.width = "0%";
    timeEl.textContent = "0:00 / 0:00";
    refresh();
  });

  // Play buttons anywhere on the site (delegated, so it survives <main> swaps).
  document.addEventListener("click", function (e) {
    var btn = e.target.closest ? e.target.closest(".play-track") : null;
    if (!btn) return;
    e.preventDefault();
    var src = new URL(btn.getAttribute("data-src"), location.href).href;
    var title = btn.getAttribute("data-title") || "";
    if (source() === src) {
      if (audio.paused) audio.play();
      else audio.pause();
      return;
    }
    audio.src = src;
    titleEl.textContent = title;
    bar.hidden = false;
    audio.play();
  });

  // --- client-side navigation so the player keeps playing ---
  var canFetch = location.protocol === "http:" || location.protocol === "https:";

  function swap(html, url, push) {
    var doc = new DOMParser().parseFromString(html, "text/html");
    var incoming = doc.querySelector("main");
    if (!incoming) throw new Error("no main");
    if (push) history.pushState({}, "", url);
    var current = document.querySelector("main");
    current.replaceWith(document.importNode(incoming, true));
    document.title = doc.title;
    window.scrollTo(0, 0);
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
      navigate(location.href, false);
    });
  }
})();
