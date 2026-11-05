# RCCAD Desktop 0.4.23 — porządki w zakładkach i nowe ikony blachy

## Zmiany 0.4.23

- **Dopasowanie i Wyrównanie** przeniesione z zakładki Bryła do zakładki **Edycja**.
- **Nowe ikony w zakładce Blacha** (na przyciskach i w nagłówkach okienek):
  - Konwertuj na blachę - klocek zamieniający się w cienką blachę z gięciem,
  - Reguły blach - narożnik pudełka ze szczeliną i wycięciem oraz zębatka ustawień (zamiast „linijki”),
  - Zawinięcie - koniec blachy zawinięty o 180° nad siebie ze strzałką wokół zagięcia.

## Zmiany 0.4.22

- **Bryła → Dopasowanie:** animowane strzałki „w lewo 45°” i „w prawo 45°” obracają przesuwaną bryłę co 45° wokół osi prostopadłej do ścian, przez ich wspólny środek - ściany dalej przylegają, a środki się pokrywają. Bieżący kąt widać między strzałkami, podgląd odświeża się od razu, a kąt zapisuje się w historii.

## Zmiany 0.4.21

- **Bryła → Dopasowanie:** kliknij ścianę bryły do przesunięcia, potem ścianę drugiej bryły. Pierwsza bryła obraca się i przesuwa tak, że jej ściana przylega do ściany docelowej, a środki obu ścian się spotykają.
- **Bryła → Wyrównanie:** kliknij ścianę bryły do przesunięcia, potem ścianę wzorcową. Cała pierwsza bryła przesuwa się bez obracania wzdłuż kierunku ściany wzorcowej, aż obie ściany leżą na tej samej wysokości - w każdej płaszczyźnie.
- Oba narzędzia mają podgląd nowego położenia, zatwierdza się je Zastosuj albo Enter, trafiają do historii (cofanie, ponowne przeliczanie po zmianie wcześniejszych kroków).

## Zmiany 0.4.20

- **Blacha → Kołnierz → Długość mierzona od strony:** zostały dwie opcje (zamiast czterech z 0.4.19):
  - **Zewnętrzna** (domyślna) - długość od wierzchołka kołnierza do zewnętrznej strony blachy; gdy na końcu kołnierza jest kolejne gięcie - od zewnętrznej do zewnętrznej strony. Przykład: blacha 1 mm, 5 mm: w środku 4 mm, między dwoma gięciami 3 mm.
  - **Wewnętrzna** - od wierzchołka do wewnętrznej strony, przy kolejnym gięciu od wewnętrznej do wewnętrznej. Przykład: 5 mm, z grubością 6 mm, przy dwóch gięciach 7 mm.
- **Płyta też:** wymiar płyty jest wymiarem zewnętrznym albo wewnętrznym gotowej blachy - np. pudełko z płyty 100 × 50 mm z wymiarami zewnętrznymi ma na zewnątrz dokładnie 100 × 50 mm.
- **Kąty:** dla kąta prostego i ostrego między ściankami wymiar sięga do przecięcia przedłużonych powierzchni, dla rozwartego - do środka łuku gięcia, zawsze wzdłuż kołnierza.
- Dołożenie gięcia na końcu kołnierza nie wydłuża go: jego wymiar obejmuje już nowe gięcie.
- Starsze projekty (także z 0.4.19) zachowują swoje wymiary.

## Zmiany 0.4.19

- **Blacha → Kołnierz → Długość mierzona od:** cztery sposoby interpretacji długości kołnierza, zapisywane osobno dla każdego gięcia:
  - **Prosta** - sam prosty odcinek za łukiem (jak dotychczas),
  - **Powierzchnie zewnętrzne** - od przecięcia zewnętrznych powierzchni kołnierza bazowego i nowego kołnierza; prosta część = L − (R + t)·tg(α/2),
  - **Powierzchnie wewnętrzne** - od przecięcia powierzchni wewnętrznych; L − R·tg(α/2),
  - **Styczna do zagięcia** - od linii stycznej do zewnętrznej strony zagięcia, prostopadłej do nowego kołnierza; L − (R + t) dla α ≥ 90°.
- Dotychczasowa opcja „Długość kołnierza jako wymiar zewnętrzny” (Reguły blach) odpowiada Powierzchniom zewnętrznym; starsze projekty zachowują swoje wymiary.

## Zmiany 0.4.18

