"""Compatibility entry point; implementation lives in bank_governance."""
import sys
from bank_governance import steward as _implementation

if __name__ == '__main__':
    raise SystemExit(_implementation.main())
else:
    sys.modules[__name__] = _implementation
