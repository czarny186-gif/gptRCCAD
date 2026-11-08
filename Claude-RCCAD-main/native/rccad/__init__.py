"""RCCAD Desktop: native Qt interface and OpenCascade solid modelling."""
__version__ = "0.4.65"
try:
    from ._build import BUILD, BUILD_DATE      # zapisywane przez stamp_build.py w CI
except ImportError:
    BUILD, BUILD_DATE = 0, ''
FULL_VERSION = f'{__version__}-{BUILD}' if BUILD else __version__
CREATED = '27.10.2026'      # początek projektu
AUTHOR = 'Radosław Czarnota'
