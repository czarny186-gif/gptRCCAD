# RCCAD Desktop 0.4.1 — blachy

## Zmiany

- Naprawiony wybór końca kołnierza przy wymiarze zewnętrznym. Każde gięcie zachowuje własny sposób wymiarowania.
- Odwracanie kierunku gięcia, kolejne gięcia na końcach kołnierzy, różne kąty i kierunki.
- Odrzucanie podwójnego gięcia tego samego końca, błędnych zależności i nakładania materiału w niezależnych łańcuchach.
- Przebudowa przez grupowanie operacji Boolean zamiast osobnego łączenia każdej bryły.
- Rozwinięcie DXF 1:1 w mm: zamknięty kontur `CUT`, osobne warstwy `BEND_UP`/`BEND_DOWN`, współczynnik K i naddatek gięcia `BA = kąt(rad) × (R + K × t)`.
- Eksport działa w tle i zapisuje atomowo; błąd nie zastępuje istniejącego pliku.

## Użycie

1. Wyciągnij prostokątny szkic na grubość blachy. W zakładce **Blacha** wybierz **Konwertuj na blachę** i płaską ścianę.
2. W **Regułach blach** ustaw K dla materiału. Dla rozwinięcia wielu boków wyłącz **Docinaj i przedłużaj narożniki**, a wycięcie narożne ustaw na **Brak**, zanim dodasz kołnierze.
3. Dodawaj **Kołnierze**; na końcu kołnierza można dodać kolejne gięcie. Ustaw kąt, promień, długość i ewentualnie **Odwróć kierunek gięcia**.
4. Zaznacz jedną blachę w drzewie obiektów i wybierz **Rozwinięcie DXF**. W CAM tnij tylko warstwę `CUT`. Warstwy gięcia nie są przeznaczone do cięcia.

## Ograniczenia tej wersji

Rozwinięcie obejmuje prostokątne płyty i niezależne łańcuchy kołnierzy. Nie rozwija docinanych narożników, wycięć narożnych ani zawinięć. Otwory i inne zmiany dodane poza historią blachy blokują eksport, aby nie zniknęły z pliku cięcia. Docinanie narożników w modelu 3D obsługuje sąsiednie kołnierze 90°; dla innych kątów trzeba je wyłączyć. Wspólne przejścia narożników nie mają pełnej analizy kolizji materiału.

Domyślne K=0,44 wymaga sprawdzenia na konkretnym materiale i giętarce. Eksport nie dodaje kompensacji szczeliny lasera; wykonuje ją CAM. Ta wersja nie oferuje pełnego rozwijania dowolnych modeli jak Fusion 360.

## Instalacja Windows

Pobierz `RCCAD-Desktop-Windows-x64.zip`, rozpakuj w całości i uruchom `RCCAD Desktop.exe`. Zachowaj katalog `_internal`. `SHA256.txt` zawiera sumę kontrolną paczki. Wydanie powstaje dopiero po testach źródeł i autotestach gotowego EXE, obejmujących również trzy gięcia i odczyt wyeksportowanego DXF.
