import json

from pi_evaluator.domain.identity import candidate_identity


def _baseline():
    package = {
        "model": "gemini-flash",
        "system_prompt": "You are a coding agent.",
        "skills": ["lint", "format", "test"],
        "template_values": {"language": "python", "style": "pep8"},
    }
    suite = {"suite_id": "coding_v1", "suite_version": "1.0.0"}
    versions = {
        "pi_version": "0.4.2",
        "package_versions": {"lint": "1.0.0", "format": "2.1.0"},
        "eval_suite_version": "1.0.0",
    }
    return package, suite, versions


def test_identical_inputs_hash_equal():
    p, s, v = _baseline()
    assert candidate_identity(p, s, v) == candidate_identity(p, s, v)


def test_reordered_package_keys_hash_equal():
    p, s, v = _baseline()
    p_reordered = {
        "template_values": p["template_values"],
        "skills": p["skills"],
        "system_prompt": p["system_prompt"],
        "model": p["model"],
    }
    assert candidate_identity(p, s, v) == candidate_identity(p_reordered, s, v)


def test_reordered_template_values_hash_equal():
    p, s, v = _baseline()
    p2 = dict(p)
    p2["template_values"] = {"style": "pep8", "language": "python"}
    assert candidate_identity(p, s, v) == candidate_identity(p2, s, v)


def test_reordered_package_versions_hash_equal():
    p, s, v = _baseline()
    v2 = dict(v)
    v2["package_versions"] = {"format": "2.1.0", "lint": "1.0.0"}
    assert candidate_identity(p, s, v) == candidate_identity(p, s, v2)


def test_reordered_skills_hash_equal():
    """Pi's ``--tools`` flag is order-insensitive (verified against
    0.74), so two packages whose only difference is skill ordering
    refer to the same configuration and must hash equal."""
    p, s, v = _baseline()
    p2 = dict(p)
    p2["skills"] = ["test", "format", "lint"]
    assert candidate_identity(p, s, v) == candidate_identity(p2, s, v)


def test_skills_with_different_members_hash_differs():
    p, s, v = _baseline()
    p2 = dict(p)
    p2["skills"] = ["lint", "format"]  # one element removed
    assert candidate_identity(p, s, v) != candidate_identity(p2, s, v)


def test_pretty_printed_dicts_hash_equal():
    """Whitespace / formatting of input JSON cannot affect the hash:
    inputs are dicts, so canonicalization is built in. We verify by
    constructing dicts via different code paths (json.loads of pretty
    JSON) and confirming equality."""
    p, s, v = _baseline()
    pretty = json.dumps(p, indent=4)
    p_reloaded = json.loads(pretty)
    assert candidate_identity(p, s, v) == candidate_identity(p_reloaded, s, v)


def test_different_model_hash_differs():
    p, s, v = _baseline()
    p2 = dict(p)
    p2["model"] = "claude-haiku"
    assert candidate_identity(p, s, v) != candidate_identity(p2, s, v)


def test_different_suite_hash_differs():
    p, s, v = _baseline()
    s2 = {"suite_id": "coding_v2", "suite_version": "1.0.0"}
    assert candidate_identity(p, s, v) != candidate_identity(p, s2, v)


def test_different_pi_version_hash_differs():
    p, s, v = _baseline()
    v2 = dict(v)
    v2["pi_version"] = "0.5.0"
    assert candidate_identity(p, s, v) != candidate_identity(p, s, v2)


def test_envelope_prevents_field_collision():
    """A package-shaped value placed under eval_suite_ref must not
    collide with the same value placed under package."""
    shared = {"k": "v"}
    h1 = candidate_identity(shared, {}, {})
    h2 = candidate_identity({}, shared, {})
    assert h1 != h2


def test_digest_is_64_hex_chars():
    p, s, v = _baseline()
    h = candidate_identity(p, s, v)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)
