feat(click): instrument the text= path — same action, same vocabulary

selector= and text= claim the same action but their receipts spoke different
languages: no dispatch{}, no dpr{}, no probe on the text path. The consequence
was not a missing field, it was incomparability -- the triple-fire fixed in
8e96817 could have happened on text= and nothing would have said so, because a
receipt that only says verified: true cannot contradict an execution count.

The text path locates its element by label, so there is no selector to key the
probe on: the node is stashed on window.__handTextEl and the probe attaches
there. Order is the selector path's: install the probe, dispatch one real
mouse click, read the count, escalate at most once and only on evidence that
nothing reached the target, remove the probe. The receipt now carries
dispatch{trusted_clicks,untrusted_clicks,probe,escalation,dispatches} and
dpr/dpr_reads/dispatched{css,physical,dpr_used} under the same names.

Live acceptance (isolated Chrome, real mouse), tests/live/live_text_dispatch.py:
  plain button  handler fires once, trusted=1, escalation=none, dispatches=1
  lying page    elementFromPoint overridden so a cover still eats the click:
                trusted=0 -> one escalation -> handler fires once,
                dispatch{trusted:0, untrusted:1, escalation:"js_click",
                dispatches:2}, and the page's own log keeps the fact that the
                first click landed on the cover.

Also: widening a source window in the new test with an unanchored replace hit
the same slice line inside the 2026-10-26 guard and silently widened it too --
that test went red for the right reason and was restored. Count the occurrences
first.

787 tests, five consecutive green runs. One earlier run was red and I lost the
name to a tail -4; per "one red is an open account" that stays open.
