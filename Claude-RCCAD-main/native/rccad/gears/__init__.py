"""Silnik kół zębatych RCCAD - niezależny od interfejsu, historii i dokumentu.

Ten pakiet nie importuje Qt ani modułów okna RCCAD. Wejście to parametry koła (GearParams albo słownik), wyjście to
wymiary i wyniki sprawdzenia, a w kolejnych etapach także zarys i bryła Open CASCADE. Dzięki temu te same algorytmy
(ewolwenta, korekcja, luz) posłużą później przekładniom planetarnym i zębatkowym.

Etap 1: parametry, wymiary pochodne i walidacja (params.py)."""
from .params import (GearParams, Check, KINDS, KIND_TITLES, HANDS, LIMITS, derived, validate, inv)

__all__ = ['GearParams', 'Check', 'KINDS', 'KIND_TITLES', 'HANDS', 'LIMITS', 'derived', 'validate', 'inv']
