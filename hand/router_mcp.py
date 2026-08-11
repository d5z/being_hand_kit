
# ── Plan via MCP (Tier 4) ──────────────────────────────────────────────

def route_plan_mcp(goal, steps=None, max_recoveries=3):
    """Plan+execute via MCP protocol (Tier 4). Falls back to PlanningEngine
    (Tier 1) when opencode kit is unavailable. Tier 3 recovery is
    built-in on both paths."""
    from hand.router import route_open, route_see, route_do
    from hand.session import get_session
    from hand.plan.mcp_engine import MCPEngine
    from hand.plan.engine import PlanningEngine
    from hand.plan.recovery import build_recovery_prompt

    session = get_session()
    session.clear_plan_trace()
    trace = session.plan_trace
    recovery_count = 0

    if steps is None:
        mcp = MCPEngine()
        if mcp.kit_path:
            engine_label = 'mcp'
            result = mcp.plan(goal)
        else:
            engine_label = 'cli'
            result = PlanningEngine().plan(goal)
        if not result.ok and not result.steps:
            return {'error': 'planning failed', 'details': result.error}
        steps = [(s.kind, s.action, s.raw) for s in result.steps]
    else:
        engine_label = 'manual'
        mcp = None

    i = 0
    while i < len(steps):
        kind, action, raw = steps[i]
        entry = {'kind': kind, 'action': action, 'raw': raw}
        try:
            if kind == 'open':
                res = route_open(action)
                entry['result'] = res
                trace.append(entry)
            elif kind == 'see':
                res = route_see()
                entry['result'] = res
                trace.append(entry)
            elif kind == 'do':
                res = route_do(action)
                entry['result'] = res
                trace.append(entry)
                see_res = route_see()
                trace.append({'kind': 'see', 'action': '', 'result': see_res})
            elif kind == 'done':
                entry['summary'] = raw.get('summary', '') if raw else ''
                entry['result'] = {'ok': True}
                trace.append(entry)
                break
            elif kind == 'error':
                entry['result'] = {'error': action}
                trace.append(entry)
                break
            else:
                entry['result'] = {'error': 'unknown step kind: ' + kind}
                trace.append(entry)
        except Exception as e:
            entry['result'] = {'error': str(e)}
            trace.append(entry)

        result = entry.get('result', {})
        is_failure = (isinstance(result, dict) and
                      result.get('error') is not None) or \
                     (isinstance(result, dict) and result.get('ok') is False)

        if is_failure and recovery_count < max_recoveries:
            recovery_count += 1
            recovery_prompt = build_recovery_prompt(goal, entry, trace)
            if mcp and mcp.kit_path:
                recovery_result = mcp.plan(recovery_prompt)
            else:
                recovery_result = PlanningEngine().plan(recovery_prompt)
            if recovery_result.ok and recovery_result.steps:
                recovery_steps = [(s.kind, s.action, s.raw)
                                  for s in recovery_result.steps]
                steps = steps[:i+1] + recovery_steps + steps[i+1:]
                trace.append({'kind': 'recovery',
                              'action': 'attempt #' + str(recovery_count),
                              'result': {'ok': True,
                                         'recovery_steps': len(recovery_steps)}})
            else:
                trace.append({'kind': 'recovery',
                              'action': 'attempt #' + str(recovery_count),
                              'result': {'error': 'recovery planning failed',
                                         'details': recovery_result.error}})
                break
        i += 1

    ok = len(trace) > 0 and not any(
        e.get('result', {}).get('error')
        for e in trace if e.get('kind') not in ('recovery', 'done')
    )
    return {'ok': ok, 'engine': engine_label, 'goal': goal,
            'steps': len(trace), 'recoveries': recovery_count, 'trace': trace}
