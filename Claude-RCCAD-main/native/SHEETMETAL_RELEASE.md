# RCCAD Desktop 0.4.2 — narożniki pudełek z kolejnymi gięciami

## Poprawki 0.4.2

- Narożniki są dopasowywane osobno dla łuku gięcia i prostej części kołnierza. Dalsze poziomy nie są już ucinane do pierwotnej szerokości płyty.
- Usunięte nadmierne przerwy przy kołnierzach do środka i na zewnątrz. Odstęp jest liczony od bieżących powierzchni, a nie promienia pierwszej ściany albo zasięgu całego przyszłego łańcucha.
- Cztery ściany po 5 mm można budować kolejno, dodając dalsze gięcia i odwracając ich kierunek. Przejściowy brak kołnierza na sąsiedniej stronie nie wywołuje fałszywej kolizji.
- Ciągłe ukosy przechodzą przez łuki i poziomy kontynuowane następnym gięciem. Pasujące końcowe odcinki mogą mieć styk równoległy; inne końce są dopasowywane skośnie.
- Nadal odrzucane są rzeczywiste przecięcia materiału i przypadki, w których narożniki usuwają cały swobodny koniec kołnierza.
- W **Regułach blach** przycisk **Zastosuj do zaznaczonej blachy** przelicza istniejącą blachę bez dodawania nowego gięcia. Użyj go również po otwarciu projektu zapisanego w 0.4.1; dobierz wcześniej szczelinę i sposób łączenia. Przeliczenie można cofnąć.

## Dotychczasowe funkcje


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

Rozwinięcie obejmuje prostokątne płyty i niezależne łańcuchy kołnierzy. Nie rozwija docinanych narożników, wycięć narożnych ani zawinięć. Otwory i inne zmiany dodane poza historią blachy blokują eksport, aby nie zniknęły z pliku cięcia. Docinanie narożników w modelu 3D obsługuje sąsiednie pierwsze kołnierze 90°; dalsze gięcia mogą mieć inne kąty. Dla innych kątów pierwszych ścian trzeba wyłączyć docinanie.

Domyślne K=0,44 wymaga sprawdzenia na konkretnym materiale i giętarce. Eksport nie dodaje kompensacji szczeliny lasera; wykonuje ją CAM. Ta wersja nie oferuje pełnego rozwijania dowolnych modeli jak Fusion 360.

## Instalacja Windows

Pobierz `RCCAD-Desktop-Windows-x64.zip`, rozpakuj w całości i uruchom `RCCAD Desktop.exe`. Zachowaj katalog `_internal`. `SHA256.txt` zawiera sumę kontrolną paczki. Wydanie powstaje dopiero po testach źródeł i autotestach gotowego EXE, obejmujących również trzy gięcia i odczyt wyeksportowanego DXF.
