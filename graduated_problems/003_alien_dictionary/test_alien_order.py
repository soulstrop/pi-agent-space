from alien_order import alien_order


def test_classic_example():
    assert alien_order(["wrt", "wrf", "er", "ett", "rftt"]) == "wertf"


def test_two_letters():
    assert alien_order(["z", "x"]) == "zx"


def test_chained_constraints():
    # "ca" < "cb"  → a < b
    # "cb" < "ab"  → c < a
    # Unique topological order: c < a < b.
    assert alien_order(["ca", "cb", "ab"]) == "cab"


def test_single_letter():
    assert alien_order(["a"]) == "a"


def test_repeated_word():
    assert alien_order(["a", "a"]) == "a"


def test_cycle_returns_empty():
    # "z" < "x" and "x" < "z" implies a cycle.
    assert alien_order(["z", "x", "z"]) == ""


def test_invalid_prefix_returns_empty():
    # "abc" cannot precede its own prefix "ab" in any valid lexicographic order.
    assert alien_order(["abc", "ab"]) == ""
