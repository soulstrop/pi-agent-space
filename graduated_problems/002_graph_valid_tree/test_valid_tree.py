from valid_tree import is_valid_tree


def test_valid_tree_basic():
    assert is_valid_tree(5, [[0, 1], [0, 2], [0, 3], [1, 4]]) is True


def test_valid_tree_two_nodes():
    assert is_valid_tree(2, [[0, 1]]) is True


def test_valid_tree_single_node():
    assert is_valid_tree(1, []) is True


def test_cycle_rejected():
    assert is_valid_tree(5, [[0, 1], [1, 2], [2, 3], [1, 3], [1, 4]]) is False


def test_triangle_rejected():
    assert is_valid_tree(3, [[0, 1], [1, 2], [0, 2]]) is False


def test_disconnected_rejected():
    assert is_valid_tree(4, [[0, 1], [2, 3]]) is False


def test_missing_node_rejected():
    # n=4 means nodes 0,1,2,3 must all be present; node 3 has no edges.
    assert is_valid_tree(4, [[0, 1], [1, 2]]) is False
