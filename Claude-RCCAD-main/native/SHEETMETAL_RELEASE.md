# RCCAD Desktop 0.4.9 — prostsze łączenia równoległe

## Poprawki 0.4.9

- Uproszczone podcięcia narożników w opcji **Równolegle**, zwłaszcza przy wielopoziomowych gięciach z końcowym kołnierzem 45°. Drobne zawijasy i dodatkowe walcowe powierzchnie spoiny zastąpione prostymi podcięciami w przekroju naroża.
- Uproszczenie dotyczy końców kołnierzy. Powierzchnie walcowe blachy zachowują zadane promienie i grubość; proste ścianki zachowują dotychczasowy styk równoległy i luz. Przy samych łukach pozostaje lokalny luz technologiczny.
- Docinanie jest zachowawcze: nie dodaje materiału powodującego kolizje. Testy sprawdzają też kąty ostre i rozwarte, kierunki gięć, rozwinięcie oraz aktualizację starszych projektów z wykonanymi otworami.
- Zachowana rekonstrukcja wcześniejszych wersji narożników pozwala przenieść edycje z projektów 0.4.6–0.4.8 podczas przeliczania blachy.

**Przeliczenie modelu:** zaznacz blachę → **Reguły blach → Równolegle → Zastosuj do zaznaczonej blachy**.

## Poprawki 0.4.8 — narożniki równoległe


- Poprawiona konstrukcja **Równolegle** dla ścian pochylonych i kolejnych poziomów gięć. Koniec ściany jest dopasowany do rzeczywistego obrysu sąsiedniego łańcucha gięć, także na łukach.
- Usunięte nadmiarowe narożne wypustki przy 45° i 135° oraz wybrania i resztkowe fragmenty przy wielokrotnych gięciach 90°. Grubość, promienie, kąty i długości kołnierzy pozostają zapisane według dotychczasowych zasad.
- Szczelina jest odmierzana prostopadle do stykających się powierzchni, również gdy są pochylone lub walcowe. Nie jest wycinana kilkoma przesuniętymi kopiami sąsiednich ścian.
- Wielopoziomowe połączenia równoległe objęte testami tworzą teraz jedno rozwinięcie bez odłączonych drobnych fragmentów.
- Projekty z konstrukcją z wersji 0.4.6/0.4.7 są rozpoznawane przy przeliczaniu, aby odróżnić stare narożniki od wykonanych otworów i zachować obsługiwane edycje przy przejściu na poprawiony model.
- Buforowane są analityczne narzędzia docinania, dzięki czemu jednakowe ściany i kolejne przeliczenia korzystają ze wspólnych wzorców przekroju.

**Istniejący model:** zaznacz blachę → **Reguły blach → Równolegle → Zastosuj do zaznaczonej blachy**. Operację można cofnąć. Nie trzeba zmieniać promienia ani długości gięć.

## Nowe funkcje 0.4.7

- **Rozłóż blachę** tworzy edytowalną płaską bryłę o rzeczywistej grubości. Zapisane promienie, kąty, kierunki i reguły pozostają powiązane z modelem.
- **Zegnij blachę** przywraca poprzedni układ gięć, zachowując wykonane zmiany. Na prostych ścianach można korzystać ze szkiców, wycinania, dodawania materiału i zaokrągleń także w stanie zgiętym.
- **Aktualizuj blachę** sprawdza przenoszenie zmian i przebudowuje bieżący stan bez przełączania płasko/zgięte.
- Wycięcia wykonane na płasko przez całą grubość mogą przechodzić również przez łuk gięcia oraz granicę podstawy, łuku i kołnierza. Kontur jest odwzorowywany na powierzchni walcowej, a nie na siatce podglądu.
- Historia, cofanie, ponawianie i zapis projektu zachowują opis blachy. Dodanie kolejnego kołnierza lub zastosowanie nowych reguł nie usuwa obsługiwanych otworów i innych zmian.
- Rozwinięcie DXF uwzględnia wykonane otwory i zachowuje krzywe cięcia, w tym okręgi. Eksport do lasera wymaga jednej części o jednakowej grubości; linie gięcia pozostają na osobnych warstwach.
- Zawinięcia, rozwinięcia z nakładaniem lub osobnymi fragmentami oraz miejscowe kieszenie/zaokrąglenia zmieniające grubość samego łuku nie są jeszcze obsługiwane. Proste wiercenie w zakrzywionej ścianie może nie odpowiadać wycięciu rozwijanemu przez grubość. W tych przypadkach polecenie zatrzymuje się, zachowując bieżący model i wszystkie wykonane zmiany.

**Użycie:** zaznacz blachę → Rozłóż blachę → zatwierdź edycję zwykłymi narzędziami → Zegnij blachę. Po edycji zgiętej blachy można wybrać Aktualizuj blachę lub ponownie ją rozłożyć.

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
