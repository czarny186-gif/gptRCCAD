"""Silnik kół zębatych RCCAD - niezależny od interfejsu, historii i dokumentu.

Ten pakiet nie importuje Qt ani modułów okna RCCAD. Wejście to parametry koła (GearParams albo słownik), wyjście to
wymiary, wyniki sprawdzenia i zarys. Dzięki temu te same algorytmy (ewolwenta, korekcja, luz, obtaczanie) posłużą
później przekładniom planetarnym i zębatkowym.

  params.py   parametry, wymiary pochodne (średnice, podziałki, grubości zęba, podcięcie) i walidacja - czysty Python
  profile.py  zarys zęba: punkty dokładnych krzywych (ewolwenta, trochoida stopy, łuki) - numpy
  occ.py      zarys jako krzywe Open CASCADE (zarys zęba, zarys koła, przekrój czołowy) - import osobno:
              from rccad.gears import occ  (pakiet sam nie wczytuje Open CASCADE)
"""
from .params import (GearParams, Check, KINDS, KIND_TITLES, HANDS, LIMITS, derived, validate, inv, rack_rho,
                     keyway_standard, keyway_size)
from .profile import GearError, ToothProfile, profile, check, outline_points, polygon_area

__all__ = ['GearParams', 'Check', 'KINDS', 'KIND_TITLES', 'HANDS', 'LIMITS', 'derived', 'validate', 'inv', 'rack_rho',
           'keyway_standard', 'keyway_size',
           'GearError', 'ToothProfile', 'profile', 'check', 'outline_points', 'polygon_area']
