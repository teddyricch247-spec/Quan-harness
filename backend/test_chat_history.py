"""Plain-script tests for app/chat_history.py (pure helpers, stdlib only).

Run: python test_chat_history.py
"""
from app import chat_history as ch

failures = 0


def check(name, cond):
    global failures
    if cond:
        print(f"ok   {name}")
    else:
        failures += 1
        print(f"FAIL {name}")


# --- parse_session_id ---
good = "3F2504E0-4F89-11D3-9A0C-0305E82C3301"
check("uuid canonicalised to lowercase", ch.parse_session_id(good) == good.lower())
check("non-uuid rejected", ch.parse_session_id("abc") is None)
check("injection-ish id rejected", ch.parse_session_id("x&user_id=neq.1") is None)
check("non-string rejected", ch.parse_session_id(123) is None)

# --- titles ---
check("whitespace-only title is empty", ch.clean_title("  \n\t ") == "")
check("title collapsed to one line", ch.clean_title("a\n\nb   c") == "a b c")
check("title capped", len(ch.clean_title("x" * 500)) == ch.MAX_TITLE_CHARS)
check("non-string title is empty", ch.clean_title(None) == "")
check("auto title falls back", ch.auto_title("   ") == ch.DEFAULT_TITLE)
check("auto title is capped at 60", len(ch.auto_title("word " * 40)) <= ch.AUTO_TITLE_CHARS)

# --- build_model_messages ---
msgs = ch.build_model_messages([], "hi")
check("first turn is just the user message", msgs == [{"role": "user", "content": "hi"}])

stored = [
    {"role": "user", "content": "q1"},
    {"role": "assistant", "content": "a1"},
    {"role": "user", "content": "q2 (failed send, never answered)"},
]
msgs = ch.build_model_messages(stored, "q3")
check("orphaned user message merged with the next one",
      [m["role"] for m in msgs] == ["user", "assistant", "user"]
      and msgs[-1]["content"].endswith("q3") and "q2" in msgs[-1]["content"])

msgs = ch.build_model_messages([{"role": "assistant", "content": "a0"}, {"role": "user", "content": "q"}], "n")
check("never starts with an assistant message", msgs[0]["role"] == "user")

msgs = ch.build_model_messages([{"role": "user", "content": ""}, {"role": "tool", "content": "x"}, None], "n")
check("blank, unknown-role and non-dict rows are skipped", msgs == [{"role": "user", "content": "n"}])

long = []
for i in range(300):
    long.append({"role": "user", "content": f"q{i}"})
    long.append({"role": "assistant", "content": f"a{i}"})
msgs = ch.build_model_messages(long, "latest")
check("message budget enforced", len(msgs) <= ch.HISTORY_MAX_MESSAGES)
check("newest turn always kept", msgs[-1] == {"role": "user", "content": "latest"})
check("newest history kept, oldest dropped", msgs[-2]["content"] == "a299" and all(m["content"] != "q0" for m in msgs))
check("alternation preserved after trimming",
      all(msgs[i]["role"] != msgs[i + 1]["role"] for i in range(len(msgs) - 1)) and msgs[0]["role"] == "user")

big = [{"role": "user", "content": "a" * 300_000}, {"role": "assistant", "content": "b" * 300_000}]
msgs = ch.build_model_messages(big, "c")
check("character budget enforced", sum(len(m["content"]) for m in msgs) <= ch.HISTORY_MAX_CHARS and msgs[-1]["content"] == "c")

huge = "z" * (ch.HISTORY_MAX_CHARS + 10)
msgs = ch.build_model_messages([{"role": "user", "content": "old"}, {"role": "assistant", "content": "reply"}], huge)
check("a single oversized newest message is never dropped", msgs == [{"role": "user", "content": huge}])

# --- SessionGate ---
gate = ch.SessionGate(stale_after=0.05)
check("first acquire succeeds", gate.try_acquire("s1"))
check("second acquire is refused", not gate.try_acquire("s1"))
check("other sessions are independent", gate.try_acquire("s2"))
gate.release("s1")
check("acquire after release succeeds", gate.try_acquire("s1"))
import time
time.sleep(0.06)
check("stale entry is treated as released", gate.try_acquire("s1"))

