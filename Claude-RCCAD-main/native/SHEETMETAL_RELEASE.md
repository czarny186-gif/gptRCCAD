# RCCAD Desktop 0.4.6 — połączenia równoległe i wybór krawędzi

## Poprawki 0.4.6

- W regułach blach pozostały dwa sposoby łączenia: **Równolegle** i **Blacharskie**. Usunięto osobny przycisk „Skośnie”. Stare projekty z takim zapisem nadal można odtwarzać; panel proponuje dla nich „Blacharskie”.
- Połączenia równoległe działają także na kołnierzach kontynuowanych następnym gięciem. Ścianki dochodzą do powierzchni sąsiada, zamiast automatycznie przechodzić na ukos 45°. Zakończenia łuków i prześwit są dopasowywane do rzeczywistego materiału sąsiednich gięć.
- Podczas konwersji na blachę, dodawania kołnierzy i zawinięć nie jest podświetlana na zielono cała zaznaczona bryła. Wskazanie ściany lub krawędzi pozostaje widoczne. Po zamknięciu narzędzia wraca zwykłe podświetlenie zaznaczonego obiektu.
- Aby przeliczyć istniejący model: zaznacz blachę → **Reguły blach → Równolegle → Zastosuj do zaznaczonej blachy**.
- Nowe testy sprawdzają brak ukośnych powierzchni w wielopoziomowych połączeniach równoległych, styki pochylonych ścian oraz zaznaczanie podczas pracy narzędzia.

## Poprawki 0.4.5

- Usunięta blokada wspólnych narożników dla zwykłych gięć innych niż 90°. Cztery boki podstawy można teraz zagiąć np. o 135° przy włączonym docinaniu narożników.
- Istniejące docinanie przestrzenne łuków i prostych części kołnierzy działa również dla kątów ostrych i rozwartych. Kontrola przenikania materiału pozostaje aktywna.
- Testy obejmują dziesięć kątów od 15° do 165°, rzeczywistą szczelinę narożnika, promienie, grubość, mieszane kąty i budowanie kolejnych kołnierzy krok po kroku. Test uruchamiany przez EXE sprawdza dodatkowo cztery boki po 135°.
- Nie jest to potwierdzenie zgodności każdego narożnika z Fusion 360. Zakrzywione przejścia wprowadzone w 0.4.4 nadal dotyczą gięć 90°; inne kąty korzystają z docinania płaszczyzną. Zawinięcia wymagają wyłączenia docinania wspólnych narożników.

## Poprawki 0.4.4

- Nowe łączenie **Blacharskie**: prostopadłe zakończenia pionowych ścian, symetryczna szczelina i ukośne połączenia sąsiednich poziomych kołnierzy.
- Wycięcia przy gięciach podążają za łukiem od końca poprzedniej ściany do końca następnego kołnierza. Zakrzywione są powierzchnie zakończeń; właściwe powierzchnie gięcia pozostają walcowe i zachowują promień oraz grubość.
- Nowe zakrzywione przejścia są sprawdzone dla gięć 90°, takich jak we wzorcu. Dla pozostałych kątów pozostaje dotychczasowe przycinanie łuków.
- Zakończenia pasujących ścian są dopasowywane również przy różnych wysokościach. Rozchodzące się kołnierze nadal mają proste końce.
- Nowy sposób jest domyślny przy nowej konwersji na blachę. Zapisane wcześniej projekty zachowują swoje reguły. Aby zastosować go w istniejącym projekcie: zaznacz blachę → **Reguły blach → Blacharskie → Zastosuj do zaznaczonej blachy**.
- Reguły odczytują zapisane szczeliny, wycięcia i ustawienia przed ich zmianą. Zmiana typu łączenia nie resetuje tych wartości.
- To zmiana konstrukcji gięć i narożników. Dotychczasowe liczenie długości, umiejscowienie podstawy i gabaryty nie zostały zmienione. Dopasowanie wymiarowania do innych programów pozostaje osobnym zadaniem.

## Poprawki 0.4.3

- Kołnierze rozchodzące się w różne strony nie są już automatycznie przycinane pod 45° tylko dlatego, że wyrastają ze wspólnego narożnika podstawy.
- Gdy części nie przecinają się, końce są prowadzone prosto od rzeczywistej krawędzi poprzedniego gięcia. Dotyczy to również dalszych poziomów przy krótszej sąsiedniej ścianie.
- Wspólny ukos pozostaje przy rzeczywistych połączeniach. Przed zachowaniem prostego zakończenia sprawdzane jest przecięcie materiału.
- Dodane testy: trzy powroty do środka i jeden na zewnątrz, zmiana dowolnej z czterech stron, dalsze odwrócone gięcia oraz sprawdzenie prostopadłych zakończeń.

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
