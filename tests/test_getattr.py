from asteval import Interpreter

aeval = Interpreter()
res = aeval("getattr('', '__class__')")
print(aeval.error)
