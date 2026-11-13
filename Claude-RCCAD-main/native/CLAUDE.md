# RCCAD Native — zasady projektu

## Styl interfejsu (obowiązuje każdą nową opcję / panel / narzędzie)
- Ikony są wektorowe (rccad/icons.py, QPainter), w stylu programu: kontur w kolorze atramentu (INK) lub niebieskim, jasnoniebieskie wypełnienie,
  pomarańczowy akcent (czynność / kierunek / kursor), zielony dla odbić i operacji logicznych.
- Nagłówki paneli i kroki kreatora używają SAMYCH grafik, bez kwadratowego tła: `_panel(..., kind='x_...', plain=True)` oraz
  `ui.StepRow(n, 'x_...', 'Tytuł', plain=True)`. Nową ikonę dodaj jako `kind == 'x_nazwa'` w `icons.pixmap` (siatka 48x48).
- Przyciski narzędzi: `ui.style_icon('nazwa')` (ikony t_*), stan aktywny niebieski. Pola wyboru stylu (B/I/AA) to `QPushButton#chip`.
- Kreatory wieloetapowe (powierzchnia → obszar → treść, obiekt → lustro) mają kroki `StepRow` i Enter zatwierdza.
- Ciężkie operacje wykonuj w tle (run_operation / run_preview); przeciąganie myszą ma przekształcać istniejący podgląd macierzą, bez przeliczania geometrii.
- Wersja v0.4.0-29 była uznana za bazową; zmiany wprowadzaj tylko tam, gdzie prosi użytkownik.

## Zakładki paska narzędzi
- Narzędzia górnego paska są pogrupowane w zakładki: `TABS` w `rccad/studio.py` (Szkic, Bryła, Edycja, Wzory, Pomiary, Rysunek). Nową funkcję dopisz do pasującej zakładki
  (kolejność w liście = kolejność przycisków); zakładkę z pasującym trybem program przełącza sam (`TAB_OF`). Przycisk Plik stoi poza zakładkami.
- Nowe narzędzie: ikona `t_nazwa` (+ `_w`), wpis w `_build_overlays` (lista ikon), tryb w `set_mode`/`view_clicked`, panel dopisany do `self.panels`, wpis w Pomocy i test.
- Przesuń / obróć, siatka i historia są w dolnym pasku (`self.pad`), nie w zakładkach.
- Zakładka Sklejka: geometria w `rccad/plywood.py`, okno w `rccad/plywood_ui.py` (mixin `PlywoodTools`), kroki historii `run_ply_*` w `rccad/history.py`.
- Przybornik / Ulubione bierze narzędzia automatycznie z `TABS` (`FAVORITE_TOOLS`); wyjątki tylko w `FAVORITE_EXCLUDED`. Nowe narzędzie dopisz do `TABS` i sprawdź, czy da się je dodać do Ulubionych (test w test_studio).
