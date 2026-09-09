from src.calculator import calculate

assert calculate("add", 2, 3) == 5
assert calculate("subtract", 7, 2) == 5
assert calculate("multiply", 4, 3) == 12
assert calculate("divide", 8, 2) == 4
try:
    calculate("divide", 1, 0)
except ValueError as exc:
    assert str(exc) == "division by zero"
else:
    raise AssertionError("division by zero must fail")
print("smoke PASS")