print()

# --- reasoning effort / thinking cleaning ---
import datetime, json
check("effort None stays None", ch.clean_reasoning_effort(None) is None)
check("effort normalised", ch.clean_reasoning_effort(" Max ") == "max")
for bad in ("off", "medium", "", 3, ["low"]):
    try:
        ch.clean_reasoning_effort(bad); ok = False
    except ValueError:
        ok = True
    check(f"effort {bad!r} rejected", ok)
check("clean_thinking keeps strings, trims, drops junk", ch.clean_thinking([" a ", "", 3, None, "b"]) == ["a", "b"])
check("clean_thinking non-list -> []", ch.clean_thinking(None) == [] and ch.clean_thinking("x") == [])
check("clean_thinking caps entry length", len(ch.clean_thinking(["x" * 5000])[0]) == ch.MAX_THINKING_ENTRY_CHARS)
check("clean_thinking caps count", len(ch.clean_thinking(["t"] * 1000)) == ch.MAX_THINKING_ENTRIES)

# --- GenerationJob ---
T0 = datetime.datetime(2026, 10, 4, 12, 0, 0, tzinfo=datetime.timezone.utc)
def ev(obj): return ("data: " + json.dumps(obj) + "\n\n")
job = ch.GenerationJob("s", "hello", T0, "high")
job.feed(ev({"choices": [{"delta": {"role": "assistant"}}]}))
job.feed(ev({"choices": [{"delta": {"reasoning_content": " Reading the question "}}]}))
job.feed(ev({"choices": [{"delta": {"reasoning_content": "Reading the question"}}]}))
job.feed(ev({"choices": [{"delta": {"reasoning_content": "Planning"}}]}))
job.feed(ev({"choices": [{"delta": {"content": ""}}]}))
job.feed(ev({"choices": [{"delta": {"content": "Hi"}}]}).encode())
job.feed("data: not json\n\n")
job.feed(": comment\n\n")
job.feed("data: [DONE]\n\n")
check("job collects titles, collapsing repeats", job.thinking == ["Reading the question", "Planning"])
check("job collects answer text (bytes ok)", job.text == "Hi")
check("every chunk is queued untouched for the browser", job.queue.qsize() == 9)
check("view shape", job.view()["status"] == "running" and job.view()["content"] == "hello" and job.view()["reasoning_effort"] == "high" and job.view()["error"] is None)
# --- idle fillers are a liveness signal, never a saved step (2026-10-06) ---
jf = ch.GenerationJob("s", "q", T0)
for _t in ("Thinking\n\n", "Reading the question\n\n", "Checking the answer over", "Planning\n\n", "Considering"):
    jf.feed(ev({"choices": [{"delta": {"reasoning_content": _t}}]}))
check("job never records filler words, only real titles", jf.thinking == ["Reading the question", "Planning"])
check("clean_thinking drops filler words (also from rows saved before this fix)", ch.clean_thinking(["Thinking", "Real title here", "Drafting the answer", " Considering "]) == ["Real title here"])
job.saved = True; job.finish()
check("saved + text -> done", job.status == "done")
check("finish queues the end marker", [job.queue.get_nowait() for _ in range(job.queue.qsize())][-1] is None)

j2 = ch.GenerationJob("s", "q", T0)
j2.feed(ev({"error": {"message": "boom", "type": "server_error", "code": "x"}}))
j2.feed(ev({"choices": [{"delta": {"content": "late"}}]}))
j2.saved = True; j2.finish()
check("error frame wins over later chunks / saved", j2.status == "error" and j2.error["message"] == "boom" and j2.error["code"] == "x")
j3 = ch.GenerationJob("s", "q", T0); j3.finish()
check("no text and not saved -> empty_reply", j3.status == "error" and j3.error["code"] == "empty_reply")
j4 = ch.GenerationJob("s", "q", T0); j4.feed(ev({"choices": [{"delta": {"content": "x"}}]})); j4.finish()
check("text but not saved -> not_saved", j4.status == "error" and j4.error["code"] == "not_saved")
check("view of a done job has no error", ch.GenerationJob("s", "q", T0).view()["error"] is None)