- **Wymiary linii gięcia na każdym rysunku blachy:** łańcuch wymiarów od zewnętrznych krawędzi blachy przez wszystkie linie gięcia (krawędź - gięcie - gięcie - ... - krawędź) w obu kierunkach - w Rysunku blachy do gięcia oraz w zwykłym Utwórz rysunek / Rysunek automatyczny rozłożonej blachy. Opcja „Wymiary linii gięcia” w oknie rysunku. Krótkie wartości na końcach łańcucha stoją za krawędzią, żeby się nie nakładały.
- **Szkic:** przyciąganie (z tym samym opóźnieniem) i znacznik działają już przed pierwszym kliknięciem - widać, w którym punkcie zacznie się kształt.

## Zmiany 0.4.17

- **Rysunek rozłożonej blachy:** widok izometryczny pokazuje blachę zgiętą, a rzuty (z góry, z przodu, z boku) nadal rozwinięcie z liniami gięcia. Dotyczy Utwórz rysunek, Rysunek automatyczny i Rysunek blachy do gięcia (tam widok izometryczny można dołączyć).
- **Szkic na ściance:** główny krzyż osi w tle jest ukryty, widać tylko krzyż ścianki; wraca po wyjściu ze szkicu.

## Zmiany 0.4.16

- **Rysunek → Rysunek blachy do gięcia:** kliknij blachę (zgiętą albo rozłożoną). Powstaje rozwinięcie widziane od góry blachy z wymiarami całości, łańcuchem wymiarów od krawędzi do linii gięcia i między liniami gięcia, opisem każdego gięcia (GÓRA / DÓŁ, kąt, promień), średnicami otworów oraz grubością, promieniem gięcia, współczynnikiem K i rozmiarem rozwinięcia.
- **Kierunek linii gięcia:** ściana wybrana przy „Konwertuj na blachę” jest zawsze górą blachy. Wcześniej przy niektórych proporcjach płyty górą stawał się spód, przez co rozwinięcie leżało odwrócone, a linie gięcia w górę były przerywane. Blachy zamienione we wcześniejszych wersjach zachowują zapisany układ — w razie potrzeby zamień płytę na blachę ponownie.
- **Linie gięcia na rysunku** można wymiarować (Wymiaruj, Odległość) i mierzyć (Mierz) jak krawędzie.
- **Szybsze dodawanie gięć:** cięcia narożników, które się nie zmieniają, nie są liczone ponownie (np. pudełko z czterema ściankami i zagięciami: łącznie ok. 1/3 krócej).

## Zmiany 0.4.15

- **Przyciąganie w szkicu z opóźnieniem:** kursor w ruchu nie klei się do niczego; gdy zatrzymasz go na chwilę (ok. 0,25 s) przy punkcie, przyciąga się do narożnika kratki siatki, punktu lub środka szkicu, krawędzi, okręgu, przecięcia albo do krawędzi i narożnika ścianki, na której rysujesz. Drobne drżenie ręki nie gubi złapanego punktu. Alt wyłącza przyciąganie.
- **Płynny kursor:** wyszukiwanie punktów przyciągania jest ok. 1000 razy szybsze (np. 40 kształtów w szkicu: z ok. 380 ms do poniżej 1 ms na ruch myszy).
- **Krzyż osi na ściance:** szkic na ściance bryły pokazuje tymczasowy krzyż osi (czerwona U, zielona V) przez środek ścianki, jak osie głównej siatki.
- **Strzałki** (także z bloku numerycznego) przesuwają widok w czasie szkicowania; Shift + strzałka - większy krok.
- **Wyciąganie do elementu + Wytnij** wycina także bryłę wskazaną jako cel, gdy narzędzie w nią wchodzi. Połącz nadal dołącza wyciągnięcie tylko do bryły, z której wychodzi profil.

## Zmiany 0.4.14

- **Linie gięcia na rysunku technicznym.** Rysunek rozłożonej blachy oraz rysunek z wczytanego pliku DXF (Rysunek → Załaduj plik) pokazują linie gięcia: w górę linią ciągłą, w dół przerywaną. Linie są przycięte do obrysu blachy (także wokół otworów) i nie są traktowane jak kontur.
- **Rozwinięcie DXF:** warstwa BEND_DOWN ma przerywany typ linii GIECIE_DOL, BEND_UP - ciągły.
- **Szybciej:** rozkładanie nieedytowanej blachy kilka razy szybciej (np. pudełko z czterema ściankami: z ok. 16 s do ok. 2 s), eksport rozwinięcia DXF z ok. 5 s do poniżej 1 s, a wczytanie takiego DXF w zakładce Rysunek z ok. 4 s do ułamka sekundy - krzywe są wczytywane jako pojedyncze krzywe zamiast tysięcy odcinków, więc okno rysunku nie zwalnia.
- **Wytnij** usuwa także bryły leżące w całości w wycinanym obszarze i wycina wszystko napotkane po drodze.

