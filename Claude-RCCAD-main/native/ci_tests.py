"""Run the complete native suite and expose failure tracebacks in Actions annotations."""
import sys
import unittest


def main():
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover('tests'))
    if not result.wasSuccessful():
        for test,trace in [*result.failures,*result.errors]:
            message=(test.id()+'\n'+trace)[-12000:]
            message=message.replace('%','%25').replace('\r','%0D').replace('\n','%0A')
            print('::error title=Native test failure::'+message,flush=True)
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':sys.exit(main())
