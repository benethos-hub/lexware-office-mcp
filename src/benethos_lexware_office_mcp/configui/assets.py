"""The stylesheet and the two scripts the pages carry inline.

Strings rather than files, for the reason :mod:`.render` gives: nothing to
serve, nothing to cache, nothing to go stale. The pages send them with every
response, which for a local page opened for a few minutes costs nothing.
"""

from __future__ import annotations

import json

from .cost import CHARS_PER_TOKEN

__all__ = ["CSS", "FILE_PICKER_SCRIPT", "permissions_script"]

CSS = """
  :root { color-scheme: light; }
  body { font-family: system-ui, sans-serif; max-width: 900px; margin: 1.5rem auto;
         padding: 0 1rem; line-height: 1.5; color: #1a1a1a; background: #fff; }
  nav { margin-bottom: 1.2rem; padding-bottom: .6rem; border-bottom: 1px solid #ddd;
        display: flex; align-items: center; gap: .8rem; flex-wrap: wrap; }
  nav a { text-decoration: none; color: #1a4d99; }
  nav a.here { font-weight: 700; color: #1a1a1a; }
  h1 { font-size: 1.5rem; }
  h2 { font-size: 1.15rem; margin-top: 2rem; }
  .chip { margin-left: auto; background: #eef4ff; color: #1a4d99;
          border: 1px solid #cddcff; border-radius: 999px;
          padding: .1rem .7rem; font-size: .85rem; font-weight: 600; }
  label.fld { display: block; margin-top: 1rem; font-weight: 600; }
  input[type=text], input[type=password], select, textarea {
          width: 100%; padding: .45rem; box-sizing: border-box; font-size: 1rem;
          font-family: inherit; }
  textarea { font-family: ui-monospace, Consolas, monospace; font-size: .85rem; }
  .hint { color: #555; font-size: .9rem; }
  .ok { color: #1a7f37; } .err { color: #b3261e; }
  code { background: #f0f0f0; padding: .1rem .3rem; border-radius: 3px;
         font-size: .92em; }
  button { padding: .45rem 1rem; font-size: 1rem; cursor: pointer; }
  table { border-collapse: collapse; width: 100%; margin: .6rem 0; }
  th, td { text-align: left; padding: .3rem .5rem; border-bottom: 1px solid #eee;
           vertical-align: top; }
  th { font-size: .8rem; text-transform: uppercase; letter-spacing: .04em;
       color: #555; }
  td.num { text-align: right; font-variant-numeric: tabular-nums;
           white-space: nowrap; color: #555; }
  .grp { border: 1px solid #e0e0e0; border-radius: 6px; margin: .8rem 0;
         padding: .4rem .8rem; }
  .grp h3 { margin: .4rem 0; font-size: 1rem; display: flex;
            justify-content: space-between; align-items: center; gap: .6rem;
            flex-wrap: wrap; }
  details.grp > summary { font-size: 1rem; font-weight: 700; cursor: pointer;
            padding: .3rem 0; }
  details.grp > summary .count { font-weight: 400; color: #666;
            font-size: .85rem; }
  .grp .acts button { font-size: .78rem; padding: .15rem .5rem; }
  .tool { display: flex; align-items: center; gap: .5rem; padding: .15rem 0; }
  .tool .cost { margin-left: auto; font-size: .78rem; color: #666;
                font-variant-numeric: tabular-nums; white-space: nowrap; }
  .tag { font-size: .72rem; padding: .05rem .4rem; border-radius: 3px;
         white-space: nowrap; }
  .tag.read { background: #e7f0ff; color: #1a4d99; }
  .tag.write { background: #fff0e0; color: #9a5a00; }
  .tag.del { background: #fde0e0; color: #a11; }
  .tag.keep { background: #f0ecff; color: #4b3a99; }
  .bar { position: sticky; bottom: 0; background: #fff; padding: .6rem 0;
         border-top: 1px solid #ddd; display: flex; align-items: center;
         gap: 1rem; flex-wrap: wrap; }
  .src { font-size: .75rem; color: #555; background: #f0f0f0;
         border-radius: 3px; padding: .05rem .4rem; margin-left: .4rem; }
  .src.env { background: #fff0e0; color: #9a5a00; font-weight: 600; }
  .note { border-left: 3px solid #9a5a00; background: #fffaf3;
          padding: .6rem .8rem; margin: .8rem 0; }
  .note.good { border-color: #1a7f37; background: #f4fbf5; }
  .note.bad { border-color: #b3261e; background: #fff5f5; }
  .row { display: flex; gap: .6rem; align-items: flex-end; flex-wrap: wrap; }
  .row > * { flex: 0 0 auto; }
  .row .grow { flex: 1 1 12rem; }
"""


