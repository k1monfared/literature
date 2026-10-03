/* Footnote popups. The glossary definitions are hidden spans; hovering (or
   tapping) an in-text reference shows them near the word. Delegated on document
   so it keeps working after client-side navigation. */
(function () {
  var popup = document.createElement("div");
  popup.className = "fn-popup";
  popup.id = "fn-popup";
  popup.hidden = true;
  document.body.appendChild(popup);

  var current = null;
  var hoverCapable = window.matchMedia && window.matchMedia("(hover: hover)").matches;

  function place(ref) {
    var r = ref.getBoundingClientRect();
    var p = popup.getBoundingClientRect();
    var top = r.bottom + 8;
    if (top + p.height > window.innerHeight - 8) top = r.top - p.height - 8;
    if (top < 8) top = 8;
    var left = r.left + r.width / 2 - p.width / 2;
    left = Math.max(8, Math.min(left, window.innerWidth - p.width - 8));
    popup.style.top = top + "px";
    popup.style.left = left + "px";
  }

  function show(ref) {
    var id = ref.getAttribute("data-fn");
    var def = document.getElementById(id);
    if (!def) return;
    popup.innerHTML = def.innerHTML;
    popup.hidden = false;
    current = ref;
    place(ref);
  }

  function hide() {
    popup.hidden = true;
    current = null;
  }

  function refOf(target) {
    return target && target.closest ? target.closest(".fnref") : null;
  }

  document.addEventListener("mouseover", function (e) {
    if (!hoverCapable) return;
    var ref = refOf(e.target);
    if (ref && ref !== current) show(ref);
  });

  document.addEventListener("mouseout", function (e) {
    if (!hoverCapable) return;
    var ref = refOf(e.target);
    if (ref && ref === current) hide();
  });

  document.addEventListener("click", function (e) {
    var ref = refOf(e.target);
    if (ref) {
      e.preventDefault();
      if (current === ref) {
        if (!hoverCapable) hide();
      } else {
        show(ref);
      }
      return;
    }
    if (!e.target.closest || !e.target.closest(".fn-popup")) hide();
  });

  window.addEventListener(
    "scroll",
    function () {
      if (current) place(current);
    },
    true
  );

  window.addEventListener("resize", function () {
    if (current) place(current);
  });
})();
