"""The agent loop calls into the Phase 5.6–5.8 modules (sub_agent, turn_limits, visual_qa, visual_qa_rules) and the helpers
it shares with Phase 6 (tool_schemas, tool_partition, system_prompt, image_input, stuck_detector). Those call sites are
checked here against the real definitions: every `module.name` the loop uses exists, and every call passes only parameters
the callee has. Pure AST — it needs no third-party package, so it runs in any environment, and it is the cheap test that
catches "someone renamed a parameter and the loop only breaks on a rarely-taken path" (a browser call, a delegation, an
approval round-trip) that no unit test of the callee would ever see.
"""
import ast
import os

APP = os.path.join(os.path.dirname(__file__), "..", "app", "services")
CALLEES = ("sub_agent", "turn_limits", "visual_qa", "visual_qa_rules", "tool_schemas", "tool_partition", "system_prompt", "image_input", "stuck_detector")


def _tree(name):
    return ast.parse(open(os.path.join(APP, f"{name}.py"), encoding="utf-8").read())


def _definitions(tree):
    defs = {}
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = n.args
            params = [p.arg for p in a.posonlyargs + a.args + a.kwonlyargs]
            defs[n.name] = {"kind": "func", "params": params, "positional": len(a.posonlyargs + a.args), "varargs": a.vararg is not None, "varkw": a.kwarg is not None}
        elif isinstance(n, ast.ClassDef):
            fields = [s.target.id for s in n.body if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)]
            init = next((s for s in n.body if isinstance(s, ast.FunctionDef) and s.name == "__init__"), None)
            if init is not None:
                a = init.args
                fields = [p.arg for p in a.args[1:] + a.kwonlyargs]
            inherits_init = init is None and not fields  # e.g. an Exception subclass: takes whatever its base takes
            defs[n.name] = {"kind": "class", "params": fields, "positional": len(fields), "varargs": inherits_init, "varkw": inherits_init}
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    defs[t.id] = {"kind": "value"}
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            defs[n.target.id] = {"kind": "value"}
    return defs


DEFS = {m: _definitions(_tree(m)) for m in CALLEES}
LOOP = _tree("agent_loop")


def _uses():
    for node in ast.walk(LOOP):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in DEFS:
            yield node


def test_every_name_the_agent_loop_uses_from_those_modules_exists():
    missing = sorted({f"{n.value.id}.{n.attr}" for n in _uses() if n.attr not in DEFS[n.value.id]})
    assert not missing, f"agent_loop.py uses names that don't exist: {missing}"


def test_every_call_the_agent_loop_makes_passes_only_parameters_the_callee_has():
    problems = []
    for node in ast.walk(LOOP):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)):
            continue
        module, name = node.func.value.id, node.func.attr
        spec = DEFS.get(module, {}).get(name)
        if not spec or spec["kind"] == "value":
            continue
        if not spec["varkw"]:
            for kw in node.keywords:
                if kw.arg is not None and kw.arg not in spec["params"]:
                    problems.append(f"{module}.{name}() has no parameter {kw.arg!r} (agent_loop.py:{node.lineno})")
        if not spec["varargs"] and len(node.args) > spec["positional"] and not any(isinstance(a, ast.Starred) for a in node.args):
            problems.append(f"{module}.{name}() takes {spec['positional']} positional argument(s), agent_loop.py:{node.lineno} passes {len(node.args)}")
    assert not problems, problems


def test_the_loop_actually_exercises_each_of_the_new_modules():
    used = {n.value.id for n in _uses()}
    assert {"sub_agent", "turn_limits", "visual_qa", "visual_qa_rules", "tool_schemas", "tool_partition", "image_input"} <= used


def test_the_dynamic_prompt_field_the_loop_sets_exists():
    fields = {s.target.id for n in _tree("system_prompt").body if isinstance(n, ast.ClassDef) and n.name == "DynamicSections" for s in n.body if isinstance(s, ast.AnnAssign)}
    keywords = {kw.arg for node in ast.walk(LOOP) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "DynamicSections" for kw in node.keywords}
    assert "visual_qa" in fields and keywords <= fields, keywords - fields
