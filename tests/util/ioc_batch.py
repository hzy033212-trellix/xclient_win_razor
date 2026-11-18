"""Batched IOC alert tests: every IOC test's trigger fires at the start of the ioc group.

Each IOC test waits for its alert, and Eventor matches events against the IOC feed
only every 60 s (eventor/match_interval), so one test after the other each waits
about one cycle. Instead, the first IOC test that runs fires the triggers of all
the session's IOC tests (``prime``); their events are matched in the same cycle or
two, and the session-wide AlertCollector keeps every alert, so each test then only
looks up its own alert.

Each IOC test module declares its tests as ``IOC_CASES``: test item name (with
parameter id) -> IocCase, holding exactly what the test did before: the IOC
condition, the setup right before the trigger, the Razor trigger, the event keys
it filters on, and the cleanup after its alert is checked. A test whose case was
not primed, or whose primed alert never arrives, triggers on its own as before
(``run_ioc_case``), so batching can't turn a pass into a failure.
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, List

from tests.util import hxsim_ioc

logger = logging.getLogger("tests")


def _nothing(*_args):
    return None


@dataclass
class IocCase:
    cond_key: str                                  # hxsim_ioc.CONDITIONS key
    make_trigger: Callable[[Any], Any]             # setup's result -> Razor trigger
    event_keys: List[str]                          # trigger result keys the alert is filtered on
    setup: Callable[[], Any] = _nothing            # right before the trigger
    cleanup: Callable[[Any], None] = field(default=_nothing)  # setup's result; after the alert is checked
    prime_last: bool = False                       # fired after all others (e.g. it drops the network)


# node id -> primed record; filled once per session by prime()
_primed = {}
_prime_done = False


def _case_of(item):
    return getattr(getattr(item, "module", None), "IOC_CASES", {}).get(item.name)


def prime(items):
    """Set up and fire the trigger of every IOC test in ``items``, a few seconds apart."""
    global _prime_done
    _prime_done = True
    started = time.time()
    cases = [(item, _case_of(item)) for item in items]
    cases = ([c for c in cases if c[1] is not None and not c[1].prime_last]
             + [c for c in cases if c[1] is not None and c[1].prime_last])
    for item, case in cases:
        try:
            state = case.setup()
        except Exception as e:  # the test sets up and triggers on its own
            logger.warning("IOC prime: setup of %s failed (%s); it triggers on its own", item.nodeid, e)
            continue
        try:
            trigger = case.make_trigger(state)
            filters, after = hxsim_ioc.fire_ioc_trigger(item.nodeid, case.cond_key, trigger, case.event_keys)
        except Exception as e:
            logger.warning("IOC prime: trigger of %s failed (%s); it triggers on its own", item.nodeid, e)
            case.cleanup(state)
            continue
        _primed[item.nodeid] = {"state": state, "trigger": trigger, "filters": filters, "after": after,
                                "fired": time.time()}
    logger.info("IOC prime: %d triggers fired in %ds", len(_primed), time.time() - started)


def run_ioc_case(collector, request):
    """The body of every IOC test: check the alert of its primed trigger, or set up
    and trigger on its own (no primed trigger, or its alert never came)."""
    item = request.node
    case = _case_of(item)
    assert case is not None, "No IOC_CASES entry for {}".format(item.name)
    if not _prime_done:
        prime(request.session.items)
    primed = _primed.pop(item.nodeid, None)
    if primed:
        try:
            return hxsim_ioc.verify_ioc_alert(collector, case.cond_key, primed["trigger"], case.event_keys,
                                              primed=primed)
        except AssertionError as e:
            logger.warning("IOC %s: primed alert not found (%s); triggering on its own",
                           item.nodeid, str(e).splitlines()[0])
        finally:
            case.cleanup(primed["state"])
    state = case.setup()
    try:
        return hxsim_ioc.verify_ioc_alert(collector, case.cond_key, case.make_trigger(state), case.event_keys)
    finally:
        case.cleanup(state)