# --- GenerationJobs ---
jobs = ch.GenerationJobs()
a = jobs.try_start("s1", "q", T0)
check("first start succeeds", a is not None)
check("second start while running is refused", jobs.try_start("s1", "q2", T0) is None)
check("other sessions independent", jobs.try_start("s2", "q", T0) is not None)
a.fail("x"); a.finish()
check("an errored job can be replaced", jobs.try_start("s1", "q3", T0) is not None)
check("get returns the current job", jobs.get("s1").content == "q3")
cur = jobs.get("s1"); jobs.discard("s1", a)
check("discard of an old job leaves the new one", jobs.get("s1") is cur)
jobs.discard("s1")
check("discard removes", jobs.get("s1") is None)
b = jobs.try_start("s3", "q", T0); b._started_monotonic -= ch.JOB_STALE_SECONDS + 1
check("a stale running job is treated as gone", jobs.get("s3") is None and jobs.try_start("s3", "q", T0) is not None)
c = jobs.try_start("s4", "q", T0); c.fail("x"); c.finish(); c.finished_monotonic -= ch.FAILED_JOB_TTL_SECONDS + 1
check("a failed job expires", jobs.get("s4") is None)

# --- pending_for_display ---
j = ch.GenerationJob("s", "q", T0)
old = {"role": "user", "content": "old", "created_at": "2026-10-04T11:59:00+00:00"}
check("no job -> None", ch.pending_for_display(None, [old]) is None)
check("job with only older history -> pending", ch.pending_for_display(j, [old]) is not None)
check("job hidden once its user row is saved (same instant)", ch.pending_for_display(j, [old, {"role": "user", "content": "q", "created_at": T0.isoformat()}]) is None)
check("handles Z suffix and missing fields", ch.pending_for_display(j, [{"role": "user"}, {"created_at": "2026-10-04T12:00:01Z"}]) is None)
check("handles junk timestamps", ch.pending_for_display(j, [{"created_at": "garbage"}]) is not None)
# --- playground conversation titles (2026-10-06) ---
check("default title says conversation", ch.DEFAULT_TITLE == "New conversation")
check("legacy 'New chat' is a default title", ch.is_default_title("New chat") and ch.is_default_title("  new CHAT "))
check("empty / None is a default title", ch.is_default_title("") and ch.is_default_title(None))
check("a real title is not a default", not ch.is_default_title("Trip plan"))
check("legacy title displays as the new default", ch.display_title("New chat") == "New conversation")
check("real title displays unchanged", ch.display_title("  Trip   plan ") == "Trip plan")
check("auto title skips a leading code fence", ch.auto_title("```python\nprint(1)\n```\nwhy?") == "print(1) why?")
check("auto title joins lines like before", ch.auto_title("  first   question\nwith lines ") == "first question with lines")
check("auto title strips markdown markers", ch.auto_title("# Heading\nbody") == "Heading body" and ch.auto_title("- item") == "item")
long_title = ch.auto_title("word " * 40)
check("long auto title cut at a word with an ellipsis", len(long_title) <= ch.AUTO_TITLE_CHARS and long_title.endswith("\u2026") and "wor\u2026" not in long_title)
check("auto title of non-string is the default", ch.auto_title(None) == ch.DEFAULT_TITLE)

# --- empty conversation detection ---
fresh = {"title": "New conversation", "created_at": "2026-10-06T10:00:00.123+00:00", "last_message_at": "2026-10-06T10:00:00.123+00:00"}
check("untouched row detected", ch.is_untouched(fresh))
check("legacy-titled untouched row detected", ch.is_untouched({**fresh, "title": "New chat"}))
check("titled row is not untouched", not ch.is_untouched({**fresh, "title": "Trip plan"}))
check("row with a later last_message_at is not untouched", not ch.is_untouched({**fresh, "last_message_at": "2026-10-06T10:05:00+00:00"}))
check("row with junk timestamps is not untouched", not ch.is_untouched({**fresh, "created_at": "garbage"}))
check("age is measured from created_at", abs(ch.age_seconds(fresh, ch._parse_ts("2026-10-06T10:01:00+00:00")) - 59.877) < 0.01)

print("ALL CHECKS PASSED" if failures == 0 else f"{failures} FAILED")
raise SystemExit(1 if failures else 0)

