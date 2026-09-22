"""Visual state marker — hand 0.9 S2 (docs/prd-0.9-receipt-honesty.md).

Epoch's failure analysis: ~35% of failures come from a *visual* state that no DOM
assertion names — the page is loading, showing a spinner/error page, or is
simply blank, and a text/structure assertion cannot tell "the user is looking at
a finished page" from "the user is looking at a skeleton".

This module adds a DOM-side heuristic (NO screenshot) that classifies the page
into one of five states and records the *signals* that decided it:

    loading     a visible loading indicator (spinner / skeleton / progressbar
                / [aria-busy=true] / document.readyState != complete)
    error       an error page (h1/h2/title hits the error word list, or a
                visible <img alt> names an error)
    blank       no visible text (< BLANK_TEXT_THRESHOLD chars) and no visible
                img/canvas/video
    interactive normal, interactive content
    unknown     the probe could not observe the page (no <body> / evaluation
                failed) — honest: we do not guess

Priority: error > loading > blank > interactive (PRD). `unknown` is reserved for
"no signal", never a guess between the four real states.

The marker format is the deliverable; the mapping to the py v2.1 before/after
repair states is data-gated (PRD S2.4) and comes later.
"""

import json

VISUAL_STATES = ("loading", "error", "blank", "interactive", "unknown")

# A page whose visible text is shorter than this and has no img/canvas/video is
# "blank". 20 chars is deliberately small: a real page almost always has more.
BLANK_TEXT_THRESHOLD = 20

# Words that, in the document title or an h1/h2, mean "this is an error page".
ERROR_WORDS = (
    "error", "404", "500", "not found", "page not found",
    "something went wrong", "access denied", "forbidden",
    "bad gateway", "service unavailable",
    "错误", "失败", "出错", "页面不存在", "找不到", "无法访问", "服务异常",
)

# DOM-only probe. Returns a JSON string of raw signals; classification happens
# in Python so the priority rules are unit-testable without a browser.
VISUAL_STATE_JS = r"""(function(){
function vis(el){
  if(!el||!el.getBoundingClientRect)return false;
  var r=el.getBoundingClientRect();
  if(r.width<=0||r.height<=0)return false;
  var s=window.getComputedStyle?window.getComputedStyle(el):null;
  if(s&&(s.visibility==='hidden'||s.display==='none'||s.opacity==='0'))return false;
  return true;
}
var body=document.body;
var out={body:!!body,ready_state:document.readyState,aria_busy:false,
         spinner:false,error_heading:null,error_img:false,text_len:0,has_media:false};
if(!body)return JSON.stringify(out);
var t=(body.innerText||body.textContent||'').replace(/\s+/g,' ').trim();
out.text_len=t.length;
var media=document.querySelectorAll('img,canvas,video');
for(var i=0;i<media.length;i++){if(vis(media[i])){out.has_media=true;break;}}
var busy=document.querySelectorAll('[aria-busy="true"]');
for(var j=0;j<busy.length;j++){if(vis(busy[j])){out.aria_busy=true;break;}}
var spin=document.querySelectorAll('[class*="spinner" i],[class*="loading" i],[class*="skeleton" i],[role="progressbar"]');
for(var k=0;k<spin.length;k++){if(vis(spin[k])){out.spinner=true;break;}}
var words=['error','404','500','not found','page not found','something went wrong','access denied','forbidden','bad gateway','service unavailable','错误','失败','出错','页面不存在','找不到','无法访问','服务异常'];
var head='';
var hs=document.querySelectorAll('h1,h2');
for(var m=0;m<hs.length;m++){head+=' '+((hs[m].innerText||hs[m].textContent||''));}
head=(' '+document.title+' '+head).toLowerCase();
for(var n=0;n<words.length;n++){if(head.indexOf(words[n])!==-1){out.error_heading=words[n];break;}}
var imgs=document.querySelectorAll('img[alt]');
for(var p=0;p<imgs.length;p++){var alt=(imgs[p].getAttribute('alt')||'').toLowerCase();
if(vis(imgs[p])&&(alt.indexOf('error')!==-1||alt.indexOf('错误')!==-1)){out.error_img=true;break;}}
return JSON.stringify(out);
})()"""


PROBE_MSG_ID = 88


def classify(signals):
    """(state, signals) from a raw signal dict. Pure — no browser.

    signals keys: body, ready_state, aria_busy, spinner, error_heading,
    error_img, text_len, has_media. Any missing/false means "not observed".
    """
    if not isinstance(signals, dict) or signals.get("body") is not True:
        return "unknown", ["no-body"]

    # priority: error > loading > blank > interactive
    if signals.get("error_heading"):
        return "error", ["error-heading:%s" % signals["error_heading"]]
    if signals.get("error_img"):
        return "error", ["error-img"]

    ready = signals.get("ready_state")
    if ready and ready != "complete":
        return "loading", ["readyState:%s" % ready]
    if signals.get("aria_busy"):
        return "loading", ["aria-busy"]
    if signals.get("spinner"):
        return "loading", ["spinner-class"]

    try:
        text_len = int(signals.get("text_len") or 0)
    except (TypeError, ValueError):
        text_len = 0
    if text_len < BLANK_TEXT_THRESHOLD and not signals.get("has_media"):
        return "blank", ["empty-text", "no-media"]

    found = ["content"]
    if signals.get("has_media"):
        found.append("has-media")
    return "interactive", found


def parse_probe(value):
    """The probe's JSON string -> signal dict | None (never raises)."""
    if not isinstance(value, str):
        return None
    try:
        data = json.loads(value)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def probe(ws, call=None):
    """Run the DOM probe over a live CDP socket. Never raises.

    Returns {"visual_state": <enum>, "visual_signals": [<str>...]}.
    `call` defaults to hand.perception.cdp_core.cdp_call (lazy import: keeps this
    module importable from cdp_core without a cycle).
    """
    if call is None:
        from hand.perception.cdp_core import cdp_call as call
    try:
        raw = call(ws, "Runtime.evaluate",
                   {"expression": VISUAL_STATE_JS, "returnByValue": True},
                   msg_id=PROBE_MSG_ID, timeout=5)
        value = ((raw or {}).get("result") or {}).get("value")
        signals = parse_probe(value)
    except Exception:
        signals = None
    if signals is None:
        return {"visual_state": "unknown", "visual_signals": ["probe-failed"]}
    state, found = classify(signals)
    return {"visual_state": state, "visual_signals": found}
