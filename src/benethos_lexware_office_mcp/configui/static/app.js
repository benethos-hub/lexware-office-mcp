// The configuration interface's one script. Every page works without it:
// it asks before a destructive form is sent, reads a chosen policy file
// into the import field, and keeps the tally of the permissions page. No
// inline handler and no inline data - the content security policy allows
// scripts from this origin only, so what the tally needs is on the boxes.
"use strict";

// <form data-confirm="..."> asks before it is sent, and so does a
// <button data-confirm="..."> for the submit it makes.
document.addEventListener("submit", function (event) {
  var form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
  var button = event.submitter;
  var question = (button && button.dataset.confirm) || form.dataset.confirm;
  if (question && !window.confirm(question)) {
    event.preventDefault();
  }
});

// A chosen policy file goes into the textarea, so reading one is the same
// form post as pasting one.
document.addEventListener("change", function (event) {
  var pick = event.target;
  if (!pick || pick.id !== "policyfile") return;
  var file = pick.files && pick.files[0];
  if (!file) return;
  var reader = new FileReader();
  reader.onload = function () {
    var field = document.querySelector("textarea[name=bundle]");
    if (field) field.value = reader.result;
  };
  reader.readAsText(file);
});

// The tally under the permissions form, and the buttons that tick a group
// or the whole list at once. Each box carries its cost in data-cost, and
// data-read or data-destructive where they apply.
(function () {
  var form = document.getElementById("permform");
  if (!form) return;
  var perToken = parseFloat(form.dataset.perToken) || 3.5;

  function boxes(root) {
    return Array.prototype.slice.call(root.querySelectorAll("input[name=tool]"));
  }
  function de(n) { return n.toLocaleString("de-DE"); }
  function show(id, text) {
    var node = document.getElementById(id);
    if (node) node.textContent = text;
  }
  function refresh() {
    var on = boxes(form).filter(function (c) { return c.checked; });
    var chars = on.reduce(function (sum, c) {
      return sum + (parseInt(c.dataset.cost, 10) || 0);
    }, 0);
    show("count", String(on.length));
    show("cost", de(chars));
    show("tokens", de(Math.round(chars / perToken)));
  }
  function apply(mode, scope) {
    boxes(scope).forEach(function (c) {
      if (mode === "on") c.checked = true;
      else if (mode === "off") c.checked = false;
      else if (mode === "read") c.checked = "read" in c.dataset;
      else if (mode === "reversible") c.checked = !("destructive" in c.dataset);
    });
    refresh();
  }

  document.addEventListener("click", function (event) {
    var target = event.target;
    var button = target && target.closest ? target.closest("button[data-act]") : null;
    if (!button) return;
    event.preventDefault();
    var act = button.getAttribute("data-act");
    var scoped = act.indexOf("grp-") === 0;
    apply(act.replace(/^(all-|grp-)/, ""), scoped ? button.closest("[data-group]") : form);
  });
  form.addEventListener("change", function (event) {
    if (event.target && event.target.name === "tool") refresh();
  });
  refresh();
})();
