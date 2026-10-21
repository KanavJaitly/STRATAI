"""Ad hoc (not a test file): run two P10-R1 regression tests against the pre-fix code paths."""
import inspect, textwrap, threading
import api.body_limit as bl
import api.dependencies as deps
import tests.test_phase10_hardening as t

src = inspect.getsource(bl.BodySizeLimitMiddleware.__call__)
old = src.replace("""        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            # A route that reads its own body (the manual upload's `await request.body()`) sees the simulated
            # disconnect as ClientDisconnect and raises. When that is our overflow, it is a 413, not a 500 (review
            # P10-R1).
            if not (too_large and not started):
                raise
""", """        await self.app(scope, limited_receive, guarded_send)
""")
assert old != src
ns = dict(vars(bl)); exec(textwrap.dedent(old), ns)
bl.BodySizeLimitMiddleware.__call__ = ns["__call__"]
try:
    import traceback
    t.test_a_chunked_oversized_body_read_by_the_route_itself_is_a_413_not_a_500()
    print("body limit: PASSED against pre-fix (unexpected)")
except AssertionError as e:
    print("body limit: FAILS against pre-fix as expected:", (repr(e)[:120]))

def old_get(request):  # the pre-review backoff: checked outside the lock only
    import time
    state = request.app.state
    if state.epa_source is None:
        f = state.epa_source_failed_at
        if f is not None and time.monotonic() - f < state.settings.epa_source_retry_seconds:
            return None
        with state.epa_source_lock:
            if state.epa_source is None:
                state.epa_source = deps.load_epa_source(state.settings, state.database)
                state.epa_source_failed_at = None if state.epa_source is not None else time.monotonic()
    return state.epa_source
class MP:
    def setattr(self, obj, name, value): setattr(obj, name, value)
deps.get_epa_source = old_get
try:
    t.test_a_burst_queued_behind_one_failing_load_does_not_retry_it_one_by_one(MP())
    print("epa burst: PASSED against pre-fix (unexpected)")
except AssertionError as e:
    print("epa burst: FAILS against pre-fix as expected:", (repr(e)[:120]))