# --- the two scripts -----------------------------------------------------
#
# Plain strings rather than f-strings, so a brace is a brace. What a script
# needs from the page arrives as one JSON object in front of it.

# The tally under the permissions form, and the buttons that tick a group
# or the whole list at once. Reads `PERMISSIONS`: the cost of every tool,
# the names of the reading ones, the names of the destructive ones, and
# the characters-per-token estimate.
_PERMISSIONS_JS = """
(function () {
  var COST = PERMISSIONS.cost;
  var READ = PERMISSIONS.read;
  var DESTRUCTIVE = PERMISSIONS.destructive;
  var PER_TOKEN = PERMISSIONS.perToken;
  var form = document.getElementById('permform');
  function boxes(root) {
    return Array.prototype.slice.call(
      (root || form).querySelectorAll('input[name=tool]'));
  }
  function de(n) { return n.toLocaleString('de-DE'); }
  function refresh() {
    var on = boxes(form).filter(function (c) { return c.checked; });
    var chars = on.reduce(
      function (sum, c) { return sum + (COST[c.value] || 0); }, 0);
    document.getElementById('count').textContent = on.length;
    document.getElementById('cost').textContent = de(chars);
    document.getElementById('tokens').textContent = de(Math.round(chars / PER_TOKEN));
  }
  function apply(mode, scope) {
    boxes(scope).forEach(function (c) {
      if (mode === 'on') c.checked = true;
      else if (mode === 'off') c.checked = false;
      else if (mode === 'read') c.checked = READ.indexOf(c.value) !== -1;
      else if (mode === 'reversible') c.checked = DESTRUCTIVE.indexOf(c.value) === -1;
    });
    refresh();
  }
  document.addEventListener('click', function (e) {
    var b = e.target && e.target.closest ? e.target.closest('button[data-act]') : null;
    if (!b) return;
    e.preventDefault();
    var act = b.getAttribute('data-act');
    var scoped = act.indexOf('grp-') === 0;
    apply(act.replace(/^(all-|grp-)/, ''), scoped ? b.closest('.grp') : form);
  });
  document.addEventListener('change', function (e) {
    if (e.target && e.target.name === 'tool') refresh();
  });
  refresh();
})();
"""

# A chosen policy file goes into the textarea, so reading one is the same
# form post as pasting one.
FILE_PICKER_SCRIPT = """<script>
(function () {
  var pick = document.getElementById('policyfile');
  if (!pick) return;
  pick.addEventListener('change', function () {
    var file = pick.files && pick.files[0];
    if (!file) return;
    var reader = new FileReader();
    reader.onload = function () {
      document.querySelector('textarea[name=bundle]').value = reader.result;
    };
    reader.readAsText(file);
  });
})();
</script>"""


def permissions_script(
    costs: dict[str, int], read: list[str], destructive: list[str]
) -> str:
    """The permissions form's script, with what it needs in front of it."""
    data = {
        "cost": costs,
        "read": read,
        "destructive": destructive,
        "perToken": CHARS_PER_TOKEN,
    }
    return (
        "<script>\nvar PERMISSIONS = "
        + json.dumps(data, separators=(",", ":"))
        + ";"
        + _PERMISSIONS_JS
        + "</script>"
    )
