from asteval import Interpreter

aeval = Interpreter()

def test(code):
    res = aeval(code)
    err = aeval.error
    if err:
        print(f"[{code}] ERROR:", err)
    else:
        print(f"[{code}] SUCCESS:", res)

test("''.__class__")
test("().__class__.__bases__[0].__subclasses__()")
