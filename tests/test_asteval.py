from asteval import Interpreter

aeval = Interpreter()
res = aeval("1 + 2 * 3")
print(res)
try:
    aeval("import os; os.system('calc')")
except Exception as e:
    print(e)
print(aeval.error)