## Poprawki 0.4.13

- **Wyciąganie do elementu innej bryły:** bryła wskazana jako cel wyznacza tylko wysokość. Połącz dołącza wyciągnięcie do bryły, z której wychodzi profil, a Wytnij i Wspólna działają na bryłach napotkanych po drodze. Wskazana bryła pozostaje bez zmian (również przy przeliczaniu historii). Gdy cel leży na tej samej bryle co profil (np. wyrównanie schodka), działa jak dotychczas.
- **Pole odległości** jest aktywne i zaznaczone zaraz po wybraniu profilu (i po wskazaniu elementu), więc wymiar można od razu wpisać z klawiatury i zatwierdzić Enterem.

## Nowości 0.4.12

- **Bryła → Wyciągnij → Kierunek: Oba końce.** Wskazana ściana (albo szkic na niej) i przeciwległa, równoległa ściana bryły wyciągają się o tę samą odległość, np. góra i dół sześcianu albo oba denka walca. Działa z łączeniem i wycinaniem oraz przy przeliczaniu historii.
- **Rysunek → Załaduj plik.** Płaski rysunek SVG albo DXF z komputera otwiera się w oknie rysunku technicznego jako rzut z góry: wymiary, średnice, osie, tabelka i zapis do PDF, DXF, SVG lub JPG. Jednostki z pliku są przeliczane na milimetry; okręgi i łuki pozostają prawdziwymi okręgami.
- **Blacha:** panele Konwertuj na blachę, Kołnierz, Zawinięcie i Reguły blach mieszczą się na ekranie — treść przewija się, a przyciski Zatwierdź / Anuluj / Zamknij są zawsze widoczne na dole.
- **Rozwinięcie DXF:** nowa ikona oraz linie gięcia przycięte do obrysu blachy — nie wychodzą poza kontur przy ukosach, wycięciach i szczelinach w narożnikach.

## Nowość 0.4.11

- **Bryła → Wyciągnij → Zakres: Do elementu.** Po wybraniu profilu kliknij płaszczyznę (XY, XZ, YZ), ścianę bryły, krawędź albo punkt (wierzchołek bryły lub punkt szkicu). Bryła sięga dokładnie do wysokości wskazanego elementu, mierzonej wzdłuż normalnej profilu.
- Element pod kursorem jest podświetlany; dla skośnej krawędzi liczy się punkt najbliżej kursora, dla ściany równoległej do profilu jej rzeczywista wysokość. Kliknięcie innego elementu zmienia wysokość, a ręczna zmiana odległości lub przeciągnięcie strzałki odłącza element.
- Działa ze wszystkimi operacjami (Nowa, Połącz, Wytnij, Wspólna). Dotychczasowe wyciąganie na odległość pozostaje bez zmian.

## Poprawki 0.4.10

- Można dodać zawinięcia na czterech krawędziach płyty, również od spodu, oraz na końcach istniejących kołnierzy.
- Zawinięcia podlegają trybom **Równolegle** i **Blacharskie**: odcinki powrotne otrzymują odpowiednio styk prosty lub docinanie blacharskie. Przy podstawie łuk zawinięcia nie jest sztucznie przedłużany przez narożnik.
- **Rozłóż blachę**, **Zegnij blachę**, **Aktualizuj blachę** i eksport rozwinięcia DXF obsługują zawinięcia. Rozwinięcie uwzględnia łuk 180°, odcinek powrotny, rzeczywisty promień ograniczony szczeliną oraz współczynnik K.
- Zachowywane są obsługiwane edycje na płaskiej i zgiętej blasze, w tym otwory na odcinku powrotnym i wycięcia przez łuk, oraz historia i zapis projektu.
- Naprawione rozpoznawanie dolnej strony blachy po zmianie położenia środka masy oraz rozwinięcie zawinięć blacharskich przy zerowej szczelinie narożników.

Promień zawinięcia, jak dotychczas, jest ograniczony do połowy szczeliny od powierzchni. Współczynnik K dobierz do materiału i prób gięcia. Rzeczywiste kolizje materiału lub nachodzące na siebie rozwinięcia nadal są zgłaszane bez utraty modelu.

## Poprawki 0.4.9 — prostsze łączenia równoległe


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
