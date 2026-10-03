/* Client-side language switch. Both languages are embedded in each page;
   this swaps which one is shown and updates dir/title. No navigation. */
(function () {
  var html = document.documentElement;

  function apply(lang) {
    html.setAttribute("data-ui-lang", lang);
    html.setAttribute("lang", lang);
    html.setAttribute("dir", lang === "fa" ? "rtl" : "ltr");
    var tf = html.getAttribute("data-title-fa");
    var te = html.getAttribute("data-title-en");
    if (lang === "fa" && tf) document.title = tf;
    else if (lang === "en" && te) document.title = te;
  }

  window.applyLang = apply;

  var btn = document.getElementById("lang-switch");
  if (btn) {
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      var cur = html.getAttribute("data-ui-lang") === "en" ? "fa" : "en";
      apply(cur);
    });
  }
})();
