"""Samouczek RCCAD (menu Plik → Pomoc): tematy po lewej, opis z ilustracją po prawej."""
from __future__ import annotations
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QScrollArea, QVBoxLayout, QPushButton, QFrame
from . import icons

TOPICS = [
    ('new', 'Start', 'Jak zacząć', [
        'Po uruchomieniu widzisz trzy płaszczyzny środkowe (XY, XZ, YZ). Obracaj widok lewym przyciskiem myszy, przesuwaj prawym lub Shift + lewy, zoom kółkiem.',
        'Pasek narzędzi u góry: Plik, Szkic, Wyciągnij, Obrót, Przeciągnięcie, Wyciągnięcie złożone, Skorupa, Połącz, Edytuj (zaokrąglanie, fazowanie), Lustro.',
        'Cofanie i ponawianie: strzałki w prawym górnym rogu albo Ctrl+Z / Ctrl+Y. Przycisk z warstwami pokazuje płaszczyzny, przycisk obok włącza przezroczyste bryły.']),
    ('t_toolbox', 'Ulubione i Przybornik', 'Twoje najczęściej używane narzędzia w jednej zakładce', [
        'Zakładka Ulubione (pierwsza od lewej) ma stały przycisk Przybornik, zaraz po Pliku (dyskietce). Kliknij Przybornik: otworzy się okno ze wszystkimi narzędziami ze wszystkich zakładek, pogrupowanymi według zakładek.',
        'Kliknij kółko przy narzędziu - pojawi się zielony ptaszek i narzędzie trafi do listy Ulubione na górze okna. Strzałki ▲ ▼ zmieniają kolejność: pierwsze na liście stoi na pasku zaraz po Przyborniku. U góry okna widać podgląd paska tak, jak będzie wyglądał.',
        'Zastosuj zapisuje wybór (zostaje także po ponownym uruchomieniu programu), Zamknij zamyka okno bez zmian, Reset odznacza wszystkie narzędzia. Narzędzie użyte z Ulubionych nie przełącza zakładki - zostajesz w Ulubionych.',
        'Ustawienia (Ulubione, zapamiętane wartości Kołnierza i Zawinięcia i kolejne) są w folderze „Ustawienia” obok pliku RCCAD Desktop.exe. Po aktualizacji przenieś ten folder do nowej wersji programu, a ustawienia wrócą. Gdy folderu programu nie można zapisać, ustawienia trafiają do profilu użytkownika.']),
    ('sketch', 'Szkic', 'Rysowanie na płaszczyźnie lub ścianie', [
        'Kliknij Szkic, potem płaszczyznę środkową albo dowolną płaską ścianę bryły (podświetli się na pomarańczowo). Można też kliknąć ścianę kostki widoku.',
        'Wybierz kształt: linia, prostokąt, okrąg, łuk, wielokąt, tekst. Rysuj klik–klik. Kursor w ruchu jest wolny; gdy zatrzymasz go na chwilę przy punkcie (także przed pierwszym kliknięciem, więc widać, gdzie kształt się zacznie), przyciąga się (znacznik pokazuje typ): narożniki kratek siatki, punkty i środki szkiców, krawędzie, okręgi, przecięcia oraz krawędzie i narożniki ścianki, na której rysujesz. Alt wyłącza przyciąganie.',
        'Na ściance bryły pojawia się tymczasowy krzyż osi szkicu (czerwona U, zielona V) przechodzący przez środek ścianki; główny krzyż osi jest wtedy ukryty. Strzałki (także z bloku numerycznego) przesuwają widok, Shift + strzałka - większy krok.',
        'Esc lub prawy przycisk kończy bieżącą linię i zostawia ją. Kształty nachodzące na siebie dzielą się na obszary, które można osobno wyciągać. Narzędzie Przytnij usuwa odcinek między przecięciami.',
        'Ofset (w narzędziach szkicu): kliknij kształt (prostokąt, okrąg, obrys z linii, łuk, pojedynczą linię). Otworzy się okienko: Na zewnątrz / Do wewnątrz i odległość. Przy kształcie pojawia się pomarańczowa strzałka - przeciągnij ją na zewnątrz albo do środka (przeciągnięcie przez kształt zmienia stronę). Przerywana linia pokazuje wynik, Zastosuj albo Enter dodaje nowy kształt (oryginał zostaje), Esc wybiera inny kształt. Narożniki zostają ostre.']),
    ('extrude', 'Wyciągnij', 'Wyciąganie i wycinanie', [
        'Kliknij Wyciągnij i wskaż zamknięty profil szkicu, obszar między liniami albo płaską ścianę bryły. Wybrana powierzchnia świeci się. Shift + klik dodaje kolejne profile.',
        'Pociągnij strzałkę z grotem lub wpisz odległość. Podgląd odświeża się na żywo. Operacja: Nowa bryła, Połącz, Wytnij, Wspólna część. Kierunek: jedna strona, symetrycznie, dwie strony albo oba końce.',
        'Oba końce: wskaż ścianę bryły (albo szkic na niej) - ta sama odległość zostaje wyciągnięta także na przeciwległej, równoległej ścianie, np. góra i dół sześcianu albo oba denka walca. Działa z łączeniem i wycinaniem.',
        'Zakres „Do elementu”: po wybraniu profilu kliknij płaszczyznę, ścianę, krawędź albo punkt (także punkt szkicu). Bryła sięga do wysokości tego elementu mierzonej wzdłuż normalnej profilu; dla skośnej krawędzi liczy się punkt najbliżej kursora. Kliknięcie innego elementu zmienia wysokość, ręczna zmiana odległości odłącza element.',
        'Ściany walcowe: w trybie Wyciągnij najedź na wewnętrzną ściankę otworu albo zewnętrzną powierzchnię walca (np. wałka, zaokrąglenia) - podświetli się i można ją kliknąć. Wartość dodatnia (strzałka od materiału) dodaje materiał: walec robi się grubszy, otwór mniejszy. Wartość ujemna (strzałka w materiał) wycina: walec cieńszy, otwór większy. Program sam wybiera Połącz albo Wytnij; wysokość i zakres kąta zostają jak w ścianie.',
        'Zaokrąglenie krawędzi (ściana walcowa styczna do sąsiednich ścian) zmienia swój promień i zostaje styczne - nic nie wystaje poza bryłę. Wypukłe: dodanie materiału zmniejsza promień aż do ostrego narożnika, wycięcie go zwiększa. Wklęsłe (w narożniku wewnętrznym): dodanie zwiększa promień, wycięcie zmniejsza. Wartość to przesunięcie środka łuku.',
        'Enter zatwierdza, Esc anuluje.']),
    ('t_mate', 'Dopasowanie', 'Ściana jednej bryły do ściany drugiej', [
        'Zakładka Edycja → Dopasowanie. Kliknij płaską ścianę bryły, która ma się przesunąć, potem płaską ścianę drugiej bryły. Pierwsza bryła obraca się i przesuwa tak, że jej ściana przylega do ściany drugiej bryły (patrzą na siebie), a środki obu ścian się spotykają.',
        'Zielony podgląd pokazuje nowe położenie. Kliknięcie innej ściany przesuwanej bryły zmienia jej ścianę, kliknięcie ściany innej bryły - ścianę docelową. Strzałki „w lewo 45°” i „w prawo 45°” obracają przesuwaną bryłę wokół osi prostopadłej do ścian, przez ich wspólny środek (ściany dalej przylegają); kąt widać między strzałkami. Zastosuj albo Enter zatwierdza; krok trafia do historii i przelicza się po zmianie wcześniejszych kroków.']),
    ('t_align', 'Wyrównanie', 'Ściany dwóch brył na jednej wysokości', [
        'Zakładka Edycja → Wyrównanie. Kliknij ścianę bryły, która ma się przesunąć, potem ścianę wzorcową innej bryły. Cała pierwsza bryła przesuwa się bez obracania wzdłuż kierunku ściany wzorcowej, aż obie ściany leżą na tej samej wysokości.',
        'Działa w każdej płaszczyźnie: góra / dół, przód / tył, lewo / prawo - kierunek wyznacza ściana wzorcowa.']),
    ('t_revolve', 'Obrót', 'Bryły obrotowe', [
        'Obraca profil szkicu wokół osi, tworząc okrągłą bryłę. Służy do wałków, gałek, misek i wszystkich części okrągłych względem osi.',
        'Kliknij Obrót i wskaż zamknięty profil szkicu, obszar albo płaską ścianę bryły (Shift + klik dodaje kolejne). Oś: pozioma lub pionowa oś szkicu (program sam wybiera tę, której profil nie przecina) albo Wskaż - kliknij prostą linię szkicu lub krawędź bryły.',
        'Kąt obrotu 360° daje pełną bryłę, mniejszy - wycinek. Operacja: Nowa bryła, Połącz, Wytnij, Wspólna część. Podgląd widać na żywo, Enter zatwierdza, Esc anuluje. Profil nie może przecinać osi.']),
    ('t_shell', 'Skorupa', 'Pudełka, pokrywy, części cienkościenne', [
        'Wydrąża bryłę, pozostawiając ścianki o zadanej grubości, i może otworzyć wybrane ściany. Służy do pudełek, pokryw i innych części cienkościennych.',
        'Kliknij Skorupa, wskaż bryłę, a potem klikaj płaskie ściany, które mają zostać otwarte (pomarańczowe; ponowne kliknięcie cofa). Bez otwartych ścian bryła zostaje szczelnie wydrążona w środku.',
        'Wpisz grubość ścianki i wybierz kierunek: do wewnątrz (rozmiar zewnętrzny bez zmian) albo na zewnątrz. Podgląd widać na żywo, Enter zatwierdza, Esc anuluje. Gdy ścianka jest za gruba dla bryły, program pokaże komunikat.']),
    ('t_sheet', 'Konwertuj na blachę', 'Blacha: zamiana prostopadłościanu na blachę do gięcia', [
        'Zamienia prostopadłościan na blachę. Wybrana płaska ściana staje się górą blachy, a grubość to odległość od ściany przeciwnej.',
        'Najpierw zrób szkic prostokąta albo kwadratu i wyciągnij go na grubość blachy. Potem wybierz KONWERTUJ NA BLACHĘ i kliknij płaską ścianę (prostokąt albo kwadrat). Inne kształty są odrzucane.',
        'Okno pokazuje odczytaną grubość blachy i wymiary płyty. Zamień na blachę zatwierdza, Zamknij zamyka okno bez zmian.',
        'Po konwersji można dodawać kołnierze. Program zapamiętuje blachę w historii, więc zmiana wcześniejszych kroków przelicza ją ponownie.']),
    ('t_rules', 'Reguły blach', 'Szczelina i wycięcia w narożnikach', [
        'Blacharskie: pionowe ściany mają proste zakończenia, a sąsiednie poziome kołnierze są przycinane skośnie. Wycięcie na łuku przechodzi płynnie między zakończeniami obu ścian. Okrągłe powierzchnie gięcia zachowują promień i grubość.',
        'Blacharskie jest domyślne dla nowych konwersji. Starsze projekty zachowują zapisany sposób łączenia. Aby zmienić istniejącą blachę, wybierz Blacharskie i kliknij Zastosuj do blachy (gdy żadna blacha nie jest zaznaczona, program poprosi o jej wskazanie kliknięciem). Zapisane szczeliny i wycięcia są odczytywane przy otwieraniu reguł.',
        'Ustawienia kołnierzy blachy: szczelina między kołnierzami w narożniku (obrazek obok pola pokazuje, który to odstęp; domyślnie 0,1 mm) oraz wycięcie w rogu - kliknij jedną z trzech ikon: brak, kwadrat albo okrąg - o zadanej wielkości.',
        'Wycięcie w narożniku zależy tylko od tego ustawienia. Przy „Brak” narożnik jest zamknięty: łuki dwóch gięć spotykają się po skosie i zostaje tylko szczelina między kołnierzami (na rozwinięciu wspólny kwadrat stref gięcia jest podzielony skosem, nic nie jest wycinane). Kwadrat albo okrąg dają jedno wycięcie o zadanej wielkości.',
        'Przyciski na dole: Zastosuj do blachy przelicza wskazaną blachę z bieżącymi regułami. Zastosuj zatwierdza ustawienia i od razu włącza Kołnierz (kolejne gięcia dostaną te reguły). Zamknij zamyka okno. Reset przywraca ustawienia domyślne.',
        'Reguły narożników przeliczają całą blachę przy następnym dodaniu gięcia lub po wybraniu Zastosuj do blachy. Zwykłe kołnierze obsługują także kąty ostre i rozwarte; narożniki i zawinięcia dopasowują się automatycznie do sąsiednich ścian.',
        'Równolegle: jedna ściana dochodzi do rzeczywistej powierzchni sąsiada, także na kolejnych poziomach gięć. Łuki i szczelina są dopasowywane do sąsiedniego materiału bez wymuszania ukosu 45°.',
        'Gdy kolejne kołnierze rozchodzą się w różne strony i nie przecinają się, ich końce pozostają proste. Wspólna krawędź podstawy nie wymusza ukosu na wszystkich późniejszych poziomach.',
        'Zastosuj do blachy przelicza narożniki istniejącego modelu, także w projekcie zapisanym w starszej wersji. Nie dodaje kołnierza i zachowuje sposób wymiarowania każdego istniejącego gięcia. Przeliczenie można cofnąć.',
        'Współczynnik K określa położenie warstwy obojętnej rozwinięcia. Zakres 0–0,5, domyślnie 0,44; dobierz go do materiału i prób na giętarce.']),
    ('t_flange', 'Kołnierz', 'Blacha: wyciągnięcie krawędzi w kołnierz', [
        'Wyciąga krawędź blachy w kołnierz z zadanym promieniem gięcia (promień stempla), kątem i długością prostej części.',
        'Wybierz KOŁNIERZ i ustaw promień gięcia, kąt i długość kołnierza (domyślnie R 0,5 mm, 90°, 5 mm) - obrazki obok pól pokazują, co oznacza każde ustawienie. Krawędź górnej ściany wychodzi w górę, krawędź dolnej w dół.',
        'Przyciski na dole: Zatwierdź zapamiętuje ustawienia (zostają także po ponownym uruchomieniu programu). Zaginaj włącza wyginanie - przycisk robi się czerwony i każde kliknięcie krawędzi blachy dodaje kołnierz; ponowne kliknięcie wyłącza wyginanie (zielony), wtedy kliknięcie krawędzi tylko ją pokazuje. Reset przywraca ustawienia domyślne, Zamknij zamyka okno.',
        'Odwróć kierunek gięcia zmienia stronę bez wybierania drugiej krawędzi grubości. Można kontynuować gięcia na końcach kolejnych kołnierzy, z różnymi kątami i kierunkami.',
        'Długość mierzona od strony (zapisane osobno dla każdego gięcia): Zewnętrzna - wymiar od wierzchołka kołnierza do zewnętrznej strony blachy, a przy kolejnym gięciu od zewnętrznej do zewnętrznej strony (blacha 1 mm, 5 mm: w środku 4 mm, między dwoma gięciami 3 mm); Wewnętrzna - od wierzchołka do wewnętrznej strony, przy kolejnym gięciu od wewnętrznej do wewnętrznej (z grubością 6 i 7 mm). Płyta ma wtedy wymiar zewnętrzny albo wewnętrzny gotowej blachy. Kąt prosty i ostry: do przecięcia przedłużonych powierzchni; kąt rozwarty: do środka łuku gięcia.']),
    ('t_unfold_sheet', 'Rozłóż blachę', 'Blacha: edytowalne rozwinięcie', [
        'Kliknij Rozłóż blachę: zaznaczona blacha rozkłada się od razu, a gdy żadna nie jest zaznaczona, kliknij blachę w widoku (Esc albo ponowne kliknięcie narzędzia anuluje). Powstaje płaska bryła o rzeczywistej grubości; promienie, kąty, kierunki i reguły pozostają zapisane.',
        'Na prostych obszarach używaj zwykłych szkiców, wycinania, łączenia wyciągnięć i zaokrąglania krawędzi. Na łukach można przenosić wykonane na płasko wycięcia przez całą grubość, także przez granicę ściany i łuku. Kieszenie i zaokrąglenia zmieniające grubość samego łuku oraz nakładające się lub rozdzielone rozwinięcia nie są obsługiwane. Nieudana operacja nie usuwa zmian.']),
    ('t_fold_sheet', 'Zegnij blachę', 'Blacha: powrót do zapisanych gięć', [
        'Kliknij Zegnij blachę: zaznaczona rozłożona blacha zgina się od razu, a gdy żadna nie jest zaznaczona, kliknij blachę w widoku. Program odtwarza poprzednie gięcia i przenosi zmiany z prostych ścian.',
        'Można edytować także zgiętą blachę, po czym ponownie ją rozłożyć. Kolejne przełączenia zachowują wykonane otwory i inne obsługiwane zmiany. Historia, cofanie i zapis projektu obejmują oba stany.']),
    ('t_flat', 'Rozwinięcie DXF', 'Blacha: rozwinięcie 1:1 do cięcia laserowego', [
        'Ustaw współczynnik K w Regułach blach, kliknij Rozwinięcie DXF, a potem kliknij w widoku blachę, która ma być zapisana; następnie wybierz plik. Eksport wykonuje się w tle, bez zmiany modelu ani historii.',
        'Długość naddatku gięcia BA = kąt w radianach × (R + K × grubość). DXF jest w milimetrach, w skali 1:1. Tnij tylko zamknięte kontury warstwy CUT. BEND_UP i BEND_DOWN to linie środka gięcia, nie linie cięcia; są przycięte do obrysu blachy, więc nie wychodzą poza kontur przy wycięciach i ukosach w narożnikach. Gięcie w górę to linia ciągła, w dół - przerywana (typ linii GIECIE_DOL).',
        'Edytowalne rozwinięcie uwzględnia także docinane narożniki, jeśli powstaje jedna część bez nakładania materiału. Układy wymagające innego rozcięcia są odrzucane. Dodatkowe otwory są zachowywane w nowym edytowalnym rozwinięciu. Eksport wymaga jednej części o jednakowej grubości.',
        'Kontury nie zawierają kompensacji szerokości szczeliny lasera; ustawia się ją w CAM. Przed produkcją sprawdź parametry materiału, K, kierunki i technologię gięcia.']),
    ('t_hem', 'Zawinięcie', 'Blacha: zawinięcie krawędzi o 180°', [
        'Krawędź zawija się od razu o 180° i odcinek powrotny przylega do powierzchni blachy, bez dodatkowego kołnierza.',
        'Wybierz ZAWINIĘCIE i ustaw promień, maksymalną długość zawinięcia (dopasowywaną do dostępnego miejsca) i szczelinę (min 0,1 mm) - obrazki obok pól pokazują, co oznacza każde ustawienie.',
        'Przyciski na dole jak w Kołnierzu: Zatwierdź zapamiętuje ustawienia (także po ponownym uruchomieniu programu), Zaginaj włącza wyginanie (czerwony - każde kliknięcie krawędzi płyty, kołnierza albo wolnego końca zawinięcia dodaje zawinięcie; zielony - wyłączone), Reset przywraca ustawienia domyślne, Zamknij zamyka okno.',
        'Szczelina to odstęp ponad średnicę gięcia (2 × promień). Zawinięcie działa tylko dla gięcia 90° na krawędzi.']),
    ('t_drawing', 'Rysunek', 'Rysunek techniczny z bryły', [
        'Zakładka Rysunek tworzy rysunek techniczny wybranej bryły: rzuty z przodu, z tyłu, z lewej, z prawej, z góry, z dołu i izometryczny, z wymiarami i tabelką rysunkową.',
        'Utwórz rysunek techniczny: kliknij bryłę (podświetla się na niebiesko). Otworzy się osobne okno, w którym zaznaczasz rzuty, wybierasz arkusz (A4, A3, A2), skalę, metodę rzutowania oraz wymiary: gabarytowe, średnice i promienie, osie otworów, krawędzie niewidoczne.',
        'Mierz na rysunku: kliknij dwa punkty (przyciągają się do końców linii i środków otworów) - program poda odległość w mm bryły. Kółko myszy powiększa, prawy przycisk przesuwa. Zapisz rysunek: PDF, DXF, SVG lub JPG.',
        'Rysunek automatyczny: kliknij bryłę - program sam dobierze rzuty, arkusz, skalę i wymiary, a zapyta tylko o format i miejsce zapisu.',
        'Załaduj plik: wybierz z komputera płaski rysunek SVG albo DXF. Otworzy się okno rysunku technicznego z tym kształtem jako rzutem z góry - z wymiarami, tabelką i zapisem do PDF, DXF, SVG lub JPG. Linie, łuki, okręgi, elipsy, krzywe, polilinie i bloki są wczytywane w milimetrach (jednostki z pliku są przeliczane). Linie gięcia z warstw BEND_UP i BEND_DOWN (np. z Rozwinięcia DXF) pojawiają się jako linie gięcia: w górę ciągła, w dół przerywana, przycięte do obrysu blachy.',
        'Rysunek rozłożonej blachy (Rozłóż blachę, potem Utwórz rysunek albo Rysunek automatyczny) zawiera linie gięcia w rzucie z góry i z dołu: w górę ciągła, w dół przerywana. Widok izometryczny pokazuje blachę zgiętą.',
        'Rysunek blachy do gięcia: kliknij blachę (zgiętą albo rozłożoną). Powstaje rozwinięcie widziane od góry blachy z wymiarami całości, łańcuchem wymiarów od krawędzi do linii gięcia i między liniami, opisem każdego gięcia (GÓRA / DÓŁ, kąt, promień) oraz grubością, promieniem i współczynnikiem K w lewym dolnym rogu.',
        'Każdy rysunek z liniami gięcia (opcja Wymiary linii gięcia) ma łańcuch wymiarów od zewnętrznych krawędzi blachy przez wszystkie linie gięcia. Linie gięcia można też wymiarować (Wymiaruj, Odległość) i mierzyć (Mierz) tak samo jak krawędzie.']),
    ('t_sweep', 'Przeciągnięcie', 'Profil wzdłuż ścieżki', [
        'Przeciąga profil szkicu wzdłuż ścieżki, tworząc bryłę. Służy do rur, prowadnic, uchwytów i każdej części o stałym przekroju biegnącej wzdłuż krzywej.',
        'Kliknij Przeciągnięcie, wskaż zamknięty profil (szkic, obszar albo płaską ścianę), a potem ścieżkę: linię lub łuk szkicu albo krawędź bryły. Profil powinien leżeć na początku ścieżki, prostopadle do niej.',
        'Operacja: Nowa bryła, Połącz, Wytnij, Wspólna część. Podgląd widać na żywo, Enter zatwierdza, Esc anuluje. Przycisk Wskaż ścieżkę ponownie pozwala wybrać inną ścieżkę.']),
    ('t_loft', 'Wyciągnięcie złożone', 'Bryła przez kilka profili', [
        'Tworzy gładką bryłę przechodzącą przez dwa lub więcej profili szkicu albo od profilu do punktu. Służy do przejść, lejków, uchwytów i każdego kształtu, którego przekrój zmienia się na długości.',
        'Klikaj kolejne profile w kolejności przejścia (ponowne kliknięcie usuwa profil). Tryb Do punktu: wskaż jeden profil, a potem punkt szkicu lub narożnik bryły, w którym bryła się zbiega.',
        'Przejście: Gładko albo Prosto. Operacja: Nowa, Połącz, Wytnij, Wspólna. Podgląd widać na żywo, Enter zatwierdza, Esc anuluje.']),
    ('bool', 'Połącz', 'Operacje logiczne na bryłach', [
        'Wybierz działanie: suma, różnica albo część wspólna. Kliknij bryłę bazową (niebieska), potem bryły-narzędzia (pomarańczowe). Ponowne kliknięcie odznacza.',
        'Opcja Zachowaj bryły-narzędzia pozostawia oryginały. Podgląd wyniku widać od razu.']),
    ('fillet', 'Zaokrąglanie i fazowanie', 'Krawędzie', [
        'Kliknij krawędź. Shift + klik dodaje kolejne, Ctrl + klik zaznacza cały łańcuch styczny.',
        'Rozmiar zmieniasz strzałką lub wpisując wartość. Podgląd podświetla ciepłym fioletem tylko tworzone zaokrąglenie albo fazę (widać je także przez jeszcze ostry narożnik); dwuklik w ścianę zaznacza jej krawędzie bez podświetlania całej ściany.']),
    ('t_split', 'Przetnij bryłę', 'Podział bryły na części (zakładka Edycja)', [
        'Kliknij Przetnij bryłę, potem bryłę (albo zaznacz ją wcześniej kliknięciem). Wybierz metodę ikoną: Płaszczyzna - równoległa do XY, XZ albo YZ, przez środek bryły; Ściana - płaszczyzna klikniętej płaskiej ściany; Szkic - linia, łuk albo zamknięty profil szkicu, cięcie prostopadle do szkicu przez całą bryłę; Bryła - powierzchnia innej bryły (części wewnątrz i na zewnątrz niej).',
        'Przy płaszczyźnie i ścianie Odsunięcie przesuwa cięcie wzdłuż strzałki - można je wpisać albo przeciągnąć strzałkę w widoku. Fioletowa przezroczysta płaszczyzna pokazuje, gdzie bryła zostanie przecięta.',
        'Podgląd koloruje części: zielona i pomarańczowa (przy zamkniętym profilu szkicu i przy innej bryle pomarańczowa jest wewnątrz). Zostaw: Obie części (osobne bryły), tylko Zielona albo tylko Pomarańczowa. Zastosuj albo Enter wykonuje cięcie; krok trafia do historii i przelicza się po zmianie wcześniejszych kroków.']),
    ('mirror', 'Lustro', 'Odbicie lustrzane', [
        'Krok 1: kliknij bryłę lub element szkicu do odbicia. Krok 2: kliknij ścianę, która ma być lustrem. Odbicie powstaje po drugiej stronie tej ściany.',
        'Zachowaj oryginał tworzy kopię, Połącz z oryginałem skleja obie bryły w jedną.']),
    ('x_pat_rect', 'Szyk', 'Powielanie obiektów', [
        'Kliknij bryłę lub szkic, wybierz rodzaj: prostokątny (ilość i odstęp w osiach X, Y, Z), kołowy (oś, ilość i kąt całkowity) albo wzdłuż linii (kliknij linię szkicu lub krawędź bryły).',
        'Kopie widać na bieżąco i zmieniają się razem z wartościami. Połącz kopie w jedną bryłę skleja wynik. Enter zatwierdza.']),
    ('sym', 'Przesuń i obróć', 'Transformacje', [
        'Zaznacz bryłę lub szkic. Przesuwanie: pociągnij kolorową strzałkę osi, kwadrat płaszczyzny albo złap samą bryłę lewym przyciskiem.',
        'Obrót: pociągnij kolorowy pierścień wokół osi. Wartości można też wpisać. Strzałki dopasowują się do ustawienia kamery.',
        'Okno Przesuń / Obróć (po lewej) ma pola X, Y, Z z kolorowymi ikonami osi (przesunięcie w mm, obrót w stopniach). Zastosuj zatwierdza, Zamknij zamyka okno bez zmian.']),
    ('f_save', 'Historia i zapis projektu', 'Kroki, autozapis, zapis kompaktowy', [
        'Każda operacja to krok historii na dolnym pasku. Opis kroku podaje wartości, np. „Kołnierz 20 mm, 90°”, „Przesunięcie X +15 mm”, „Wyciągnięcie 10 mm” - widać je w podpowiedzi kroku, na liście kroków i w tytule Edycji kroku.',
        'Historia pamięta 999 kroków. Przy 950 krokach program ostrzega jeden raz; po przekroczeniu limitu najstarsze kroki są usuwane (też z komunikatem). Aby zachować stan, zapisz wariant w menu historii.',
        'Plik projektu (.rccadx) zawiera całą historię: geometria jest w jednej paczce, a opisy powtarzające się w wielu krokach są zapisane raz, więc nawet bardzo długie historie otwierają się poprawnie. Starsze pliki otwierają się jak dotąd.',
        'Plik → Zapisz kompaktowo… daje mniejszy plik: kroki, które program umie przeliczyć z przepisu (kołnierze, rozłożenie, przesunięcia…), zapisuje bez geometrii i odtwarza przy otwieraniu (otwarcie trwa wtedy chwilę dłużej). Co 10. krok i bieżący stan są zapisane w całości.',
        'Autozapis co 2,5 minuty zapisuje kopię obok pliku projektu (nazwa.autosave.rccadx) - także przy otwartym narzędziu, np. Kołnierzu. Kopię otworzysz z menu historii → Otwórz autozapis.']),
    ('one', 'Widok', 'Kostka i skróty', [
        'Bryła zaznacza się tylko kliknięciem lewym przyciskiem (ciepły niebieski kolor); ponowne kliknięcie odznacza. Wynik operacji nie zaznacza się sam.',
        'Kostka w prawym górnym rogu: klik w ścianę ustawia widok z tej strony, klik w krawędź lub róg widok ukośny. Domek wraca do widoku głównego.',
        'Skróty: Ctrl+N nowy, Ctrl+O otwórz, Ctrl+S zapisz, Ctrl+Z cofnij, Ctrl+Y ponów, Enter zatwierdź, Esc anuluj.']),
]


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Pomoc — samouczek RCCAD')
        self.resize(860, 560)
        self.setStyleSheet('QDialog{background:#f4f7fb;} QListWidget{background:#ffffff;border:1px solid #d6e0ea;border-radius:10px;padding:6px;outline:0;}'
                           'QListWidget::item{padding:8px;border-radius:8px;} QListWidget::item:selected{background:#dcebfb;color:#17314a;}'
                           'QLabel#hbody{color:#27415a;font-size:14px;} QLabel#htitle{font-size:22px;font-weight:800;color:#17314a;}')
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)
        self.list = QListWidget()
        self.list.setFixedWidth(230)
        self.list.setIconSize(QSize(34, 34))
        for kind, title, sub, _ in TOPICS:
            item = QListWidgetItem(icons.badge(kind, icons.BLUE, 34), f'{title}\n{sub}')
            item.setSizeHint(QSize(200, 52))
            self.list.addItem(item)
        root.addWidget(self.list)
        right = QVBoxLayout()
        self.head = QLabel()
        self.head.setObjectName('htitle')
        self.pic = QLabel()
        top = QHBoxLayout()
        top.addWidget(self.pic)
        top.addWidget(self.head, 1)
        right.addLayout(top)
        card = QFrame()
        card.setStyleSheet('QFrame{background:#ffffff;border:1px solid #d6e0ea;border-radius:12px;}')
        cl = QVBoxLayout(card)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.body = QLabel()
        self.body.setObjectName('hbody')
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.RichText)
        self.body.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.body.setStyleSheet('border:none;background:transparent;padding:8px;')
        scroll.setWidget(self.body)
        cl.addWidget(scroll)
        right.addWidget(card, 1)
        close = QPushButton('Zamknij')
        close.clicked.connect(self.accept)
        right.addWidget(close, 0, Qt.AlignRight)
        root.addLayout(right, 1)
        self.list.currentRowChanged.connect(self.show_topic)
        self.list.setCurrentRow(0)

    def show_topic(self, row):
        if row < 0:
            return
        kind, title, sub, lines = TOPICS[row]
        self.head.setText(f'{title}\n')
        self.head.setText(title)
        self.pic.setPixmap(icons.badge(kind, icons.BLUE, 56))
        self.body.setText(''.join(f'<p style="margin:0 0 12px 0;line-height:140%">{i + 1}. {t}</p>' for i, t in enumerate(lines)))
